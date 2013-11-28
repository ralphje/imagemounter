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

__ALL__ = ['ImagePartition', 'ImageParser']
__version__ = '1.0.1'


class ImagePartition(object):
    """Information about a partition. Note that the mountpoint may be set, or not. If it is not set, exception may be
    set. Either way, if mountpoint is set, you can use the partition. Call unmount when you're done!
    """

    def __init__(self, parser=None, mountpoint=None, offset=None, fstype=None, fsdescription=None, index=None,
                 label=None, lastmountpoint=None, bindmount=None, exception=None, size=None, loopback=None,
                 volume_group=None):
        self.parser = parser
        self.mountpoint = mountpoint
        self.offset = offset
        self.fstype = fstype
        self.fsdescription = fsdescription
        self.index = index
        self.label = label
        self.lastmountpoint = lastmountpoint
        self.exception = exception
        self.size = size
        self.loopback = loopback
        self.volume_group = volume_group
        self.volumes = []
        self.bindmount = bindmount

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
            if not util.clean_unmount([u'umount'], self.bindmount, addsudo=self.parser.addsudo, rmdir=False):
                return False

            self.bindmount = None

        if self.mountpoint:
            if not util.clean_unmount([u'umount'], self.mountpoint, addsudo=self.parser.addsudo):
                return False

            self.mountpoint = None

        return True

    def __unicode__(self):
        return u'{0}:{1}'.format(self.index, self.fsdescription)

    def __str__(self):
        return str(self.__unicode__())

    def get_description(self):
        if self.size:
            desc = u'{0} '.format(self.get_size_gib())
        else:
            desc = u''

        desc += u'{1}:{0}'.format(self.fstype, self.index)

        if self.label:
            desc += u' {0}'.format(self.label)

        return desc

    def get_size_gib(self):
        if self.size and (isinstance(self.size, int) or self.size.isdigit()):
            return u"{0} GiB".format(round(self.size / 1024.0 ** 3, 2))
        else:
            return self.size

    def __cmp__(self, other):
        return cmp(self.lastmountpoint, other.lastmountpoint)


