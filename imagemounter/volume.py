import collections
import io
import logging
import os
import subprocess
import re
import tempfile
import threading
import shutil
import warnings

from imagemounter import _util, filesystems, FILE_SYSTEM_TYPES, VOLUME_SYSTEM_TYPES, dependencies
from imagemounter.exceptions import NoMountpointAvailableError, SubsystemError, \
    NoLoopbackAvailableError, NotMountedError, \
    ImageMounterError
from imagemounter.volume_system import VolumeSystem

logger = logging.getLogger(__name__)


class Volume(object):
    """Information about a volume. Note that every detected volume gets their own Volume object, though it may or may
    not be mounted. This can be seen through the :attr:`mountpoint` attribute -- if it is not set, perhaps the
    :attr:`exception` attribute is set with an exception.
    """

    def __init__(self, disk, parent=None, index="0", size=0, offset=0, flag='alloc', slot=0, fstype=None, key="",
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
        :param FileSystem fstype: the fstype you wish to use for this Volume.
            If not specified, will be retrieved from the ImageParser instance instead.
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

    @property
    def fstype(self):
        warnings.warn("fstype is deprecated in favor of filesystem", DeprecationWarning)
        return self.filesystem

    def _get_fstype_from_parser(self, fstype=None):
        """Load fstype information from the parser instance."""
        if not fstype:
            if self.index in self.disk.parser.fstypes:
                fstype = self.disk.parser.fstypes[self.index]
            elif '*' in self.disk.parser.fstypes:
                fstype = self.disk.parser.fstypes['*']
            elif '?' in self.disk.parser.fstypes and self.disk.parser.fstypes['?'] is not None:
                fstype = "?" + self.disk.parser.fstypes['?']
            else:
                fstype = ""

        if not fstype:
            self.filesystem = None
        elif fstype in VOLUME_SYSTEM_TYPES:
            self.volumes.vstype = fstype
            self.filesystem = FILE_SYSTEM_TYPES["volumesystem"](self)
        elif fstype.startswith("?"):
            fallback = FILE_SYSTEM_TYPES[fstype[1:]](self)
            self.filesystem = filesystems.FallbackFileSystem(self, fallback)
        else:
            self.filesystem = FILE_SYSTEM_TYPES[fstype](self)

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

    @dependencies.require(dependencies.blkid, none_on_failure=True)
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

    @dependencies.require(dependencies.magic, none_on_failure=True)
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

    @dependencies.require(dependencies.photorec)
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

        self._paths['carve'] = self._make_mountpoint(suffix="carve")

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

    @dependencies.require(dependencies.vshadowmount)
    def detect_volume_shadow_copies(self):
        """Method to call vshadowmount and mount NTFS volume shadow copies.

        :return: iterable with the :class:`Volume` objects of the VSS
        :raises CommandNotFoundError: if the underlying command does not exist
        :raises SubSystemError: if the underlying command fails
        :raises NoMountpointAvailableError: if there is no mountpoint available
        """

        self._paths['vss'] = self._make_mountpoint(suffix="vss")

        try:
            _util.check_call_(["vshadowmount", "-o", str(self.offset), self.get_raw_path(), self._paths['vss']])
        except Exception as e:
            logger.exception("Failed mounting the volume shadow copies.")
            raise SubsystemError(e)
        else:
            return self.volumes.detect_volumes(vstype='vss')

    def _should_mount(self, only_mount=None, skip_mount=None):
        """Indicates whether this volume should be mounted. Internal method, used by imount.py"""

        om = only_mount is None \
            or self.index in only_mount \
            or self.info.get('lastmountpoint') in only_mount \
            or self.info.get('label') in only_mount
        sm = skip_mount is None \
            or (self.index not in skip_mount
             and self.info.get('lastmountpoint') not in skip_mount
             and self.info.get('label') not in skip_mount)
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
                yield from v.init(only_mount, skip_mount, swallow_exceptions)

    def init_volume(self):
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
        self.mount()
        self.detect_mountpoint()

        return True

    def _make_mountpoint(self, casename=None, suffix=''):
        """Creates a directory that can be used as a mountpoint.

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

            fstype = self.filesystem.type if self.filesystem is not None else None
            if self.disk.parser.casename == case_name:  # the casename is already in the path in this case
                pretty_label = "{0}-{1}".format(self.index, self.get_safe_label() or fstype or 'volume')
            else:
                pretty_label = "{0}-{1}-{2}".format(case_name, self.index,
                                                    self.get_safe_label() or fstype or 'volume')
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
                return path
            except Exception:
                logger.exception("Could not create mountdir.")
                raise NoMountpointAvailableError()
        else:
            t = tempfile.mkdtemp(prefix='im_' + self.index + '_',
                                 suffix='_' + self.get_safe_label() + ("_" + suffix if suffix else ""),
                                 dir=parser.mountdir)
            return t

    def _clear_mountpoint(self):
        """Clears a created mountpoint. Does not unmount it, merely deletes it."""

        if self.mountpoint:
            os.rmdir(self.mountpoint)
            self.mountpoint = ""

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

        fstype_fallback = None
        if isinstance(self.filesystem, filesystems.FallbackFileSystem):
            fstype_fallback = self.filesystem.fallback
        elif isinstance(self.filesystem, filesystems.FileSystem):
            return self.filesystem

        result = collections.Counter()

        for source, description in (('fsdescription', self.info.get('fsdescription')),
                                    ('guid', self.info.get('guid')),
                                    ('blikid', self._get_blkid_type),
                                    ('magic', self._get_magic_type)):
            # For efficiency reasons, not all functions are called instantly.
            if callable(description):
                description = description()

            logger.debug("Trying to determine fs type from {} '{}'".format(source, description))
            if not description:
                continue

            # Iterate over all results and update the certainty of all FS types
            for type in FILE_SYSTEM_TYPES.values():
                result.update(type.detect(source, description))

            # Now sort the results by their certainty
            logger.debug("Current certainty levels: {}".format(result))

            # If we have not found any candidates, we continue
            if not result:
                continue

            # If we have candidates of which we are not entirely certain, we just continue
            max_res = result.most_common(1)[0][1]
            if max_res < 50:
                logger.debug("Highest certainty item is lower than 50, continuing...")
            # If we have multiple candidates with the same score, we just continue
            elif len([True for type, certainty in result.items() if certainty == max_res]) > 1:
                logger.debug("Multiple items with highest certainty level, so continuing...")
            else:
                self.filesystem = result.most_common(1)[0][0](self)
                return self.filesystem

        # Now be more lax with the fallback:
        if result:
            max_res = result.most_common(1)[0][1]
            if max_res > 0:
                self.filesystem = result.most_common(1)[0][0](self)
                return self.filesystem
        if fstype_fallback:
            self.filesystem = fstype_fallback
            return self.filesystem

    def mount(self):
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

        self.filesystem = self.determine_fs_type()
        self._load_fsstat_data()

        # Prepare mount command
        try:
            self.filesystem.mount()

            self.was_mounted = True
            self.is_mounted = True

        except Exception as e:
            logger.exception("Execution failed due to {} {}".format(type(e), e), exc_info=True)
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

    @dependencies.require(dependencies.fsstat, none_on_failure=True)
    def _load_fsstat_data(self, timeout=3):
        """Using :command:`fsstat`, adds some additional information of the volume to the Volume."""

        def stats_thread():
            try:
                cmd = ['fsstat', self.get_raw_path(), '-o', str(self.offset // self.disk.block_size)]

                # Setting the fstype explicitly makes fsstat much faster and more reliable
                # In some versions, the auto-detect yaffs2 check takes ages for large images
                fstype = {
                    "ntfs": "ntfs", "fat": "fat", "ext": "ext", "iso": "iso9660", "hfs+": "hfs",
                    "ufs": "ufs", "swap": "swap", "exfat": "exfat",
                }.get(self.filesystem.type, None)
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

        if self._paths.get('vss'):
            try:
                _util.clean_unmount(['fusermount', '-u'], self._paths['vss'])
            except SubsystemError:
                if not allow_lazy:
                    raise
                _util.clean_unmount(['fusermount', '-uz'], self._paths['vss'])
            del self._paths['vss']

        if self._paths.get('bindmounts'):
            for mp in self._paths['bindmounts']:
                _util.clean_unmount(['umount'], mp, rmdir=False)
            del self._paths['bindmounts']

        if self._paths.get('carve'):
            try:
                shutil.rmtree(self._paths['carve'])
            except OSError as e:
                raise SubsystemError(e)
            else:
                del self._paths['carve']

        self.filesystem.unmount(allow_lazy=allow_lazy)

        self.is_mounted = False
