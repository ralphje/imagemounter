import inspect
import logging
import os
import random
import re
import subprocess
import sys
import tempfile
import time

from imagemounter import _util, VOLUME_SYSTEM_TYPES
from imagemounter.exceptions import UnsupportedFilesystemError, IncorrectFilesystemError, ArgumentError, \
    KeyInvalidError, ImageMounterError, SubsystemError

logger = logging.getLogger(__name__)


class FileSystemType(object):
    type = None
    aliases = []
    guids = []

    _needs_mountpoint = True
    _mount_type = None
    _mount_opts = ""

    def __eq__(self, other):
        return isinstance(other, FileSystemType) and self.type == other.type

    def __hash__(self):
        return hash((self.type, ))

    def __str__(self):
        return self.type

    def detect(self, source, description):
        if source == "guid" and description in self.guids:
            return {self: 100}

        description = description.lower()
        if description == self.type:
            return {self: 100}
        elif re.search(r"\b" + self.type + r"\b", description):
            return {self: 80}
        elif any((re.search(r"\b" + alias + r"\b", description) for alias in self.aliases)):
            return {self: 70}
        return {}

    def mount(self, volume):
        """Mounts the given volume on the provided mountpoint. The default implementation simply calls mount.

        :param Volume volume: The volume to be mounted
        :param mountpoint: The file system path to mount the filesystem on.
        :raises UnsupportedFilesystemError: when the volume system type can not be mounted.
        """

        volume._make_mountpoint()
        self._call_mount(volume, volume.mountpoint, self._mount_type or self.type, self._mount_opts)

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


class FallbackFileSystemType(FileSystemType):
    """Only used when passing in a file system type where the file system is unknown, but a fallback is provided."""

    def __init__(self, fallback, *args, **kwargs):
        self.fallback = fallback
        super(FallbackFileSystemType, self).__init__(*args, **kwargs)

    def __str__(self):
        return "?" + self.type


class UnknownFileSystemType(FileSystemType):
    type = 'unknown'

    def mount(self, volume):
        # explicitly not specifying any type
        volume._make_mountpoint()
        self._call_mount(volume, volume.mountpoint)


class VolumeSystemFileSystemType(FileSystemType):
    type = 'volumesystem'
    aliases = VOLUME_SYSTEM_TYPES

    def detect(self, source, description):
        description = description.lower()
        # only detect when it is explicitly in there.
        if any((alias == description for alias in self.aliases)):
            return {self: 80}
        elif 'bsd' in description:
            return {self: 30}
        return {}

    def mount(self, volume):
        for _ in volume.volumes.detect_volumes():
            pass


class DirectoryFileSystemType(FileSystemType):
    type = 'dir'

    def mount(self, volume):
        volume._make_mountpoint()
        os.rmdir(volume.mountpoint)
        os.symlink(volume.get_raw_path(), volume.mountpoint)


