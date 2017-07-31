from __future__ import print_function
from __future__ import unicode_literals
from __future__ import division

import io
import logging
import os
import random
import subprocess
import re
import tempfile
import threading
import shutil
import time

from imagemounter import _util, FILE_SYSTEM_TYPES, VOLUME_SYSTEM_TYPES
from imagemounter.exceptions import CommandNotFoundError, NoMountpointAvailableError, SubsystemError, \
    NoLoopbackAvailableError, UnsupportedFilesystemError, NotMountedError, IncorrectFilesystemError, ArgumentError, \
    ImageMounterError, KeyInvalidError
from imagemounter.volume_system import VolumeSystem

logger = logging.getLogger(__name__)


FILE_SYSTEM_GUIDS = {
    '2AE031AA-0F40-DB11-9590-000C2911D1B8': 'vmfs',
    '8053279D-AD40-DB11-BF97-000C2911D1B8': 'vmkcore-diagnostics',
    '6A898CC3-1DD2-11B2-99A6-080020736631': 'zfs-member',
    'C38C896A-D21D-B211-99A6-080020736631': 'zfs-member',
    '0FC63DAF-8483-4772-8E79-3D69D8477DE4': 'linux',
    'E6D6D379-F507-44C2-A23C-238F2A3DF928': 'lvm',
    '79D3D6E6-07F5-C244-A23C-238F2A3DF928': 'lvm',
    'CA7D7CCB-63ED-4C53-861C-1742536059CC': 'luks'
}


