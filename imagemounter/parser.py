from __future__ import print_function
from __future__ import unicode_literals

import logging
import sys
import os
import tempfile

from imagemounter.disk import Disk
from imagemounter.exceptions import NoRootFoundError, ImageMounterError, DiskIndexError

logger = logging.getLogger(__name__)


# noinspection PyShadowingNames
class ImageParser(object):
    """Root object of the :mod:`imagemounter` Python interface. This class should be sufficient allowing access to the
    underlying functions of this module.

    """

    def __init__(self, paths=(), force_disk_indexes=False,
                 casename=None, read_write=False, disk_mounter='auto',
                 volume_detector='auto', vstypes=None,
                 fstypes=None, keys=None, mountdir=None, pretty=False, **args):
        """Instantiation of this class does not automatically mount, detect or analyse :class:`Disk` s, though it
        initialises each provided path as a new :class:`Disk` object.

        :param paths: list of paths to base images that should be mounted
        :type paths: iterable
        :param force_disk_indexes: if True, a Disk index is always included. If False, will only use Disk indexes if
                                   more than 1 Disk is provided to the paths
        :param casename: the name of the case, used when prettifying names
        :param bool read_write: indicates whether disks should be mounted with a read-write cache enabled
        :param str disk_mounter: the method to mount the base images with
        :param dict fstypes: dict mapping volume indices to file system types to use; use * and ? as volume indexes for
                             additional control. Only when ?=none, unknown will not be used as fallback.
        :param dict keys: dict mapping volume indices to key material
        :param str mountdir: location where mountpoints are created, defaulting to a temporary location
        :param bool pretty: indicates whether pretty names should be used for the mountpoints
        :param args: ignored
        """

        from imagemounter import __version__
        logger.debug("imagemounter version %s", __version__)

        # Store other arguments
        self.casename = casename

        self.fstypes = {str(k): v for k, v in fstypes.items()} if fstypes else {'?': 'unknown'}
        if '?' in self.fstypes and (not self.fstypes['?'] or self.fstypes['?'] == 'none'):
            self.fstypes['?'] = None
        self.keys = {str(k): v for k, v in keys.items()} if keys else {}
        self.vstypes = {str(k): v for k, v in vstypes.items()} if vstypes else {}

        self.mountdir = mountdir
        if self.casename:
            self.mountdir = os.path.join(mountdir or tempfile.gettempdir(), self.casename)
        self.pretty = pretty

        # Add disks
        self.disks = []
        for path in paths:
            self.add_disk(path, len(paths) > 1 or force_disk_indexes,
                          read_write=read_write, disk_mounter=disk_mounter, volume_detector=volume_detector)

    def __getitem__(self, item):
        item = str(item)
        for d in self.disks:
            if d.index == item:
                return d
        raise KeyError(item)

    def add_disk(self, path, force_disk_indexes=True, **args):
        """Adds a disk specified by the path to the ImageParser.

        :param path: The path to the disk volume
        :param force_disk_indexes: If true, always uses disk indexes. If False, only uses disk indexes if this is the
                                   second volume you add. If you plan on using this method, always leave this True.
                                   If you add a second disk when the previous disk has no index, an error is raised.
        :param args: Arguments to pass to the constructor of the Disk.
        """
        if self.disks and self.disks[0].index is None:
            raise DiskIndexError("First disk has no index.")

        if force_disk_indexes or self.disks:
            index = len(self.disks) + 1
        else:
            index = None
        disk = Disk(self, path, index=str(index) if index else None, **args)
        self.disks.append(disk)
        return disk

    def init(self, single=None, swallow_exceptions=True):
        """Handles all important disk-mounting tasks, i.e. calls the :func:`Disk.init` function on all underlying
        disks. It yields every volume that is encountered, including volumes that have not been mounted.

        :param single: indicates whether the :class:`Disk` should be mounted as a single disk, not as a single disk or
            whether it should try both (defaults to :const:`None`)
        :type single: bool|None
        :param swallow_exceptions: specify whether you want the init calls to swallow exceptions
        :rtype: generator
        """
        for d in self.disks:
            for v in d.init(single, swallow_exceptions=swallow_exceptions):
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

    def init_volumes(self, single=None, only_mount=None, swallow_exceptions=True):
        """Detects volumes (as volume system or as single volume) in all disks and yields the volumes. This calls
        :func:`Disk.init_volumes` on all disks and should be called after :func:`mount_disks`.

        :rtype: generator"""

        for disk in self.disks:
            logger.info("Mounting volumes in {0}".format(disk))
            for volume in disk.init_volumes(single, only_mount, swallow_exceptions=swallow_exceptions):
                yield volume

    def get_by_index(self, index):
        """Returns a Volume or Disk by its index."""

        try:
            return self[index]
        except KeyError:
            for v in self.get_volumes():
                if v.index == str(index):
                    return v
        raise KeyError(index)

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
        :rtype: boolean
        :raises SubsystemError: when one of the underlying commands fails. Some are swallowed.
        :raises CleanupError: when actual cleanup fails. Some are swallowed.
        """

        # To ensure clean unmount after reconstruct, we sort across all volumes in all our disks to provide a proper
        # order
        volumes = list(sorted(self.get_volumes(), key=lambda v: v.mountpoint or "", reverse=True))
        for v in volumes:
            try:
                v.unmount()
            except ImageMounterError:
                logger.error("Error unmounting volume {0}".format(v.mountpoint))

        # Now just clean the rest.
        for disk in self.disks:
            disk.unmount(remove_rw)

    def reconstruct(self):
        """Reconstructs the filesystem of all volumes mounted by the parser by inspecting the last mount point and
        bind mounting everything.

        :raises: NoRootFoundError if no root could be found
        :return: the root :class:`Volume`
        """
        volumes = list(sorted((v for v in self.get_volumes() if v.mountpoint and v.info.get('lastmountpoint')),
                              key=lambda v: v.mountpoint or "", reverse=True))

        try:
            root = list(filter(lambda x: x.info.get('lastmountpoint') == '/', volumes))[0]
        except IndexError:
            logger.error("Could not find / while reconstructing, aborting!")
            raise NoRootFoundError()

        volumes.remove(root)

        for v in volumes:
            v.bindmount(os.path.join(root.mountpoint, v.info.get('lastmountpoint')[1:]))
        return root

