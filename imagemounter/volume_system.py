from __future__ import print_function
from __future__ import unicode_literals

import logging
import os
import subprocess
from collections import defaultdict

import re

from imagemounter import _util
from imagemounter.exceptions import ArgumentError, SubsystemError, ModuleNotFoundError

logger = logging.getLogger(__name__)


class VolumeSystem(object):
    """A VolumeSystem is a collection of volumes. Every :class:`Disk` contains exactly one VolumeSystem. Each
    system contains several :class:`Volumes`, which, in turn, may contain additional volume systems.
    """

    def __init__(self, parent, vstype='', volume_detector=''):
        """Creates a VolumeSystem.

        :param parent: the parent may either be a :class:`Disk` or a :class:`Volume` that contains this  VolumeSystem.
        :param str vstype: the volume system type to use.
        :param str volume_detector: the volume system detection method to use
        """

        self.parent = parent
        self.disk = parent.disk if hasattr(parent, 'disk') else parent

        if vstype:
            self.vstype = vstype
        elif self.parent.index in self.disk.parser.vstypes:
            self.vstype = self.disk.parser.vstypes[self.parent.index]
        elif '*' in self.disk.parser.vstypes:
            self.vstype = self.disk.parser.vstypes['*']
        else:
            self.vstype = "detect"
        if volume_detector == 'auto' or not volume_detector:
            self.volume_detector = VolumeSystem._determine_auto_detection_method()
        else:
            self.volume_detector = volume_detector

        self.volume_source = ""
        self.volumes = []
        self.has_detected = False

        self._disktype = defaultdict(dict)

    def __iter__(self):
        for v in self.volumes:
            yield v

    def __len__(self):
        return len(self.volumes)

    def __getitem__(self, item):
        item_suffix = ".{}".format(item)
        for v in self.volumes:
            if v.index.endswith(item_suffix) or v.index == str(item):
                return v
        raise KeyError

    def _make_subvolume(self, **args):
        """Creates a subvolume, adds it to this class and returns it."""

        from imagemounter.volume import Volume
        v = Volume(disk=self.disk, parent=self.parent,
                   volume_detector=self.volume_detector,
                   **args)  # vstype is not passed down, let it decide for itself.
        self.volumes.append(v)
        return v

    def _make_single_subvolume(self, only_one=True, **args):
        """Creates a subvolume, adds it to this class, sets the volume index to 0 and returns it.

        :param bool only_one: if this volume system already has at least one volume, it is returned instead.
        """

        if only_one and self.volumes:
            return self.volumes[0]

        if self.parent.index is None:
            index = '0'
        else:
            index = '{0}.0'.format(self.parent.index)
        volume = self._make_subvolume(index=index, **args)
        return volume

    def detect_volumes(self, vstype=None, method=None, force=False):
        """Iterator for detecting volumes within this volume system.

        :param str vstype: The volume system type to use. If None, uses :attr:`vstype`
        :param str method: The detection method to use. If None, uses :attr:`detection`
        :param bool force: Specify if you wnat to force running the detection if has_Detected is True.
        """
        if self.has_detected and not force:
            logger.warning("Detection already ran.")
            return

        if vstype is None:
            vstype = self.vstype
        if method is None:
            method = self.volume_detector

        if method == 'auto':
            method = VolumeSystem._determine_auto_detection_method()

        if vstype == 'lvm':
            for v in self._detect_lvm_volumes(self.parent.info.get('volume_group')):
                yield v
        elif vstype == 'vss':
            for v in self._detect_vss_volumes(self.parent._paths['vss']):
                yield v
        elif method == 'single':  # dummy method for Disk
            for v in self._detect_single_volume():
                yield v
        elif method == 'mmls':
            for v in self._detect_mmls_volumes(vstype):
                yield v
        elif method == 'parted':
            for v in self._detect_parted_volumes(vstype):
                yield v
        elif method == 'pytsk3':
            for v in self._detect_pytsk3_volumes(vstype):
                yield v
        else:
            logger.error("No viable detection method found")
            raise ArgumentError("No viable detection method found")

        self.has_detected = True

    @staticmethod
    def _determine_auto_detection_method():
        """Return the detection method to use when the detection method is 'auto'"""

        if _util.module_exists('pytsk3'):
            return 'pytsk3'
        elif _util.command_exists('mmls'):
            return 'mmls'
        else:
            return 'parted'

    def _format_index(self, idx):
        """Returns a formatted index given the disk index idx."""

        if self.parent.index is not None:
            return '{0}.{1}'.format(self.parent.index, idx)
        else:
            return str(idx)

    def _detect_single_volume(self):
        """'Detects' a single volume. It should not be called other than from a :class:`Disk`."""
        volume = self._make_single_subvolume(offset=0)
        is_directory = os.path.isdir(self.parent.get_raw_path())

        if is_directory:
            filesize = _util.check_output_(['du', '-scDb', self.parent.get_raw_path()]).strip()
            if filesize:
                volume.size = int(filesize.splitlines()[-1].split()[0])

        else:
            description = _util.check_output_(['file', '-sL', self.parent.get_raw_path()]).strip()
            if description:
                # description is the part after the :, until the first comma
                volume.info['fsdescription'] = description.split(': ', 1)[1].split(',', 1)[0].strip()
                if 'size' in description:
                    volume.size = int(re.findall(r'size:? (\d+)', description)[0])
                else:
                    volume.size = os.path.getsize(self.parent.get_raw_path())

        volume.flag = 'alloc'
        self.volume_source = 'single'
        self._assign_disktype_data(volume)
        yield volume

    def _find_pytsk3_volumes(self, vstype='detect'):
        """Finds all volumes based on the pytsk3 library."""

        try:
            # noinspection PyUnresolvedReferences
            import pytsk3
        except ImportError:
            logger.error("pytsk3 not installed, could not detect volumes")
            raise ModuleNotFoundError("pytsk3")

        baseimage = None
        try:
            # ewf raw image is now available on base mountpoint
            # either as ewf1 file or as .dd file
            raw_path = self.parent.get_raw_path()
            # noinspection PyBroadException
            try:
                baseimage = pytsk3.Img_Info(raw_path)
            except Exception:
                logger.error("Failed retrieving image info (possible empty image).", exc_info=True)
                return []

            try:
                volumes = pytsk3.Volume_Info(baseimage, getattr(pytsk3, 'TSK_VS_TYPE_' + vstype.upper()),
                                             self.parent.offset // self.disk.block_size)
                self.volume_source = 'multi'
                return volumes
            except Exception as e:
                # some bug in sleuthkit makes detection sometimes difficult, so we hack around it:
                if "(GPT or DOS at 0)" in str(e) and vstype != 'gpt':
                    self.vstype = 'gpt'
                    # noinspection PyBroadException
                    try:
                        logger.warning("Error in retrieving volume info: TSK couldn't decide between GPT and DOS, "
                                       "choosing GPT for you. Use --vstype=dos to force DOS.", exc_info=True)
                        volumes = pytsk3.Volume_Info(baseimage, getattr(pytsk3, 'TSK_VS_TYPE_GPT'))
                        self.volume_source = 'multi'
                        return volumes
                    except Exception as e:
                        logger.exception("Failed retrieving image info (possible empty image).")
                        raise SubsystemError(e)
                else:
                    logger.exception("Failed retrieving image info (possible empty image).")
                    raise SubsystemError(e)
        finally:
            if baseimage:
                baseimage.close()
                del baseimage

    def _detect_pytsk3_volumes(self, vstype='detect'):
        """Generator that mounts every partition of this image and yields the mountpoint."""

        # Loop over all volumes in image.
        for p in self._find_pytsk3_volumes(vstype):
            import pytsk3

            volume = self._make_subvolume(index=self._format_index(p.addr),
                                          offset=p.start * self.disk.block_size,
                                          size=p.len * self.disk.block_size)
            # Fill volume with more information
            volume.info['fsdescription'] = p.desc.strip().decode('utf-8')

            if p.flags == pytsk3.TSK_VS_PART_FLAG_ALLOC:
                volume.flag = 'alloc'
                volume.slot = _util.determine_slot(p.table_num, p.slot_num)
                self._assign_disktype_data(volume)
                logger.info("Found allocated {2}: block offset: {0}, length: {1} ".format(p.start, p.len,
                                                                                          volume.info['fsdescription']))
            elif p.flags == pytsk3.TSK_VS_PART_FLAG_UNALLOC:
                volume.flag = 'unalloc'
                logger.info("Found unallocated space: block offset: {0}, length: {1} ".format(p.start, p.len))
            elif p.flags == pytsk3.TSK_VS_PART_FLAG_META:
                volume.flag = 'meta'
                logger.info("Found meta volume: block offset: {0}, length: {1} ".format(p.start, p.len))

            yield volume

    def _detect_mmls_volumes(self, vstype='detect'):
        """Finds and mounts all volumes based on mmls."""

        try:
            cmd = ['mmls']
            if self.parent.offset:
                cmd.extend(['-o', str(self.parent.offset // self.disk.block_size)])
            if vstype != 'detect':
                cmd.extend(['-t', vstype])
            cmd.append(self.parent.get_raw_path())
            output = _util.check_output_(cmd, stderr=subprocess.STDOUT)
            self.volume_source = 'multi'
        except Exception as e:
            # some bug in sleuthkit makes detection sometimes difficult, so we hack around it:
            if hasattr(e, 'output') and "(GPT or DOS at 0)" in e.output.decode() and vstype != 'gpt':
                self.vstype = 'gpt'
                # noinspection PyBroadException
                try:
                    logger.warning("Error in retrieving volume info: mmls couldn't decide between GPT and DOS, "
                                   "choosing GPT for you. Use --vstype=dos to force DOS.", exc_info=True)
                    cmd = ['mmls', '-t', 'gpt', self.parent.get_raw_path()]
                    output = _util.check_output_(cmd, stderr=subprocess.STDOUT)
                    self.volume_source = 'multi'
                except Exception as e:
                    logger.exception("Failed executing mmls command")
                    raise SubsystemError(e)
            else:
                logger.exception("Failed executing mmls command")
                raise SubsystemError(e)

        output = output.split("Description", 1)[-1]
        for line in output.splitlines():
            if not line:
                continue
            # noinspection PyBroadException
            try:
                values = line.split(None, 5)

                # sometimes there are only 5 elements available
                description = ''
                index, slot, start, end, length = values[0:5]
                if len(values) > 5:
                    description = values[5]

                volume = self._make_subvolume(index=self._format_index(int(index[:-1])),
                                              offset=int(start) * self.disk.block_size,
                                              size=int(length) * self.disk.block_size)
                volume.info['fsdescription'] = description
            except Exception:
                logger.exception("Error while parsing mmls output")
                continue

            if slot.lower() == 'meta':
                volume.flag = 'meta'
                logger.info("Found meta volume: block offset: {0}, length: {1}".format(start, length))
            elif slot.lower().startswith('-----'):
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
                                                                                          volume.info['fsdescription']))

            yield volume

    def _detect_parted_volumes(self, vstype='detect'):
        """Finds and mounts all volumes based on parted."""

        # for some reason, parted does not properly return extended volume types in its machine
        # output, so we need to execute it twice.
        meta_volumes = []
        # noinspection PyBroadException
        try:
            output = _util.check_output_(['parted', self.parent.get_raw_path(), 'print'], stdin=subprocess.PIPE)
            for line in output.splitlines():
                if 'extended' in line:
                    meta_volumes.append(int(line.split()[0]))
        except Exception:
            logger.exception("Failed executing parted command.")
            # skip detection of meta volumes

        # noinspection PyBroadException
        try:
            # parted does not support passing in the vstype. It either works, or it doesn't.
            cmd = ['parted', self.parent.get_raw_path(), '-sm', 'unit s', 'print free']
            output = _util.check_output_(cmd, stdin=subprocess.PIPE)
            self.volume_source = 'multi'
        except Exception as e:
            logger.exception("Failed executing parted command")
            raise SubsystemError(e)

        num = 0
        for line in output.splitlines():
            if line.startswith("Warning") or not line or ':' not in line or line.startswith(self.parent.get_raw_path()):
                continue
            line = line[:-1]  # remove last ;
            try:
                slot, start, end, length, description = line.split(':', 4)
                if ':' in description:
                    description, label, flags = description.split(':', 2)
                else:
                    description, label, flags = description, '', ''

                try:
                    slot = int(slot)
                except ValueError:
                    continue

                volume = self._make_subvolume(index=self._format_index(num),
                                              offset=int(start[:-1]) * self.disk.block_size,  # remove last s
                                              size=int(length[:-1]) * self.disk.block_size)
                volume.info['fsdescription'] = description
                if label:
                    volume.info['label'] = label
                if flags:
                    volume.info['parted_flags'] = flags

                # TODO: detection of meta volumes

                if description == 'free':
                    volume.flag = 'unalloc'
                    logger.info("Found unallocated space: block offset: {0}, length: {1}".format(start[:-1],
                                                                                                 length[:-1]))
                elif slot in meta_volumes:
                    volume.flag = 'meta'
                    volume.slot = slot
                    logger.info("Found meta volume: block offset: {0}, length: {1}".format(start[:-1], length[:-1]))
                else:
                    volume.flag = 'alloc'
                    volume.slot = slot
                    self._assign_disktype_data(volume)
                    logger.info("Found allocated {2}: block offset: {0}, length: {1} "
                                .format(start[:-1], length[:-1], volume.info['fsdescription']))
            except AttributeError:
                logger.exception("Error while parsing parted output")
                continue

            num += 1

            yield volume

    def _detect_lvm_volumes(self, volume_group):
        """Gather information about lvolumes, gathering their label, size and raw path"""

        result = _util.check_output_(["lvm", "lvdisplay", volume_group])
        cur_v = None
        for l in result.splitlines():
            if "--- Logical volume ---" in l:
                cur_v = self._make_subvolume(index=self._format_index(len(self)), flag='alloc')
                cur_v.info['fsdescription'] = 'Logical Volume'
            if "LV Name" in l:
                cur_v.info['label'] = l.replace("LV Name", "").strip()
            if "LV Size" in l:
                size, unit = l.replace("LV Size", "").strip().split(" ", 1)
                cur_v.size = int(float(size.replace(',', '.')) * {'KiB': 1024, 'MiB': 1024 ** 2,
                                                                  'GiB': 1024 ** 3, 'TiB': 1024 ** 4}.get(unit, 1))
            if "LV Path" in l:
                cur_v._paths['lv'] = l.replace("LV Path", "").strip()
                cur_v.offset = 0

        logger.info("{0} volumes found".format(len(self)))
        self.volume_source = 'multi'
        return self.volumes

    def _detect_vss_volumes(self, path):
        """Detect volume shadow copy volumes in the specified path."""

        try:
            volume_info = _util.check_output_(["vshadowinfo", "-o", str(self.parent.offset), self.parent.get_raw_path()])
        except Exception as e:
            logger.exception("Failed obtaining info from the volume shadow copies.")
            raise SubsystemError(e)

        current_store = None
        for line in volume_info.splitlines():
            line = line.strip()
            if line.startswith("Store:"):
                idx = line.split(":")[-1].strip()
                current_store = self._make_subvolume(index=self._format_index(idx), flag='alloc', offset=0)
                current_store._paths['vss_store'] = os.path.join(path, 'vss' + idx)
                current_store.info['fsdescription'] = 'VSS Store'
            elif line.startswith("Volume size"):
                current_store.size = int(line.split(":")[-1].strip().split()[0])
            elif line.startswith("Creation time"):
                current_store.info['creation_time'] = line.split(":")[-1].strip()

        return self.volumes

    def preload_volume_data(self):
        """Preloads volume data. It is used to call internal methods that contain information about a volume."""

        self._load_disktype_data()

    def _load_disktype_data(self):
        """Calls the :command:`disktype` command and obtains the disk GUID from GPT volume systems. As we
        are running the tool anyway, the label is also extracted from the tool if it is not yet set.

        The disktype data is only loaded and not assigned to volumes yet.
        """

        if not _util.command_exists('disktype'):
            logger.warning("disktype not installed, could not detect volume type")
            return None

        disktype = _util.check_output_(['disktype', self.parent.get_raw_path()]).strip()

        current_partition = None
        for line in disktype.splitlines():
            if not line:
                continue
            # noinspection PyBroadException
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
            except Exception:
                logger.exception("Error while parsing disktype output")
                return

    def _assign_disktype_data(self, volume, slot=None):
        """Assigns cached disktype data to a volume."""

        if slot is None:
            slot = volume.slot
        if slot in self._disktype:
            data = self._disktype[slot]
            if not volume.info.get('guid') and 'guid' in data:
                volume.info['guid'] = data['guid']
            if not volume.info.get('label') and 'label' in data:
                volume.info['label'] = data['label']
