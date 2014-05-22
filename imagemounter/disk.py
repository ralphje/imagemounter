from __future__ import print_function
from __future__ import unicode_literals

import glob
import os
import re
import subprocess
import tempfile
from imagemounter import util, BLOCK_SIZE
from imagemounter.volume import Volume


class Disk(object):
    """Representation of a disk, image file or anything else that can be considered a disk. """

    #noinspection PyUnusedLocal
    def __init__(self, parser, path, offset=0, vstype='detect', read_write=False, method='auto', detection='auto',
                 multifile=True, index=None, **args):
        """Instantiation of this class does not automatically mount, detect or analyse the disk. You will need the
        :func:`init` method for this.

        :param parser: the parent parser
        :type parser: :class:`ImageParser`
        :param int offset: offset of the disk where the volume (system) resides
        :param str vstype: the volume system type
        :param bool read_write: indicates whether the disk should be mounted with a read-write cache enabled
        :param str method: the method to mount the base image with
        :param str detection: the method to detect volumes in the volume system with
        :param bool multifile: indicates whether :func:`mount` should attempt to call the underlying mount method with
                all files of a split file when passing a single file does not work
        :param args: arguments that should be passed down to :class:`Volume` objects
        """


        self.parser = parser

        # Find the type and the paths
        path = os.path.expandvars(os.path.expanduser(path))
        if util.is_encase(path):
            self.type = 'encase'
        else:
            self.type = 'dd'
        self.paths = sorted(util.expand_path(path))

        self.offset = offset
        self.vstype = vstype.lower()

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

        if detection == 'auto':
            if util.module_exists('pytsk3'):
                self.detection = 'pytsk3'
            else:
                self.detection = 'mmls'
        else:
            self.detection = detection

        self.read_write = read_write
        self.rwpath = None
        self.multifile = multifile
        self.index = index
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
        """Calls several methods required to perform a full initialisation: :func:`mount`, :func:`add_to_raid` and
        :func:`mount_volumes` and yields all detected volumes.

        :param bool|None single: indicates whether the disk should be mounted as a single disk, not as a single disk or
            whether it should try both (defaults to :const:`None`)
        :param bool raid: indicates whether RAID detection is enabled
        :rtype: generator
        """

        self.mount()
        if raid:
            self.add_to_raid()

        for v in self.mount_volumes(single):
            yield v

    def mount(self):
        """Mounts the base image on a temporary location using the mount method stored in :attr:`method`. If mounting
        was successful, :attr:`mountpoint` is set to the temporary mountpoint.

        If :attr:`read_write` is enabled, a temporary read-write cache is also created and stored in :attr:`rwpath`.

        :return: whether the mounting was successful
        :rtype: bool
        """

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
        """Returns the raw path to the mounted disk image, i.e. the raw :file:`.dd`, :file:`.raw` or :file:`ewf1`
        file.

        :rtype: str
        """

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
        """Adds the disk to a central RAID volume.

        This function will first test whether it is actually a RAID volume by using :func:`is_raid` and, if so, will
        add the disk to the array via a loopback device.

        :return: whether the addition succeeded"""

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
        """Gets a list of all volumes in this disk, including volumes that are contained in other volumes."""

        volumes = []
        for v in self.volumes:
            volumes.extend(v.get_volumes())
        return volumes

    def mount_volumes(self, single=None):
        """Generator that detects and mounts all volumes in the disk.

        If *single* is :const:`True`, this method will call :Func:`mount_single_volumes`. If *single* is False, only
        :func:`mount_multiple_volumes` is called. If *single* is None, :func:`mount_multiple_volumes` is always called,
        being followed by :func:`mount_single_volume` if no volumes were detected.
        """

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
        """Mounts a volume assuming that the mounted image does not contain a full disk image, but only a
        single volume.

        A new :class:`Volume` object is created based on the disk file and :func:`init` is called on this object.

        This function will typically yield one volume, although if the volume contains other volumes, multiple volumes
        may be returned.
        """

        volume = Volume(disk=self, **self.args)
        volume.offset = 0
        if self.index is None:
            volume.index = 0
        else:
            volume.index = '{0}.0'.format(self.index)

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

    def mount_multiple_volumes(self):
        """Generator that will detect volumes in the disk file, generate :class:`Volume` objects based on this
        information and call :func:`init` on these.
        """

        if self.detection == 'mmls':
            for v in self._mount_mmls_volumes():
                yield v
        elif self.detection == 'pytsk3':
            for v in self._mount_pytsk3_volumes():
                yield v
        else:
            self._debug("[-] No viable detection method found")
            return

    mount_partitions = mount_multiple_volumes  # Backwards compatibility

    def _find_pytsk3_volumes(self):
        """Finds all volumes based on the pytsk3 library."""

        try:
            # noinspection PyUnresolvedReferences
            import pytsk3
        except ImportError:
            self._debug("[-] pytsk3 not installed, could not detect volumes")
            return []

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

            try:
                volumes = pytsk3.Volume_Info(baseimage, getattr(pytsk3, 'TSK_VS_TYPE_' + self.vstype.upper()))
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

    def _mount_pytsk3_volumes(self):
        """Generator that mounts every partition of this image and yields the mountpoint."""

        # Loop over all volumes in image.
        for p in self._find_pytsk3_volumes():
            import pytsk3

            volume = Volume(disk=self, **self.args)
            self.volumes.append(volume)

            # Fill volume with more information
            volume.offset = p.start * BLOCK_SIZE
            volume.fsdescription = p.desc
            if self.index is not None:
                volume.index = '{0}.{1}'.format(self.index, p.addr)
            else:
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

    def _mount_mmls_volumes(self):
        """Finds and mounts all volumes based on mmls."""

        try:
            cmd = ['mmls']
            if self.vstype != 'detect':
                cmd.extend(['-t', self.vstype])
            cmd.append(self.get_raw_path())
            output = util.check_output_(cmd, self.parser)
            self.volume_source = 'multi'
        except Exception as e:
            self._debug("[-] Failed executing mmls command")
            self._debug(e)
            return

        output = output.split("Description", 1)[-1]
        for line in output.splitlines():
            if not line:
                continue
            try:
                index, slot, start, end, length, description = line.split(None, 5)
                volume = Volume(disk=self, **self.args)
                self.volumes.append(volume)

                volume.offset = int(start) * BLOCK_SIZE
                volume.fsdescription = description
                if self.index is not None:
                    volume.index = '{0}.{1}'.format(self.index, int(index[:-1]))
                else:
                    volume.index = int(index[:-1])
                volume.size = int(length) * BLOCK_SIZE
            except Exception as e:
                self._debug("[-] Error while parsing mmls output")
                self._debug(e)
                continue

            if slot.lower() == 'meta':
                volume.flag = 'meta'
            elif slot.lower() == '-----':
                volume.flag = 'unalloc'
            else:
                volume.flag = 'alloc'

            # unalloc / meta partitions do not have stats and can not be mounted
            if volume.flag != 'alloc':
                yield volume
                continue

            for v in volume.init():
                yield v

    def rw_active(self):
        """Indicates whether anything has been written to a read-write cache."""

        return self.rwpath and os.path.getsize(self.rwpath)

    def unmount(self, remove_rw=False):
        """Removes all ties of this disk to the filesystem, so the image can be unmounted successfully. Warning: this
        method will destruct the entire RAID array in which this disk takes part.
        """

        for m in list(sorted(self.volumes, key=lambda v: v.mountpoint or "", reverse=True)):
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