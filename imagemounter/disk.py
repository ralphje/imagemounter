from __future__ import print_function
from __future__ import unicode_literals
from collections import defaultdict

import glob
import logging
import os
import re
import subprocess
import tempfile
import time

from imagemounter import _util, BLOCK_SIZE
from imagemounter.volume import Volume


logger = logging.getLogger(__name__)


class Disk(object):
    """Representation of a disk, image file or anything else that can be considered a disk. """

    # noinspection PyUnusedLocal
    def __init__(self, parser, path, offset=0, vstype='detect', read_write=False, method='auto', detection='auto',
                 multifile=True, index=None, mount_directories=True, **args):
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
        :param str index: the base index of this Disk
        :param bool mount_directories: indicates whether directories should also be 'mounted'
        :param args: arguments that should be passed down to :class:`Volume` objects
        """

        self.parser = parser

        # Find the type and the paths
        path = os.path.expandvars(os.path.expanduser(path))
        if _util.is_encase(path):
            self.type = 'encase'
        elif _util.is_vmware(path):
            self.type = 'vmdk'
        elif _util.is_compressed(path):
            self.type = 'compressed'
        else:
            self.type = 'dd'
        self.paths = sorted(_util.expand_path(path))

        self.offset = offset
        self.vstype = vstype.lower()

        self.block_size = BLOCK_SIZE

        self.read_write = read_write

        self.method = method

        if detection == 'auto':
            if _util.module_exists('pytsk3'):
                self.detection = 'pytsk3'
            elif _util.command_exists('mmls'):
                self.detection = 'mmls'
            else:
                self.detection = 'parted'
        else:
            self.detection = detection

        self.read_write = read_write
        self.rwpath = ""
        self.multifile = multifile
        self.index = index
        self.mount_directories = mount_directories
        self.args = args

        self.name = os.path.split(path)[1]
        self.mountpoint = ''
        self.avfs_mountpoint = ''
        self.volumes = []
        self.volume_source = ""

        self._disktype = defaultdict(dict)

        self.loopback = ""
        self.md_device = ""

    def __unicode__(self):
        return self.name

    def __str__(self):
        return self.__unicode__()

    def init(self, single=None, raid=True, disktype=True):
        """Calls several methods required to perform a full initialisation: :func:`mount`, :func:`add_to_raid` and
        :func:`mount_volumes` and yields all detected volumes.

        :param bool|None single: indicates whether the disk should be mounted as a single disk, not as a single disk or
            whether it should try both (defaults to :const:`None`)
        :param bool raid: indicates whether RAID detection is enabled
        :param bool disktype: indicates whether disktype data should be loaded and used
        :rtype: generator
        """

        self.mount()
        if raid:
            self.add_to_raid()
        if disktype:
            self.load_disktype_data()

        for v in self.mount_volumes(single):
            yield v

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

        # Find the mount methods
        if self.method == 'auto':
            methods = []

            def add_method_if_exists(method):
                if (method == 'avfs' and _util.command_exists('avfsd')) or _util.command_exists(method):
                    methods.append(method)

            if self.read_write:
                add_method_if_exists('xmount')
            else:
                if self.type == 'encase':
                    add_method_if_exists('ewfmount')
                elif self.type == 'vmdk':
                    add_method_if_exists('vmware-mount')
                    add_method_if_exists('affuse')
                elif self.type == 'dd':
                    add_method_if_exists('affuse')
                elif self.type == 'compressed':
                    add_method_if_exists('avfs')
                add_method_if_exists('xmount')
        else:
            methods = [self.method]

        cmds = []
        for method in methods:
            if method == 'avfs':  # avfs does not participate in the fallback stuff, unfortunately
                self.avfs_mountpoint = tempfile.mkdtemp(prefix='image_mounter_avfs_')

                # start by calling the mountavfs command to initialize avfs
                _util.check_call_(['avfsd', self.avfs_mountpoint, '-o', 'allow_other'], stdout=subprocess.PIPE)

                # no multifile support for avfs
                avfspath = self.avfs_mountpoint + '/' + os.path.abspath(self.paths[0]) + '#'
                targetraw = os.path.join(self.mountpoint, 'avfs')

                os.symlink(avfspath, targetraw)
                logger.debug("Symlinked {} with {}".format(avfspath, targetraw))
                raw_path = self.get_raw_path()
                logger.debug("Raw path to avfs is {}".format(raw_path))
                if self.method == 'auto':
                    self.method = 'avfs'
                return raw_path is not None

            elif method == 'xmount':
                cmds.extend([['xmount', '--in', 'ewf' if self.type == 'encase' else 'dd']])
                if self.read_write:
                    cmds[-1].extend(['--rw', self.rwpath])

            elif method == 'affuse':
                cmds.extend([['affuse', '-o', 'allow_other'], ['affuse']])

            elif method == 'ewfmount':
                cmds.extend([['ewfmount', '-X', 'allow_other'], ['ewfmount']])

            elif method == 'vmware-mount':
                cmds.extend([['vmware-mount', '-f']])

            elif method == 'dummy':
                os.rmdir(self.mountpoint)
                self.mountpoint = ""
                logger.debug("Raw path to dummy is {}".format(self.get_raw_path()))
                return True

            else:
                raise Exception("Unknown mount method {0}".format(self.method))

        # if multifile is enabled, add additional mount methods to the end of it
        for cmd in cmds[:]:
            if self.multifile:
                cmds.append(cmd[:])
                cmds[-1].extend(self.paths)
                cmds[-1].append(self.mountpoint)
            cmd.append(self.paths[0])
            cmd.append(self.mountpoint)

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
                if self.method == 'auto':
                    self.method = cmd[0]
                return raw_path is not None

        logger.error('Unable to mount {0}'.format(self.paths[0]), exc_info=True)
        os.rmdir(self.mountpoint)
        self.mountpoint = ""

        return False

    def get_raw_path(self):
        """Returns the raw path to the mounted disk image, i.e. the raw :file:`.dd`, :file:`.raw` or :file:`ewf1`
        file.

        :rtype: str
        """

        if self.method == 'dummy':
            return self.paths[0]
        else:
            if self.method == 'avfs' and os.path.isdir(os.path.join(self.mountpoint, 'avfs')):
                logger.debug("AVFS mounted as a directory, will look in directory for (random) file.")
                # there is no support for disks inside disks, so this will fail to work for zips containing
                # E01 files or so.
                searchdirs = (os.path.join(self.mountpoint, 'avfs'), self.mountpoint)
            else:
                searchdirs = (self.mountpoint, )

            raw_path = []
            for searchdir in searchdirs:
                raw_path.extend(glob.glob(os.path.join(searchdir, '*.dd')))
                raw_path.extend(glob.glob(os.path.join(searchdir, '*.iso')))
                raw_path.extend(glob.glob(os.path.join(searchdir, '*.raw')))
                raw_path.extend(glob.glob(os.path.join(searchdir, '*.dmg')))
                raw_path.extend(glob.glob(os.path.join(searchdir, 'ewf1')))
                raw_path.extend(glob.glob(os.path.join(searchdir, 'flat')))
                raw_path.extend(glob.glob(os.path.join(searchdir, 'avfs')))  # apparently it is not a dir

            if not raw_path:
                logger.warning("No viable mount file found in {}.".format(searchdirs))
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

        if not _util.command_exists('mdadm'):
            logger.info("mdadm not installed, could not detect RAID")
            return False

        # Scan for new lvm volumes
        # noinspection PyBroadException
        try:
            result = _util.check_output_(["mdadm", "--examine", self.get_raw_path()], stderr=subprocess.STDOUT)
            for l in result.splitlines():
                if 'Raid Level' in l:
                    logger.debug("Detected RAID level " + l[l.index(':') + 2:])
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
        # noinspection PyBroadException
        try:
            self.loopback = _util.check_output_(['losetup', '-f']).strip()
        except Exception:
            logger.warning("No free loopback device found for RAID", exc_info=True)
            return False

        # mount image as loopback
        cmd = ['losetup', '-o', str(self.offset), self.loopback, self.get_raw_path()]
        if not self.read_write:
            cmd.insert(1, '-r')

        try:
            _util.check_call_(cmd, stdout=subprocess.PIPE)
        except Exception:
            logger.exception("Failed mounting image to loopback")
            return False

        try:
            # use mdadm to mount the loopback to a md device
            # incremental and run as soon as available
            output = _util.check_output_(['mdadm', '-IR', self.loopback], stderr=subprocess.STDOUT)
            match = re.findall(r"attached to ([^ ,]+)", output)
            if match:
                self.md_device = os.path.realpath(match[0])
                logger.info("Mounted RAID to {0}".format(self.md_device))
        except Exception as e:
            logger.exception("Failed mounting RAID.")
            return False

        return True

    def load_disktype_data(self):
        """Calls the :command:`disktype` command and obtains the disk GUID from GPT volume systems. As we
        are running the tool anyway, the label is also extracted from the tool if it is not yet set.

        The disktype data is only loaded and not assigned to volumes yet.
        """

        if not _util.command_exists('disktype'):
            logger.warning("disktype not installed, could not detect volume type")
            return None

        disktype = _util.check_output_(['disktype', self.get_raw_path()]).strip()

        current_partition = None
        for line in disktype.splitlines():
            if not line:
                continue
            try:
                line = line.strip()

                find_partition_nr = re.match(r"^Partition (\d+):", line)
                if find_partition_nr:
                    current_partition = int(find_partition_nr.group(1))
                elif current_partition is not None:
                    if line.startswith("Type ") and "GUID" in line:
                        self._disktype[current_partition]['guid'] = \
                            line[line.index('GUID') + 5:-1].strip()  # output is between ()
                    elif line.startswith("Partition Name "):
                        self._disktype[current_partition]['label'] = \
                            line[line.index('Name ') + 6:-1].strip()  # output is between ""
            except Exception as e:
                logger.exception("Error while parsing disktype output")
                return

    def _assign_disktype_data(self, volume, slot=None):
        """Assigns cached disktype data to a volume."""

        if slot is None:
            slot = volume.slot
        if slot in self._disktype:
            data = self._disktype[slot]
            if not volume.guid and 'guid' in data:
                volume.guid = data['guid']
            if not volume.label and 'label' in data:
                volume.label = data['label']

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

        if os.path.isdir(self.get_raw_path()) and self.mount_directories:
            logger.info("Raw path is a directory: using directory mount method")
            for v in self.mount_directory():
                yield v

        elif single:
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
                logger.info("Mounting as single volume instead")
                for v in self.mount_single_volume():
                    yield v

    def mount_directory(self):
        """Method that 'mounts' a directory. It actually just symlinks it. It is useful for AVFS mounts, that
        are not otherwise detected. This is a last resort method.
        """

        if not self.mount_directories:
            return

        volume = Volume(disk=self, **self.args)
        volume.offset = 0
        if self.index is None:
            volume.index = 0
        else:
            volume.index = '{0}.0'.format(self.index)

        filesize = _util.check_output_(['du', '-scDb', self.get_fs_path()]).strip()
        if filesize:
            volume.size = int(filesize.splitlines()[-1].split()[0])

        volume.flag = 'alloc'
        volume.fsdescription = 'Directory'
        self.volumes = [volume]
        self.volume_source = 'directory'

        for v in volume.init(no_stats=True):  # stats can't be retrieved from directory
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

        description = _util.check_output_(['file', '-sL', self.get_fs_path()]).strip()
        if description:
            # description is the part after the :, until the first comma
            volume.fsdescription = description.split(': ', 1)[1].split(',', 1)[0].strip()
            if 'size' in description:
                volume.size = int(re.findall(r'size:? (\d+)', description)[0])
            else:
                volume.size = os.path.getsize(self.get_fs_path())

        volume.flag = 'alloc'
        self.volumes = [volume]
        self.volume_source = 'single'
        self._assign_disktype_data(volume)

        for v in volume.init(no_stats=True):  # stats can't  be retrieved from single volumes
            yield v

    def mount_multiple_volumes(self):
        """Generator that will detect volumes in the disk file, generate :class:`Volume` objects based on this
        information and call :func:`init` on these.
        """

        if self.detection == 'mmls':
            for v in self._mount_mmls_volumes():
                yield v
        elif self.detection == 'parted':
            for v in self._mount_parted_volumes():
                yield v
        elif self.detection == 'pytsk3':
            for v in self._mount_pytsk3_volumes():
                yield v
        else:
            logger.error("No viable detection method found")
            return

    def _find_pytsk3_volumes(self):
        """Finds all volumes based on the pytsk3 library."""

        try:
            # noinspection PyUnresolvedReferences
            import pytsk3
        except ImportError:
            logger.error("pytsk3 not installed, could not detect volumes")
            return []

        baseimage = None
        try:
            # ewf raw image is now available on base mountpoint
            # either as ewf1 file or as .dd file
            raw_path = self.get_raw_path()
            try:
                baseimage = pytsk3.Img_Info(raw_path)
            except Exception as e:
                logger.error("Failed retrieving image info (possible empty image).", exc_info=True)
                return []

            try:
                volumes = pytsk3.Volume_Info(baseimage, getattr(pytsk3, 'TSK_VS_TYPE_' + self.vstype.upper()))
                self.volume_source = 'multi'
                return volumes
            except Exception as e:
                # some bug in sleuthkit makes detection sometimes difficult, so we hack around it:
                if "(GPT or DOS at 0)" in str(e) and self.vstype != 'gpt':
                    self.vstype = 'gpt'
                    try:
                        logger.warning("[-] Error in retrieving volume info: TSK couldn't decide between GPT and DOS, "
                                       "choosing GPT for you. Use --vstype=dos to force DOS.", exc_info=True)
                        volumes = pytsk3.Volume_Info(baseimage, getattr(pytsk3, 'TSK_VS_TYPE_' + self.vstype.upper()))
                        self.volume_source = 'multi'
                        return volumes
                    except Exception as e:
                        logger.exception("Failed retrieving image info (possible empty image).")
                        return []
                else:
                    logger.exception("Failed retrieving image info (possible empty image).")
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
            volume.offset = p.start * self.block_size
            volume.fsdescription = p.desc.strip()
            if self.index is not None:
                volume.index = '{0}.{1}'.format(self.index, p.addr)
            else:
                volume.index = p.addr
            volume.size = p.len * self.block_size

            if p.flags == pytsk3.TSK_VS_PART_FLAG_ALLOC:
                volume.flag = 'alloc'
                volume.slot = _util.determine_slot(p.table_num, p.slot_num)
                self._assign_disktype_data(volume)
                logger.info("Found allocated {2}: block offset: {0}, length: {1} ".format(p.start, p.len,
                                                                                          volume.fsdescription))
            elif p.flags == pytsk3.TSK_VS_PART_FLAG_UNALLOC:
                volume.flag = 'unalloc'
                logger.info("Found unallocated space: block offset: {0}, length: {1} ".format(p.start, p.len))
            elif p.flags == pytsk3.TSK_VS_PART_FLAG_META:
                volume.flag = 'meta'
                logger.info("Found meta volume: block offset: {0}, length: {1} ".format(p.start, p.len))

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
            output = _util.check_output_(cmd, stderr=subprocess.STDOUT)
            self.volume_source = 'multi'
        except Exception as e:
            # some bug in sleuthkit makes detection sometimes difficult, so we hack around it:
            if hasattr(e, 'output') and "(GPT or DOS at 0)" in e.output.decode() and self.vstype != 'gpt':
                self.vstype = 'gpt'
                try:
                    logger.warning("[-] Error in retrieving volume info: mmls couldn't decide between GPT and DOS, "
                                   "choosing GPT for you. Use --vstype=dos to force DOS.", exc_info=True)
                    cmd = ['mmls', '-t', self.vstype, self.get_raw_path()]
                    output = _util.check_output_(cmd, stderr=subprocess.STDOUT)
                    self.volume_source = 'multi'
                except Exception as e:
                    logger.exception("Failed executing mmls command")
                    return
            else:
                logger.exception("[-] Failed executing mmls command")
                return

        output = output.split("Description", 1)[-1]
        for line in output.splitlines():
            if not line:
                continue
            try:
                values = line.split(None, 5)

                # sometimes there are only 5 elements available
                description = ''
                index, slot, start, end, length = values[0:5]
                if len(values) > 5:
                    description = values[5]

                volume = Volume(disk=self, **self.args)
                self.volumes.append(volume)

                volume.offset = int(start) * self.block_size
                volume.fsdescription = description
                if self.index is not None:
                    volume.index = '{0}.{1}'.format(self.index, int(index[:-1]))
                else:
                    volume.index = int(index[:-1])
                volume.size = int(length) * self.block_size
            except Exception as e:
                logger.exception("Error while parsing mmls output")
                continue

            if slot.lower() == 'meta':
                volume.flag = 'meta'
                logger.info("Found meta volume: block offset: {0}, length: {1}".format(start, length))
            elif slot.lower() == '-----':
                volume.flag = 'unalloc'
                logger.info("Found unallocated space: block offset: {0}, length: {1}".format(start, length))
            else:
                volume.flag = 'alloc'
                if ":" in slot:
                    volume.slot = _util.determine_slot(*slot.split(':'))
                else:
                    volume.slot = _util.determine_slot(-1, slot)
                self._assign_disktype_data(volume)
                logger.info("Found allocated {2}: block offset: {0}, length: {1} ".format(start, length,
                                                                                          volume.fsdescription))

            # unalloc / meta partitions do not have stats and can not be mounted
            if volume.flag != 'alloc':
                yield volume
                continue

            for v in volume.init():
                yield v

    def _mount_parted_volumes(self):
        """Finds and mounts all volumes based on parted."""

        # for some reason, parted does not properly return extended volume types in its machine
        # output, so we need to execute it twice.
        meta_volumes = []
        try:
            output = _util.check_output_(['parted', self.get_raw_path(), 'print'])
            for line in output.splitlines():
                if 'extended' in line:
                    meta_volumes.append(int(line.split()[0]))
        except Exception:
            logger.exception("Failed executing parted command.")
            # skip detection of meta volumes

        try:
            # parted does not support passing in the vstype. It either works, or it doesn't.
            cmd = ['parted', self.get_raw_path(), '-sm', 'unit s', 'print free']
            output = _util.check_output_(cmd)
            self.volume_source = 'multi'
        except Exception as e:
            logger.exception("Failed executing parted command")
            return

        num = 0
        for line in output.splitlines():
            if line.startswith("Warning") or not line or ':' not in line or line.startswith(self.get_raw_path()):
                continue
            line = line[:-1]  # remove last ;
            try:
                slot, start, end, length, description = line.split(':', 4)
                if ':' in description:
                    description, label, flags = description.split(':', 2)
                else:
                    description, label, flags = description, '', ''

                volume = Volume(disk=self, **self.args)
                self.volumes.append(volume)
                volume.offset = int(start[:-1]) * self.block_size  # remove last s
                volume.size = int(length[:-1]) * self.block_size
                volume.fsdescription = description
                if self.index is not None:
                    volume.index = '{0}.{1}'.format(self.index, num)
                else:
                    volume.index = num

                # TODO: detection of meta volumes

                if description == 'free':
                    volume.flag = 'unalloc'
                    logger.info("Found unallocated space: block offset: {0}, length: {1}".format(start[:-1], length[:-1]))
                elif int(slot) in meta_volumes:
                    volume.flag = 'meta'
                    volume.slot = int(slot)
                    logger.info("Found meta volume: block offset: {0}, length: {1}".format(start[:-1], length[:-1]))
                else:
                    volume.flag = 'alloc'
                    volume.slot = int(slot)
                    self._assign_disktype_data(volume)
                    logger.info("Found allocated {2}: block offset: {0}, length: {1} ".format(start[:-1], length[:-1],
                                                                                              volume.fsdescription))
            except AttributeError as e:
                logger.exception("Error while parsing parted output")
                continue

            num += 1

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
                logger.warning("Error unmounting volume {0}".format(m.mountpoint))

        # TODO: remove specific device from raid array
        if self.md_device:
            # Removes the RAID device first. Actually, we should be able to remove the devices from the array separately,
            # but whatever.
            try:
                _util.check_call_(['mdadm', '-S', self.md_device], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                self.md_device = None
            except Exception as e:
                logger.warning("Failed unmounting MD device {0}".format(self.md_device), exc_info=True)

        if self.loopback:
            # noinspection PyBroadException
            try:
                _util.check_call_(['losetup', '-d', self.loopback])
                self.loopback = None
            except Exception:
                logger.warning("Failed deleting loopback device {0}".format(self.loopback), exc_info=True)

        if self.mountpoint and not _util.clean_unmount(['fusermount', '-u'], self.mountpoint):
            logger.error("Error unmounting base {0}".format(self.mountpoint))
            return False

        if self.avfs_mountpoint and not _util.clean_unmount(['fusermount', '-u'], self.avfs_mountpoint):
            logger.error("Error unmounting AVFS mountpoint {0}".format(self.avfs_mountpoint))
            return False

        if self.rw_active() and remove_rw:
            os.remove(self.rwpath)

        return True

