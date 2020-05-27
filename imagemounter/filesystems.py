import inspect
import logging
import os
import random
import re
import subprocess
import sys
import tempfile
import time

from imagemounter import _util, VOLUME_SYSTEM_TYPES, dependencies
from imagemounter.exceptions import UnsupportedFilesystemError, IncorrectFilesystemError, ArgumentError, \
    KeyInvalidError, ImageMounterError, SubsystemError, NoLoopbackAvailableError, NoMountpointAvailableError

logger = logging.getLogger(__name__)


class MountpointFileSystemMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mountpoint = None

    def _make_mountpoint(self, casename=None, suffix=''):
        """Creates a directory that can be used as a mountpoint.

        :returns: the mountpoint path
        :raises NoMountpointAvailableError: if no mountpoint could be made
        """
        self.mountpoint = self.volume._make_mountpoint(casename, suffix)

    def _clear_mountpoint(self):
        """Clears a created mountpoint. Does not unmount it, merely deletes it."""

        if self.mountpoint is not None:
            os.rmdir(self.mountpoint)
            self.mountpoint = None

    def unmount(self, allow_lazy=False):
        """Unmounts the given volume."""
        super().unmount(allow_lazy=allow_lazy)

        if self.mountpoint is not None:
            _util.clean_unmount(['umount'], self.mountpoint)
            self.mountpoint = None


class LoopbackFileSystemMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.loopback = None

    def _find_loopback(self):
        """Finds a free loopback device that can be used. The loopback is stored in :attr:`loopback`. If *use_loopback*
        is True, the loopback will also be used directly.

        :returns: the loopback address
        :raises NoLoopbackAvailableError: if no loopback could be found
        """

        # noinspection PyBroadException
        try:
            self.loopback = _util.check_output_(['losetup', '-f']).strip()
        except Exception as e:
            logger.warning("No free loopback device found.", exc_info=True)
            raise NoLoopbackAvailableError()

        # noinspection PyBroadException
        try:
            cmd = ['losetup', '-o', str(self.volume.offset), '--sizelimit', str(self.volume.size),
                   self.loopback, self.volume.get_raw_path()]
            if not self.volume.disk.read_write:
                cmd.insert(1, '-r')
            _util.check_call_(cmd, stdout=subprocess.PIPE)
        except Exception:
            logger.exception("Loopback device could not be mounted.")
            self._free_loopback()
            raise NoLoopbackAvailableError()

    def _free_loopback(self):
        if self.loopback is not None:
            try:
                _util.check_call_(['losetup', '-d', self.loopback], wrap_error=True)
            except Exception:
                pass  # TODO

    def unmount(self, allow_lazy=False):
        super().unmount(allow_lazy=allow_lazy)

        if self.loopback is not None:
            _util.check_call_(['losetup', '-d', self.loopback], wrap_error=True)
            self.loopback = None


class FileSystem:
    type = None
    aliases = []
    guids = []

    _mount_type = None
    _mount_opts = ""

    def __init__(self, volume):
        super().__init__()
        self.volume = volume

    def __str__(self):
        return self.type

    @classmethod
    def detect(cls, source, description):
        """Detects the type of a volume based on the provided information. It returns the plausibility for all
        file system types as a dict. Although it is only responsible for returning its own plausibility, it is possible
        that one type of filesystem is more likely than another, e.g. when NTFS detects it is likely to be NTFS, it
        can also update the plausibility of exFAT to indicate it is less likely.

        All scores a cumulative. When multiple sources are used, it is also cumulative. For instance, if run 1 is 25
        certain, and run 2 is 25 certain as well, it will become 50 certain.

        :meth:`Volume.detect_fs_type` will return immediately if the score is higher than 50 and there is only 1
        FS type with the highest score. Otherwise, it will continue with the next run. If at the end of all runs no
        viable FS type was found, it will return the highest scoring FS type (if it is > 0), otherwise it will return
        the FS type fallback.

        :param source: The source of the description
        :param description: The description to detect with
        :return: Dict with mapping of FsType() objects to scores
        """

        if source == "guid" and description in cls.guids:
            return {cls: 100}

        description = description.lower()
        if description == cls.type:
            return {cls: 100}
        elif re.search(r"\b" + cls.type + r"\b", description):
            return {cls: 80}
        elif any((re.search(r"\b" + alias + r"\b", description) for alias in cls.aliases)):
            return {cls: 70}
        return {}

    def mount(self):
        """Mounts the filesystem. Must be implemented by subclasses.

        :raises UnsupportedFilesystemError: when the volume system type can not be mounted.
        """

        raise NotImplementedError()

    def unmount(self, allow_lazy=False):
        """Unmounts the filesystem. Default implementation is to do nothing.
        """

        return


