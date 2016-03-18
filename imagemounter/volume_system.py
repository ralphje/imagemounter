from __future__ import print_function
from __future__ import unicode_literals

import logging
import subprocess
from collections import defaultdict

import re

from imagemounter import _util


logger = logging.getLogger(__name__)


class VolumeSystem(object):

    def __init__(self):
        self._disktype = defaultdict(dict)

    @staticmethod
    def _determine_auto_detection_method():
        if _util.module_exists('pytsk3'):
            return 'pytsk3'
        elif _util.command_exists('mmls'):
            return 'mmls'
        else:
            return 'parted'

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

    def _mount_volumes(self, vstype='detect', method='auto', only_mount=None):
        if method == 'auto':
            method = VolumeSystem._determine_auto_detection_method()

        if method == 'mmls':
            for v in self._mount_mmls_volumes(vstype, only_mount):
                yield v
        elif method == 'parted':
            for v in self._mount_parted_volumes(vstype, only_mount):
                yield v
        elif method == 'pytsk3':
            for v in self._mount_pytsk3_volumes(vstype, only_mount):
                yield v
        else:
            logger.error("No viable detection method found")
            return

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
            raw_path = self.get_raw_path()
            try:
                baseimage = pytsk3.Img_Info(raw_path)
            except Exception as e:
                logger.error("Failed retrieving image info (possible empty image).", exc_info=True)
                return []

            try:
                volumes = pytsk3.Volume_Info(baseimage, getattr(pytsk3, 'TSK_VS_TYPE_' + vstype.upper()),
                                             int(self.offset) / self.block_size)
                self.volume_source = 'multi'
                return volumes
            except Exception as e:
                # some bug in sleuthkit makes detection sometimes difficult, so we hack around it:
                if "(GPT or DOS at 0)" in str(e) and vstype != 'gpt':
                    self.vstype = 'gpt'
                    try:
                        logger.warning("Error in retrieving volume info: TSK couldn't decide between GPT and DOS, "
                                       "choosing GPT for you. Use --vstype=dos to force DOS.", exc_info=True)
                        volumes = pytsk3.Volume_Info(baseimage, getattr(pytsk3, 'TSK_VS_TYPE_GPT'))
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

    def _mount_pytsk3_volumes(self, vstype='detect', only_mount=None):
        """Generator that mounts every partition of this image and yields the mountpoint."""

        # Loop over all volumes in image.
        for p in self._find_pytsk3_volumes(vstype):
            import pytsk3

            volume = self._make_subvolume()
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

            for v in volume.init(only_mount=only_mount):
                yield v

    def _mount_mmls_volumes(self, vstype='detect', only_mount=None):
        """Finds and mounts all volumes based on mmls."""

        try:
            cmd = ['mmls']
            if self.offset:
                cmd.extend(['-o', str(int(self.offset) / self.block_size)])
            if vstype != 'detect':
                cmd.extend(['-t', vstype])
            cmd.append(self.get_raw_path())
            output = _util.check_output_(cmd, stderr=subprocess.STDOUT)
            self.volume_source = 'multi'
        except Exception as e:
            # some bug in sleuthkit makes detection sometimes difficult, so we hack around it:
            if hasattr(e, 'output') and "(GPT or DOS at 0)" in e.output.decode() and vstype != 'gpt':
                self.vstype = 'gpt'
                try:
                    logger.warning("Error in retrieving volume info: mmls couldn't decide between GPT and DOS, "
                                   "choosing GPT for you. Use --vstype=dos to force DOS.", exc_info=True)
                    cmd = ['mmls', '-t', 'gpt', self.get_raw_path()]
                    output = _util.check_output_(cmd, stderr=subprocess.STDOUT)
                    self.volume_source = 'multi'
                except Exception as e:
                    logger.exception("Failed executing mmls command")
                    return
            else:
                logger.exception("Failed executing mmls command")
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

                volume = self._make_subvolume()
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

            for v in volume.init(only_mount=only_mount):
                yield v

    def _mount_parted_volumes(self, vstype='detect', only_mount=None):
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

                volume = self._make_subvolume()
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

            for v in volume.init(only_mount=only_mount):
                yield v
