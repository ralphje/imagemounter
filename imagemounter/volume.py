from __future__ import print_function
from __future__ import unicode_literals

import os
import random
import subprocess
import re
import tempfile
import threading
import sys
from imagemounter import util, BLOCK_SIZE


class Volume(object):
    """Information about a partition. Note that the mountpoint may be set, or not. If it is not set, exception may be
    set. Either way, if mountpoint is set, you can use the partition. Call unmount when you're done!
    """

    def __init__(self, disk=None, stats=False, fsforce=False, fsfallback=None, fstypes=None, pretty=False,
                 mountdir=None, **args):
        self.disk = disk
        self.stats = stats
        self.fsforce = fsforce
        self.fsfallback = fsfallback
        self.fstypes = fstypes or {}
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
        self.was_mounted = False

        # Used by functions that create subvolumes
        self.volumes = []
        self.parent = None

        # Used by lvm specific functions
        self.volume_group = None
        self.lv_path = None

        # Used by LUKS
        self.luks_path = None

        self.args = args

    def __unicode__(self):
        return '{0}:{1}'.format(self.index, self.fsdescription)

    def __str__(self):
        return str(self.__unicode__())

    def __cmp__(self, other):
        return cmp(self.lastmountpoint, other.lastmountpoint)

    # noinspection PyProtectedMember
    def _debug(self, val):
        if self.disk:
            self.disk._debug(val)

    def get_description(self, with_size=True):
        desc = ''

        if with_size and self.size:
            desc += '{0} '.format(self.get_size_gib())

        desc += '{1}:{0}'.format(self.fstype or self.fsdescription, self.index)

        if self.label:
            desc += ' {0}'.format(self.label)

        if self.version:  # NTFS
            desc += ' [{0}]'.format(self.version)

        return desc

    def get_size_gib(self):
        # Python 3 compatibility
        if sys.version_info[0] == 2:
            integer_types = (int, long)
        else:
            integer_types = int

        # noinspection PyUnresolvedReferences
        if self.size and (isinstance(self.size, integer_types) or self.size.isdigit()):
            if self.size < 1024:
                return "{0} B".format(self.size)
            elif self.size < 1024 ** 2:
                return "{0} KiB".format(round(self.size / 1024, 2))
            elif self.size < 1024**3:
                return "{0} MiB".format(round(self.size / 1024.0 ** 2, 2))
            elif self.size < 1024**4:
                return "{0} GiB".format(round(self.size / 1024.0 ** 3, 2))
            else:
                return "{0} TiB".format(round(self.size / 1024.0 ** 4, 2))
        else:
            return self.size

    def get_fs_type(self):
        """Determines the FS type for this partition. Used internally to determine which mount system to use."""

        # Determine fs type. If forced, always use provided type.
        if str(self.index) in self.fstypes:
            fstype = self.fstypes[str(self.index)]
        elif self.fsforce:
            fstype = self.fsfallback
        else:
            fsdesc = self.fsdescription.lower()
            # for the purposes of this function, logical volume is nothing, and 'primary' is rather useless info.
            if fsdesc in ('logical volume', 'luks container', 'primary'):
                fsdesc = ''
            if not fsdesc and self.fstype:
                fsdesc = self.fstype.lower()

            if '0x83' in fsdesc or '0xfd' in fsdesc or re.search(r'\bext[0-9]*\b', fsdesc):
                fstype = 'ext'
            elif 'bsd' in fsdesc:
                fstype = 'bsd'
            elif '0x07' in fsdesc or 'ntfs' in fsdesc:
                fstype = 'ntfs'
            elif '0x8e' in fsdesc or 'lvm' in fsdesc:
                fstype = 'lvm'
            elif 'luks' in fsdesc:
                fstype = 'luks'
            else:
                fstype = self.fsfallback

            if fstype:
                self._debug("    Detected {0} as {1}".format(fsdesc, fstype))

        return fstype

    def get_raw_base_path(self):
        """Retrieves the base mount path. Used to determine source mount."""

        if self.lv_path:
            return self.lv_path
        elif self.luks_path:
            return '/dev/mapper/' + self.luks_path
        elif self.parent and self.parent.luks_path:
            return '/dev/mapper/' + self.parent.luks_path
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

        if not self.volumes:
            yield self
        else:
            for v in self.volumes:
                self._debug("    Mounting LVM volume {0}".format(v))
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
                self.mountpoint = tempfile.mkdtemp(prefix='im_' + str(self.index) + '_',
                                                   suffix='_' + self.get_safe_label(),
                                                   dir=self.mountdir)

        # Prepare mount command
        try:
            if fstype == 'ext':
                # ext
                cmd = ['mount', raw_path, self.mountpoint, '-t', 'ext4', '-o',
                       'loop,noexec,noload,offset=' + str(self.offset)]
                if not self.disk.read_write:
                    cmd[-1] += ',ro'

                util.check_call_(cmd, self, stdout=subprocess.PIPE)

            elif fstype == 'bsd':
                # ufs
                #mount -t ufs -o ufstype=ufs2,loop,ro,offset=4294967296 /tmp/image/ewf1 /media/a
                cmd = ['mount', raw_path, self.mountpoint, '-t', 'ufs', '-o',
                       'ufstype=ufs2,loop,offset=' + str(self.offset)]
                if not self.disk.read_write:
                    cmd[-1] += ',ro'

                util.check_call_(cmd, self, stdout=subprocess.PIPE)

            elif fstype == 'ntfs':
                # NTFS
                cmd = ['mount', raw_path, self.mountpoint, '-t', 'ntfs', '-o',
                       'loop,noexec,offset=' + str(self.offset)]
                if not self.disk.read_write:
                    cmd[-1] += ',ro'

                util.check_call_(cmd, self, stdout=subprocess.PIPE)

            elif fstype == 'luks':
                self.open_luks_container()

            elif fstype == 'unknown':  # mounts without specifying the filesystem type
                cmd = ['mount', raw_path, self.mountpoint, '-o', 'loop,offset=' + str(self.offset)]
                if not self.disk.read_write:
                    cmd[-1] += ',ro'

                util.check_call_(cmd, self, stdout=subprocess.PIPE)

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

                cmd = ['losetup', '-o', str(self.offset), self.loopback, raw_path]
                if not self.disk.read_write:
                    cmd.insert(1, '-r')

                util.check_call_(cmd, self, stdout=subprocess.PIPE)

                self.find_lvm_volumes()

            else:
                try:
                    size = self.size / BLOCK_SIZE
                except TypeError:
                    size = self.size

                self._debug("[-] Unknown filesystem {0} (block offset: {1}, length: {2})"
                            .format(self, self.offset / BLOCK_SIZE, size))
                return False

            self.was_mounted = True

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

    def open_luks_container(self):
        """Alternative to the mount command, trying to open a LUKS container"""

        # Open a loopback device
        #noinspection PyBroadException
        try:
            self.loopback = util.check_output_(['losetup', '-f'], self).strip()
        except Exception:
            self._debug("[-] No free loopback device found for LUKS")
            return None

        cmd = ['losetup', '-o', str(self.offset), self.loopback, self.get_raw_base_path()]
        if not self.disk.read_write:
            cmd.insert(1, '-r')

        util.check_call_(cmd, self, stdout=subprocess.PIPE)

        # Check if this is a LUKS device
        # noinspection PyBroadException
        try:
            util.check_call_(["cryptsetup", "isLuks", self.loopback], self, stderr=subprocess.STDOUT)
            # ret = 0 if isLuks
        except Exception:
            self._debug("[-] Not a LUKS volume")
            # clean the loopback device, we want this method to be clean as possible
            # noinspection PyBroadException
            try:
                util.check_call_(['losetup', '-d', self.loopback], self)
                self.loopback = None
            except Exception:
                pass

            return None

        # Open the LUKS container
        self.luks_path = 'image_mounter_' + str(random.randint(10000, 99999))

        # noinspection PyBroadException
        try:
            cmd = ["cryptsetup", "luksOpen", self.loopback, self.luks_path]
            util.check_call_(cmd, self)
        except Exception:
            self.luks_path = None
            return None

        size = None
        # noinspection PyBroadException
        try:
            result = util.check_output_(["cryptsetup", "status", self.luks_path], self)
            for l in result.splitlines():
                if "size:" in l and "key" not in l:
                    size = int(l.replace("size:", "").replace("sectors", "").strip()) * BLOCK_SIZE
        except Exception:
            pass

        container = Volume(disk=self.disk, stats=self.stats, fsforce=self.fsforce,
                           fsfallback=self.fsfallback, fstypes=self.fstypes, pretty=self.pretty, mountdir=self.mountdir)
        container.index = "{0}.0".format(self.index)
        container.fsdescription = 'LUKS container'
        container.flag = 'alloc'
        container.parent = self
        container.offset = 0
        container.size = size  # kan uit status gehaald worden
        self.volumes.append(container)

        return container

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
            if self.loopback in l or (self.offset == 0 and self.get_raw_base_path() in l):
                for vg in re.findall(r'VG (\S+)', l):
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
                                           fsfallback=self.fsfallback, fstypes=self.fstypes,
                                           pretty=self.pretty, mountdir=self.mountdir))
                self.volumes[-1].index = "{0}.{1}".format(self.index, len(self.volumes) - 1)
                self.volumes[-1].fsdescription = 'Logical Volume'
                self.volumes[-1].flag = 'alloc'
                self.volumes[-1].parent = self
            if "LV Name" in l:
                self.volumes[-1].label = l.replace("LV Name", "").strip()
            if "LV Size" in l:
                self.volumes[-1].size = l.replace("LV Size", "").strip()
            if "LV Path" in l:
                self.volumes[-1].lv_path = l.replace("LV Path", "").strip()
                self.volumes[-1].offset = 0

        self._debug("    {0} volumes found".format(len(self.volumes)))

        return self.volumes

    def get_volumes(self):
        """Gets a list of all subvolumes and the current volume. (Recursive.)"""

        if self.volumes:
            volumes = []
            for v in self.volumes:
                volumes.extend(v.get_volumes())
            volumes.append(self)
            return volumes
        else:
            return [self]

    def fill_stats(self):
        """Fills some additional fields from the object using fsstat."""

        process = None

        def stats_thread():
            try:
                cmd = ['fsstat', self.get_raw_base_path(), '-o', str(self.offset / BLOCK_SIZE)]
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

        if self.loopback and self.luks_path:
            try:
                util.check_call_(['cryptsetup', 'luksClose', self.luks_path], self, stdout=subprocess.PIPE)
            except Exception:
                return False

            self.luks_path = None

        if self.loopback:
            try:
                util.check_call_(['losetup', '-d', self.loopback], self)
            except Exception:
                return False

            self.loopback = None

        if self.bindmountpoint:
            if not util.clean_unmount(['umount'], self.bindmountpoint, rmdir=False, parser=self):
                return False

            self.bindmountpoint = None

        if self.mountpoint:
            if not util.clean_unmount(['umount'], self.mountpoint, parser=self):
                return False

            self.mountpoint = None

        return True
