import copy
import re
import subprocess
import tempfile
import pytsk3
import threading
import glob
import sys
import os
import warnings

from imagemounter import util
from termcolor import colored

__ALL__ = ['Volume', 'ImageParser']
__version__ = '1.4.0'

BLOCK_SIZE = 512


class ImageParser(object):
    def __init__(self, paths, out=sys.stdout, verbose=False, color=False, **args):
        if isinstance(paths, (str, unicode)):
            self.paths = [paths]
        else:
            self.paths = paths
        self.out = out
        self.verbose = verbose
        self.verbose_color = color
        self.args = args

        self.disks = []
        for path in self.paths:
            self.disks.append(Disk(self, path, **self.args))

    def _debug(self, val):
        if self.verbose:
            if self.verbose_color:
                print >> self.out, colored(val, "cyan")
            else:
                print >> self.out, val

    def mount_disks(self):
        """Mounts all disks in the parser."""

        result = True
        for disk in self.disks:
            result = disk.mount() and result
        return result

    def rw_active(self):
        """Indicates whether any RW cache is active."""
        result = False
        for disk in self.disks:
            result = disk.rw_active() or result
        return result

    mount_base = mount_disks  # backwards compatibility

    def mount_raid(self):
        """Crates a RAID device and adds all devices to the RAID. Returns True if all devices were added
        successfully. Should be called before mount_disks.
        """

        result = True
        for disk in self.disks:
            result = disk.add_to_raid() and result
        return result

    def mount_single_volume(self):
        for disk in self.disks:
            for volume in disk.mount_single_volume():
                yield volume

    def mount_multiple_volumes(self):
        for disk in self.disks:
            for volume in disk.mount_multiple_volumes():
                yield volume

    def mount_volumes(self, single=None):
        """Mounts all volumes in all disks. Call mount_disks first."""

        for disk in self.disks:
            for volume in disk.mount_volumes(single):
                yield volume

    def clean(self, remove_rw=False):
        """Cleans everything."""

        for disk in self.disks:
            if not disk.unmount(remove_rw):
                self._debug("[-] Error unmounting {0}".format(disk))
                return False

        return True



    #Backwards compatibiltiy
    @staticmethod
    def force_clean(execute=True):
        return util.force_clean(execute)

    def reconstruct(self):
        """Reconstructs the filesystem of all volumes mounted by the parser by inspecting the last mount point and
        bind mounting everything.
        """
        volumes = []
        for disk in self.disks:
            volumes.extend(disk.volumes)
        volumes = list(reversed(sorted(volumes)))

        mounted_partitions = filter(lambda x: x.mountpoint, volumes)
        viable_for_reconstruct = sorted(filter(lambda x: x.lastmountpoint, mounted_partitions))

        try:
            root = filter(lambda x: x.lastmountpoint == '/', viable_for_reconstruct)[0]
        except IndexError:
            self._debug(u"[-] Could not find / while reconstructing, aborting!")
            return None

        viable_for_reconstruct.remove(root)

        for v in viable_for_reconstruct:
            v.bindmount(os.path.join(root.mountpoint, v.lastmountpoint[1:]))
        return root


