from __future__ import print_function
from __future__ import unicode_literals
from collections import defaultdict

import glob
import logging
import os
import re
import subprocess
import tempfile
import time

from imagemounter import _util, BLOCK_SIZE
from imagemounter.volume_system import VolumeSystem

logger = logging.getLogger(__name__)


class Disk(object):
    """Representation of a disk, image file or anything else that can be considered a disk. """

    # noinspection PyUnusedLocal
    def __init__(self, parser, path, offset=0, read_write=False, method='auto',
                 multifile=True, index=None, mount_directories=True, **args):
        """Instantiation of this class does not automatically mount, detect or analyse the disk. You will need the
        :func:`init` method for this.

        Only use arguments offset and further as keyword arguments.

        :param parser: the parent parser
        :type parser: :class:`ImageParser`
        :param int offset: offset of the disk where the volume (system) resides
        :param bool read_write: indicates whether the disk should be mounted with a read-write cache enabled
        :param str method: the method to mount the base image with
        :param bool multifile: indicates whether :func:`mount` should attempt to call the underlying mount method with
                all files of a split file when passing a single file does not work
        :param str index: the base index of this Disk
        :param bool mount_directories: indicates whether directories should also be 'mounted'
        :param args: arguments that should be passed down to :class:`Volume` objects
        """

        self.parser = parser

        # Find the type and the paths
        path = os.path.expandvars(os.path.expanduser(path))
        if _util.is_encase(path):
            self.type = 'encase'
        elif _util.is_vmware(path):
            self.type = 'vmdk'
        elif _util.is_compressed(path):
            self.type = 'compressed'
        else:
            self.type = 'dd'
        self.paths = sorted(_util.expand_path(path))

        self.offset = offset
        self.block_size = BLOCK_SIZE
        self.read_write = read_write
        self.method = method

        self.read_write = read_write
        self.rwpath = ""
        self.multifile = multifile
        self.index = index
        self.mount_directories = mount_directories
        self.args = args

        self.name = os.path.split(path)[1]
        self.mountpoint = ''
        self.avfs_mountpoint = ''
        self.volumes = VolumeSystem(parent=self, **args)
        self.volume_source = ""

        self.offset = 0
        self._disktype = defaultdict(dict)

        self.loopback = ""
        self.md_device = ""

    def __unicode__(self):
        return self.name

    def __str__(self):
        return self.__unicode__()

    def __getitem__(self, item):
        return self.volumes[item]

    def init(self, single=None, raid=True, disktype=True):
        """Calls several methods required to perform a full initialisation: :func:`mount`, :func:`add_to_raid` and
        :func:`mount_volumes` and yields all detected volumes.

        :param bool|None single: indicates whether the disk should be mounted as a single disk, not as a single disk or
            whether it should try both (defaults to :const:`None`)
        :param bool raid: indicates whether RAID detection is enabled
        :param bool disktype: indicates whether disktype data should be loaded and used
        :rtype: generator
        """

        self.mount()
        if raid:
            self.add_to_raid()
        if disktype:
            self.volumes.load_disktype_data()

        for v in self.mount_volumes(single):
            yield v

    def mount(self):
        """Mounts the base image on a temporary location using the mount method stored in :attr:`method`. If mounting
        was successful, :attr:`mountpoint` is set to the temporary mountpoint.

        If :attr:`read_write` is enabled, a temporary read-write cache is also created and stored in :attr:`rwpath`.

        :return: whether the mounting was successful
        :rtype: bool
        """

        if self.parser.casename:
            self.mountpoint = tempfile.mkdtemp(prefix='image_mounter_', suffix='_' + self.parser.casename)
        else:
            self.mountpoint = tempfile.mkdtemp(prefix='image_mounter_')

        if self.read_write:
            self.rwpath = tempfile.mkstemp(prefix="image_mounter_rw_cache_")[1]

        # Find the mount methods
        if self.method == 'auto':
            methods = []

            def add_method_if_exists(method):
                if (method == 'avfs' and _util.command_exists('avfsd')) or _util.command_exists(method):
                    methods.append(method)

            if self.read_write:
                add_method_if_exists('xmount')
            else:
                if self.type == 'encase':
                    add_method_if_exists('ewfmount')
                elif self.type == 'vmdk':
                    add_method_if_exists('vmware-mount')
                    add_method_if_exists('affuse')
                elif self.type == 'dd':
                    add_method_if_exists('affuse')
                elif self.type == 'compressed':
                    add_method_if_exists('avfs')
                add_method_if_exists('xmount')
        else:
            methods = [self.method]

        cmds = []
        for method in methods:
            if method == 'avfs':  # avfs does not participate in the fallback stuff, unfortunately
                self.avfs_mountpoint = tempfile.mkdtemp(prefix='image_mounter_avfs_')

                # start by calling the mountavfs command to initialize avfs
                _util.check_call_(['avfsd', self.avfs_mountpoint, '-o', 'allow_other'], stdout=subprocess.PIPE)

                # no multifile support for avfs
                avfspath = self.avfs_mountpoint + '/' + os.path.abspath(self.paths[0]) + '#'
                targetraw = os.path.join(self.mountpoint, 'avfs')

                os.symlink(avfspath, targetraw)
                logger.debug("Symlinked {} with {}".format(avfspath, targetraw))
                raw_path = self.get_raw_path()
                logger.debug("Raw path to avfs is {}".format(raw_path))
                if self.method == 'auto':
                    self.method = 'avfs'
                return raw_path is not None

            elif method == 'xmount':
                cmds.append(['xmount', '--in', 'ewf' if self.type == 'encase' else 'dd'])
                if self.read_write:
                    cmds[-1].extend(['--rw', self.rwpath])

            elif method == 'affuse':
                cmds.extend([['affuse', '-o', 'allow_other'], ['affuse']])

            elif method == 'ewfmount':
                cmds.extend([['ewfmount', '-X', 'allow_other'], ['ewfmount']])

            elif method == 'vmware-mount':
                cmds.append(['vmware-mount', '-r', '-f'])

            elif method == 'dummy':
                os.rmdir(self.mountpoint)
                self.mountpoint = ""
                logger.debug("Raw path to dummy is {}".format(self.get_raw_path()))
                return True

            else:
                raise Exception("Unknown mount method {0}".format(self.method))

        # add path and mountpoint to the cmds
        # if multifile is enabled, add additional mount methods to the end of it
        for cmd in cmds[:]:
            if self.multifile and len(self.paths) > 1:
                cmds.append(cmd[:])
                cmds[-1].extend(self.paths)
                cmds[-1].append(self.mountpoint)
            cmd.append(self.paths[0])
            cmd.append(self.mountpoint)

        for cmd in cmds:
            # noinspection PyBroadException
            try:
                _util.check_call_(cmd, stdout=subprocess.PIPE)
                # mounting does not seem to be instant, add a timer here
                time.sleep(.1)
            except Exception:
                logger.warning('Could not mount {0}, trying other method'.format(self.paths[0]), exc_info=True)
                continue
            else:
                raw_path = self.get_raw_path()
                logger.debug("Raw path to disk is {}".format(raw_path))
                if self.method == 'auto':
                    self.method = cmd[0]
                return raw_path is not None

        logger.error('Unable to mount {0}'.format(self.paths[0]))
        os.rmdir(self.mountpoint)
        self.mountpoint = ""

        return False

    def get_raw_path(self):
        """Returns the raw path to the mounted disk image, i.e. the raw :file:`.dd`, :file:`.raw` or :file:`ewf1`
        file.

        :rtype: str
        """

        if self.method == 'dummy':
            return self.paths[0]
        else:
            if self.method == 'avfs' and os.path.isdir(os.path.join(self.mountpoint, 'avfs')):
                logger.debug("AVFS mounted as a directory, will look in directory for (random) file.")
                # there is no support for disks inside disks, so this will fail to work for zips containing
                # E01 files or so.
                searchdirs = (os.path.join(self.mountpoint, 'avfs'), self.mountpoint)
            else:
                searchdirs = (self.mountpoint, )

            raw_path = []
            for searchdir in searchdirs:
                # avfs: apparently it is not a dir
                for pattern in ['*.dd', '*.iso', '*.raw', '*.dmg', 'ewf1', 'flat', 'avfs']:
                    raw_path.extend(glob.glob(os.path.join(searchdir, pattern)))

            if not raw_path:
                logger.warning("No viable mount file found in {}.".format(searchdirs))
                return None
            return raw_path[0]

    def get_fs_path(self):
        """Returns the path to the filesystem. Most of the times this is the image file, but may instead also return
        the MD device or loopback device the filesystem is mounted to.

        :rtype: str
        """

        if self.md_device:
            return self.md_device
        elif self.loopback:
            return self.loopback
        else:
            return self.get_raw_path()

    def is_raid(self):
        """Tests whether this image (was) part of a RAID array. Requires :command:`mdadm` to be installed."""

        if not _util.command_exists('mdadm'):
            logger.info("mdadm not installed, could not detect RAID")
            return False

        # Scan for new lvm volumes
        # noinspection PyBroadException
        try:
            result = _util.check_output_(["mdadm", "--examine", self.get_raw_path()], stderr=subprocess.STDOUT)
            for l in result.splitlines():
                if 'Raid Level' in l:
                    logger.debug("Detected RAID level " + l[l.index(':') + 2:])
                    break
            else:
                return False
        except Exception:
            return False

        return True

    def add_to_raid(self):
        """Adds the disk to a central RAID volume.

        This function will first test whether it is actually a RAID volume by using :func:`is_raid` and, if so, will
        add the disk to the array via a loopback device.

        :return: whether the addition succeeded
        """

        if not self.is_raid():
            return False

        # find free loopback device
        # noinspection PyBroadException
        try:
            self.loopback = _util.check_output_(['losetup', '-f']).strip()
        except Exception:
            logger.warning("No free loopback device found for RAID", exc_info=True)
            return False

        # mount image as loopback
        cmd = ['losetup', '-o', str(self.offset), self.loopback, self.get_raw_path()]
        if not self.read_write:
            cmd.insert(1, '-r')

        try:
            _util.check_call_(cmd, stdout=subprocess.PIPE)
        except Exception:
            logger.exception("Failed mounting image to loopback")
            return False

        try:
            # use mdadm to mount the loopback to a md device
            # incremental and run as soon as available
            output = _util.check_output_(['mdadm', '-IR', self.loopback], stderr=subprocess.STDOUT)
            match = re.findall(r"attached to ([^ ,]+)", output)
            if match:
                self.md_device = os.path.realpath(match[0])
                logger.info("Mounted RAID to {0}".format(self.md_device))
        except Exception as e:
            logger.exception("Failed mounting RAID.")
            return False

        return True

    def mount_volumes(self, single=None, only_mount=None):
        """Generator that detects and mounts all volumes in the disk.

        If *single* is :const:`True`, this method will call :Func:`mount_single_volumes`. If *single* is False, only
        :func:`mount_multiple_volumes` is called. If *single* is None, :func:`mount_multiple_volumes` is always called,
        being followed by :func:`mount_single_volume` if no volumes were detected.
        """

        if os.path.isdir(self.get_raw_path()) and self.mount_directories:
            logger.info("Raw path is a directory: using directory mount method")
            for v in self.mount_directory(only_mount):
                yield v

        elif single:
            # if single, then only use single_Volume
            for v in self.mount_single_volume(only_mount):
                yield v
        else:
            # if single == False or single == None, loop over all volumes
            amount = 0
            for v in self.mount_multiple_volumes(only_mount):
                amount += 1
                yield v

            # if single == None and no volumes were mounted, use single_volume
            if single is None and amount == 0:
                logger.info("Mounting as single volume instead")
                for v in self.mount_single_volume(only_mount):
                    yield v

    def mount_directory(self, only_mount=None):
        """Method that 'mounts' a directory. It actually just symlinks it. It is useful for AVFS mounts, that
        are not otherwise detected. This is a last resort method.
        """

        if not self.mount_directories:
            return

        volume = self.volumes._make_single_subvolume()
        volume.offset = 0
        volume.flag = 'alloc'
        volume.fsdescription = 'Directory'

        filesize = _util.check_output_(['du', '-scDb', self.get_fs_path()]).strip()
        if filesize:
            volume.size = int(filesize.splitlines()[-1].split()[0])

        self.volume_source = 'directory'

        for v in volume.init(no_stats=True, only_mount=only_mount):  # stats can't be retrieved from directory
            yield v

    def mount_single_volume(self, only_mount=None):
        """Mounts a volume assuming that the mounted image does not contain a full disk image, but only a
        single volume.

        A new :class:`Volume` object is created based on the disk file and :func:`init` is called on this object.

        This function will typically yield one volume, although if the volume contains other volumes, multiple volumes
        may be returned.
        """

        volume = self.volumes._make_single_subvolume()
        volume.offset = 0

        description = _util.check_output_(['file', '-sL', self.get_fs_path()]).strip()
        if description:
            # description is the part after the :, until the first comma
            volume.fsdescription = description.split(': ', 1)[1].split(',', 1)[0].strip()
            if 'size' in description:
                volume.size = int(re.findall(r'size:? (\d+)', description)[0])
            else:
                volume.size = os.path.getsize(self.get_fs_path())

        volume.flag = 'alloc'
        self.volume_source = 'single'
        self.volumes._assign_disktype_data(volume)

        for v in volume.init(no_stats=True, only_mount=only_mount):  # stats can't  be retrieved from single volumes
            yield v

    def mount_multiple_volumes(self, only_mount=None):
        """Generator that will detect volumes in the disk file, generate :class:`Volume` objects based on this
        information and call :func:`init` on these.
        """

        for v in self.volumes.detect_volumes():
            for w in v.init(only_mount=only_mount):
                yield w

    def get_volumes(self):
        """Gets a list of all volumes in this disk, including volumes that are contained in other volumes."""

        volumes = []
        for v in self.volumes:
            volumes.extend(v.get_volumes())
        return volumes

    def rw_active(self):
        """Indicates whether anything has been written to a read-write cache."""

        return self.rwpath and os.path.getsize(self.rwpath)

    def unmount(self, remove_rw=False):
        """Removes all ties of this disk to the filesystem, so the image can be unmounted successfully. Warning: this
        method will destruct the entire RAID array in which this disk takes part.
        """

        for m in list(sorted(self.volumes, key=lambda v: v.mountpoint or "", reverse=True)):
            if not m.unmount():
                logger.warning("Error unmounting volume {0}".format(m.mountpoint))

        # TODO: remove specific device from raid array
        if self.md_device:
            # Removes the RAID device first. Actually, we should be able to remove the devices from the array separately,
            # but whatever.
            try:
                _util.check_call_(['mdadm', '-S', self.md_device], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                self.md_device = None
            except Exception as e:
                logger.warning("Failed unmounting MD device {0}".format(self.md_device), exc_info=True)

        if self.loopback:
            # noinspection PyBroadException
            try:
                _util.check_call_(['losetup', '-d', self.loopback])
                self.loopback = None
            except Exception:
                logger.warning("Failed deleting loopback device {0}".format(self.loopback), exc_info=True)

        if self.mountpoint and not _util.clean_unmount(['fusermount', '-u'], self.mountpoint):
            logger.error("Error unmounting base {0}".format(self.mountpoint))
            return False

        if self.avfs_mountpoint and not _util.clean_unmount(['fusermount', '-u'], self.avfs_mountpoint):
            logger.error("Error unmounting AVFS mountpoint {0}".format(self.avfs_mountpoint))
            return False

        if self.rw_active() and remove_rw:
            os.remove(self.rwpath)

        return True

