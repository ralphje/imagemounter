from __future__ import print_function
from __future__ import unicode_literals

import logging
import subprocess
from collections import defaultdict

import re

from imagemounter import _util

logger = logging.getLogger(__name__)


class VolumeSystem(object):
    """A VolumeSystem is a collection of volumes. Every :class:`Disk` contains exactly one VolumeSystem. Each
    system contains several :class:`Volumes`, which, in turn, may contain additional volume systems.
    """

    def __init__(self, parent, vstype='detect', detection='auto', **args):
        """Creates a VolumeSystem.

        :param parent: the parent may either be a :class:`Disk` or a :class:`Volume` that contains this  VolumeSystem.
        :param str vstype: the volume system type to use.
        :param str detection: the volume system detection method to use
        :param args: additional arguments to pass to :class:`Volume`s created
        """

        self.parent = parent
        self.disk = parent.disk if hasattr(parent, 'disk') else parent

        self.vstype = vstype
        if detection == 'auto':
            self.detection = VolumeSystem._determine_auto_detection_method()
        else:
            self.detection = detection

        self.volume_source = ""
        self.volumes = []

        self._disktype = defaultdict(dict)
        self.args = args

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

    def _make_subvolume(self):
        """Creates a subvolume, adds it to this class and returns it."""

        from imagemounter.volume import Volume
        # we also pass in the detection and vstype, so it gets to Volume.args, which gets passed back when the Volume
        # creates a new VolumeType
        v = Volume(disk=self.disk, parent=self.parent, detection=self.detection, vstype=self.vstype, **self.args)
        self.volumes.append(v)
        return v

    def _make_single_subvolume(self):
        """Creates a subvolume, adds it to this class, sets the volume index to 0 and returns it."""

        volume = self._make_subvolume()
        if self.parent.index is None:
            volume.index = '0'
        else:
            volume.index = '{0}.0'.format(self.parent.index)
        return volume

    def detect_volumes(self, vstype=None, method=None):
        """Iterator for detecting volumes within this volume system.

        :param str vstype: The volume system type to use. If None, uses :attr:`vstype`
        :param str method: The detection method to use. If None, uses :attr:`detection`
        """

        if vstype is None:
            vstype = self.vstype
        if method is None:
            method = self.detection

        if method == 'auto':
            method = VolumeSystem._determine_auto_detection_method()

        if vstype == 'lvm':
            for v in self._detect_lvm_volumes(self.parent.info.get('volume_group')):
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
            return

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

    def _find_pytsk3_volumes(self, vstype='detect'):
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
            raw_path = self.parent.get_raw_path()
            # noinspection PyBroadException
            try:
                baseimage = pytsk3.Img_Info(raw_path)
            except Exception:
                logger.error("Failed retrieving image info (possible empty image).", exc_info=True)
                return []

            try:
                volumes = pytsk3.Volume_Info(baseimage, getattr(pytsk3, 'TSK_VS_TYPE_' + vstype.upper()),
                                             int(self.parent.offset) / self.disk.block_size)
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
                    except Exception:
                        logger.exception("Failed retrieving image info (possible empty image).")
                        return []
                else:
                    logger.exception("Failed retrieving image info (possible empty image).")
                    return []
        finally:
            if baseimage:
                baseimage.close()
                del baseimage

    def _detect_pytsk3_volumes(self, vstype='detect'):
        """Generator that mounts every partition of this image and yields the mountpoint."""

        # Loop over all volumes in image.
        for p in self._find_pytsk3_volumes(vstype):
            import pytsk3

            volume = self._make_subvolume()
            # Fill volume with more information
            volume.offset = p.start * self.disk.block_size
            volume.info['fsdescription'] = p.desc.strip()
            volume.index = self._format_index(p.addr)
            volume.size = p.len * self.disk.block_size

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
                cmd.extend(['-o', str(int(self.parent.offset) / self.disk.block_size)])
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
                except Exception:
                    logger.exception("Failed executing mmls command")
                    return
            else:
                logger.exception("Failed executing mmls command")
                return

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

                volume = self._make_subvolume()
                volume.offset = int(start) * self.disk.block_size
                volume.info['fsdescription'] = description
                volume.index = self._format_index(int(index[:-1]))
                volume.size = int(length) * self.disk.block_size
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
            output = _util.check_output_(['parted', self.parent.get_raw_path(), 'print'])
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
            output = _util.check_output_(cmd)
            self.volume_source = 'multi'
        except Exception:
            logger.exception("Failed executing parted command")
            return

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

                volume = self._make_subvolume()
                volume.offset = int(start[:-1]) * self.disk.block_size  # remove last s
                volume.size = int(length[:-1]) * self.disk.block_size
                volume.info['fsdescription'] = description
                volume.index = self._format_index(num)

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
                cur_v = self._make_subvolume()
                cur_v.index = self._format_index(len(self) - 1)
                cur_v.info['fsdescription'] = 'Logical Volume'
                cur_v.flag = 'alloc'
            if "LV Name" in l:
                cur_v.info['label'] = l.replace("LV Name", "").strip()
            if "LV Size" in l:
                cur_v.size = l.replace("LV Size", "").strip()
            if "LV Path" in l:
                cur_v._paths['lv'] = l.replace("LV Path", "").strip()
                cur_v.offset = 0

        logger.info("{0} volumes found".format(len(self)))
        return self.volumes

    def load_disktype_data(self):
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