class ImageParser(object):
    """Parses an image and mounts it."""

    #noinspection PyUnusedLocal
    def __init__(self, path, out=sys.stdout, addsudo=False, loopback="/dev/loop0", mountdir=None, vstype='detect',
                 fstype=None, read_write=False, verbose=False, color=False, stats=False, method='auto', **args):
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
        self.addsudo = addsudo

        if read_write:
            self.rwpath = tempfile.mkstemp(prefix="image_mounter_rw_cache_")[1]
        else:
            self.rwpath = None
        self.name = os.path.split(path)[1]
        self.basemountpoint = u''
        self.partitions = []
        self.baseimage = None
        self.volumes = None
        self.loopback = loopback
        self.mountdir = mountdir

        self.vstype = getattr(pytsk3, 'TSK_VS_TYPE_' + vstype.upper())
        self.fstype = fstype

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

    def mount_partitions(self):
        """Generator that mounts every partition of this image and yields the mountpoint."""

        # ewf raw image is now available on basemountpoint
        # either as ewf1 file or as .dd file
        raw_path = glob.glob(os.path.join(self.basemountpoint, u'*.dd'))
        raw_path.extend(glob.glob(os.path.join(self.basemountpoint, u'*.raw')))
        raw_path.extend(glob.glob(os.path.join(self.basemountpoint, u'ewf1')))
        raw_path = raw_path[0]
        try:
            self.baseimage = pytsk3.Img_Info(raw_path)
            self.volumes = pytsk3.Volume_Info(self.baseimage, self.vstype)

        except Exception as e:
            self._debug(u"[-] Failed retrieving image or volume info (possible empty image).")
            self._debug(e)
            return

        # Loop over all volumes in image.
        for p in self.volumes:
            try:
                partition = ImagePartition(parser=self)
                self.partitions.append(partition)
                partition.offset = p.start * 512
                partition.fsdescription = p.desc
                partition.index = p.addr

                # Retrieve additional information about image by using fsstat.
                # Perhaps this must be done after the mount, or with a sleep to ensure the file is really closed.
                if self.stats:
                    StatRetriever(self, partition, raw_path, p.start).run()

                ## Obtain information about filesystem
                #d = pytsk3.FS_Info(self.image, offset=partition.offset)

                suffix = partition.label.replace("/", "_") if partition.label else ""
                partition.mountpoint = tempfile.mkdtemp(prefix=u'im_' + str(partition.index) + u'_', suffix=suffix,
                                                        dir=self.mountdir)
                #mount -t ext4 -o loop,ro,noexec,noload,offset=241790330880 \
                #/media/image/ewf1 /media/a

                # Prepare mount command
                if self.fstype:
                    fsdesc = ''  # prevent fsdesc below from doing something
                else:
                    fsdesc = partition.fsdescription.lower()

                if u'0x83' in fsdesc or '0xfd' in fsdesc or self.fstype == 'ext':
                    # ext
                    cmd = [u'mount', raw_path, partition.mountpoint, u'-t', u'ext4', u'-o',
                           u'loop,noexec,noload,offset=' + str(partition.offset)]
                    if not self.read_write:
                        cmd[-1] += ',ro'

                    partition.fstype = 'Ext'

                elif u'bsd' in fsdesc or self.fstype == 'bsd':
                    # ufs
                    #mount -t ufs -o ufstype=ufs2,loop,ro,offset=4294967296 /tmp/image/ewf1 /media/a
                    cmd = [u'mount', raw_path, partition.mountpoint, u'-t', u'ufs', u'-o',
                           u'ufstype=ufs2,loop,offset=' + str(partition.offset)]
                    if not self.read_write:
                        cmd[-1] += ',ro'

                    partition.fstype = 'UFS'

                elif u'0x07' in fsdesc or self.fstype == 'ntfs':
                    # NTFS
                    cmd = [u'mount', raw_path, partition.mountpoint, u'-t', u'ntfs', u'-o',
                           u'loop,noexec,offset=' + str(partition.offset)]
                    if not self.read_write:
                        cmd[-1] += ',ro'

                    partition.fstype = 'NTFS'

                elif u'0x8e' in fsdesc or self.fstype == 'lvm':
                    # LVM
                    os.environ['LVM_SUPPRESS_FD_WARNINGS'] = '1'

                    # don't need mountpoint
                    os.rmdir(partition.mountpoint)
                    partition.mountpoint = None

                    # set up loopback
                    partition.loopback = self.loopback

                    cmd = [u'losetup', u'-o', str(partition.offset), partition.loopback, raw_path]
                    if not self.read_write:
                        cmd.insert(1, '-r')

                    partition.fstype = 'LVM'

                else:
                    self._debug("[-] Unknown filesystem {0}".format(partition))
                    os.rmdir(partition.mountpoint)
                    partition.mountpoint = None
                    yield partition
                    #print u'[-] Unknown filesystem encountered: ' + p.desc
                    continue

                util.check_call_(cmd, self, stdout=subprocess.PIPE)

                # LVM is a partition of partitions.
                if u'lvm' in partition.fstype.lower():
                    # yield from ...
                    for r in self._perform_lvm_actions(partition):
                        yield r
                else:
                    yield partition
                #del d

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

    def _perform_lvm_actions(self, partition):
        """Performs post-mount actions on a LVM."""

        # Scan for new lvm volumes
        result = util.check_output_(["lvm", "pvscan"], self)
        for l in result.splitlines():
            if partition.loopback in l:
                for vg in re.findall(r'VG (\w+)', l):
                    partition.volume_group = vg
        if not partition.volume_group:
            self._debug("[-] Volume is not a volume group.")

        # Enable lvm volumes
        util.check_call_(["vgchange", "-a", "y", partition.volume_group], self, stdout=subprocess.PIPE)

        # Gather information about lvolumes, gathering their label, size and raw path
        result = util.check_output_(["lvdisplay", partition.volume_group], self)
        for l in result.splitlines():
            if "--- Logical volume ---" in l:
                partition.volumes.append(copy.copy(partition))
                partition.volumes[-1].index = "{0}.{1}".format(partition.index, len(partition.volumes) - 1)
                partition.volumes[-1].loopback = None
                partition.volumes[-1].volumes = []
            if "LV Name" in l:
                partition.volumes[-1].label = l.replace("LV Name", "").strip()
            if "LV Size" in l:
                partition.volumes[-1].size = l.replace("LV Size", "").strip()
            if "LV Path" in l:
                partition.volumes[-1].lv_path = l.replace("LV Path", "").strip()

        # Mount all volumes as ext
        for volume in partition.volumes:
            try:
                path = volume.lv_path
                volume.mountpoint = tempfile.mkdtemp(prefix=u'im_' + str(volume.index) + u'_',
                                                     suffix='_' + volume.label, dir=self.mountdir)
                volume.fstype = 'Ext'
                volume.fsdescription = 'LVM Volume'
                cmd = [u'mount', path, volume.mountpoint, u'-t', u'ext4', u'-o', u'loop,noexec,noload']
                if not self.read_write:
                    cmd[-1] += ',ro'

                util.check_call_(cmd, self)

                yield volume
            except Exception as e:
                volume.fsdescription = 'Unknown LVM Volume'
                self._debug("[-] LVM support is limited to Ext filesystems!")
                volume.exception = e
                self._debug(e)
                try:
                    if volume.mountpoint:
                        os.rmdir(volume.mountpoint)
                        volume.mountpoint = None
                except Exception as ex:
                    self._debug(ex)
                yield volume

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

        if self.basemountpoint and not util.clean_unmount([u'fusermount', u'-u'], self.basemountpoint, addsudo=self.addsudo):
            self._debug(u"[-] Error unmounting base partition {0}".format(self.basemountpoint))
            return False
        return True

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


