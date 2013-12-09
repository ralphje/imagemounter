import copy
import re
import subprocess
import tempfile
import pytsk3
import threading
import glob
import sys
import os

from imagemounter import util
from termcolor import colored

__ALL__ = ['Volume', 'ImageParser']
__version__ = '1.2.2'

BLOCK_SIZE = 512


class ImageParser(object):
    """Parses an image and mounts it."""

    VOLUME_SYSTEM_TYPES = ('detect', 'dos', 'bsd', 'sun', 'mac', 'gpt', 'dbfiller')

    #noinspection PyUnusedLocal
    def __init__(self, path, out=sys.stdout, mountdir=None, vstype='detect',
                 fstype=None, fsforce=False, read_write=False, verbose=False, color=False, stats=False, method='auto',
                 **args):
        path = os.path.expandvars(os.path.expanduser(path))
        if util.is_encase(path):
            self.type = 'encase'
        else:
            self.type = 'dd'
        self.paths = sorted(util.expand_path(path))

        self.read_write = read_write
        self.verbose = verbose
        self.verbose_color = color
        self.stats = stats

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

        self.out = out

        if read_write:
            self.rwpath = tempfile.mkstemp(prefix="image_mounter_rw_cache_")[1]
        else:
            self.rwpath = None
        self.name = os.path.split(path)[1]
        self.basemountpoint = u''
        self.partitions = []
        self.baseimage = None
        self.volumes = None
        self.mountdir = mountdir

        if vstype == 'any':
            self.vstype = 'any'
        else:
            self.vstype = getattr(pytsk3, 'TSK_VS_TYPE_' + vstype.upper())
        self.fstype = fstype
        self.fsforce = fsforce

    def _debug(self, val):
        if self.verbose:
            if self.verbose_color:
                print >> self.out, colored(val, "cyan")
            else:
                print >> self.out, val

    def mount_base(self):
        """Mount the image at a temporary path for analysis"""

        self.basemountpoint = tempfile.mkdtemp(prefix=u'image_mounter_')

        for paths in (self.paths[:1], self.paths):
            try:
                if self.method == 'xmount':
                    cmd = [u'xmount', '--in', 'ewf' if self.type == 'encase' else 'dd']
                    if self.read_write:
                        cmd.extend(['--rw', self.rwpath])
                elif self.method == 'affuse':
                    cmd = [u'affuse', '-o', 'allow_other']
                elif self.method == 'ewfmount':
                    cmd = [u'ewfmount', '-X', 'allow_other']
                else:
                    raise Exception("Unknown mount method {0}".format(self.method))

                cmd.extend(paths)
                cmd.append(self.basemountpoint)

                util.check_call_(cmd, self, stdout=subprocess.PIPE)
                return True

            except Exception as e:
                self._debug(u'[-] Could not mount {0} (see below), will try multi-file method'.format(paths[0]))
                self._debug(e)

        os.rmdir(self.basemountpoint)
        self.basemountpoint = None

        return False

    def get_raw_path(self):
        raw_path = glob.glob(os.path.join(self.basemountpoint, u'*.dd'))
        raw_path.extend(glob.glob(os.path.join(self.basemountpoint, u'*.raw')))
        raw_path.extend(glob.glob(os.path.join(self.basemountpoint, u'ewf1')))
        return raw_path[0]

    def mount_partitions(self):
        """Generator that mounts every partition of this image and yields the mountpoint."""

        # ewf raw image is now available on basemountpoint
        # either as ewf1 file or as .dd file
        raw_path = self.get_raw_path()
        try:
            self.baseimage = pytsk3.Img_Info(raw_path)
        except Exception as e:
            self._debug(u"[-] Failed retrieving image info (possible empty image).")
            self._debug(e)
            return

        # any loops over all vstypes
        if self.vstype == 'any':
            for vs in ImageParser.VOLUME_SYSTEM_TYPES:
                #noinspection PyBroadException
                try:
                    vst = getattr(pytsk3, 'TSK_VS_TYPE_' + vs.upper())
                    self.volumes = pytsk3.Volume_Info(self.baseimage, vst)
                    self._debug(u"[+] Using VS type {0}".format(vs))
                    break
                except Exception as e:
                    self._debug(u"    VS type {0} did not work".format(vs))
            else:
                self._debug(u"[-] Failed retrieving volume info")
                return
        else:
            try:
                self.volumes = pytsk3.Volume_Info(self.baseimage, self.vstype)
            except Exception as e:
                self._debug(u"[-] Failed retrieving volume info (possible empty image).")
                self._debug(e)
                return

        # Loop over all volumes in image.
        for p in self.volumes:
            try:
                partition = Volume(parser=self)
                self.partitions.append(partition)
                partition.offset = p.start * BLOCK_SIZE
                partition.fsdescription = p.desc
                partition.index = p.addr
                partition.size = p.len * BLOCK_SIZE

                # Retrieve additional information about image by using fsstat.
                if self.stats:
                    partition.fill_stats()

                partition.mount()
                subvolumes = partition.find_lvm_volumes()  # this method does nothing when it is not an lvm
                if not subvolumes:
                    yield partition
                else:
                    # yield from subvolumes
                    for p in subvolumes:
                        self._debug(u"    Mounting LVM volume {0}".format(p))
                        if self.stats:
                            p.fill_stats()
                        p.mount()
                        yield p

            except Exception as e:
                partition.exception = e
                self._debug(e)
                try:
                    if partition.mountpoint:
                        os.rmdir(partition.mountpoint)
                        partition.mountpoint = None
                except Exception as ex:
                    self._debug(ex)
                yield partition

    def rw_active(self):
        """Indicates whether the rw-path is active."""

        return self.rwpath and os.path.getsize(self.rwpath)

    def clean(self, remove_rw=False):
        """Method that removes all ties to the filesystem, so the image can be unmounted successfully"""

        if self.baseimage:
            self.baseimage.close()
        self.baseimage = None
        self.volumes = None

        if self.rw_active() and remove_rw:
            os.remove(self.rwpath)

        for m in self.partitions:
            if not m.unmount():
                self._debug(u"[-] Error unmounting partition {0}".format(m.mountpoint))

        if self.basemountpoint and not util.clean_unmount([u'fusermount', u'-u'], self.basemountpoint):
            self._debug(u"[-] Error unmounting base partition {0}".format(self.basemountpoint))
            return False
        return True

    #noinspection PyBroadException
    @staticmethod
    def force_clean(execute=True):
        """Cleans previous mount points without knowing which is mounted. It assumes proper naming of mountpoints.

        1. Unmounts all bind mounted folders in folders with a name of the form /im_0_
        2. Unmounts all folders with a name of the form /im_0_ or originating from /image_mounter_
        3. Deactivates volume groups which originate from a loopback device, which originates from /image_mounter
        4. ... and unmounts their related loopback devices
        5. Unmounts all /image_mounter_ folders
        6. Removes all /tmp/image_mounter folders

        Performs only a dry run when execute==False
        """

        commands = []

        # find all mountponits
        mountpoints = {}
        try:
            result = util.check_output_(['mount'])
            for line in result.splitlines():
                m = re.match(r'(.+) on (.+) type (.+) \((.+)\)', line)
                if m:
                    mountpoints[m.group(2)] = (m.group(1), m.group(3), m.group(4))
        except Exception:
            pass

        # start by unmounting all bind mounts
        for mountpoint, (orig, fs, opts) in mountpoints.items():
            if 'bind' in opts and re.match(r".*/im_[0-9.]+_.+", mountpoint):
                commands.append('umount {0}'.format(mountpoint))
                if execute:
                    util.clean_unmount(['umount'], mountpoint, rmdir=False)
        # now unmount all mounts originating from an image_mounter
        for mountpoint, (orig, fs, opts) in mountpoints.items():
            if 'bind' not in opts and ('/image_mounter_' in orig or re.match(r".*/im_[0-9.]+_.+", mountpoint)):
                commands.append('umount {0}'.format(mountpoint))
                commands.append('rm -Rf {0}'.format(mountpoint))
                if execute:
                    util.clean_unmount(['umount'], mountpoint)

        # find all loopback devices
        loopbacks = {}
        try:
            result = util.check_output_(['losetup', '-a'])
            for line in result.splitlines():
                m = re.match(r'(.+): (.+) \((.+)\).*', line)
                if m:
                    loopbacks[m.group(1)] = m.group(3)
        except Exception:
            pass

        # find volume groups
        try:
            result = util.check_output_(['pvdisplay'])
            pvname = vgname = None
            for line in result.splitlines():
                if '--- Physical volume ---' in line:
                    pvname = vgname = None
                elif "PV Name" in line:
                    pvname = line.replace("PV Name", "").strip()
                elif "VG Name" in line:
                    vgname = line.replace("VG Name", "").strip()

                if pvname and vgname:
                    try:
                        # unmount volume groups with a physical volume originating from a disk image
                        if '/image_mounter_' in loopbacks[pvname]:
                            commands.append('lvchange -a n {0}'.format(vgname))
                            commands.append('losetup -d {0}'.format(pvname))
                            if execute:
                                util.check_output_(['lvchange', '-a', 'n', vgname])
                                util.check_output_(['losetup', '-d', pvname])
                    except Exception:
                        pass
                    pvname = vgname = None

        except Exception:
            pass

        # unmount base image
        for mountpoint, _ in mountpoints.items():
            if '/image_mounter_' in mountpoint:
                commands.append('fusermount -u {0}'.format(mountpoint))
                commands.append('rm -Rf {0}'.format(mountpoint))
                if execute:
                    util.clean_unmount(['fusermount', '-u'], mountpoint)

        # finalize by cleaning /tmp
        for folder in glob.glob("/tmp/im_*"):
            if re.match(r".*/im_[0-9.]+_.+", folder):
                cmd = 'rm -Rf {0}'.format(folder)
                if cmd not in commands:
                    commands.append(cmd)
                if execute:
                    try:
                        os.rmdir(folder)
                    except Exception:
                        pass
        for folder in glob.glob("/tmp/image_mounter_*"):
            cmd = 'rm -Rf {0}'.format(folder)
            if cmd not in commands:
                commands.append(cmd)
            if execute:
                try:
                    os.rmdir(folder)
                except Exception:
                    pass

        return commands

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
            try:
                v.bindmount = os.path.join(root.mountpoint, v.lastmountpoint[1:])
                util.check_call_(['mount', '--bind', v.mountpoint, v.bindmount], self, stdout=subprocess.PIPE)
            except Exception as e:
                v.bindmount = None
                self._debug("[-] Error bind mounting {0}.".format(v))
                self._debug(e)
        return root


