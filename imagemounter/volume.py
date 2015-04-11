from __future__ import print_function
from __future__ import unicode_literals

import io
import os
import random
import subprocess
import re
import tempfile
import threading
import sys
from imagemounter import util, FILE_SYSTEM_TYPES


FILE_SYSTEM_GUIDS = {
    '2AE031AA-0F40-DB11-9590-000C2911D1B8': 'vmfs',
    '8053279D-AD40-DB11-BF97-000C2911D1B8': 'vmkcore-diagnostics',
    '6A898CC3-1DD2-11B2-99A6-080020736631': 'zfs-member',
    'C38C896A-D21D-B211-99A6-080020736631': 'zfs-member'
}


class Volume(object):
    """Information about a volume. Note that every detected volume gets their own Volume object, though it may or may
    not be mounted. This can be seen through the :attr:`mountpoint` attribute -- if it is not set, perhaps the
    :attr:`exception` attribute is set with an exception.
    """

    def __init__(self, disk=None, stats=False, fsforce=False, fsfallback=None, fstypes=None, pretty=False,
                 mountdir=None, **args):
        """Creates a Volume object that is not mounted yet.

        :param disk: the parent disk
        :type disk: :class:`Disk`
        :param bool stats: indicates whether :func:`init` should try to fill statistics
        :param bool fsforce: indicates whether the file system type in *fsfallback* should be used for all file systems
        :param str fsfallback: the file system type to use when automatic detection fails
        :param dict fstypes: dict mapping volume indices to file system types to (forcibly) use
        :param bool pretty: indicates whether pretty names should be used for the mountpoints
        :param str mountdir: location where mountpoints are created, defaulting to a temporary location
        :param args: additional arguments
        """

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
        self.slot = 0
        self.size = 0
        self.flag = 'alloc'
        self.guid = None
        self.fsdescription = None
        self.fstype = None

        # Should be filled by fill_stats
        self.lastmountpoint = None
        self.label = None
        self.version = None
        self.statfstype = None

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

    # noinspection PyProtectedMember
    def _debug(self, val, level=1):
        if self.disk:
            self.disk._debug(val, level)

    def get_description(self, with_size=True):
        """Obtains a generic description of the volume, containing the file system type, index, label and NTFS version.
        If *with_size* is provided, the volume size is also included.
        """

        desc = ''

        if with_size and self.size:
            desc += '{0} '.format(self.get_size_gib())

        desc += '{1}:{0}'.format(self.statfstype or self.fsdescription, self.index)

        if self.label:
            desc += ' {0}'.format(self.label)

        if self.version:  # NTFS
            desc += ' [{0}]'.format(self.version)

        return desc

    def get_size_gib(self):
        """Obtains the size of the volume in a human-readable format (i.e. in TiBs, GiBs or MiBs)."""

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

    def get_magic_type(self):
        """Checks the volume for its magic bytes and returns the magic."""

        # if we were able to load the module magic
        try:
            # noinspection PyUnresolvedReferences
            import magic

            with io.open(self.disk.get_fs_path(), "rb") as file:
                file.seek(self.offset)
                header = file.read(4096)
            result = magic.from_buffer(header).decode()
            self._debug("    Magic detection returned {}".format(result), 2)
            return result
        except ImportError:
            self._debug("    The python-magic module is not available.")
        except AttributeError:
            self._debug("    The python-magic module is not available, but another module named magic was found.")
        return None

    def determine_fs_type(self):
        """Determines the FS type for this partition. This function is used internally to determine which mount system
        to use, based on the file system description. Return values include *ext*, *bsd*, *ntfs*, *lvm* and *luks*.
        """

        # Determine fs type. If forced, always use provided type.
        if str(self.index) in self.fstypes:
            self.fstype = self.fstypes[str(self.index)]
        elif self.fsforce:
            self.fstype = self.fsfallback
        else:
            # we have two possible sources for determining the FS type: the description given to us by the detection
            # method, and the type given to us by the stat function
            for fsdesc in (self.fsdescription, self.statfstype, self.get_magic_type, self.fill_guid):
                # For efficiency reasons, not all functions are called instantly.
                if callable(fsdesc):
                    fsdesc = fsdesc()
                if not fsdesc:
                    continue
                fsdesc = fsdesc.lower()

                # for the purposes of this function, logical volume is nothing, and 'primary' is rather useless info
                if fsdesc in ('logical volume', 'luks container', 'primary', 'basic data partition'):
                    continue

                if re.search(r'\bext[0-9]*\b', fsdesc):
                    self.fstype = 'ext'
                elif 'bsd' in fsdesc:
                    self.fstype = 'bsd'
                elif '0x07' in fsdesc or 'ntfs' in fsdesc:
                    self.fstype = 'ntfs'
                elif '0x8e' in fsdesc or 'lvm' in fsdesc:
                    self.fstype = 'lvm'
                elif 'luks' in fsdesc:
                    self.fstype = 'luks'
                elif 'fat' in fsdesc or 'efi system partition' in fsdesc:
                    # based on http://en.wikipedia.org/wiki/EFI_System_partition, efi is always fat.
                    self.fstype = 'fat'
                elif 'iso 9660' in fsdesc:
                    self.fstype = 'iso'
                elif 'linux compressed rom file system' in fsdesc:
                    self.fstype = 'cramfs'
                elif fsdesc.startswith("sgi xfs"):
                    self.fstype = "xfs"
                elif re.search(r'\bswap file\b', fsdesc):
                    self.fstype = 'swap'
                elif re.search(r'\bsquashfs\b', fsdesc):
                    self.fstype = 'squashfs'
                elif "jffs2" in fsdesc:
                    self.fstype = 'jffs2'
                elif re.search(r'\bminix filesystem\b', fsdesc):
                    self.fstype = 'minix'
                elif fsdesc in FILE_SYSTEM_GUIDS:
                    # this is a bit of a workaround for the fill_guid method
                    self.fstype = FILE_SYSTEM_GUIDS[fsdesc]
                else:
                    continue  # this loop failed

                self._debug("    Detected {0} as {1}".format(fsdesc, self.fstype))
                if self.fstype not in FILE_SYSTEM_TYPES:
                    self._debug("[-] Detected filesystem is not yet supported")
                break  # we found something
            else:  # we found nothing
                self.fstype = self.fsfallback

        return self.fstype

    get_fs_type = determine_fs_type  # backwards compatibility, remove in 2.0

    def get_raw_base_path(self):
        """Retrieves the base mount path of the volume. Typically equals to :func:`Disk.get_fs_path` but may also be the
        path to a logical volume. This is used to determine the source path for a mount call.
        """

        if self.lv_path:
            return self.lv_path
        elif self.luks_path:
            return '/dev/mapper/' + self.luks_path
        elif self.parent and self.parent.luks_path:
            return '/dev/mapper/' + self.parent.luks_path
        else:
            return self.disk.get_fs_path()

    def get_safe_label(self):
        """Returns a label that is safe to add to a path in the mountpoint for this volume."""

        if self.label == '/':
            return 'root'

        suffix = re.sub(r"[/ \(\)]+", "_", self.label) if self.label else ""
        if suffix and suffix[0] == '_':
            suffix = suffix[1:]
        if len(suffix) > 2 and suffix[-1] == '_':
            suffix = suffix[:-1]
        return suffix

    def init(self, no_stats=False):
        """Generator that mounts this volume and either yields itself or recursively generates its subvolumes.

        More specifically, this function will call :func:`fill_stats` (iff *no_stats* is False), followed by
        :func:`mount`, followed by a call to :func:`detect_mountpoint`, after which ``self`` is yielded, or the result
        of the :func:`init` call on each subvolume is yielded
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

    def _make_mountpoint(self):
        """Creates a directory that can be used as a mountpoint. The directory is stored in :attr:`mountpoint`

        :return: boolean indicating whether the mountpoint was successfully created.
        """

        if self.pretty:
            md = self.mountdir or tempfile.tempdir
            pretty_label = "{0}-{1}".format(".".join(os.path.basename(self.disk.paths[0]).split('.')[0:-1]),
                                            self.get_safe_label() or self.index)
            path = os.path.join(md, pretty_label)
            #noinspection PyBroadException
            try:
                os.mkdir(path, 777)
                self.mountpoint = path
                return True
            except:
                self._debug("[-] Could not create mountdir.")
                return False
        else:
            self.mountpoint = tempfile.mkdtemp(prefix='im_' + str(self.index) + '_',
                                               suffix='_' + self.get_safe_label(),
                                               dir=self.mountdir)
            return True

    def _find_loopback(self, use_loopback=True):
        """Finds a free loopback device that can be used. The loopback is stored in :attr:`loopback`. If *use_loopback*
        is True, the loopback will also be used directly.

        :return: boolean indicating whether a loopback device was found
        """

        # noinspection PyBroadException
        try:
            self.loopback = util.check_output_(['losetup', '-f'], self).strip()
        except Exception:
            self._debug("[-] No free loopback device found.")
            return False

        # noinspection PyBroadException
        if use_loopback:
            try:
                cmd = ['losetup', '-o', str(self.offset), self.loopback, self.get_raw_base_path()]
                if not self.disk.read_write:
                    cmd.insert(1, '-r')
                util.check_call_(cmd, self, stdout=subprocess.PIPE)
            except Exception as e:
                self._debug("[-] Loopback device could not be mounted.")
                self._debug(e)
                return False
        return True

    def mount(self):
        """Based on the file system type as determined by :func:`determine_fs_type`, the proper mount command is executed
        for this volume. The volume is mounted in a temporary path (or a pretty path if :attr:`pretty` is enabled) in
        the mountpoint as specified by :attr:`mountpoint`.

        If the file system type is a LUKS container, :func:`open_luks_container` is called only. If it is a LVM volume,
        :func:`find_lvm_volumes` is called after the LVM has been mounted. Both methods will add subvolumes to
        :attr:`volumes`

        :return: boolean indicating whether the mount succeeded
        """

        raw_path = self.get_raw_base_path()
        self.determine_fs_type()

        # we need a mountpoint if it is not a lvm or luks volume
        if self.fstype not in ('luks', 'lvm') and self.fstype in FILE_SYSTEM_TYPES and not self._make_mountpoint():
            return False

        # Prepare mount command
        try:
            if self.fstype == 'ext':
                # ext
                cmd = ['mount', raw_path, self.mountpoint, '-t', 'ext4', '-o',
                       'loop,noexec,noload,offset=' + str(self.offset)]
                if not self.disk.read_write:
                    cmd[-1] += ',ro'

                util.check_call_(cmd, self, stdout=subprocess.PIPE)

            elif self.fstype == 'bsd':
                # ufs
                #mount -t ufs -o ufstype=ufs2,loop,ro,offset=4294967296 /tmp/image/ewf1 /media/a
                cmd = ['mount', raw_path, self.mountpoint, '-t', 'ufs', '-o',
                       'ufstype=ufs2,loop,offset=' + str(self.offset)]
                if not self.disk.read_write:
                    cmd[-1] += ',ro'

                util.check_call_(cmd, self, stdout=subprocess.PIPE)

            elif self.fstype == 'ntfs':
                # NTFS
                cmd = ['mount', raw_path, self.mountpoint, '-t', 'ntfs', '-o',
                       'loop,noexec,offset=' + str(self.offset)]
                if not self.disk.read_write:
                    cmd[-1] += ',ro'

                util.check_call_(cmd, self, stdout=subprocess.PIPE)

            elif self.fstype == 'xfs':
                # ext
                cmd = ['mount', raw_path, self.mountpoint, '-t', 'xfs', '-o',
                       'loop,norecovery,offset=' + str(self.offset)]
                if not self.disk.read_write:
                    cmd[-1] += ',ro'

                util.check_call_(cmd, self, stdout=subprocess.PIPE)

            elif self.fstype in ('iso', 'udf', 'squashfs', 'cramfs', 'minix'):
                command = {'iso': 'iso9660', 'fat': 'vfat'}.get(self.fstype, self.fstype)
                cmd = ['mount', raw_path, self.mountpoint, '-t', command, '-o',
                       'loop,offset=' + str(self.offset)]
                # not always needed, only to make command generic
                if not self.disk.read_write:
                    cmd[-1] += ',ro'

                util.check_call_(cmd, self, stdout=subprocess.PIPE)

            elif self.fstype == 'vmfs':
                self.loopback = self.setup_loopback()

                cmd = ['vmfs-fuse', self.loopback, self.mountpoint]

                util.check_call_(cmd, self, stdout=subprocess.PIPE)

            elif self.fstype == 'unknown':  # mounts without specifying the filesystem type
                cmd = ['mount', raw_path, self.mountpoint, '-o', 'loop,offset=' + str(self.offset)]
                if not self.disk.read_write:
                    cmd[-1] += ',ro'

                util.check_call_(cmd, self, stdout=subprocess.PIPE)

            elif self.fstype == 'jffs2':
                self.open_jffs2()

            elif self.fstype == 'luks':
                self.open_luks_container()

            elif self.fstype == 'lvm':
                # LVM
                os.environ['LVM_SUPPRESS_FD_WARNINGS'] = '1'

                # find free loopback device
                if not self._find_loopback():
                    return False

                self.find_lvm_volumes()

            else:
                try:
                    size = self.size / self.disk.block_size
                except TypeError:
                    size = self.size

                self._debug("[-] Unknown filesystem {0} (type: {1}, block offset: {2}, length: {3})"
                            .format(self, self.fstype, self.offset / self.disk.block_size, size))
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
        """Bind mounts the volume to another mountpoint. Only works if the volume is already mounted. Note that only the
        last bindmountpoint is remembered and cleaned.

        :return: bool indicating whether the bindmount succeeded
        """

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
        """Command that is an alternative to the :func:`mount` command that opens a LUKS container. The opened volume is
        added to the subvolume set of this volume. Requires the user to enter the key manually.

        :return: the Volume contained in the LUKS container, or None on failure.
        """

        # Open a loopback device
        if not self._find_loopback():
            return None

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
            if not self.disk.read_write:
                cmd.insert(1, '-r')
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
                    size = int(l.replace("size:", "").replace("sectors", "").strip()) * self.disk.block_size
        except Exception:
            pass

        container = Volume(disk=self.disk, stats=self.stats, fsforce=self.fsforce,
                           fsfallback=self.fsfallback, fstypes=self.fstypes, pretty=self.pretty, mountdir=self.mountdir)
        container.index = "{0}.0".format(self.index)
        container.fsdescription = 'LUKS container'
        container.flag = 'alloc'
        container.parent = self
        container.offset = 0
        container.size = size
        self.volumes.append(container)

        return container

    def open_jffs2(self):
        """Perform specific operations to mount a JFFS2 image. This kind of image is sometimes used for things like
        bios images. so external tools are required but given this method you don't have to memorize anything and it
        works fast and easy.

        Note that this module might not yet work while mounting multiple images at the same time.
        """
        # we have to make a ram-device to store the image, we keep 20% overhead
        size_in_kb = int((self.size / 1024) * 1.2)
        util.check_call_(['modprobe', '-v', 'mtd'], self)
        util.check_call_(['modprobe', '-v', 'jffs2'], self)
        util.check_call_(['modprobe', '-v', 'mtdram', 'total_size={}'.format(size_in_kb), 'erase_size=256'], self)
        util.check_call_(['modprobe', '-v', 'mtdblock'], self)
        util.check_call_(['dd', 'if=' + self.get_raw_base_path(), 'of=/dev/mtd0'], self)
        util.check_call_(['mount', '-t', 'jffs2', '/dev/mtdblock0', self.mountpoint], self)

        return True

    def find_lvm_volumes(self, force=False):
        """Performs post-mount actions on a LVM. Scans for active volume groups from the loopback device, activates it
        and fills :attr:`volumes` with the logical volumes.

        If *force* is true, the LVM detection is ran even when the LVM is not mounted on a loopback device.
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
        """Recursively gets a list of all subvolumes and the current volume."""

        if self.volumes:
            volumes = []
            for v in self.volumes:
                volumes.extend(v.get_volumes())
            volumes.append(self)
            return volumes
        else:
            return [self]

    def fill_guid(self):
        """Calls the :command:`disktype` command and obtains the disk GUID from GPT volume systems. As we
        are running the tool anyway, the label is also extracted from the tool if it is not yet set.

        :return: None if an exception occurred or the GUID if succeeded.
        """

        if not util.command_exists('disktype'):
            self._debug("    disktype not installed, could not detect volume type")
            return None

        disktype = util.check_output_(['disktype', self.disk.get_raw_path()], self).strip()
        partition_nr = self.slot + 1

        # Only works if we have a GPT partition table
        if "GPT partition map" not in disktype:
            self._debug("    Not a GPT partition table, no GUID available.")
            return None
        disktype_gpt = disktype.split("GPT partition map", 1)[-1]
        match_found = False
        for line in disktype_gpt.splitlines():
            if not line:
                continue
            try:
                line = line.strip()

                if line.startswith('Partition'):
                    match_found = line.startswith('Partition '+str(partition_nr)+':')

                if match_found:
                    if line.startswith("Type ") and "GUID" in line and not self.guid:
                        self.guid = line[line.index('GUID') + 5:-1].strip()  # output is between ()
                    elif line.startswith("Partition Name ") and not self.label:
                        self.label = line[line.index('Name ') + 6:-1].strip()  # output is between ""

            except Exception as e:
                self._debug("[-] Error while parsing disktype output")
                self._debug(e)
                continue

        self._debug("    GUID of volume is {}".format(self.guid), 2)

        return self.guid

    def fill_stats(self):
        """Using :command:`fsstat`, adds some additional information of the volume to the Volume."""

        process = None

        def stats_thread():
            try:
                cmd = ['fsstat', self.get_raw_base_path(), '-o', str(self.offset // self.disk.block_size)]
                self._debug('    {0}'.format(' '.join(cmd)))
                #noinspection PyShadowingNames
                process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

                for line in iter(process.stdout.readline, b''):
                    line = line.decode()
                    if line.startswith("File System Type:"):
                        self.statfstype = line[line.index(':') + 2:].strip()
                    elif line.startswith("Last Mount Point:") or line.startswith("Last mounted on:"):
                        self.lastmountpoint = line[line.index(':') + 2:].strip().replace("//", "/")
                    elif line.startswith("Volume Name:") and not self.label:
                        self.label = line[line.index(':') + 2:].strip()
                    elif line.startswith("Version:"):
                        self.version = line[line.index(':') + 2:].strip()
                    elif line.startswith("Source OS:"):
                        self.version = line[line.index(':') + 2:].strip()
                    elif 'CYLINDER GROUP INFORMATION' in line:
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
        """Attempts to detect the previous mountpoint if this was not done through :func:`fill_stats`. This detection
        does some heuristic method on the mounted volume.
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
        """Unounts the volume from the filesystem."""

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