class Volume(object):
    """Information about a volume. Note that every detected volume gets their own Volume object, though it may or may
    not be mounted. This can be seen through the :attr:`mountpoint` attribute -- if it is not set, perhaps the
    :attr:`exception` attribute is set with an exception.
    """

    def __init__(self, disk, parent=None, index="0", size=0, offset=0, flag='alloc', slot=0, fstype="", key="",
                 vstype='', volume_detector='auto'):
        """Creates a Volume object that is not mounted yet.

        Only use arguments as keyword arguments.

        :param disk: the parent disk
        :type disk: :class:`Disk`
        :param parent: the parent volume or disk.
        :param str index: the volume index within its volume system, see the attribute documentation.
        :param int size: the volume size, see the attribute documentation.
        :param int offset: the volume offset, see the attribute documentation.
        :param str flag: the volume flag, see the attribute documentation.
        :param int slot: the volume slot, see the attribute documentation.
        :param str fstype: the fstype you wish to use for this Volume. May be ?<fstype> as a fallback value. If not
                           specified, will be retrieved from the ImageParser instance instead.
        :param str key: the key to use for this Volume.
        :param str vstype: the volume system type to use.
        :param str volume_detector: the volume system detection method to use
        """

        self.parent = parent
        self.disk = disk

        # Should be filled somewhere
        self.size = size
        self.offset = offset
        self.index = index
        self.slot = slot
        self.flag = flag
        self.block_size = self.disk.block_size

        self.volumes = VolumeSystem(parent=self, vstype=vstype, volume_detector=volume_detector)

        self.fstype = fstype
        self._get_fstype_from_parser(fstype)

        if key:
            self.key = key
        elif self.index in self.disk.parser.keys:
            self.key = self.disk.parser.keys[self.index]
        elif '*' in self.disk.parser.keys:
            self.key = self.disk.parser.keys['*']
        else:
            self.key = ""

        self.info = {}
        self._paths = {}

        self.mountpoint = ""
        self.loopback = ""
        self.was_mounted = False
        self.is_mounted = False

    def __unicode__(self):
        return '{0}:{1}'.format(self.index, self.info.get('fsdescription') or '-')

    def __str__(self):
        return str(self.__unicode__())

    def __getitem__(self, item):
        return self.volumes[item]

    @property
    def numeric_index(self):
        try:
            return tuple([int(x) for x in self.index.split(".")])
        except ValueError:
            return ()

    def _get_fstype_from_parser(self, fstype=None):
        """Load fstype information from the parser instance."""
        if fstype:
            self.fstype = fstype
        elif self.index in self.disk.parser.fstypes:
            self.fstype = self.disk.parser.fstypes[self.index]
        elif '*' in self.disk.parser.fstypes:
            self.fstype = self.disk.parser.fstypes['*']
        elif '?' in self.disk.parser.fstypes and self.disk.parser.fstypes['?'] is not None:
            self.fstype = "?" + self.disk.parser.fstypes['?']
        else:
            self.fstype = ""

        if self.fstype in VOLUME_SYSTEM_TYPES:
            self.volumes.vstype = self.fstype
            self.fstype = 'volumesystem'

    def get_description(self, with_size=True, with_index=True):
        """Obtains a generic description of the volume, containing the file system type, index, label and NTFS version.
        If *with_size* is provided, the volume size is also included.
        """

        desc = ''

        if with_size and self.size:
            desc += '{0} '.format(self.get_formatted_size())

        s = self.info.get('statfstype') or self.info.get('fsdescription') or '-'
        if with_index:
            desc += '{1}:{0}'.format(s, self.index)
        else:
            desc += s

        if self.info.get('label'):
            desc += ' {0}'.format(self.info.get('label'))

        if self.info.get('version'):  # NTFS
            desc += ' [{0}]'.format(self.info.get('version'))

        return desc

    def get_formatted_size(self):
        """Obtains the size of the volume in a human-readable format (i.e. in TiBs, GiBs or MiBs)."""

        if self.size is not None:
            if self.size < 1024:
                return "{0} B".format(self.size)
            elif self.size < 1024 ** 2:
                return "{0} KiB".format(round(self.size / 1024, 2))
            elif self.size < 1024 ** 3:
                return "{0} MiB".format(round(self.size / 1024 ** 2, 2))
            elif self.size < 1024 ** 4:
                return "{0} GiB".format(round(self.size / 1024 ** 3, 2))
            else:
                return "{0} TiB".format(round(self.size / 1024 ** 4, 2))
        else:
            return self.size

    def _get_blkid_type(self):
        """Retrieves the FS type from the blkid command."""
        try:
            result = _util.check_output_(['blkid', '-p', '-O', str(self.offset), self.get_raw_path()])
            if not result:
                return None

            # noinspection PyTypeChecker
            blkid_result = dict(re.findall(r'([A-Z]+)="(.+?)"', result))

            self.info['blkid_data'] = blkid_result

            if 'PTTYPE' in blkid_result and 'TYPE' not in blkid_result:
                return blkid_result.get('PTTYPE')
            else:
                return blkid_result.get('TYPE')

        except Exception:
            return None  # returning None is better here, since we do not care about the exception in determine_fs_type

    def _get_magic_type(self):
        """Checks the volume for its magic bytes and returns the magic."""

        try:
            with io.open(self.disk.get_fs_path(), "rb") as file:
                file.seek(self.offset)
                fheader = file.read(min(self.size, 4096) if self.size else 4096)
        except IOError:
            logger.exception("Failed reading first 4K bytes from volume.")
            return None

        # TODO fallback to img-cat image -s blocknum | file -
        # if we were able to load the module magic
        try:
            # noinspection PyUnresolvedReferences
            import magic

            if hasattr(magic, 'from_buffer'):
                # using https://github.com/ahupp/python-magic
                logger.debug("Using python-magic Python package for file type magic")
                result = magic.from_buffer(fheader).decode()
                self.info['magic_data'] = result
                return result

            elif hasattr(magic, 'open'):
                # using Magic file extensions by Rueben Thomas (Ubuntu python-magic module)
                logger.debug("Using python-magic system package for file type magic")
                ms = magic.open(magic.NONE)
                ms.load()
                result = ms.buffer(fheader)
                ms.close()
                self.info['magic_data'] = result
                return result

            else:
                logger.warning("The python-magic module is not available, but another module named magic was found.")

        except ImportError:
            logger.warning("The python-magic module is not available.")
        except AttributeError:
            logger.warning("The python-magic module is not available, but another module named magic was found.")
        return None  # returning None is better here, since we do not care about the exception in determine_fs_type

    def get_raw_path(self, include_self=False):
        """Retrieves the base mount path of the volume. Typically equals to :func:`Disk.get_fs_path` but may also be the
        path to a logical volume. This is used to determine the source path for a mount call.

        The value returned is normally based on the parent's paths, e.g. if this volume is mounted to a more specific
        path, only its children return the more specific path, this volume itself will keep returning the same path.
        This makes for consistent use of the offset attribute. If you do not need this behaviour, you can override this
        with the include_self argument.

        This behavior, however, is not retained for paths that directly affect the volume itself, not the child volumes.
        This includes VSS stores and LV volumes.
        """

        v = self
        if not include_self:
            # lv / vss_store are exceptions, as it covers the volume itself, not the child volume
            if v._paths.get('lv'):
                return v._paths['lv']
            elif v._paths.get('vss_store'):
                return v._paths['vss_store']
            elif v.parent and v.parent != self.disk:
                v = v.parent
            else:
                return self.disk.get_fs_path()

        while True:
            if v._paths.get('lv'):
                return v._paths['lv']
            elif v._paths.get('bde'):
                return v._paths['bde'] + '/bde1'
            elif v._paths.get('luks'):
                return '/dev/mapper/' + v._paths['luks']
            elif v._paths.get('md'):
                return v._paths['md']
            elif v._paths.get('vss_store'):
                return v._paths['vss_store']

            # Only if the volume has a parent that is not a disk, we try to check the parent for a location.
            if v.parent and v.parent != self.disk:
                v = v.parent
            else:
                break
        return self.disk.get_fs_path()

    def get_safe_label(self):
        """Returns a label that is safe to add to a path in the mountpoint for this volume."""

        if self.info.get('label') == '/':
            return 'root'

        suffix = re.sub(r"[/ \(\)]+", "_", self.info.get('label')) if self.info.get('label') else ""
        if suffix and suffix[0] == '_':
            suffix = suffix[1:]
        if len(suffix) > 2 and suffix[-1] == '_':
            suffix = suffix[:-1]
        return suffix

    def carve(self, freespace=True):
        """Call this method to carve the free space of the volume for (deleted) files. Note that photorec has its
        own interface that temporarily takes over the shell.

        :param freespace: indicates whether the entire volume should be carved (False) or only the free space (True)
        :type freespace: bool
        :return: string to the path where carved data is available
        :raises CommandNotFoundError: if the underlying command does not exist
        :raises SubsystemError: if the underlying command fails
        :raises NoMountpointAvailableError: if there is no mountpoint available
        :raises NoLoopbackAvailableError: if there is no loopback available (only when volume has no slot number)
        """

        if not _util.command_exists('photorec'):
            logger.warning("photorec is not installed, could not carve volume")
            raise CommandNotFoundError("photorec")

        self._make_mountpoint(var_name='carve', suffix="carve", in_paths=True)

        # if no slot, we need to make a loopback that we can use to carve the volume
        loopback_was_created_for_carving = False
        if not self.slot:
            if not self.loopback:
                self._find_loopback()
                # Can't carve if volume has no slot number and can't be mounted on loopback.
                loopback_was_created_for_carving = True

            # noinspection PyBroadException
            try:
                _util.check_call_(["photorec", "/d", self._paths['carve'] + os.sep, "/cmd", self.loopback,
                                  ("freespace," if freespace else "") + "search"])

                # clean out the loop device if we created it specifically for carving
                if loopback_was_created_for_carving:
                    # noinspection PyBroadException
                    try:
                        _util.check_call_(['losetup', '-d', self.loopback])
                    except Exception:
                        pass
                    else:
                        self.loopback = ""

                return self._paths['carve']
            except Exception as e:
                logger.exception("Failed carving the volume.")
                raise SubsystemError(e)
        else:
            # noinspection PyBroadException
            try:
                _util.check_call_(["photorec", "/d", self._paths['carve'] + os.sep, "/cmd", self.get_raw_path(),
                                  str(self.slot) + (",freespace" if freespace else "") + ",search"])
                return self._paths['carve']

            except Exception as e:
                logger.exception("Failed carving the volume.")
                raise SubsystemError(e)

    def detect_volume_shadow_copies(self):
        """Method to call vshadowmount and mount NTFS volume shadow copies.

        :return: iterable with the :class:`Volume` objects of the VSS
        :raises CommandNotFoundError: if the underlying command does not exist
        :raises SubSystemError: if the underlying command fails
        :raises NoMountpointAvailableError: if there is no mountpoint available
        """

        if not _util.command_exists('vshadowmount'):
            logger.warning("vshadowmount is not installed, could not mount volume shadow copies")
            raise CommandNotFoundError('vshadowmount')

        self._make_mountpoint(var_name='vss', suffix="vss", in_paths=True)

        try:
            _util.check_call_(["vshadowmount", "-o", str(self.offset), self.get_raw_path(), self._paths['vss']])
        except Exception as e:
            logger.exception("Failed mounting the volume shadow copies.")
            raise SubsystemError(e)
        else:
            return self.volumes.detect_volumes(vstype='vss')

    def _should_mount(self, only_mount=None, skip_mount=None):
        """Indicates whether this volume should be mounted. Internal method, used by imount.py"""

        om = only_mount is None or \
            self.index in only_mount or \
            self.info.get('lastmountpoint') in only_mount or \
            self.info.get('label') in only_mount
        sm = skip_mount is None or \
            (self.index not in skip_mount and
             self.info.get('lastmountpoint') not in skip_mount and
             self.info.get('label') not in skip_mount)
        return om and sm

    def init(self, only_mount=None, skip_mount=None, swallow_exceptions=True):
        """Generator that mounts this volume and either yields itself or recursively generates its subvolumes.

        More specifically, this function will call :func:`load_fsstat_data` (iff *no_stats* is False), followed by
        :func:`mount`, followed by a call to :func:`detect_mountpoint`, after which ``self`` is yielded, or the result
        of the :func:`init` call on each subvolume is yielded

        :param only_mount: if specified, only volume indexes in this list are mounted. Volume indexes are strings.
        :param skip_mount: if specified, volume indexes in this list are not mounted.
        :param swallow_exceptions: if True, any error occuring when mounting the volume is swallowed and added as an
            exception attribute to the yielded objects.
        """
        if swallow_exceptions:
            self.exception = None

        try:
            if not self._should_mount(only_mount, skip_mount):
                yield self
                return

            if not self.init_volume():
                yield self
                return

        except ImageMounterError as e:
            if swallow_exceptions:
                self.exception = e
            else:
                raise

        if not self.volumes:
            yield self
        else:
            for v in self.volumes:
                for s in v.init(only_mount, skip_mount, swallow_exceptions):
                    yield s

    def init_volume(self, fstype=None):
        """Initializes a single volume. You should use this method instead of :func:`mount` if you want some sane checks
        before mounting.
        """

        logger.debug("Initializing volume {0}".format(self))

        if not self._should_mount():
            return False

        if self.flag != 'alloc':
            return False

        if self.info.get('raid_status') == 'waiting':
            logger.info("RAID array %s not ready for mounting", self)
            return False

        if self.is_mounted:
            logger.info("%s is currently mounted, not mounting it again", self)
            return False

        logger.info("Mounting volume {0}".format(self))
        self.mount(fstype=fstype)
        self.detect_mountpoint()

        return True

    def _make_mountpoint(self, casename=None, var_name='mountpoint', suffix='', in_paths=False):
        """Creates a directory that can be used as a mountpoint. The directory is stored in :attr:`mountpoint`,
        or the varname as specified by the argument. If in_paths is True, the path is stored in the :attr:`_paths`
        attribute instead.

        :returns: the mountpoint path
        :raises NoMountpointAvailableError: if no mountpoint could be made
        """
        parser = self.disk.parser

        if parser.mountdir and not os.path.exists(parser.mountdir):
            os.makedirs(parser.mountdir)

        if parser.pretty:
            md = parser.mountdir or tempfile.gettempdir()
            case_name = casename or self.disk.parser.casename or \
                ".".join(os.path.basename(self.disk.paths[0]).split('.')[0:-1]) or \
                os.path.basename(self.disk.paths[0])

            if self.disk.parser.casename == case_name:  # the casename is already in the path in this case
                pretty_label = "{0}-{1}".format(self.index, self.get_safe_label() or self.fstype or 'volume')
            else:
                pretty_label = "{0}-{1}-{2}".format(case_name, self.index,
                                                    self.get_safe_label() or self.fstype or 'volume')
            if suffix:
                pretty_label += "-" + suffix
            path = os.path.join(md, pretty_label)

            # check if path already exists, otherwise try to find another nice path
            if os.path.exists(path):
                for i in range(2, 100):
                    path = os.path.join(md, pretty_label + "-" + str(i))
                    if not os.path.exists(path):
                        break
                else:
                    logger.error("Could not find free mountdir.")
                    raise NoMountpointAvailableError()

            # noinspection PyBroadException
            try:
                os.mkdir(path, 777)
                if in_paths:
                    self._paths[var_name] = path
                else:
                    setattr(self, var_name, path)
                return path
            except Exception:
                logger.exception("Could not create mountdir.")
                raise NoMountpointAvailableError()
        else:
            t = tempfile.mkdtemp(prefix='im_' + self.index + '_',
                                 suffix='_' + self.get_safe_label() + ("_" + suffix if suffix else ""),
                                 dir=parser.mountdir)
            if in_paths:
                self._paths[var_name] = t
            else:
                setattr(self, var_name, t)
            return t

    def _find_loopback(self, use_loopback=True, var_name='loopback'):
        """Finds a free loopback device that can be used. The loopback is stored in :attr:`loopback`. If *use_loopback*
        is True, the loopback will also be used directly.

        :returns: the loopback address
        :raises NoLoopbackAvailableError: if no loopback could be found
        """

        # noinspection PyBroadException
        try:
            loopback = _util.check_output_(['losetup', '-f']).strip()
            setattr(self, var_name, loopback)
        except Exception:
            logger.warning("No free loopback device found.", exc_info=True)
            raise NoLoopbackAvailableError()

        # noinspection PyBroadException
        if use_loopback:
            try:
                cmd = ['losetup', '-o', str(self.offset), '--sizelimit', str(self.size),
                       loopback, self.get_raw_path()]
                if not self.disk.read_write:
                    cmd.insert(1, '-r')
                _util.check_call_(cmd, stdout=subprocess.PIPE)
            except Exception:
                logger.exception("Loopback device could not be mounted.")
                raise NoLoopbackAvailableError()
        return loopback

    def _free_loopback(self, var_name='loopback'):
        if getattr(self, var_name):
            _util.check_call_(['losetup', '-d', getattr(self, var_name)], wrap_error=True)
            setattr(self, var_name, "")

    def determine_fs_type(self):
        """Determines the FS type for this partition. This function is used internally to determine which mount system
        to use, based on the file system description. Return values include *ext*, *ufs*, *ntfs*, *lvm* and *luks*.

        Note: does not do anything if fstype is already set to something sensible.
        """

        fstype_fallback = self.fstype[1:] if self.fstype and self.fstype.startswith("?") else ""

        # Determine fs type. If forced, always use provided type.
        if self.fstype in FILE_SYSTEM_TYPES:
            pass  # already correctly set
        elif self.fstype in VOLUME_SYSTEM_TYPES:
            self.volumes.vstype = self.fstype
            self.fstype = 'volumesystem'
        else:
            last_resort = None  # use this if we can't determine the FS type more reliably
            # we have two possible sources for determining the FS type: the description given to us by the detection
            # method, and the type given to us by the stat function
            for fsdesc in (self.info.get('fsdescription'), self.info.get('guid'),
                           self._get_blkid_type, self._get_magic_type):
                # For efficiency reasons, not all functions are called instantly.
                if callable(fsdesc):
                    fsdesc = fsdesc()
                logger.debug("Trying to determine fs type from '{}'".format(fsdesc))
                if not fsdesc:
                    continue
                fsdesc = fsdesc.lower()

                # for the purposes of this function, logical volume is nothing, and 'primary' is rather useless info
                if fsdesc in ('logical volume', 'luks volume', 'bde volume', 'raid volume',
                              'primary', 'basic data partition', 'vss store'):
                    continue

                if fsdesc == 'directory':
                    self.fstype = 'dir'  # dummy fs type
                elif re.search(r'\bext[0-9]*\b', fsdesc):
                    self.fstype = 'ext'
                elif '4.2bsd' in fsdesc or 'ufs 2' in fsdesc:
                    self.fstype = 'ufs'
                elif 'bsd' in fsdesc:
                    self.fstype = 'volumesystem'
                    self.volumes.fstype = 'bsd'
                elif 'ntfs / exfat' in fsdesc:
                    last_resort = 'ntfs'
                    continue
                elif 'ntfs' in fsdesc:
                    self.fstype = 'ntfs'
                elif 'exfat' in fsdesc:
                    self.fstype = 'exfat'
                elif '0x8e' in fsdesc or 'lvm' in fsdesc:
                    self.fstype = 'lvm'
                elif 'squashfs' in fsdesc:  # before hfs
                    self.fstype = 'squashfs'
                elif 'hfs+' in fsdesc:
                    self.fstype = 'hfs+'
                elif 'hfs' in fsdesc:
                    self.fstype = 'hfs'
                elif 'luks' in fsdesc:
                    self.fstype = 'luks'
                elif 'fat' in fsdesc or 'efi system partition' in fsdesc:
                    # based on http://en.wikipedia.org/wiki/EFI_System_partition, efi is always fat.
                    self.fstype = 'fat'
                elif 'iso 9660' in fsdesc or 'iso9660' in fsdesc:
                    self.fstype = 'iso'
                elif 'linux compressed rom file system' in fsdesc or 'cramfs' in fsdesc:
                    self.fstype = 'cramfs'
                elif fsdesc.startswith("sgi xfs") or re.search(r'\bxfs\b', fsdesc):
                    self.fstype = "xfs"
                elif 'swap file' in fsdesc or 'linux swap' in fsdesc or 'linux-swap' in fsdesc or 'swap (0x01)' in fsdesc:
                    self.fstype = 'swap'
                elif "jffs2" in fsdesc:
                    self.fstype = 'jffs2'
                elif "minix filesystem" in fsdesc:
                    self.fstype = 'minix'
                elif 'vmfs_volume_member' in fsdesc:
                    self.fstype = 'vmfs'
                elif 'linux_raid_member' in fsdesc or 'linux software raid' in fsdesc:
                    self.fstype = 'raid'
                # dos/mbr boot sector is shown for a lot of types, not just for volume system, so we ignore this for now
                # elif "dos/mbr boot sector" in fsdesc:
                #     self.fstype = 'volumesystem'
                #     self.volumes.vstype = 'detect'
                elif fsdesc in FILE_SYSTEM_TYPES:
                    # fallback for stupid cases where we can not determine 'ufs' from the fsdesc 'ufs'
                    self.fstype = fsdesc
                elif fsdesc in VOLUME_SYSTEM_TYPES:
                    self.fstype = 'volumesystem'
                    self.volumes.vstype = fsdesc
                elif fsdesc.upper() in FILE_SYSTEM_GUIDS:
                    # this is a bit of a workaround for the fill_guid method
                    self.fstype = FILE_SYSTEM_GUIDS[fsdesc.upper()]
                elif '0x83' in fsdesc:
                    # this is a linux mount, but we can't figure out which one.
                    # we hand it off to the OS, maybe it can try something.
                    # if we use last_resort for more enhanced stuff, we may need to check if we are not setting
                    # it to something less specific here
                    last_resort = 'unknown'
                    continue
                else:
                    continue  # this loop failed

                logger.info("Detected {0} as {1}".format(fsdesc, self.fstype))

                if isinstance(self.parent, Volume) and \
                        self.parent.offset == self.offset and \
                        self.size == self.parent.size and \
                        self.fstype == self.parent.fstype and \
                        self.volumes.vstype == self.parent.volumes.vstype and \
                        self.get_raw_path() == self.parent.get_raw_path():
                    logger.warning("Detected volume type is identical to the parent. This makes little sense. "
                                   "Assuming detection was wrong.")
                    continue

                break  # we found something
            else:  # we found nothing
                # if last_resort is something more sensible than unknown, we use that
                # if we have specified a fsfallback which is not set to None, we use that
                # if last_resort is unknown or the fallback is not None, we use unknown
                if last_resort and last_resort != 'unknown':
                    self.fstype = last_resort
                elif fstype_fallback:
                    self.fstype = fstype_fallback
                elif last_resort == 'unknown' or not fstype_fallback:
                    self.fstype = 'unknown'

        return self.fstype

    def mount(self, fstype=None):
        """Based on the file system type as determined by :func:`determine_fs_type`, the proper mount command is executed
        for this volume. The volume is mounted in a temporary path (or a pretty path if :attr:`pretty` is enabled) in
        the mountpoint as specified by :attr:`mountpoint`.

        If the file system type is a LUKS container or LVM, additional methods may be called, adding subvolumes to
        :attr:`volumes`

        :raises NotMountedError: if the parent volume/disk is not mounted
        :raises NoMountpointAvailableError: if no mountpoint was found
        :raises NoLoopbackAvailableError: if no loopback device was found
        :raises UnsupportedFilesystemError: if the fstype is not supported for mounting
        :raises SubsystemError: if one of the underlying commands failed
        """

        if not self.parent.is_mounted:
            raise NotMountedError(self.parent)

        raw_path = self.get_raw_path()
        if fstype is None:
            fstype = self.determine_fs_type()
        self._load_fsstat_data()

        # we need a mountpoint if it is not a lvm or luks volume
        if fstype not in ('luks', 'lvm', 'bde', 'raid', 'volumesystem') and \
                fstype in FILE_SYSTEM_TYPES:
            self._make_mountpoint()

        # Prepare mount command
        try:
            def call_mount(type, opts):
                cmd = ['mount', raw_path, self.mountpoint, '-t', type, '-o', opts]
                if not self.disk.read_write:
                    cmd[-1] += ',ro'

                _util.check_output_(cmd, stderr=subprocess.STDOUT)

            if fstype == 'ext':
                call_mount('ext4', 'noexec,noload,loop,offset=' + str(self.offset) + ',sizelimit=' + str(self.size))

            elif fstype == 'ufs':
                # TODO: support for other ufstypes
                call_mount('ufs', 'ufstype=ufs2,loop,offset=' + str(self.offset) + ',sizelimit=' + str(self.size))

            elif fstype == 'ntfs':
                call_mount('ntfs', 'show_sys_files,noexec,force,loop,streams_interface=windows,offset=' + str(self.offset) + ',sizelimit=' + str(self.size))

            elif fstype == 'exfat':
                call_mount('exfat', 'noexec,force,loop,offset=' + str(self.offset) + ',sizelimit=' + str(self.size))

            elif fstype == 'xfs':
                call_mount('xfs', 'norecovery,loop,offset=' + str(self.offset) + ',sizelimit=' + str(self.size))

            elif fstype == 'hfs+':
                call_mount('hfsplus', 'force,loop,offset=' + str(self.offset) + ',sizelimit=' + str(self.size))

            elif fstype in ('iso', 'udf', 'squashfs', 'cramfs', 'minix', 'fat', 'hfs'):
                mnt_type = {'iso': 'iso9660', 'fat': 'vfat'}.get(fstype, fstype)
                call_mount(mnt_type, 'loop,offset=' + str(self.offset) + ',sizelimit=' + str(self.size))

            elif fstype == 'vmfs':
                self._find_loopback()
                _util.check_call_(['vmfs-fuse', self.loopback, self.mountpoint], stdout=subprocess.PIPE)

            elif fstype == 'unknown':  # mounts without specifying the filesystem type
                cmd = ['mount', raw_path, self.mountpoint, '-o', 'loop,offset=' + str(self.offset) + ',sizelimit=' + str(self.size)]
                if not self.disk.read_write:
                    cmd[-1] += ',ro'

                _util.check_call_(cmd, stdout=subprocess.PIPE)

            elif fstype == 'jffs2':
                self._open_jffs2()

            elif fstype == 'luks':
                self._open_luks_container()

            elif fstype == 'bde':
                self._open_bde_container()

            elif fstype == 'lvm':
                self._open_lvm()
                self.volumes.vstype = 'lvm'
                for _ in self.volumes.detect_volumes('lvm'):
                    pass

            elif fstype == 'raid':
                self._open_raid_volume()

            elif fstype == 'dir':
                os.rmdir(self.mountpoint)
                os.symlink(raw_path, self.mountpoint)

            elif fstype == 'volumesystem':
                for _ in self.volumes.detect_volumes():
                    pass

            else:
                try:
                    size = self.size // self.disk.block_size
                except TypeError:
                    size = self.size

                logger.warning("Unsupported filesystem {0} (type: {1}, block offset: {2}, length: {3})"
                               .format(self, fstype, self.offset // self.disk.block_size, size))
                raise UnsupportedFilesystemError(fstype)

            self.was_mounted = True
            self.is_mounted = True
            self.fstype = fstype
        except Exception as e:
            logger.exception("Execution failed due to {} {}".format(type(e), e), exc_info=True)
            try:
                if self.mountpoint:
                    os.rmdir(self.mountpoint)
                    self.mountpoint = ""
                if self.loopback:
                    self.loopback = ""
            except Exception:
                logger.exception("Clean-up failed", exc_info=True)

            if not isinstance(e, ImageMounterError):
                raise SubsystemError(e)
            else:
                raise

    def bindmount(self, mountpoint):
        """Bind mounts the volume to another mountpoint. Only works if the volume is already mounted.

        :raises NotMountedError: when the volume is not yet mounted
        :raises SubsystemError: when the underlying command failed
        """

        if not self.mountpoint:
            raise NotMountedError(self)
        try:
            _util.check_call_(['mount', '--bind', self.mountpoint, mountpoint], stdout=subprocess.PIPE)
            if 'bindmounts' in self._paths:
                self._paths['bindmounts'].append(mountpoint)
            else:
                self._paths['bindmounts'] = [mountpoint]
            return True
        except Exception as e:
            logger.exception("Error bind mounting {0}.".format(self))
            raise SubsystemError(e)

    def _open_luks_container(self):
        """Command that is an alternative to the :func:`mount` command that opens a LUKS container. The opened volume is
        added to the subvolume set of this volume. Requires the user to enter the key manually.

        TODO: add support for :attr:`keys`

        :return: the Volume contained in the LUKS container, or None on failure.
        :raises NoLoopbackAvailableError: when no free loopback could be found
        :raises IncorrectFilesystemError: when this is not a LUKS volume
        :raises SubsystemError: when the underlying command fails
        """

        # Open a loopback device
        self._find_loopback()

        # Check if this is a LUKS device
        # noinspection PyBroadException
        try:
            _util.check_call_(["cryptsetup", "isLuks", self.loopback], stderr=subprocess.STDOUT)
            # ret = 0 if isLuks
        except Exception:
            logger.warning("Not a LUKS volume")
            # clean the loopback device, we want this method to be clean as possible
            # noinspection PyBroadException
            try:
                self._free_loopback()
            except Exception:
                pass
            raise IncorrectFilesystemError()

        try:
            extra_args = []
            key = None
            if self.key:
                t, v = self.key.split(':', 1)
                if t == 'p':  # passphrase
                    key = v
                elif t == 'f':  # key-file
                    extra_args = ['--key-file', v]
                elif t == 'm':  # master-key-file
                    extra_args = ['--master-key-file', v]
            else:
                logger.warning("No key material provided for %s", self)
        except ValueError:
            logger.exception("Invalid key material provided (%s) for %s. Expecting [arg]:[value]", self.key, self)
            self._free_loopback()
            raise ArgumentError()

        # Open the LUKS container
        self._paths['luks'] = 'image_mounter_luks_' + str(random.randint(10000, 99999))

        # noinspection PyBroadException
        try:
            cmd = ["cryptsetup", "luksOpen", self.loopback, self._paths['luks']]
            cmd.extend(extra_args)
            if not self.disk.read_write:
                cmd.insert(1, '-r')

            if key is not None:
                logger.debug('$ {0}'.format(' '.join(cmd)))
                # for py 3.2+, we could have used input=, but that doesn't exist in py2.7.
                p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                p.communicate(key.encode("utf-8"))
                p.wait()
                retcode = p.poll()
                if retcode:
                    raise KeyInvalidError()
            else:
                _util.check_call_(cmd)
        except ImageMounterError:
            del self._paths['luks']
            self._free_loopback()
            raise
        except Exception as e:
            del self._paths['luks']
            self._free_loopback()
            raise SubsystemError(e)

        size = None
        # noinspection PyBroadException
        try:
            result = _util.check_output_(["cryptsetup", "status", self._paths['luks']])
            for l in result.splitlines():
                if "size:" in l and "key" not in l:
                    size = int(l.replace("size:", "").replace("sectors", "").strip()) * self.disk.block_size
        except Exception:
            pass

        container = self.volumes._make_single_subvolume(flag='alloc', offset=0, size=size)
        container.info['fsdescription'] = 'LUKS Volume'

        return container

    def _open_bde_container(self):
        """Mounts a BDE container. Uses key material provided by the :attr:`keys` attribute. The key material should be
        provided in the same format as to :cmd:`bdemount`, used as follows:

        k:full volume encryption and tweak key
        p:passphrase
        r:recovery password
        s:file to startup key (.bek)

        :return: the Volume contained in the BDE container
        :raises ArgumentError: if the keys argument is invalid
        :raises SubsystemError: when the underlying command fails
        """

        self._paths['bde'] = tempfile.mkdtemp(prefix='image_mounter_bde_')

        try:
            if self.key:
                t, v = self.key.split(':', 1)
                key = ['-' + t, v]
            else:
                logger.warning("No key material provided for %s", self)
                key = []
        except ValueError:
            logger.exception("Invalid key material provided (%s) for %s. Expecting [arg]:[value]", self.key, self)
            raise ArgumentError()

        # noinspection PyBroadException
        try:
            cmd = ["bdemount", self.get_raw_path(), self._paths['bde'], '-o', str(self.offset)]
            cmd.extend(key)
            _util.check_call_(cmd)
        except Exception as e:
            del self._paths['bde']
            logger.exception("Failed mounting BDE volume %s.", self)
            raise SubsystemError(e)

        container = self.volumes._make_single_subvolume(flag='alloc', offset=0, size=self.size)
        container.info['fsdescription'] = 'BDE Volume'

        return container

    def _open_jffs2(self):
        """Perform specific operations to mount a JFFS2 image. This kind of image is sometimes used for things like
        bios images. so external tools are required but given this method you don't have to memorize anything and it
        works fast and easy.

        Note that this module might not yet work while mounting multiple images at the same time.
        """
        # we have to make a ram-device to store the image, we keep 20% overhead
        size_in_kb = int((self.size / 1024) * 1.2)
        _util.check_call_(['modprobe', '-v', 'mtd'])
        _util.check_call_(['modprobe', '-v', 'jffs2'])
        _util.check_call_(['modprobe', '-v', 'mtdram', 'total_size={}'.format(size_in_kb), 'erase_size=256'])
        _util.check_call_(['modprobe', '-v', 'mtdblock'])
        _util.check_call_(['dd', 'if=' + self.get_raw_path(), 'of=/dev/mtd0'])
        _util.check_call_(['mount', '-t', 'jffs2', '/dev/mtdblock0', self.mountpoint])

    def _open_lvm(self):
        """Performs mount actions on a LVM. Scans for active volume groups from the loopback device, activates it
        and fills :attr:`volumes` with the logical volumes.

        :raises NoLoopbackAvailableError: when no loopback was available
        :raises IncorrectFilesystemError: when the volume is not a volume group
        """
        os.environ['LVM_SUPPRESS_FD_WARNINGS'] = '1'

        # find free loopback device
        self._find_loopback()
        time.sleep(0.2)

        try:
            # Scan for new lvm volumes
            result = _util.check_output_(["lvm", "pvscan"])
            for l in result.splitlines():
                if self.loopback in l or (self.offset == 0 and self.get_raw_path() in l):
                    for vg in re.findall(r'VG (\S+)', l):
                        self.info['volume_group'] = vg

            if not self.info.get('volume_group'):
                logger.warning("Volume is not a volume group. (Searching for %s)", self.loopback)
                raise IncorrectFilesystemError()

            # Enable lvm volumes
            _util.check_call_(["lvm", "vgchange", "-a", "y", self.info['volume_group']], stdout=subprocess.PIPE)
        except Exception:
            self._free_loopback()
            raise

    def _open_raid_volume(self):
        """Add the volume to a RAID system. The RAID array is activated as soon as the array can be activated.

        :raises NoLoopbackAvailableError: if no loopback device was found
        """

        self._find_loopback()

        raid_status = None
        try:
            # use mdadm to mount the loopback to a md device
            # incremental and run as soon as available
            output = _util.check_output_(['mdadm', '-IR', self.loopback], stderr=subprocess.STDOUT)

            match = re.findall(r"attached to ([^ ,]+)", output)
            if match:
                self._paths['md'] = os.path.realpath(match[0])
                if 'which is already active' in output:
                    logger.info("RAID is already active in other volume, using %s", self._paths['md'])
                    raid_status = 'active'
                elif 'not enough to start' in output:
                    self._paths['md'] = self._paths['md'].replace("/dev/md/", "/dev/md")
                    logger.info("RAID volume added, but not enough to start %s", self._paths['md'])
                    raid_status = 'waiting'
                else:
                    logger.info("RAID started at {0}".format(self._paths['md']))
                    raid_status = 'active'
        except Exception as e:
            logger.exception("Failed mounting RAID.")
            self._free_loopback()
            raise SubsystemError(e)

        # search for the RAID volume
        for v in self.disk.parser.get_volumes():
            if v._paths.get("md") == self._paths['md'] and v.volumes:
                logger.debug("Adding existing volume %s to volume %s", v.volumes[0], self)
                v.volumes[0].info['raid_status'] = raid_status
                self.volumes.volumes.append(v.volumes[0])
                return v.volumes[0]
        else:
            logger.debug("Creating RAID volume for %s", self)
            container = self.volumes._make_single_subvolume(flag='alloc', offset=0, size=self.size)
            container.info['fsdescription'] = 'RAID Volume'
            container.info['raid_status'] = raid_status
            return container

    def get_volumes(self):
        """Recursively gets a list of all subvolumes and the current volume."""

        if self.volumes:
            volumes = []
            for v in self.volumes:
                volumes.extend(v.get_volumes())
            volumes.append(self)
            return volumes
        else:
            return [self]

    def _load_fsstat_data(self, timeout=3):
        """Using :command:`fsstat`, adds some additional information of the volume to the Volume."""

        if not _util.command_exists('fsstat'):
            logger.warning("fsstat is not installed, could not mount volume shadow copies")
            return

        def stats_thread():
            try:
                cmd = ['fsstat', self.get_raw_path(), '-o', str(self.offset // self.disk.block_size)]

                # Setting the fstype explicitly makes fsstat much faster and more reliable
                # In some versions, the auto-detect yaffs2 check takes ages for large images
                fstype = {
                    "ntfs": "ntfs", "fat": "fat", "ext": "ext", "iso": "iso9660", "hfs+": "hfs",
                    "ufs": "ufs", "swap": "swap", "exfat": "exfat",
                }.get(self.fstype, None)
                if fstype:
                    cmd.extend(["-f", fstype])

                logger.debug('$ {0}'.format(' '.join(cmd)))
                stats_thread.process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

                for line in iter(stats_thread.process.stdout.readline, b''):
                    line = line.decode('utf-8')
                    logger.debug('< {0}'.format(line))
                    if line.startswith("File System Type:"):
                        self.info['statfstype'] = line[line.index(':') + 2:].strip()
                    elif line.startswith("Last Mount Point:") or line.startswith("Last mounted on:"):
                        self.info['lastmountpoint'] = line[line.index(':') + 2:].strip().replace("//", "/")
                    elif line.startswith("Volume Name:") and not self.info.get('label'):
                        self.info['label'] = line[line.index(':') + 2:].strip()
                    elif line.startswith("Version:"):
                        self.info['version'] = line[line.index(':') + 2:].strip()
                    elif line.startswith("Source OS:"):
                        self.info['version'] = line[line.index(':') + 2:].strip()
                    elif 'CYLINDER GROUP INFORMATION' in line or 'BLOCK GROUP INFORMATION' in line:
                        # noinspection PyBroadException
                        try:
                            stats_thread.process.terminate()
                            logger.debug("Terminated fsstat at cylinder/block group information.")
                        except Exception:
                            pass
                        break

                if self.info.get('lastmountpoint') and self.info.get('label'):
                    self.info['label'] = "{0} ({1})".format(self.info['lastmountpoint'], self.info['label'])
                elif self.info.get('lastmountpoint') and not self.info.get('label'):
                    self.info['label'] = self.info['lastmountpoint']
                elif not self.info.get('lastmountpoint') and self.info.get('label') and \
                        self.info['label'].startswith("/"):  # e.g. /boot1
                    if self.info['label'].endswith("1"):
                        self.info['lastmountpoint'] = self.info['label'][:-1]
                    else:
                        self.info['lastmountpoint'] = self.info['label']

            except Exception:  # ignore any exceptions here.
                logger.exception("Error while obtaining stats.")

        stats_thread.process = None

        thread = threading.Thread(target=stats_thread)
        thread.start()
        thread.join(timeout)
        if thread.is_alive():
            # noinspection PyBroadException
            try:
                stats_thread.process.terminate()
            except Exception:
                pass
            thread.join()
            logger.debug("Killed fsstat after {0}s".format(timeout))

    def detect_mountpoint(self):
        """Attempts to detect the previous mountpoint if this was not done through :func:`load_fsstat_data`. This
        detection does some heuristic method on the mounted volume.
        """

        if self.info.get('lastmountpoint'):
            return self.info.get('lastmountpoint')
        if not self.mountpoint:
            return None

        result = None
        paths = os.listdir(self.mountpoint)
        if 'grub' in paths:
            result = '/boot'
        elif 'usr' in paths and 'var' in paths and 'root' in paths:
            result = '/'
        elif 'bin' in paths and 'lib' in paths and 'local' in paths and 'src' in paths and 'usr' not in paths:
            result = '/usr'
        elif 'bin' in paths and 'lib' in paths and 'local' not in paths and 'src' in paths and 'usr' not in paths:
            result = '/usr/local'
        elif 'lib' in paths and 'local' in paths and 'tmp' in paths and 'var' not in paths:
            result = '/var'
        # elif sum(['bin' in paths, 'boot' in paths, 'cdrom' in paths, 'dev' in paths, 'etc' in paths, 'home' in paths,
        #          'lib' in paths, 'lib64' in paths, 'media' in paths, 'mnt' in paths, 'opt' in paths,
        #          'proc' in paths, 'root' in paths, 'sbin' in paths, 'srv' in paths, 'sys' in paths, 'tmp' in paths,
        #          'usr' in paths, 'var' in paths]) > 11:
        #    result = '/'

        if result:
            self.info['lastmountpoint'] = result
            if not self.info.get('label'):
                self.info['label'] = self.info['lastmountpoint']
            logger.info("Detected mountpoint as {0} based on files in volume".format(self.info['lastmountpoint']))

        return result

    # noinspection PyBroadException
    def unmount(self, allow_lazy=False):
        """Unounts the volume from the filesystem.

        :raises SubsystemError: if one of the underlying processes fails
        :raises CleanupError: if the cleanup fails
        """

        for volume in self.volumes:
            try:
                volume.unmount(allow_lazy=allow_lazy)
            except ImageMounterError:
                pass

        if self.is_mounted:
            logger.info("Unmounting volume %s", self)

        if self.loopback and self.info.get('volume_group'):
            _util.check_call_(["lvm", 'vgchange', '-a', 'n', self.info['volume_group']],
                              wrap_error=True, stdout=subprocess.PIPE)
            self.info['volume_group'] = ""

        if self.loopback and self._paths.get('luks'):
            _util.check_call_(['cryptsetup', 'luksClose', self._paths['luks']], wrap_error=True, stdout=subprocess.PIPE)
            del self._paths['luks']

        if self._paths.get('bde'):
            try:
                _util.clean_unmount(['fusermount', '-u'], self._paths['bde'])
            except SubsystemError:
                if not allow_lazy:
                    raise
                _util.clean_unmount(['fusermount', '-uz'], self._paths['bde'])
            del self._paths['bde']

        if self._paths.get('md'):
            md_path = self._paths['md']
            del self._paths['md']  # removing it here to ensure we do not enter an infinite loop, will add it back later

            # MD arrays are a bit complicated, we also check all other volumes that are part of this array and
            # unmount them as well.
            logger.debug("All other volumes that use %s as well will also be unmounted", md_path)
            for v in self.disk.get_volumes():
                if v != self and v._paths.get('md') == md_path:
                    v.unmount(allow_lazy=allow_lazy)

            try:
                _util.check_output_(["mdadm", '--stop', md_path], stderr=subprocess.STDOUT)
            except Exception as e:
                self._paths['md'] = md_path
                raise SubsystemError(e)

        if self._paths.get('vss'):
            try:
                _util.clean_unmount(['fusermount', '-u'], self._paths['vss'])
            except SubsystemError:
                if not allow_lazy:
                    raise
                _util.clean_unmount(['fusermount', '-uz'], self._paths['vss'])
            del self._paths['vss']

        if self.loopback:
            _util.check_call_(['losetup', '-d', self.loopback], wrap_error=True)
            self.loopback = ""

        if self._paths.get('bindmounts'):
            for mp in self._paths['bindmounts']:
                _util.clean_unmount(['umount'], mp, rmdir=False)
            del self._paths['bindmounts']

        if self.mountpoint:
            _util.clean_unmount(['umount'], self.mountpoint)
            self.mountpoint = ""

        if self._paths.get('carve'):
            try:
                shutil.rmtree(self._paths['carve'])
            except OSError as e:
                raise SubsystemError(e)
            else:
                del self._paths['carve']

        self.is_mounted = False