class StatRetriever(object):
    def __init__(self, analyser, partition, raw_path, offset):
        self.partition = partition
        self.raw_path = raw_path
        self.offset = offset
        self.process = None
        self.analyser = analyser
        self._debug = analyser._debug

        self.stdout = ''
        self.stderr = ''

    def run(self):
        def target():
            try:
                cmd = [u'fsstat', self.raw_path, u'-o', str(self.offset)]
                if self.analyser.addsudo:
                    cmd.insert(0, 'sudo')

                self._debug('    {0}'.format(' '.join(cmd)))
                self.process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                #self.stdout, self.stderr = self.process.communicate()

                frag_size = frag_range = block_size = block_range = 0
                for line in iter(self.process.stdout.readline, b''):
                    if line.startswith("File System Type:"):
                        self.partition.fstype = line[line.index(':') + 2:].strip()
                    if line.startswith("Last Mount Point:") or line.startswith("Last mounted on:"):
                        self.partition.lastmountpoint = line[line.index(':') + 2:].strip()
                    if line.startswith("Volume Name:"):
                        self.partition.label = line[line.index(':') + 2:].strip()
                    # Used for calculating disk size
                    if line.startswith("Fragment Range:"):
                        frag_range = int(line[line.index('-') + 2:]) - int(line[line.index(':') + 2:line.index('-') - 1])
                    if line.startswith("Block Range:"):
                        block_range = int(line[line.index('-') + 2:]) - int(line[line.index(':') + 2:line.index('-') - 1])
                    if line.startswith("Fragment Size:"):
                        frag_size = int(line[line.index(':') + 2:])
                    if line.startswith("Block Size:"):
                        block_size = int(line[line.index(':') + 2:])
                    if 'CYLINDER GROUP INFORMATION' in line:
                        try:
                            self.process.terminate()  # some attempt
                        except Exception:
                            pass
                        break

                if self.partition.lastmountpoint and self.partition.label:
                    self.partition.label = "{0} ({1})".format(self.partition.lastmountpoint, self.partition.label)
                elif self.partition.lastmountpoint and not self.partition.label:
                    self.partition.label = self.partition.lastmountpoint

                if frag_size and frag_range:
                    self.partition.size = frag_size * frag_range
                elif block_size and block_range:
                    self.partition.size = block_size * block_range
            except Exception as e:  # ignore any exceptions here.
                self._debug("[-] Error while obtaining stats.")
                self._debug(e)
                pass

        thread = threading.Thread(target=target)
        thread.start()

        duration = 5  # longest possible duration for fsstat.
        thread.join(duration)
        if thread.is_alive():
            try:
                self.process.terminate()
            except Exception:
                pass
            thread.join()
            self._debug("    Killed fsstat after {0}s".format(duration))