class Disk(object):
    """Parses an image and mounts it."""

    VOLUME_SYSTEM_TYPES = ('detect', 'dos', 'bsd', 'sun', 'mac', 'gpt', 'dbfiller')

    #noinspection PyUnusedLocal
    def __init__(self, parser, path, offset=0, vstype='detect', read_write=False, method='auto', multifile=True,
                 **args):

        self.parser = parser

        # Find the type and the paths
        path = os.path.expandvars(os.path.expanduser(path))
        if util.is_encase(path):
            self.type = 'encase'
        else:
            self.type = 'dd'
        self.paths = sorted(util.expand_path(path))

        self.offset = offset

        if vstype.lower() == 'any':
            self.vstype = 'any'
        else:
            self.vstype = getattr(pytsk3, 'TSK_VS_TYPE_' + vstype.upper())

        self.read_write = read_write

        if method == 'auto':
            if self.read_write:
                self.method = 'xmount'
            elif self.type == 'encase' and util.command_exists('ewfmount'):
                self.method = 'ewfmount'
            elif self.type == 'dd' and util.command_exists('affuse'):
                self.method = 'affuse'
            else:
                self.method = 'xmount'
        else:
            self.method = method

        self.read_write = read_write
        self.rwpath = None
        self.multifile = multifile
        self.args = args

        self.name = os.path.split(path)[1]
        self.mountpoint = u''
        self.volumes = []

        self.loopback = None
        self.md_device = None

    def __unicode__(self):
        return unicode(self.name)

    def __str__(self):
        return str(self.__unicode__())

    def _debug(self, val):
        #noinspection PyProtectedMember
        return self.parser._debug(val)

    def init(self, single=None, raid=True):
        """Performs a full initialization. If single is None, mount_volumes is performed. If this returns nothing,
        mount_single_volume is used in addition."""

        self.mount()
        if raid:
            self.add_to_raid()

        for v in self.mount_volumes(single):
            yield v

    def mount(self):
        """Mount the image at a temporary path for analysis"""

        self.mountpoint = tempfile.mkdtemp(prefix=u'image_mounter_')

        if self.multifile:
            pathss = (self.paths[:1], self.paths)
        else:
            pathss = (self.paths[:1], )

        if self.read_write:
            self.rwpath = tempfile.mkstemp(prefix="image_mounter_rw_cache_")[1]

        for paths in pathss:
            try:
                fallbackcmd = None
                if self.method == 'xmount':
                    cmd = [u'xmount', '--in', 'ewf' if self.type == 'encase' else 'dd']
                    if self.read_write:
                        cmd.extend(['--rw', self.rwpath])

                elif self.method == 'affuse':
                    cmd = [u'affuse', '-o', 'allow_other']
                    fallbackcmd = [u'affuse']

                elif self.method == 'ewfmount':
                    cmd = [u'ewfmount', '-X', 'allow_other']
                    fallbackcmd = [u'ewfmount']

                elif self.method == 'dummy':
                    # remove basemountpoint
                    os.rmdir(self.mountpoint)
                    self.mountpoint = None
                    return True

                else:
                    raise Exception("Unknown mount method {0}".format(self.method))

                try:
                    cmd.extend(paths)
                    cmd.append(self.mountpoint)
                    util.check_call_(cmd, self, stdout=subprocess.PIPE)
                except Exception as e:
                    if fallbackcmd:
                        fallbackcmd.extend(paths)
                        fallbackcmd.append(self.mountpoint)
                        util.check_call_(fallbackcmd, self, stdout=subprocess.PIPE)
                    else:
                        raise
                return True

            except Exception as e:
                self._debug(u'[-] Could not mount {0} (see below), will try multi-file method'.format(paths[0]))
                self._debug(e)

        os.rmdir(self.mountpoint)
        self.mountpoint = None

        return False

    def get_raw_path(self):
        """Returns the raw path to the disk image"""

        if self.method == 'dummy':
            return self.paths[0]
        else:
            raw_path = glob.glob(os.path.join(self.mountpoint, u'*.dd'))
            raw_path.extend(glob.glob(os.path.join(self.mountpoint, u'*.raw')))
            raw_path.extend(glob.glob(os.path.join(self.mountpoint, u'ewf1')))
            return raw_path[0]

    def get_fs_path(self):
        """Returns the path to the filesystem. Most of the times this is the image file, but may instead also return
        the MD device or loopback device the filesystem is mounted to.
        """

        if self.md_device:
            return self.md_device
        elif self.loopback:
            return self.loopback
        else:
            return self.get_raw_path()

    def is_raid(self):
        """Tests whether this image is in RAID."""

        if not util.command_exists('mdadm'):
            self._debug("    mdadm not installed, so could not detect RAID")
            return False

        # Scan for new lvm volumes
        result = util.check_output_(["mdadm", "--examine", self.get_raw_path()], self)
        for l in result.splitlines():
            if 'Raid Level' in l:
                self._debug("    Detected RAID level " + l[l.index(':') + 2:])
                break
        else:
            return False

        return True

    def add_to_raid(self):
        """Adds the disk to the main RAID"""

        if not self.is_raid():
            return False

        # find free loopback device
        #noinspection PyBroadException
        try:
            self.loopback = util.check_output_(['losetup', '-f'], self).strip()
        except Exception:
            self._debug("[-] No free loopback device found for RAID")
            return False

        # mount image as loopback
        cmd = [u'losetup', u'-o', str(self.offset), self.loopback, self.get_raw_path()]
        if not self.read_write:
            cmd.insert(1, '-r')

        try:
            util.check_call_(cmd, self, stdout=subprocess.PIPE)
        except Exception as e:
            self._debug("[-] Failed mounting image to loopback")
            self._debug(e)
            return False

        try:
            # use mdadm to mount the loopback to a md device
            # incremental and run as soon as available
            output = util.check_output_(['mdadm', '-IR', self.loopback], self, stderr=subprocess.STDOUT)
            match = re.findall(r"attached to ([^ ,]+)", output)
            if match:
                self.md_device = os.path.realpath(match[0])
                self._debug("    Mounted RAID to {0}".format(self.md_device))
        except Exception as e:
            self._debug("[-] Failed mounting RAID.")
            self._debug(e)
            return False

        return True

    def mount_volumes(self, single=None):
        if single:
            # if single, then only use single_Volume
            for v in self.mount_single_volume():
                yield v
        else:
            # if single == False or single == None, loop over all volumes
            amount = 0
            for v in self.mount_multiple_volumes():
                amount += 1
                yield v

            # if single == None and no volumes were mounted, use single_volume
            if single is None and amount == 0:
                for v in self.mount_single_volume():
                    yield v

    def mount_single_volume(self):
        """Assumes the mounted image does not contain a full disk image, but only a single volume."""

        volume = Volume(disk=self, **self.args)
        volume.offset = 0
        volume.index = 0

        description = util.check_output_(['file', '-sL', self.get_fs_path()]).strip()
        if description:
            volume.fsdescription = description.split(': ', 1)[1].split(',', 1)[0].strip()
            if 'size' in description:
                volume.size = int(description.split('size: ', 1)[1].strip())

        volume.flag = 'alloc'
        self.volumes = [volume]

        for v in volume.init(no_stats=True):  # stats can't  be retrieved from single volumes
            yield v

    def _find_volumes(self):
        """Finds all volumes based on the pytsk3 library."""

        baseimage = None
        try:
            # ewf raw image is now available on basemountpoint
            # either as ewf1 file or as .dd file
            raw_path = self.get_raw_path()
            try:
                baseimage = pytsk3.Img_Info(raw_path)
            except Exception as e:
                self._debug(u"[-] Failed retrieving image info (possible empty image).")
                self._debug(e)
                return []

            # any loops over all vstypes
            if self.vstype == 'any':
                for vs in ImageParser.VOLUME_SYSTEM_TYPES:
                    #noinspection PyBroadException
                    try:
                        vst = getattr(pytsk3, 'TSK_VS_TYPE_' + vs.upper())
                        volumes = pytsk3.Volume_Info(baseimage, vst)
                        self._debug(u"[+] Using VS type {0}".format(vs))
                        return volumes
                        break
                    except Exception:
                        self._debug(u"    VS type {0} did not work".format(vs))
                else:
                    self._debug(u"[-] Failed retrieving volume info")
                    return []
            else:
                # base case: just obtian all volumes
                try:
                    volumes = pytsk3.Volume_Info(baseimage, self.vstype)
                    return volumes
                except Exception as e:
                    self._debug(u"[-] Failed retrieving volume info (possible empty image).")
                    self._debug(e)
                    return []
        finally:
            if baseimage:
                baseimage.close()

    def mount_multiple_volumes(self):
        """Generator that mounts every partition of this image and yields the mountpoint."""

        # Loop over all volumes in image.
        for p in self._find_volumes():
            volume = Volume(disk=self, **self.args)
            self.volumes.append(volume)

            # Fill volume with more information
            volume.offset = p.start * BLOCK_SIZE
            volume.fsdescription = p.desc
            volume.index = p.addr
            volume.size = p.len * BLOCK_SIZE

            if p.flags == pytsk3.TSK_VS_PART_FLAG_ALLOC:
                volume.flag = 'alloc'
            elif p.flags == pytsk3.TSK_VS_PART_FLAG_UNALLOC:
                volume.flag = 'unalloc'
                self._debug("    Unallocated space: block offset: {0}, length: {1} ".format(p.start, p.len))
            elif p.flags == pytsk3.TSK_VS_PART_FLAG_META:
                volume.flag = 'meta'

            # unalloc / meta partitions do not have stats and can not be mounted
            if volume.flag != 'alloc':
                yield volume
                continue

            for v in volume.init():
                yield v

    mount_partitions = mount_multiple_volumes  # Backwards compatibility

    def rw_active(self):
        """Indicates whether the rw-path is active."""

        return self.rwpath and os.path.getsize(self.rwpath)

    def unmount(self, remove_rw=False):
        """Method that removes all ties to the filesystem, so the image can be unmounted successfully"""

        for m in list(reversed(sorted(self.volumes))):
            if not m.unmount():
                self._debug(u"[-] Error unmounting volume {0}".format(m.mountpoint))

        # TODO: remove specific device from raid array
        if self.md_device:
            # Removes the RAID device first. Actually, we should be able to remove the devices from the array separately,
            # but whatever.
            try:
                util.check_call_(['mdadm', '-S', self.md_device], self, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                self.md_device = None
            except Exception as e:
                self._debug(u"[-] Failed unmounting MD device {0}".format(self.md_device))
                self._debug(e)

        if self.loopback:
            try:
                util.check_call_(['losetup', '-d', self.loopback], self)
                self.loopback = None
            except Exception:
                self._debug(u"[-] Failed deleting loopback device {0}".format(self.loopback))

        if self.mountpoint and not util.clean_unmount([u'fusermount', u'-u'], self.mountpoint):
            self._debug(u"[-] Error unmounting base {0}".format(self.mountpoint))
            return False

        if self.rw_active() and remove_rw:
            os.remove(self.rwpath)

        return True

    clean = unmount  # backwards compatibility

    def reconstruct(self):
        """Reconstructs the filesystem of all currently mounted partitions by inspecting the last mount point and
        bind mounting everything.
        """
        mounted_partitions = filter(lambda x: x.mountpoint, self.partitions)
        viable_for_reconstruct = sorted(filter(lambda x: x.lastmountpoint, mounted_partitions))

        try:
            root = filter(lambda x: x.lastmountpoint == '/', viable_for_reconstruct)[0]
        except IndexError:
            self._debug(u"[-] Could not find / while reconstructing, aborting!")
            return None

        viable_for_reconstruct.remove(root)

        for v in viable_for_reconstruct:
            v.bindmount(os.path.join(root.mountpoint, v.lastmountpoint[1:]))
        return root


class Volume(object):
    """Information about a partition. Note that the mountpoint may be set, or not. If it is not set, exception may be
    set. Either way, if mountpoint is set, you can use the partition. Call unmount when you're done!
    """

    def __init__(self, disk=None, stats=False, fsforce=False, fsfallback=None, pretty=False, mountdir=None, **args):
        self.disk = disk
        self.stats = stats
        self.fsforce = fsforce
        self.fsfallback = fsfallback
        self.pretty = pretty
        self.mountdir = mountdir

        # Should be filled somewhere
        self.size = 0
        self.offset = 0
        self.index = 0
        self.size = 0
        self.flag = 'alloc'
        self.fsdescription = None

        # Should be filled by fill_stats
        self.lastmountpoint = None
        self.label = None
        self.version = None
        self.fstype = None

        # Should be filled by mount
        self.mountpoint = None
        self.bindmountpoint = None
        self.loopback = None
        self.exception = None

        # Used by lvm specific functions
        self.volume_group = None
        self.volumes = []
        self.lv_path = None

    def __unicode__(self):
        return u'{0}:{1}'.format(self.index, self.fsdescription)

    def __str__(self):
        return str(self.__unicode__())

    def __cmp__(self, other):
        return cmp(self.lastmountpoint, other.lastmountpoint)

    def _debug(self, val):
        if self.disk:
            self.disk._debug(val)

    def get_description(self, with_size=True):
        desc = ''

        if with_size and self.size:
            desc += u'{0} '.format(self.get_size_gib())

        desc += u'{1}:{0}'.format(self.fstype or self.fsdescription, self.index)

        if self.label:
            desc += u' {0}'.format(self.label)

        if self.version:  # NTFS
            desc += u' [{0}]'.format(self.version)

        return desc

    def get_size_gib(self):
        if self.size and (isinstance(self.size, (int, long)) or self.size.isdigit()):
            if self.size < 1024:
                return u"{0} B".format(self.size)
            elif self.size < 1024 ** 2:
                return u"{0} KiB".format(round(self.size / 1024, 2))
            elif self.size < 1024**3:
                return u"{0} MiB".format(round(self.size / 1024.0 ** 2, 2))
            elif self.size < 1024**4:
                return u"{0} GiB".format(round(self.size / 1024.0 ** 3, 2))
            else:
                return u"{0} TiB".format(round(self.size / 1024.0 ** 4, 2))
        else:
            return self.size

    def get_fs_type(self):
        """Determines the FS type for this partition. Used internally to determine which mount system to use."""

        # Determine fs type. If forced, always use provided type.
        if self.fsforce:
            fstype = self.fsfallback
        else:
            fsdesc = self.fsdescription.lower()
            # for the purposes of this function, logical volume is nothing, and 'primary' is rather useless info.
            if fsdesc in ('logical volume', 'primary'):
                fsdesc = ''
            if not fsdesc and self.fstype:
                fsdesc = self.fstype.lower()

            if u'0x83' in fsdesc or '0xfd' in fsdesc or re.search(r'\bext[0-9]*\b', fsdesc):
                fstype = 'ext'
            elif u'bsd' in fsdesc:
                fstype = 'bsd'
            elif u'0x07' in fsdesc or 'ntfs' in fsdesc:
                fstype = 'ntfs'
            elif u'0x8e' in fsdesc or 'lvm' in fsdesc:
                fstype = 'lvm'
            else:
                fstype = self.fsfallback

            if fstype:
                self._debug("    Detected {0} as {1}".format(fsdesc, fstype))
        return fstype

    def get_raw_base_path(self):
        """Retrieves the base mount path. Used to determine source mount."""

        if self.lv_path:
            return self.lv_path
        else:
            return self.disk.get_fs_path()

    def get_safe_label(self):
        """Returns a label to be added to a path in the fs for this volume."""

        if self.label == '/':
            return 'root'

        suffix = re.sub(r"[/ \(\)]+", "_", self.label) if self.label else ""
        if suffix and suffix[0] == '_':
            suffix = suffix[1:]
        if len(suffix) > 2 and suffix[-1] == '_':
            suffix = suffix[:-1]
        return suffix

    def init(self, no_stats=False):
        """Calls all methods required to fully mount the volume. Yields all subvolumes, or the volume itself,
        if none.
        """

        if self.stats and not no_stats:
            self.fill_stats()
        self.mount()
        if self.stats and not no_stats:
            self.detect_mountpoint()

        subvolumes = self.find_lvm_volumes()

        if not subvolumes:
            yield self
        else:
            for v in subvolumes:
                self._debug(u"    Mounting LVM volume {0}".format(v))
                for s in v.init():
                    yield s

    def mount(self):
        """Mounts the partition locally."""

        raw_path = self.get_raw_base_path()
        fstype = self.get_fs_type()

        # we need a mountpoint if it is not a lvm
        if fstype in ('ext', 'bsd', 'ntfs', 'unknown'):
            if self.pretty:
                md = self.mountdir or tempfile.tempdir
                pretty_label = "{0}-{1}".format(".".join(os.path.basename(self.disk.paths[0]).split('.')[0:-1]),
                                                self.get_safe_label() or self.index)
                path = os.path.join(md, pretty_label)
                #noinspection PyBroadException
                try:
                    os.mkdir(path, 777)
                    self.mountpoint = path
                except:
                    self._debug("[-] Could not create mountdir.")
                    return False
            else:
                self.mountpoint = tempfile.mkdtemp(prefix=u'im_' + str(self.index) + u'_',
                                                   suffix=u'_' + self.get_safe_label(),
                                                   dir=self.mountdir)

        # Prepare mount command
        try:
            if fstype == 'ext':
                # ext
                cmd = [u'mount', raw_path, self.mountpoint, u'-t', u'ext4', u'-o',
                       u'loop,noexec,noload,offset=' + str(self.offset)]
                if not self.disk.read_write:
                    cmd[-1] += ',ro'

                #if not self.fstype:
                #    self.fstype = 'Ext'

            elif fstype == 'bsd':
                # ufs
                #mount -t ufs -o ufstype=ufs2,loop,ro,offset=4294967296 /tmp/image/ewf1 /media/a
                cmd = [u'mount', raw_path, self.mountpoint, u'-t', u'ufs', u'-o',
                       u'ufstype=ufs2,loop,offset=' + str(self.offset)]
                if not self.disk.read_write:
                    cmd[-1] += ',ro'

                #if not self.fstype:
                #    self.fstype = 'UFS'

            elif fstype == 'ntfs':
                # NTFS
                cmd = [u'mount', raw_path, self.mountpoint, u'-t', u'ntfs', u'-o',
                       u'loop,noexec,offset=' + str(self.offset)]
                if not self.disk.read_write:
                    cmd[-1] += ',ro'

                #if not self.fstype:
                #    self.fstype = 'NTFS'

            elif fstype == 'unknown':  # mounts without specifying the filesystem type
                cmd = [u'mount', raw_path, self.mountpoint, u'-o', u'loop,offset=' + str(self.offset)]
                if not self.disk.read_write:
                    cmd[-1] += ',ro'

                #if not self.fstype:
                #    self.fstype = 'Unknown'

            elif fstype == 'lvm':
                # LVM
                os.environ['LVM_SUPPRESS_FD_WARNINGS'] = '1'

                # find free loopback device
                #noinspection PyBroadException
                try:
                    self.loopback = util.check_output_(['losetup', '-f'], self).strip()
                except Exception:
                    self._debug("[-] No free loopback device found for LVM")
                    return False

                cmd = [u'losetup', u'-o', str(self.offset), self.loopback, raw_path]
                if not self.disk.read_write:
                    cmd.insert(1, '-r')

                #if not self.fstype:
                #    self.fstype = 'LVM'

            else:
                try:
                    size = self.size / BLOCK_SIZE
                except TypeError:
                    size = self.size

                self._debug("[-] Unknown filesystem {0} (block offset: {1}, length: {2})"
                            .format(self, self.offset / BLOCK_SIZE, size))
                return False

            # Execute mount
            util.check_call_(cmd, self, stdout=subprocess.PIPE)

            return True
        except Exception as e:
            self._debug("[-] Execution failed due to {0}".format(e))
            self.exception = e

            try:
                if self.mountpoint:
                    os.rmdir(self.mountpoint)
                    self.mountpoint = None
                if self.loopback:
                    self.loopback = None
            except Exception as e2:
                self._debug(e2)

            return False

    def bindmount(self, mountpoint):
        """Bind mounts the volume to another mountpoint."""

        if not self.mountpoint:
            return False
        try:
            self.bindmountpoint = mountpoint
            util.check_call_(['mount', '--bind', self.mountpoint, self.bindmountpoint], self, stdout=subprocess.PIPE)
            return True
        except Exception as e:
            self.bindmountpoint = None
            self._debug("[-] Error bind mounting {0}.".format(self))
            self._debug(e)
            return False

    def find_lvm_volumes(self, force=False):
        """Performs post-mount actions on a LVM.

        Scans for active volume groups from the loopback device, activates it and fills self.volumes with the logical
        volumes
        """

        if not self.loopback and not force:
            return []

        # Scan for new lvm volumes
        result = util.check_output_(["lvm", "pvscan"], self)
        for l in result.splitlines():
            if self.loopback in l or (self.offset == 0 and self.disk.get_fs_path() in l):
                for vg in re.findall(r'VG (\w+)', l):
                    self.volume_group = vg

        if not self.volume_group:
            self._debug("[-] Volume is not a volume group.")
            return []

        # Enable lvm volumes
        util.check_call_(["vgchange", "-a", "y", self.volume_group], self, stdout=subprocess.PIPE)

        # Gather information about lvolumes, gathering their label, size and raw path
        result = util.check_output_(["lvdisplay", self.volume_group], self)
        for l in result.splitlines():
            if "--- Logical volume ---" in l:
                self.volumes.append(Volume(disk=self.disk, stats=self.stats, fsforce=self.fsforce,
                                           fsfallback=self.fsfallback, pretty=self.pretty, mountdir=self.mountdir))
                self.volumes[-1].index = "{0}.{1}".format(self.index, len(self.volumes) - 1)
                self.volumes[-1].fsdescription = 'Logical Volume'
                self.volumes[-1].flag = 'alloc'
            if "LV Name" in l:
                self.volumes[-1].label = l.replace("LV Name", "").strip()
            if "LV Size" in l:
                self.volumes[-1].size = l.replace("LV Size", "").strip()
            if "LV Path" in l:
                self.volumes[-1].lv_path = l.replace("LV Path", "").strip()
                self.volumes[-1].offset = 0

        self._debug("    {0} volumes found".format(len(self.volumes)))

        return self.volumes

    def fill_stats(self):
        """Fills some additional fields from the object using fsstat."""

        process = None

        def stats_thread():
            try:
                cmd = [u'fsstat', self.get_raw_base_path(), u'-o', str(self.offset / BLOCK_SIZE)]
                self._debug('    {0}'.format(' '.join(cmd)))
                #noinspection PyShadowingNames
                process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

                for line in iter(process.stdout.readline, b''):
                    if line.startswith("File System Type:"):
                        self.fstype = line[line.index(':') + 2:].strip()
                    if line.startswith("Last Mount Point:") or line.startswith("Last mounted on:"):
                        self.lastmountpoint = line[line.index(':') + 2:].strip().replace("//", "/")
                    if line.startswith("Volume Name:") and not self.label:
                        self.label = line[line.index(':') + 2:].strip()
                    if line.startswith("Version:"):
                        self.version = line[line.index(':') + 2:].strip()
                    if line.startswith("Source OS:"):
                        self.version = line[line.index(':') + 2:].strip()
                    if 'CYLINDER GROUP INFORMATION' in line:
                        #noinspection PyBroadException
                        try:
                            process.terminate()  # some attempt
                        except Exception:
                            pass
                        break

                if self.lastmountpoint and self.label:
                    self.label = "{0} ({1})".format(self.lastmountpoint, self.label)
                elif self.lastmountpoint and not self.label:
                    self.label = self.lastmountpoint
                elif not self.lastmountpoint and self.label and self.label.startswith("/"):  # e.g. /boot1
                    if self.label.endswith("1"):
                        self.lastmountpoint = self.label[:-1]
                    else:
                        self.lastmountpoint = self.label

            except Exception as e:  # ignore any exceptions here.
                self._debug("[-] Error while obtaining stats.")
                self._debug(e)
                pass

        thread = threading.Thread(target=stats_thread)
        thread.start()

        duration = 5  # longest possible duration for fsstat.
        thread.join(duration)
        if thread.is_alive():
            #noinspection PyBroadException
            try:
                process.terminate()
            except Exception:
                pass
            thread.join()
            self._debug("    Killed fsstat after {0}s".format(duration))

    def detect_mountpoint(self):
        """Attempts to detect the previous mountpoint if the stats are failing on doing so. The volume must be mounted
        first.
        """

        if self.lastmountpoint:
            return self.lastmountpoint
        if not self.mountpoint:
            return None

        result = None
        paths = os.listdir(self.mountpoint)
        if 'grub' in paths:
            result = '/boot'
        elif 'usr' in paths and 'var' in paths and 'root' in paths:
            result = '/'
        elif 'bin' in paths and 'lib' in paths and 'local' in paths and 'src' in paths and not 'usr' in paths:
            result = '/usr'
        elif 'bin' in paths and 'lib' in paths and 'local' not in paths and 'src' in paths and not 'usr' in paths:
            result = '/usr/local'
        elif 'lib' in paths and 'local' in paths and 'tmp' in paths and not 'var' in paths:
            result = '/var'
        #elif sum(['bin' in paths, 'boot' in paths, 'cdrom' in paths, 'dev' in paths, 'etc' in paths, 'home' in paths,
        #          'lib' in paths, 'lib64' in paths, 'media' in paths, 'mnt' in paths, 'opt' in paths,
        #          'proc' in paths, 'root' in paths, 'sbin' in paths, 'srv' in paths, 'sys' in paths, 'tmp' in paths,
        #          'usr' in paths, 'var' in paths]) > 11:
        #    result = '/'

        if result:
            self.lastmountpoint = result
            if not self.label:
                self.label = self.lastmountpoint
            self._debug("    Detected mountpoint as {0} based on files in volume".format(self.lastmountpoint))

        return result

    #noinspection PyBroadException
    def unmount(self):
        """Unounts the partition from the filesystem."""

        for volume in self.volumes:
            volume.unmount()

        if self.loopback and self.volume_group:
            try:
                util.check_call_(['vgchange', '-a', 'n', self.volume_group], self, stdout=subprocess.PIPE)
            except Exception:
                return False

            self.volume_group = None

        if self.loopback:
            try:
                util.check_call_(['losetup', '-d', self.loopback], self)
            except Exception:
                return False

            self.loopback = None

        if self.bindmountpoint:
            if not util.clean_unmount([u'umount'], self.bindmountpoint, rmdir=False):
                return False

            self.bindmountpoint = None

        if self.mountpoint:
            if not util.clean_unmount([u'umount'], self.mountpoint):
                return False

            self.mountpoint = None

        return True