class UnsupportedFileSystemType(FileSystemType):
    """File system type for file systems that are known, but not supported."""

    def mount(self, volume):
        try:
            size = volume.size // volume.disk.block_size
        except TypeError:
            size = volume.size

        logger.warning("Unsupported filesystem {0} (type: {1}, block offset: {2}, length: {3})"
                       .format(volume, self.type, volume.offset // volume.disk.block_size, size))
        raise UnsupportedFilesystemError(self.type)


class SwapFileSystemType(UnsupportedFileSystemType):
    type = 'swap'


class ExtFileSystemType(FileSystemType):
    type = 'ext'
    aliases = ['ext1', 'ext2', 'ext3', 'ext4']
    _mount_type = 'ext4'
    _mount_opts = 'noexec,noload'


class UfsFileSystemType(FileSystemType):
    type = 'ufs'
    aliases = ['4.2bsd', 'ufs2', 'ufs 2']
    # TODO: support for other ufstypes
    _mount_opts = 'ufstype=ufs2'

    def detect(self, source, description):
        res = super(UfsFileSystemType, self).detect(source, description)
        if "BSD" in description and "4.2BSD" not in description and "UFS" not in description:
            # Strange thing happens where UFS is concerned: it is detected as UFS when it should be detected
            # as volumesystemtype
            res.update({self: -20, VolumeSystemFileSystemType(): 20})
        return res


class NtfsFileSystemType(FileSystemType):
    type = 'ntfs'
    _mount_opts = 'show_sys_files,noexec,force,streams_interface=windows'

    def detect(self, source, description):
        res = super(NtfsFileSystemType, self).detect(source, description)
        if "FAT" in description and "NTFS" in description:
            res.update({NtfsFileSystemType(): 40, FatFileSystemType(): -50, ExfatFileSystemType(): -50})
            # if there is also ntfs in it, it is more likely to be ntfs
        return res


class ExfatFileSystemType(FileSystemType):
    type = 'exfat'
    _mount_opts = 'noexec,force'


class XfsFileSystemType(FileSystemType):
    type = 'xfs'
    _mount_opts = 'norecovery'


class HfsFileSystemType(FileSystemType):
    type = 'hfs'


class HfsPlusFileSystemType(FileSystemType):
    type = 'hfs+'
    aliases = ['hfsplus']
    _mount_type = 'hfsplus'
    _mount_opts = 'force'


class IsoFileSystemType(FileSystemType):
    type = 'iso'
    aliases = ['iso 9660', 'iso9660']
    _mount_type = 'iso9660'


class FatFileSystemType(FileSystemType):
    type = 'fat'
    aliases = ['efi system partition', 'vfat', 'fat12', 'fat16']
    _mount_type = 'vfat'

    def detect(self, source, description):
        res = super(FatFileSystemType, self).detect(source, description)
        if "DOS FAT" in description:
            res.update({VolumeSystemFileSystemType(): -50})  # DOS FAT
        return res


class UdfFileSystemType(FileSystemType):
    type = 'udf'


class SquashfsFileSystemType(FileSystemType):
    type = 'squashfs'


class CramfsFileSystemType(FileSystemType):
    type = 'cramfs'
    aliases = ['linux compressed rom file system']


class MinixFileSystemType(FileSystemType):
    type = 'minix'


class VmfsFileSystemType(FileSystemType):
    type = 'vmfs'
    aliases = ['vmfs_volume_member']
    guids = ['2AE031AA-0F40-DB11-9590-000C2911D1B8']

    def mount(self, volume):
        volume._make_mountpoint()
        volume._find_loopback()
        _util.check_call_(['vmfs-fuse', volume.loopback, volume.mountpoint], stdout=subprocess.PIPE)


class Jffs2FileSystemType(FileSystemType):
    type = 'jffs2'

    def mount(self, volume):
        """Perform specific operations to mount a JFFS2 image. This kind of image is sometimes used for things like
        bios images. so external tools are required but given this method you don't have to memorize anything and it
        works fast and easy.

        Note that this module might not yet work while mounting multiple images at the same time.
        """
        # we have to make a ram-device to store the image, we keep 20% overhead
        size_in_kb = int((volume.size / 1024) * 1.2)
        _util.check_call_(['modprobe', '-v', 'mtd'])
        _util.check_call_(['modprobe', '-v', 'jffs2'])
        _util.check_call_(['modprobe', '-v', 'mtdram', 'total_size={}'.format(size_in_kb), 'erase_size=256'])
        _util.check_call_(['modprobe', '-v', 'mtdblock'])
        _util.check_call_(['dd', 'if=' + volume.get_raw_path(), 'of=/dev/mtd0'])
        _util.check_call_(['mount', '-t', 'jffs2', '/dev/mtdblock0', mountpoint])


class LuksFileSystemType(FileSystemType):
    type = 'luks'
    guids = ['CA7D7CCB-63ED-4C53-861C-1742536059CC']

    def detect(self, source, description):
        res = super(LuksFileSystemType, self).detect(source, description)
        if description == 'LUKS Volume':
            res.update({self: 0})
        return res

    def mount(self, volume):
        """Command that is an alternative to the :func:`mount` command that opens a LUKS container. The opened volume is
        added to the subvolume set of this volume. Requires the user to enter the key manually.

        TODO: add support for :attr:`keys`

        :return: the Volume contained in the LUKS container, or None on failure.
        :raises NoLoopbackAvailableError: when no free loopback could be found
        :raises IncorrectFilesystemError: when this is not a LUKS volume
        :raises SubsystemError: when the underlying command fails
        """

        # Open a loopback device
        volume._find_loopback()

        # Check if this is a LUKS device
        # noinspection PyBroadException
        try:
            _util.check_call_(["cryptsetup", "isLuks", volume.loopback], stderr=subprocess.STDOUT)
            # ret = 0 if isLuks
        except Exception:
            logger.warning("Not a LUKS volume")
            # clean the loopback device, we want this method to be clean as possible
            # noinspection PyBroadException
            try:
                volume._free_loopback()
            except Exception:
                pass
            raise IncorrectFilesystemError()

        try:
            extra_args = []
            key = None
            if volume.key:
                t, v = volume.key.split(':', 1)
                if t == 'p':  # passphrase
                    key = v
                elif t == 'f':  # key-file
                    extra_args = ['--key-file', v]
                elif t == 'm':  # master-key-file
                    extra_args = ['--master-key-file', v]
            else:
                logger.warning("No key material provided for %s", volume)
        except ValueError:
            logger.exception("Invalid key material provided (%s) for %s. Expecting [arg]:[value]", volume.key, volume)
            volume._free_loopback()
            raise ArgumentError()

        # Open the LUKS container
        volume._paths['luks'] = 'image_mounter_luks_' + str(random.randint(10000, 99999))

        # noinspection PyBroadException
        try:
            cmd = ["cryptsetup", "luksOpen", volume.loopback, volume._paths['luks']]
            cmd.extend(extra_args)
            if not volume.disk.read_write:
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
            del volume._paths['luks']
            volume._free_loopback()
            raise
        except Exception as e:
            del volume._paths['luks']
            volume._free_loopback()
            raise SubsystemError(e)

        size = None
        # noinspection PyBroadException
        try:
            result = _util.check_output_(["cryptsetup", "status", volume._paths['luks']])
            for l in result.splitlines():
                if "size:" in l and "key" not in l:
                    size = int(l.replace("size:", "").replace("sectors", "").strip()) * volume.disk.block_size
        except Exception:
            pass

        container = volume.volumes._make_single_subvolume(flag='alloc', offset=0, size=size)
        container.info['fsdescription'] = 'LUKS Volume'

        return container


class BdeFileSystemType(FileSystemType):
    type = 'bde'

    def detect(self, source, description):
        res = super(BdeFileSystemType, self).detect(source, description)
        if description == 'BDE Volume':
            res.update({self: 0})
        return res

    def mount(self, volume):
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

        volume._paths['bde'] = tempfile.mkdtemp(prefix='image_mounter_bde_')

        try:
            if volume.key:
                t, v = volume.key.split(':', 1)
                key = ['-' + t, v]
            else:
                logger.warning("No key material provided for %s", volume)
                key = []
        except ValueError:
            logger.exception("Invalid key material provided (%s) for %s. Expecting [arg]:[value]", volume.key, volume)
            raise ArgumentError()

        # noinspection PyBroadException
        try:
            cmd = ["bdemount", volume.get_raw_path(), volume._paths['bde'], '-o', str(volume.offset)]
            cmd.extend(key)
            _util.check_call_(cmd)
        except Exception as e:
            del volume._paths['bde']
            logger.exception("Failed mounting BDE volume %s.", volume)
            raise SubsystemError(e)

        container = volume.volumes._make_single_subvolume(flag='alloc', offset=0, size=volume.size)
        container.info['fsdescription'] = 'BDE Volume'

        return container


class LvmFileSystemType(FileSystemType):
    type = 'lvm'
    aliases = ['0x8e']
    guids = ['E6D6D379-F507-44C2-A23C-238F2A3DF928', '79D3D6E6-07F5-C244-A23C-238F2A3DF928']

    def mount(self, volume):
        """Performs mount actions on a LVM. Scans for active volume groups from the loopback device, activates it
        and fills :attr:`volumes` with the logical volumes.

        :raises NoLoopbackAvailableError: when no loopback was available
        :raises IncorrectFilesystemError: when the volume is not a volume group
        """
        os.environ['LVM_SUPPRESS_FD_WARNINGS'] = '1'

        # find free loopback device
        volume._find_loopback()
        time.sleep(0.2)

        try:
            # Scan for new lvm volumes
            result = _util.check_output_(["lvm", "pvscan"])
            for l in result.splitlines():
                if volume.loopback in l or (volume.offset == 0 and volume.get_raw_path() in l):
                    for vg in re.findall(r'VG (\S+)', l):
                        volume.info['volume_group'] = vg

            if not volume.info.get('volume_group'):
                logger.warning("Volume is not a volume group. (Searching for %s)", volume.loopback)
                raise IncorrectFilesystemError()

            # Enable lvm volumes
            _util.check_call_(["lvm", "vgchange", "-a", "y", volume.info['volume_group']], stdout=subprocess.PIPE)
        except Exception:
            volume._free_loopback()
            raise

        volume.volumes.vstype = 'lvm'
        # fills it up.
        for _ in volume.volumes.detect_volumes('lvm'):
            pass


class RaidFileSystemType(FileSystemType):
    type = 'raid'
    aliases = ['linux_raid_member', 'linux software raid']

    def detect(self, source, description):
        res = super(RaidFileSystemType, self).detect(source, description)
        if description == 'RAID Volume':
            res.update({self: 0})
        return res

    def mount(self, volume):
        """Add the volume to a RAID system. The RAID array is activated as soon as the array can be activated.

        :raises NoLoopbackAvailableError: if no loopback device was found
        """

        volume._find_loopback()

        raid_status = None
        try:
            # use mdadm to mount the loopback to a md device
            # incremental and run as soon as available
            output = _util.check_output_(['mdadm', '-IR', volume.loopback], stderr=subprocess.STDOUT)

            match = re.findall(r"attached to ([^ ,]+)", output)
            if match:
                volume._paths['md'] = os.path.realpath(match[0])
                if 'which is already active' in output:
                    logger.info("RAID is already active in other volume, using %s", volume._paths['md'])
                    raid_status = 'active'
                elif 'not enough to start' in output:
                    volume._paths['md'] = volume._paths['md'].replace("/dev/md/", "/dev/md")
                    logger.info("RAID volume added, but not enough to start %s", volume._paths['md'])
                    raid_status = 'waiting'
                else:
                    logger.info("RAID started at {0}".format(volume._paths['md']))
                    raid_status = 'active'
        except Exception as e:
            logger.exception("Failed mounting RAID.")
            volume._free_loopback()
            raise SubsystemError(e)

        # search for the RAID volume
        for v in volume.disk.parser.get_volumes():
            if v._paths.get("md") == volume._paths['md'] and v.volumes:
                logger.debug("Adding existing volume %s to volume %s", v.volumes[0], volume)
                v.volumes[0].info['raid_status'] = raid_status
                volume.volumes.volumes.append(v.volumes[0])
                return v.volumes[0]
        else:
            logger.debug("Creating RAID volume for %s", self)
            container = volume.volumes._make_single_subvolume(flag='alloc', offset=0, size=volume.size)
            container.info['fsdescription'] = 'RAID Volume'
            container.info['raid_status'] = raid_status
            return container


# Populate the FILE_SYSTEM_TYPES
FILE_SYSTEM_TYPES = {}
for _, cls in inspect.getmembers(sys.modules[__name__], inspect.isclass):
    if issubclass(cls, FileSystemType) and cls != FileSystemType and cls.type is not None:
        FILE_SYSTEM_TYPES[cls.type] = cls()