class MountFileSystem(MountpointFileSystemMixin, FileSystem):
    def mount(self):
        """Mounts the given volume. The default implementation simply calls mount.

        :raises UnsupportedFilesystemError: when the volume system type can not be mounted.
        """

        self._make_mountpoint()
        try:
            self._call_mount(self.volume, self.mountpoint, self._mount_type or self.type, self._mount_opts)
        except Exception:
            # undo the creation of the mountpoint
            self._clear_mountpoint()
            raise

    def _call_mount(self, volume, mountpoint, type=None, opts=""):
        """Calls the mount command, specifying the mount type and mount options."""

        # default arguments for calling mount
        if opts and not opts.endswith(','):
            opts += ","
        opts += 'loop,offset=' + str(volume.offset) + ',sizelimit=' + str(volume.size)

        # building the command
        cmd = ['mount', volume.get_raw_path(), mountpoint, '-o', opts]

        # add read-only if needed
        if not volume.disk.read_write:
            cmd[-1] += ',ro'

        # add the type if specified
        if type is not None:
            cmd += ['-t', type]

        _util.check_output_(cmd, stderr=subprocess.STDOUT)


class FallbackFileSystem(FileSystem):
    """Only used when passing in a file system type where the file system is unknown, but a fallback is provided."""

    def __init__(self, volume, fallback, *args, **kwargs):
        self.fallback = fallback
        super().__init__(volume, *args, **kwargs)

    def __str__(self):
        return "?" + str(self.fallback)


class UnknownFileSystem(MountFileSystem):
    type = 'unknown'

    def mount(self):
        # explicitly not specifying any type
        self._make_mountpoint()
        try:
            self._call_mount(self.volume, self.mountpoint)
        except Exception:
            # undo the creation of the mountpoint
            self._clear_mountpoint()
            raise


class VolumeSystemFileSystem(FileSystem):
    type = 'volumesystem'
    aliases = VOLUME_SYSTEM_TYPES

    @classmethod
    def detect(cls, source, description):
        description = description.lower()
        # only detect when it is explicitly in there.
        if any((alias == description for alias in cls.aliases)):
            return {cls: 80}
        elif 'bsd' in description:
            return {cls: 30}
        return {}

    def mount(self):
        for _ in self.volume.volumes.detect_volumes():
            pass

    def unmount(self, allow_lazy=False):
        for volume in self.volume.volumes:
            try:
                volume.unmount(allow_lazy=allow_lazy)
            except ImageMounterError:
                pass


class DirectoryFileSystem(MountpointFileSystemMixin, FileSystem):
    type = 'dir'

    def mount(self):
        self._make_mountpoint()
        os.rmdir(self.mountpoint)
        os.symlink(self.volume.get_raw_path(), self.mountpoint)


