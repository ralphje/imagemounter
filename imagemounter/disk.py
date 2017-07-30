from __future__ import print_function
from __future__ import unicode_literals
from collections import defaultdict

import glob
import logging
import os
import subprocess
import tempfile
import time

from imagemounter import _util, BLOCK_SIZE
from imagemounter.exceptions import ImageMounterError, ArgumentError, MountpointEmptyError, MountError, \
    NoNetworkBlockAvailableError, SubsystemError
from imagemounter.volume_system import VolumeSystem

logger = logging.getLogger(__name__)


class Disk(object):
    """Representation of a disk, image file or anything else that can be considered a disk. """

    # noinspection PyUnusedLocal
    def __init__(self, parser, path, index=None, offset=0, block_size=BLOCK_SIZE, read_write=False, vstype='',
                 disk_mounter='auto', volume_detector='auto'):
        """Instantiation of this class does not automatically mount, detect or analyse the disk. You will need the
        :func:`init` method for this.

        Only use arguments offset and further as keyword arguments.

        :param parser: the parent parser
        :type parser: :class:`ImageParser`
        :param str path: the path of the Disk
        :param str index: the base index of this Disk
        :param int offset: offset of the disk where the volume (system) resides
        :param int block_size:
        :param bool read_write: indicates whether the disk should be mounted with a read-write cache enabled
        :param str vstype: the volume system type to use.
        :param str disk_mounter: the method to mount the base image with
        :param str volume_detector: the volume system detection method to use
        """

        self.parser = parser

        # Find the type and the paths
        path = os.path.expandvars(os.path.expanduser(path))
        self.paths = sorted(_util.expand_path(path))

        self.offset = offset
        self.block_size = block_size
        self.read_write = read_write
        self.disk_mounter = disk_mounter or 'auto'
        self.index = index

        self._name = os.path.split(path)[1]
        self._paths = {}
        self.rwpath = ""
        self.mountpoint = ""
        self.volumes = VolumeSystem(parent=self, volume_detector=volume_detector, vstype=vstype)

        self.was_mounted = False
        self.is_mounted = False

        self._disktype = defaultdict(dict)

    def __unicode__(self):
        return self._name

    def __str__(self):
        return self.__unicode__()

    def __getitem__(self, item):
        return self.volumes[item]

    def get_disk_type(self):
        if _util.is_encase(self.paths[0]):
            return 'encase'
        elif _util.is_vmware(self.paths[0]):
            return 'vmdk'
        elif _util.is_compressed(self.paths[0]):
            return 'compressed'
        elif _util.is_qcow2(self.paths[0]):
            return 'qcow2'
        else:
            return 'dd'

    def _get_mount_methods(self, disk_type):
        """Finds which mount methods are suitable for the specified disk type. Returns a list of all suitable mount
        methods.
        """
        if self.disk_mounter == 'auto':
            methods = []

            def add_method_if_exists(method):
                if (method == 'avfs' and _util.command_exists('avfsd')) or \
                        (method == 'nbd' and _util.command_exists('qemu-nbd')) or \
                        _util.command_exists(method):
                    methods.append(method)

            if self.read_write:
                add_method_if_exists('xmount')
            else:
                if disk_type == 'encase':
                    add_method_if_exists('ewfmount')
                elif disk_type == 'vmdk':
                    add_method_if_exists('vmware-mount')
                    add_method_if_exists('affuse')
                elif disk_type == 'dd':
                    add_method_if_exists('affuse')
                elif disk_type == 'compressed':
                    add_method_if_exists('avfs')
                elif disk_type == 'qcow2':
                    add_method_if_exists('nbd')
                add_method_if_exists('xmount')
        else:
            methods = [self.disk_mounter]
        return methods

    def _mount_avfs(self):
        """Mounts the AVFS filesystem."""

        self._paths['avfs'] = tempfile.mkdtemp(prefix='image_mounter_avfs_')

        # start by calling the mountavfs command to initialize avfs
        _util.check_call_(['avfsd', self._paths['avfs'], '-o', 'allow_other'], stdout=subprocess.PIPE)

        # no multifile support for avfs
        avfspath = self._paths['avfs'] + '/' + os.path.abspath(self.paths[0]) + '#'
        targetraw = os.path.join(self.mountpoint, 'avfs')

        os.symlink(avfspath, targetraw)
        logger.debug("Symlinked {} with {}".format(avfspath, targetraw))
        raw_path = self.get_raw_path()
        logger.debug("Raw path to avfs is {}".format(raw_path))
        if raw_path is None:
            raise MountpointEmptyError()

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

        disk_type = self.get_disk_type()
        methods = self._get_mount_methods(disk_type)

        cmds = []
        for method in methods:
            if method == 'avfs':  # avfs does not participate in the fallback stuff, unfortunately
                self._mount_avfs()
                self.disk_mounter = method
                self.was_mounted = True
                self.is_mounted = True
                return

            elif method == 'dummy':
                os.rmdir(self.mountpoint)
                self.mountpoint = ""
                logger.debug("Raw path to dummy is {}".format(self.get_raw_path()))
                self.disk_mounter = method
                self.was_mounted = True
                self.is_mounted = True
                return

            elif method == 'xmount':
                cmds.append(['xmount', '--in', 'ewf' if disk_type == 'encase' else 'dd'])
                if self.read_write:
                    cmds[-1].extend(['--rw', self.rwpath])
                cmds[-1].extend(self.paths)  # specify all paths, xmount needs this :(
                cmds[-1].append(self.mountpoint)

            elif method == 'affuse':
                cmds.extend([['affuse', '-o', 'allow_other', self.paths[0], self.mountpoint],
                             ['affuse', self.paths[0], self.mountpoint]])

            elif method == 'ewfmount':
                cmds.extend([['ewfmount', '-X', 'allow_other', self.paths[0], self.mountpoint],
                             ['ewfmount', self.paths[0], self.mountpoint]])

            elif method == 'vmware-mount':
                cmds.append(['vmware-mount', '-r', '-f', self.paths[0], self.mountpoint])

            elif method == 'nbd':
                _util.check_output_(['modprobe', 'nbd', 'max_part=63'])  # Load nbd driver
                try:
                    self._paths['nbd'] = _util.get_free_nbd_device()  # Get free nbd device
                except NoNetworkBlockAvailableError:
                    logger.warning("No free network block device found.", exc_info=True)
                    raise
                cmds.extend([['qemu-nbd', '--read-only', '-c', self._paths['nbd'], self.paths[0]]])

            else:
                raise ArgumentError("Unknown mount method {0}".format(self.disk_mounter))

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
                self.disk_mounter = cmd[0]

                if raw_path is None:
                    raise MountpointEmptyError()
                self.was_mounted = True
                self.is_mounted = True
                return

        logger.error('Unable to mount {0}'.format(self.paths[0]))
        os.rmdir(self.mountpoint)
        self.mountpoint = ""
        raise MountError()

    def get_raw_path(self):
        """Returns the raw path to the mounted disk image, i.e. the raw :file:`.dd`, :file:`.raw` or :file:`ewf1`
        file.

        :rtype: str
        """

        if self.disk_mounter == 'dummy':
            return self.paths[0]
        else:
            if self.disk_mounter == 'avfs' and os.path.isdir(os.path.join(self.mountpoint, 'avfs')):
                logger.debug("AVFS mounted as a directory, will look in directory for (random) file.")
                # there is no support for disks inside disks, so this will fail to work for zips containing
                # E01 files or so.
                searchdirs = (os.path.join(self.mountpoint, 'avfs'), self.mountpoint)
            else:
                searchdirs = (self.mountpoint, )

            raw_path = []
            if self._paths.get('nbd'):
                raw_path.append(self._paths['nbd'])

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

        if self._paths.get('md'):
            return self._paths['md']
        else:
            return self.get_raw_path()

    def detect_volumes(self, single=None):
        """Generator that detects the volumes from the Disk, using one of two methods:

        * Single volume: the entire Disk is a single volume
        * Multiple volumes: the Disk is a volume system

        :param single: If *single* is :const:`True`, this method will call :Func:`init_single_volumes`.
                       If *single* is False, only :func:`init_multiple_volumes` is called. If *single* is None,
                       :func:`init_multiple_volumes` is always called, being followed by :func:`init_single_volume`
                       if no volumes were detected.
        """
        # prevent adding the same volumes twice
        if self.volumes.has_detected:
            for v in self.volumes:
                yield v

        elif single:
            for v in self.volumes.detect_volumes(method='single'):
                yield v

        else:
            # if single == False or single == None, loop over all volumes
            amount = 0
            try:
                for v in self.volumes.detect_volumes():
                    amount += 1
                    yield v
            except ImageMounterError:
                pass  # ignore and continue to single mount

            # if single == None and no volumes were mounted, use single_volume
            if single is None and amount == 0:
                logger.info("Detecting as single volume instead")
                for v in self.volumes.detect_volumes(method='single', force=True):
                    yield v

    def init(self, single=None, only_mount=None, skip_mount=None, swallow_exceptions=True):
        """Calls several methods required to perform a full initialisation: :func:`mount`, and
        :func:`mount_volumes` and yields all detected volumes.

        :param bool|None single: indicates whether the disk should be mounted as a single disk, not as a single disk or
            whether it should try both (defaults to :const:`None`)
        :param list only_mount: If set, must be a list of volume indexes that are only mounted.
        :param list skip_mount: If set, must be a list of volume indexes tat should not be mounted.
        :param bool swallow_exceptions: If True, Exceptions are not raised but rather set on the instance.
        :rtype: generator
        """

        self.mount()
        self.volumes.preload_volume_data()

        for v in self.init_volumes(single, only_mount=only_mount, skip_mount=skip_mount,
                                   swallow_exceptions=swallow_exceptions):
            yield v

    def init_volumes(self, single=None, only_mount=None, skip_mount=None, swallow_exceptions=True):
        """Generator that detects and mounts all volumes in the disk.

        :param single: If *single* is :const:`True`, this method will call :Func:`init_single_volumes`.
                       If *single* is False, only :func:`init_multiple_volumes` is called. If *single* is None,
                       :func:`init_multiple_volumes` is always called, being followed by :func:`init_single_volume`
                       if no volumes were detected.
        :param list only_mount: If set, must be a list of volume indexes that are only mounted.
        :param list skip_mount: If set, must be a list of volume indexes tat should not be mounted.
        :param bool swallow_exceptions: If True, Exceptions are not raised but rather set on the instance.
        """

        for volume in self.detect_volumes(single=single):
            for vol in volume.init(only_mount=only_mount, skip_mount=skip_mount,
                                   swallow_exceptions=swallow_exceptions):
                yield vol

    def get_volumes(self):
        """Gets a list of all volumes in this disk, including volumes that are contained in other volumes."""

        volumes = []
        for v in self.volumes:
            volumes.extend(v.get_volumes())
        return volumes

    def rw_active(self):
        """Indicates whether anything has been written to a read-write cache."""

        return self.rwpath and os.path.getsize(self.rwpath)

    def unmount(self, remove_rw=False, allow_lazy=False):
        """Removes all ties of this disk to the filesystem, so the image can be unmounted successfully.

        :raises SubsystemError: when one of the underlying commands fails. Some are swallowed.
        :raises CleanupError: when actual cleanup fails. Some are swallowed.
        """

        for m in list(sorted(self.volumes, key=lambda v: v.mountpoint or "", reverse=True)):
            try:
                m.unmount(allow_lazy=allow_lazy)
            except ImageMounterError:
                logger.warning("Error unmounting volume {0}".format(m.mountpoint))

        if self._paths.get('nbd'):
            _util.clean_unmount(['qemu-nbd', '-d'], self._paths['nbd'], rmdir=False)

        if self.mountpoint:
            try:
                _util.clean_unmount(['fusermount', '-u'], self.mountpoint)
            except SubsystemError:
                if not allow_lazy:
                    raise
                _util.clean_unmount(['fusermount', '-uz'], self.mountpoint)

        if self._paths.get('avfs'):
            try:
                _util.clean_unmount(['fusermount', '-u'], self._paths['avfs'])
            except SubsystemError:
                if not allow_lazy:
                    raise
                _util.clean_unmount(['fusermount', '-uz'], self._paths['avfs'])

        if self.rw_active() and remove_rw:
            os.remove(self.rwpath)

        self.is_mounted = False