class Volume(object):
    """Information about a partition. Note that the mountpoint may be set, or not. If it is not set, exception may be
    set. Either way, if mountpoint is set, you can use the partition. Call unmount when you're done!
    """

    def __init__(self, parser=None, mountpoint=None, offset=0, fstype=None, fsdescription=None, index=None,
                 label=None, lastmountpoint=None, version=None, bindmount=None, exception=None, size=None,
                 loopback=None, volume_group=None):
        self.parser = parser
        self.mountpoint = mountpoint
        self.offset = offset
        self.fstype = fstype
        self.fsdescription = fsdescription
        self.index = index
        self.label = label
        self.version = version
        self.lastmountpoint = lastmountpoint
        self.exception = exception
        self.size = size
        self.loopback = loopback

        self.volume_group = volume_group
        self.volumes = []
        self.lv_path = None

        self.bindmount = bindmount

    def __unicode__(self):
        return u'{0}:{1}'.format(self.index, self.fsdescription)

    def __str__(self):
        return str(self.__unicode__())

    def __cmp__(self, other):
        return cmp(self.lastmountpoint, other.lastmountpoint)

    def _debug(self, val):
        if self.parser:
            #noinspection PyProtectedMember
            self.parser._debug(val)

    def get_description(self):
        if self.size:
            desc = u'{0} '.format(self.get_size_gib())
        else:
            desc = u''

        desc += u'{1}:{0}'.format(self.fstype, self.index)

        if self.label:
            desc += u' {0}'.format(self.label)

        if self.version:  # NTFS
            desc += u' [{0}]'.format(self.version)

        return desc

    def get_size_gib(self):
        if self.size and (isinstance(self.size, (int, long)) or self.size.isdigit()):
            return u"{0} GiB".format(round(self.size / 1024.0 ** 3, 2))
        else:
            return self.size

    def get_fs_type(self):
        """Determines the FS type for this partition. Used internally to determine which mount system to use."""

        # Determine fs type. If forced, always use provided type.
        if self.parser.fsforce:
            fstype = self.parser.fstype
        else:
            fsdesc = self.fsdescription.lower()
            # for the purposes of this function, logical volume is nothing.
            if fsdesc == 'logical volume':
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
                fstype = self.parser.fstype

            self._debug("    Detected {0} as {1}".format(fsdesc,fstype))
        return fstype

    def get_raw_base_path(self):
        """Retrieves the base mount path. Used to determine source mount."""

        if self.lv_path:
            return self.lv_path
        else:
            return self.parser.get_raw_path()

    def mount(self):
        """Mounts the partition locally."""

        raw_path = self.get_raw_base_path()
        fstype = self.get_fs_type()

        # we need a mountpoint if it is not a lvm
        if fstype in ('ext', 'bsd', 'ntfs', 'unknown'):
            suffix = re.sub(r"[/ \(\)]+", "_", self.label) if self.label else ""
            if suffix and not suffix[0] == '_':
                suffix = '_' + suffix
            if len(suffix) > 2 and suffix[-1] == '_':
                suffix = suffix[:-1]
            self.mountpoint = tempfile.mkdtemp(prefix=u'im_' + str(self.index) + u'_', suffix=suffix,
                                               dir=self.parser.mountdir)

        # Prepare mount command
        try:
            if fstype == 'ext':
                # ext
                cmd = [u'mount', raw_path, self.mountpoint, u'-t', u'ext4', u'-o',
                       u'loop,noexec,noload,offset=' + str(self.offset)]
                if not self.parser.read_write:
                    cmd[-1] += ',ro'

                if not self.fstype:
                    self.fstype = 'Ext'

            elif fstype == 'bsd':
                # ufs
                #mount -t ufs -o ufstype=ufs2,loop,ro,offset=4294967296 /tmp/image/ewf1 /media/a
                cmd = [u'mount', raw_path, self.mountpoint, u'-t', u'ufs', u'-o',
                       u'ufstype=ufs2,loop,offset=' + str(self.offset)]
                if not self.parser.read_write:
                    cmd[-1] += ',ro'

                if not self.fstype:
                    self.fstype = 'UFS'

            elif fstype == 'ntfs':
                # NTFS
                cmd = [u'mount', raw_path, self.mountpoint, u'-t', u'ntfs', u'-o',
                       u'loop,noexec,offset=' + str(self.offset)]
                if not self.parser.read_write:
                    cmd[-1] += ',ro'

                if not self.fstype:
                    self.fstype = 'NTFS'

            elif fstype == 'unknown':  # mounts without specifying the filesystem type
                cmd = [u'mount', raw_path, self.mountpoint, u'-o', u'loop,offset=' + str(self.offset)]
                if not self.parser.read_write:
                    cmd[-1] += ',ro'

                if not self.fstype:
                    self.fstype = 'Unknown'

            elif fstype == 'lvm':
                # LVM
                os.environ['LVM_SUPPRESS_FD_WARNINGS'] = '1'

                # find free loopback device
                #noinspection PyBroadException
                try:
                    self.loopback = util.check_output_(['losetup', '-f'], self.parser).strip()
                except Exception:
                    self._debug("[-] No free loopback device found for LVM")
                    return False

                cmd = [u'losetup', u'-o', str(self.offset), self.loopback, raw_path]
                if not self.parser.read_write:
                    cmd.insert(1, '-r')

                if not self.fstype:
                    self.fstype = 'LVM'

            else:
                self._debug("[-] Unknown filesystem {0}".format(self))
                return False

            # Execute mount
            util.check_call_(cmd, self.parser, stdout=subprocess.PIPE)

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
            if self.loopback in l:
                for vg in re.findall(r'VG (\w+)', l):
                    self.volume_group = vg

        if not self.volume_group:
            self._debug("[-] Volume is not a volume group.")
            return []

        # Enable lvm volumes
        util.check_call_(["vgchange", "-a", "y", self.volume_group], self.parser, stdout=subprocess.PIPE)

        # Gather information about lvolumes, gathering their label, size and raw path
        result = util.check_output_(["lvdisplay", self.volume_group], self.parser)
        for l in result.splitlines():
            if "--- Logical volume ---" in l:
                self.volumes.append(Volume(parser=self.parser))
                self.volumes[-1].index = "{0}.{1}".format(self.index, len(self.volumes) - 1)
                self.volumes[-1].fsdescription = 'Logical Volume'
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
                        self.lastmountpoint = line[line.index(':') + 2:].strip()
                    if line.startswith("Volume Name:") and not self.label:
                        self.label = line[line.index(':') + 2:].strip()
                    if line.startswith("Version:"):
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

    #noinspection PyBroadException
    def unmount(self):
        """Unounts the partition from the filesystem."""

        for volume in self.volumes:
            volume.unmount()

        if self.loopback and self.volume_group:
            try:
                util.check_call_(['vgchange', '-a', 'n', self.volume_group], self.parser, stdout=subprocess.PIPE)
            except Exception:
                return False

            self.volume_group = None

        if self.loopback:
            try:
                util.check_call_(['losetup', '-d', self.loopback], self.parser)
            except Exception:
                return False

            self.loopback = None

        if self.bindmount:
            if not util.clean_unmount([u'umount'], self.bindmount, rmdir=False):
                return False

            self.bindmount = None

        if self.mountpoint:
            if not util.clean_unmount([u'umount'], self.mountpoint):
                return False

            self.mountpoint = None

        return True