class UnsupportedFileSystem(FileSystem):
    """File system type for file systems that are known, but not supported."""

    def mount(self):
        try:
            size = self.volume.size // self.volume.disk.block_size
        except TypeError:
            size = self.volume.size

        logger.warning("Unsupported filesystem {0} (type: {1}, block offset: {2}, length: {3})"
                       .format(self.volume, self.type, self.volume.offset // self.volume.disk.block_size, size))
        raise UnsupportedFilesystemError(self.type)


class SwapFileSystemType(UnsupportedFileSystem):
    type = 'swap'


class ExtFileSystem(MountFileSystem):
    type = 'ext'
    aliases = ['ext1', 'ext2', 'ext3', 'ext4']
    _mount_type = 'ext4'
    _mount_opts = 'noexec,noload'


class UfsFileSystem(MountFileSystem):
    type = 'ufs'
    aliases = ['4.2bsd', 'ufs2', 'ufs 2']
    # TODO: support for other ufstypes
    _mount_opts = 'ufstype=ufs2'

    @classmethod
    def detect(cls, source, description):
        res = super().detect(source, description)
        if "BSD" in description and "4.2BSD" not in description and "UFS" not in description:
            # Strange thing happens where UFS is concerned: it is detected as UFS when it should be detected
            # as volumesystemtype
            res.update({cls: -20, VolumeSystemFileSystem: 20})
        return res


class NtfsFileSystem(MountFileSystem):
    type = 'ntfs'
    _mount_opts = 'show_sys_files,noexec,force,streams_interface=windows'

    @classmethod
    def detect(cls, source, description):
        res = super().detect(source, description)
        if "FAT" in description and "NTFS" in description:
            res.update({NtfsFileSystem: 40, FatFileSystem: -50, ExfatFileSystem: -50})
            # if there is also ntfs in it, it is more likely to be ntfs
        return res


class ExfatFileSystem(MountFileSystem):
    type = 'exfat'
    _mount_opts = 'noexec,force'


class XfsFileSystem(MountFileSystem):
    type = 'xfs'
    _mount_opts = 'norecovery'


class HfsFileSystem(MountFileSystem):
    type = 'hfs'


class HfsPlusFileSystem(MountFileSystem):
    type = 'hfs+'
    aliases = ['hfsplus']
    _mount_type = 'hfsplus'
    _mount_opts = 'force'


class IsoFileSystem(MountFileSystem):
    type = 'iso'
    aliases = ['iso 9660', 'iso9660']
    _mount_type = 'iso9660'


class FatFileSystem(MountFileSystem):
    type = 'fat'
    aliases = ['efi system partition', 'vfat', 'fat12', 'fat16']
    _mount_type = 'vfat'

    @classmethod
    def detect(cls, source, description):
        res = super().detect(source, description)
        if "DOS FAT" in description:
            res.update({VolumeSystemFileSystem: -50})  # DOS FAT
        return res


class UdfFileSystem(MountFileSystem):
    type = 'udf'


class SquashfsFileSystem(MountFileSystem):
    type = 'squashfs'


class CramfsFileSystem(MountFileSystem):
    type = 'cramfs'
    aliases = ['linux compressed rom file system']


class MinixFileSystem(MountFileSystem):
    type = 'minix'


class VmfsFileSystem(LoopbackFileSystemMixin, MountFileSystem):
    type = 'vmfs'
    aliases = ['vmfs_volume_member']
    guids = ['2AE031AA-0F40-DB11-9590-000C2911D1B8']

    def mount(self):
        self._make_mountpoint()
        self._find_loopback()
        try:
            _util.check_call_(['vmfs-fuse', self.loopback, self.mountpoint], stdout=subprocess.PIPE)
        except Exception:
            self._free_loopback()
            self._clear_mountpoint()
            raise


class Jffs2FileSystem(MountFileSystem):
    type = 'jffs2'

    def mount(self):
        """Perform specific operations to mount a JFFS2 image. This kind of image is sometimes used for things like
        bios images. so external tools are required but given this method you don't have to memorize anything and it
        works fast and easy.

        Note that this module might not yet work while mounting multiple images at the same time.
        """
        # we have to make a ram-device to store the image, we keep 20% overhead
        size_in_kb = int((self.volume.size / 1024) * 1.2)
        _util.check_call_(['modprobe', '-v', 'mtd'])
        _util.check_call_(['modprobe', '-v', 'jffs2'])
        _util.check_call_(['modprobe', '-v', 'mtdram', 'total_size={}'.format(size_in_kb), 'erase_size=256'])
        _util.check_call_(['modprobe', '-v', 'mtdblock'])
        _util.check_call_(['dd', 'if=' + self.volume.get_raw_path(), 'of=/dev/mtd0'])

        self._make_mountpoint()
        _util.check_call_(['mount', '-t', 'jffs2', '/dev/mtdblock0', self.mountpoint])


class LuksFileSystem(LoopbackFileSystemMixin, FileSystem):
    type = 'luks'
    guids = ['CA7D7CCB-63ED-4C53-861C-1742536059CC']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.luks_name = None

    @classmethod
    def detect(cls, source, description):
        res = super().detect(source, description)
        if description == 'LUKS Volume':
            res.update({cls: 0})
        return res

    @dependencies.require(dependencies.cryptsetup)
    def mount(self):
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
            self._free_loopback()
            raise IncorrectFilesystemError()

        try:
            extra_args = []
            key = None
            if self.volume.key:
                t, v = self.volume.key.split(':', 1)
                if t == 'p':  # passphrase
                    key = v
                elif t == 'f':  # key-file
                    extra_args = ['--key-file', v]
                elif t == 'm':  # master-key-file
                    extra_args = ['--master-key-file', v]
            else:
                logger.warning("No key material provided for %s", self.volume)
        except ValueError:
            logger.exception("Invalid key material provided (%s) for %s. Expecting [arg]:[value]",
                             self.volume.key, self.volume)
            self._free_loopback()
            raise ArgumentError()

        # Open the LUKS container
        self.luks_name = 'image_mounter_luks_' + str(random.randint(10000, 99999))

        # noinspection PyBroadException
        try:
            cmd = ["cryptsetup", "luksOpen", self.loopback, self.luks_name]
            cmd.extend(extra_args)
            if not self.volume.disk.read_write:
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
            self.luks_name = None
            self._free_loopback()
            raise
        except Exception as e:
            self.luks_name = None
            self._free_loopback()
            raise SubsystemError(e)

        size = None
        # noinspection PyBroadException
        try:
            result = _util.check_output_(["cryptsetup", "status", self.luks_name])
            for line in result.splitlines():
                if "size:" in line and "key" not in line:
                    size = int(line.replace("size:", "").replace("sectors", "").strip()) * self.volume.disk.block_size
        except Exception:
            pass

        container = self.volume.volumes._make_single_subvolume(flag='alloc', offset=0, size=size)
        container.info['fsdescription'] = 'LUKS Volume'

        return container

    def unmount(self, allow_lazy=False):
        if self.luks_name is not None:
            _util.check_call_(['cryptsetup', 'luksClose', self.luks_name], wrap_error=True, stdout=subprocess.PIPE)
            self.luks_name = None
        super().unmount(allow_lazy=allow_lazy)


class BdeFileSystem(MountpointFileSystemMixin, FileSystem):
    type = 'bde'

    @classmethod
    def detect(cls, source, description):
        res = super().detect(source, description)
        if description == 'BDE Volume':
            res.update({cls: 0})
        return res

    @dependencies.require(dependencies.bdemount)
    def mount(self):
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

        self._make_mountpoint()

        try:
            if self.volume.key:
                t, v = self.volume.key.split(':', 1)
                key = ['-' + t, v]
            else:
                logger.warning("No key material provided for %s", self.volume)
                key = []
        except ValueError:
            logger.exception("Invalid key material provided (%s) for %s. Expecting [arg]:[value]", self.volume.key, self.volume)
            raise ArgumentError()

        # noinspection PyBroadException
        try:
            cmd = ["bdemount", self.volume.get_raw_path(), self.mountpoint, '-o', str(self.volume.offset)]
            cmd.extend(key)
            _util.check_call_(cmd)
        except Exception as e:
            self._clear_mountpoint()
            logger.exception("Failed mounting BDE volume %s.", self.volume)
            raise SubsystemError(e)

        container = self.volume.volumes._make_single_subvolume(flag='alloc', offset=0, size=self.volume.size)
        container.info['fsdescription'] = 'BDE Volume'

        return container


class LvmFileSystem(LoopbackFileSystemMixin, FileSystem):
    type = 'lvm'
    aliases = ['0x8e']
    guids = ['E6D6D379-F507-44C2-A23C-238F2A3DF928', '79D3D6E6-07F5-C244-A23C-238F2A3DF928']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.vgname = None

    @dependencies.require(dependencies.lvm)
    def mount(self):
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
            for line in result.splitlines():
                if self.loopback in line or (self.volume.offset == 0 and self.volume.get_raw_path() in line):
                    for vg in re.findall(r'VG (\S+)', line):
                        self.vgname = vg

            if not self.vgname:
                logger.warning("Volume is not a volume group. (Searching for %s)", self.volume.loopback)
                raise IncorrectFilesystemError()

            # Enable lvm volumes
            _util.check_call_(["lvm", "vgchange", "-a", "y", self.volume.info['volume_group']], stdout=subprocess.PIPE)
        except Exception:
            self._free_loopback()
            self.vgname = None
            raise

        self.volume.info['volume_group'] = self.vgname
        self.volume.volumes.vstype = 'lvm'
        # fills it up.
        for _ in self.volume.volumes.detect_volumes('lvm'):
            pass

    def unmount(self, allow_lazy=False):
        if self.vgname:
            _util.check_call_(["lvm", 'vgchange', '-a', 'n', self.vgname], wrap_error=True, stdout=subprocess.PIPE)
            self.vgname = None


class RaidFileSystem(LoopbackFileSystemMixin, FileSystem):
    type = 'raid'
    aliases = ['linux_raid_member', 'linux software raid']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.mdpath = None

    @classmethod
    def detect(cls, source, description):
        res = super().detect(source, description)
        if description == 'RAID Volume':
            res.update({cls: 0})
        return res

    def _iter_same_md_volumes(self):
        for v in self.volume.disk.parser.get_volumes():
            if v != self.volume and v.filesystem.type == self.type and v.filesystem.mdpath == self.mdpath:
                yield v

    @dependencies.require(dependencies.mdadm)
    def mount(self):
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
                self.mdpath = os.path.realpath(match[0])
                if 'which is already active' in output:
                    logger.info("RAID is already active in other volume, using %s", self.mdpath)
                    raid_status = 'active'
                elif 'not enough to start' in output:
                    self.mdpath = self.mdpath.replace("/dev/md/", "/dev/md")
                    logger.info("RAID volume added, but not enough to start %s", self.mdpath)
                    raid_status = 'waiting'
                else:
                    logger.info("RAID started at {0}".format(self.mdpath))
                    raid_status = 'active'
        except Exception as e:
            logger.exception("Failed mounting RAID.")
            self._free_loopback()
            raise SubsystemError(e)

        # search for the RAID volume
        for v in self._iter_same_md_volumes():
            if v.volumes:
                logger.debug("Adding existing volume %s to volume %s", v.volumes[0], self.volume)
                v.volumes[0].info['raid_status'] = raid_status
                self.volume.volumes.volumes.append(v.volumes[0])
                return v.volumes[0]
        else:
            logger.debug("Creating RAID volume for %s", self)
            container = self.volume.volumes._make_single_subvolume(flag='alloc', offset=0, size=self.volume.size)
            container.info['fsdescription'] = 'RAID Volume'
            container.info['raid_status'] = raid_status
            return container

    def unmount(self, allow_lazy=False):
        if self.mdpath is not None:
            # MD arrays are a bit complicated, we also check all other volumes that are part of this array and
            # unmount them as well.
            logger.debug("All other volumes that use %s as well will also be unmounted", self.mdpath)

            for v in self._iter_same_md_volumes():
                v.unmount(allow_lazy=allow_lazy)

            try:
                _util.check_output_(["mdadm", '--stop', self.mdpath], stderr=subprocess.STDOUT)
            except Exception as e:
                raise SubsystemError(e)

            self.mdpath = None

        super().unmount(allow_lazy=allow_lazy)


# Populate the FILE_SYSTEM_TYPES
FILE_SYSTEM_TYPES = {}
for _, cls in inspect.getmembers(sys.modules[__name__], inspect.isclass):
    if issubclass(cls, FileSystem) and cls != FileSystem and cls.type is not None:
        FILE_SYSTEM_TYPES[cls.type] = cls
