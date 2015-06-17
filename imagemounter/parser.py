from __future__ import print_function
from __future__ import unicode_literals

import logging
import sys
import os
from imagemounter.disk import Disk


logger = logging.getLogger(__name__)


# noinspection PyShadowingNames
class ImageParser(object):
    """Root object of the :mod:`imagemounter` Python interface. This class should be sufficient allowing access to the
    underlying functions of this module.

    """

    def __init__(self, paths, casename=None, **args):
        """Instantiation of this class does not automatically mount, detect or analyse :class:`Disk` s, though it
        initialises each provided path as a new :class:`Disk` object.

        :param paths: list of paths to base images that should be mounted
        :type paths: iterable
        :param casename: the name of the case, used when prettifying names
        :param args: arguments that should be passed down to :class:`Disk` and :class:`Volume` objects
        """

        # Python 3 compatibility
        if sys.version_info[0] == 2:
            string_types = basestring
        else:
            string_types = str

        if isinstance(paths, string_types):
            self.paths = [paths]
        else:
            self.paths = paths
        self.casename = casename
        self.args = args

        self.disks = []
        index = 0
        for path in self.paths:
            if len(self.paths) == 1:
                index = None
            else:
                index += 1
            self.disks.append(Disk(self, path, index=index, **self.args))

    def init(self, single=None, raid=True):
        """Handles all important disk-mounting tasks, i.e. calls the :func:`Disk.init` function on all underlying
        disks. It yields every volume that is encountered, including volumes that have not been mounted.

        :param single: indicates whether the :class:`Disk` should be mounted as a single disk, not as a single disk or
            whether it should try both (defaults to :const:`None`)
        :type single: bool|None
        :param raid: indicates whether RAID detection is enabled
        :type raid: bool
        :rtype: generator
        """
        for d in self.disks:
            for v in d.init(single, raid):
                yield v

    def mount_disks(self):
        """Mounts all disks in the parser, i.e. calling :func:`Disk.mount` on all underlying disks. You probably want to
        use :func:`init` instead.

        :return: whether all mounts have succeeded
        :rtype: bool"""

        result = True
        for disk in self.disks:
            result = disk.mount() and result
        return result

    def rw_active(self):
        """Indicates whether a read-write cache is active in any of the disks.

        :rtype: bool"""
        result = False
        for disk in self.disks:
            result = disk.rw_active() or result
        return result

    def mount_raid(self):
        """Creates a RAID device and adds all devices to the RAID array, i.e. calling :func:`Disk.add_to_raid` on all
        underlying disks. Should be called before :func:`mount_disks`.

        :return: whether all disks were successfully added
        :rtype: bool
        """

        result = True
        for disk in self.disks:
            result = disk.add_to_raid() and result
        return result

    def mount_single_volume(self):
        """Detects the full disk as a single volume and yields the volume. This calls
        :func:`Disk.mount_single_volume` on all disks and should be called after :func:`mount_disks`

        :rtype: generator"""

        for disk in self.disks:
            logger.info("Mounting volumes in {0}".format(disk))
            for volume in disk.mount_single_volume():
                yield volume

    def mount_multiple_volumes(self):
        """Detects volumes in all disks (all mounted as a volume system) and yields the volumes. This calls
        :func:`Disk.mount_multiple_volumes` on all disks and should be called after :func:`mount_disks`.

        :rtype: generator"""

        for disk in self.disks:
            logger.info("Mounting volumes in {0}".format(disk))
            for volume in disk.mount_multiple_volumes():
                yield volume

    def mount_volumes(self, single=None):
        """Detects volumes (as volume system or as single volume) in all disks and yields the volumes. This calls
        :func:`Disk.mount_multiple_volumes` on all disks and should be called after :func:`mount_disks`.

        :rtype: generator"""

        for disk in self.disks:
            logger.info("Mounting volumes in {0}".format(disk))
            for volume in disk.mount_volumes(single):
                yield volume

    def get_volumes(self):
        """Gets a list of all volumes of all disks, concatenating :func:`Disk.get_volumes` of all disks.

        :rtype: list"""

        volumes = []
        for disk in self.disks:
            volumes.extend(disk.get_volumes())
        return volumes

    def clean(self, remove_rw=False):
        """Cleans all volumes of all disks (:func:`Volume.unmount`) and all disks (:func:`Disk.unmount`). Volume errors
        are ignored, but returns immediately on disk unmount error.

        :param bool remove_rw: indicates whether a read-write cache should be removed
        :return: whether the command completed successfully
        :rtype: boolean"""

        # To ensure clean unmount after reconstruct, we sort across all volumes in all our disks to provide a proper
        # order
        volumes = list(sorted(self.get_volumes(), key=lambda v: v.mountpoint or "", reverse=True))
        for v in volumes:
            if not v.unmount():
                logger.error("Error unmounting volume {0}".format(v.mountpoint))

        # Now just clean the rest.
        for disk in self.disks:
            if not disk.unmount(remove_rw):
                logger.error("Error unmounting {0}".format(disk))
                return False

        return True

    def reconstruct(self):
        """Reconstructs the filesystem of all volumes mounted by the parser by inspecting the last mount point and
        bind mounting everything.

        :return: None on failure, or the root :class:`Volume` on success
        """
        volumes = list(sorted((v for v in self.get_volumes() if v.mountpoint and v.lastmountpoint),
                              key=lambda v: v.mountpoint or "", reverse=True))

        try:
            root = list(filter(lambda x: x.lastmountpoint == '/', volumes))[0]
        except IndexError:
            logger.error("Could not find / while reconstructing, aborting!")
            return None

        volumes.remove(root)

        for v in volumes:
            v.bindmount(os.path.join(root.mountpoint, v.lastmountpoint[1:]))
        return root

