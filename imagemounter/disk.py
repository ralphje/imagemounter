from __future__ import print_function
from __future__ import unicode_literals

import glob
import os
import pytsk3
import re
import subprocess
import tempfile
from imagemounter import util, BLOCK_SIZE, VOLUME_SYSTEM_TYPES
from imagemounter.volume import Volume


class Disk(object):
    """Parses an image and mounts it."""

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
        self.mountpoint = ''
        self.volumes = []
        self.volume_source = None

        self.loopback = None
        self.md_device = None

    def __unicode__(self):
        return self.name

    def __str__(self):
        return self.__unicode__()

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

        self.mountpoint = tempfile.mkdtemp(prefix='image_mounter_')

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
                    cmd = ['xmount', '--in', 'ewf' if self.type == 'encase' else 'dd']
                    if self.read_write:
                        cmd.extend(['--rw', self.rwpath])

                elif self.method == 'affuse':
                    cmd = ['affuse', '-o', 'allow_other']
                    fallbackcmd = ['affuse']

                elif self.method == 'ewfmount':
                    cmd = ['ewfmount', '-X', 'allow_other']
                    fallbackcmd = ['ewfmount']

                elif self.method == 'dummy':
                    # remove basemountpoint
                    os.rmdir(self.mountpoint)
                    self.mountpoint = None
                    return True

                else:
                    raise Exception("Unknown mount method {0}".format(self.method))

                # noinspection PyBroadException
                try:
                    cmd.extend(paths)
                    cmd.append(self.mountpoint)
                    util.check_call_(cmd, self, stdout=subprocess.PIPE)
                except Exception:
                    if fallbackcmd:
                        fallbackcmd.extend(paths)
                        fallbackcmd.append(self.mountpoint)
                        util.check_call_(fallbackcmd, self, stdout=subprocess.PIPE)
                    else:
                        raise
                return True

            except Exception as e:
                self._debug('[-] Could not mount {0} (see below), will try multi-file method'.format(paths[0]))
                self._debug(e)

        os.rmdir(self.mountpoint)
        self.mountpoint = None

        return False

    def get_raw_path(self):
        """Returns the raw path to the disk image"""

        if self.method == 'dummy':
            return self.paths[0]
        else:
            raw_path = glob.glob(os.path.join(self.mountpoint, '*.dd'))
            raw_path.extend(glob.glob(os.path.join(self.mountpoint, '*.raw')))
            raw_path.extend(glob.glob(os.path.join(self.mountpoint, 'ewf1')))
            if not raw_path:
                self._debug("No mount found in {}.".format(self.mountpoint))
                return None
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
            self._debug("    mdadm not installed, could not detect RAID")
            return False

        # Scan for new lvm volumes
        # noinspection PyBroadException
        try:
            result = util.check_output_(["mdadm", "--examine", self.get_raw_path()], self, stderr=subprocess.STDOUT)
            for l in result.splitlines():
                if 'Raid Level' in l:
                    self._debug("    Detected RAID level " + l[l.index(':') + 2:])
                    break
            else:
                return False
        except Exception:
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
        cmd = ['losetup', '-o', str(self.offset), self.loopback, self.get_raw_path()]
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

    def get_volumes(self):
        volumes = []
        for v in self.volumes:
            volumes.extend(v.get_volumes())
        return volumes

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
                self._debug("    Mounting as single volume instead")
                for v in self.mount_single_volume():
                    yield v

    def mount_single_volume(self):
        """Assumes the mounted image does not contain a full disk image, but only a single volume."""

        volume = Volume(disk=self, **self.args)
        volume.offset = 0
        volume.index = 0

        description = util.check_output_(['file', '-sL', self.get_fs_path()]).strip()
        if description:
            # description is the part after the :, until the first comma
            volume.fsdescription = description.split(': ', 1)[1].split(',', 1)[0].strip()
            if 'size' in description:
                volume.size = re.findall(r'size: (\d+)', description)[0]
            else:
                volume.size = os.path.getsize(self.get_fs_path())

        volume.flag = 'alloc'
        self.volumes = [volume]
        self.volume_source = 'single'

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
                self._debug("[-] Failed retrieving image info (possible empty image).")
                self._debug(e)
                return []

            # any loops over all vstypes
            if self.vstype == 'any':
                for vs in VOLUME_SYSTEM_TYPES:
                    #noinspection PyBroadException
                    try:
                        vst = getattr(pytsk3, 'TSK_VS_TYPE_' + vs.upper())
                        volumes = pytsk3.Volume_Info(baseimage, vst)
                        self._debug("[+] Using VS type {0}".format(vs))
                        return volumes
                    except Exception:
                        self._debug("    VS type {0} did not work".format(vs))
                else:
                    self._debug("[-] Failed retrieving volume info")
                    return []
            else:
                # base case: just obtain all volumes
                try:
                    volumes = pytsk3.Volume_Info(baseimage, self.vstype)
                    self.volume_source = 'multi'
                    return volumes
                except Exception as e:
                    self._debug("[-] Failed retrieving volume info (possible empty image).")
                    self._debug(e)
                    return []
        finally:
            if baseimage:
                baseimage.close()
                del baseimage

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
        """Method that removes all ties to the filesystem, so the image can be unmounted successfully. Warning: """

        for m in list(reversed(sorted(self.volumes))):
            if not m.unmount():
                self._debug("[-] Error unmounting volume {0}".format(m.mountpoint))

        # TODO: remove specific device from raid array
        if self.md_device:
            # Removes the RAID device first. Actually, we should be able to remove the devices from the array separately,
            # but whatever.
            try:
                util.check_call_(['mdadm', '-S', self.md_device], self, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                self.md_device = None
            except Exception as e:
                self._debug("[-] Failed unmounting MD device {0}".format(self.md_device))
                self._debug(e)

        if self.loopback:
            # noinspection PyBroadException
            try:
                util.check_call_(['losetup', '-d', self.loopback], self)
                self.loopback = None
            except Exception:
                self._debug("[-] Failed deleting loopback device {0}".format(self.loopback))

        if self.mountpoint and not util.clean_unmount(['fusermount', '-u'], self.mountpoint, parser=self):
            self._debug("[-] Error unmounting base {0}".format(self.mountpoint))
            return False

        if self.rw_active() and remove_rw:
            os.remove(self.rwpath)

        return True

    clean = unmount  # backwards compatibility