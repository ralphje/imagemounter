Python interface
================

While :command:`imount` heavily utilizes the Python API of :mod:`imagemounter`, this API is also available for other classes.

Data structure
--------------

The basic structure of :mod:`imagemounter` is the :class:`imagemounter.ImageParser` class, which provides access to underlying :class:`imagemounter.Disk` and :class:`imagemounter.Volume` objects. Each file name passed to a new :class:`imagemounter.ImageParser` object results in one :class:`imagemounter.Disk` object. :class:`imagemounter.Volume` objects are created by analysis of the :class:`Disk` object (each volume generates one object, even if it is not mountable), and each :class:`imagemounter.Volume` can have one or more subvolumes.

For instance, a LUKS volume may contain a LVM system that contains a Ext volume. This would create a :class:`Disk` with a :class:`Volume` containing a :class:`Volume` which contains the actual Ext :class:`Volume`. Subvolumes are managed through :class:`imagemounter.VolumeSystem`s, which is used by both the :class:`Volume` and :class:`Disk` classes.

Most operations are managed on a :class:`Volume` level, although individual disk file mounting (and volume detection) is performed on a :class:`Disk` level and reconstruction is performed on a :class:`ImageParser` level. This means the following main parts make up the Python package:

- :class:`imagemounter.ImageParser`, maintaining a list of Disks, providing several methods that are carried out on all disks (e.g. mount) and reconstruct.
- :class:`imagemounter.Disk`, which represents a single disk iamge and can be mounted, and maintain volumes. It is also responsible for maintaining the write cache. Although a Disk is able to detect volumes, a Volume has similar capabilities.
- :class:`imagemounter.Volume`, which can detect its own type and fill its stats, can be mounted, and maintain subvolumes.
- :class:`imagemounter.VolumeSystem`, which is used to manage subvolumes and can detect volumes from a volume system.

All three classes maintain an ``init()`` method that yields the volumes below it. You should call ``clean()`` on the parser as soon as you are done; you may also call ``unmount()`` on separate volumes or disks, which will also unmount all volumes below it. Warning: unmounting one of the RAID volumes in a RAID array, causes the entire array to be unmounted.

Reference
---------
.. module:: imagemounter

If you utilize the API, you typically only require the :class:`ImageParser` object, e.g.::

    parser = ImageParser(['/path/to/disk'])
    for v in parser.init():
        print v.size
    root = parser.reconstruct()
    print root.mountpoint
    parser.clean()

The best example of the use of the Python interface is the :command:`imount` command. The entirety of all methods and attributes is documented below.

ImageParser
^^^^^^^^^^^

.. autoclass:: ImageParser

   .. automethod:: add_disk
   .. automethod:: init
   .. automethod:: init_volumes
   .. automethod:: reconstruct
   .. automethod:: clean
   .. automethod:: force_clean

   Most methods above, especially :func:`init`, handle most complicated tasks. However, you may need some more fine-grained control over the mount process, which may require you to use the following methods. Each of these methods passes their activities down to all disks in the parser and return whether it succeeded.

   .. automethod:: rw_active
   .. automethod:: get_volumes
   .. automethod:: get_by_index

   .. automethod:: mount_disks
   .. automethod:: mount_volumes

   For completeness, this is a list of all attributes of :class:`ImageParser`:

   .. attribute:: disks

      List of all :class:`Disk` objects.

   .. attribute:: paths
                  casename
                  fstypes
                  keys
                  vstypes
                  mountdir
                  pretty

      See the constructor of :class:`ImageParser`.

Disk
^^^^

.. autoclass:: Disk

   .. automethod:: init
   .. automethod:: mount
   .. automethod:: detect_volumes
   .. automethod:: init_volumes
   .. automethod:: unmount

   The following methods are only required if you want some fine-grained control, typically if you are not using :func:`init`.

   .. automethod:: get_disk_type
   .. automethod:: rw_active
   .. automethod:: get_fs_path
   .. automethod:: get_raw_path
   .. automethod:: get_volumes

   The following attributes are also available:

   .. attribute:: index

      Disk index. May be None if it is the only disk of this type.

   .. attribute:: mountpoint

      The mountpoint of the disk, after a call to :func:`mount`.

   .. attribute:: rwpath

      The path to the read-write cache, filled after a call to :func:`mount`.

   .. attribute:: volumes

      :class:`VolumeSystem` of all direct child volumes of this disk, excluding all subvolumes. See :func:`get_volumes`.

   .. attribute:: method

      Used to store the base mount method. If it is set to ``auto``, this value will be overwritten with the actually used
      mount method after calling :func:`mount`.

      See also the constructor of :class:`Disk`.

   .. attribute:: parser
                  paths
                  offset
                  read_write
                  disk_mounter

      See the constructor of :class:`Disk`.

Volume
^^^^^^

.. autoclass:: Volume


   .. automethod:: init
   .. automethod:: init_volume
   .. automethod:: unmount

   The following methods offer some more information about the volume:

   .. automethod:: get_description
   .. automethod:: get_safe_label
   .. automethod:: get_formatted_size
   .. automethod:: get_volumes

   These functions offer access to some internals:

   .. automethod:: determine_fs_type
   .. automethod:: get_raw_path
   .. automethod:: mount
   .. automethod:: bindmount
   .. automethod:: carve
   .. automethod:: detect_volume_shadow_copies
   .. automethod:: detect_mountpoint

   The following details may also be available as attributes:

   .. attribute:: size

      The size of the volume in bytes.

   .. attribute:: offset

      The offset of the volume in the disk in bytes.

   .. attribute:: index

      The index of the volume in the disk. If there are subvolumes, the index is separated by periods, though the exact
      format depends on the detection method and its format.

   .. attribute:: slot

      Internal slot number of the volume.

   .. attribute:: flag

      Indicates whether this volume is allocated (*alloc*), unallocated (*unalloc*) or a meta volume (*meta*).

   .. attribute:: block_size

      The block size of this volume.

   .. attribute:: fstype

      The volume file system type used internally as determined by :func:`determine_fs_type`.

   .. attribute:: key

      The key used by some crypto methods.

   .. attribute:: info

      A dict containing information about the volume. Not all keys are always available. Some common keys include:

      * fsdescription -- A description of the file system type, usually set by the detection method
      * lastmountpoint -- The last mountpoint of this volume. Set by :func:`load_fsstat_data` or
        :func:`detect_mountpoint` and only available for UFS and Ext volumes
      * label -- The volume label as detected by :func:`load_fsstat_data`
      * version -- The volume version as detected by :func:`load_fsstat_data`
      * statfstype -- The volume file system type as detected by :func:`load_fsstat_data`
      * guid -- The volume GUID
      * volume_group -- Used for LVM support

      The contents of the info dict are not considered part of a stable API and are subject to change in the future.

   .. attribute:: mountpoint

      The mountpoint of the volume after :func:`mount` has been called.

   .. attribute:: loopback

      The loopback device used by the volume after :func:`mount` (or related methods) has been called.

   .. attribute:: was_mounted
                  is_mounted

      Booleans indicating that the volume has successfully been mounted during its lifetime, and is currently mounted

   .. attribute:: volumes
                  parent

      :attr:`volumes` contains a :class:`VolumeSystem` of all subvolumes of this volume; :attr:`parent` contains the parent volume (if
      any).

   .. attribute:: disk
                  stats
                  fstypes
                  pretty
                  mountdir
                  args

      See the constructor of :class:`Volume`.

VolumeSystem
^^^^^^^^^^^^

.. autoclass:: VolumeSystem

   .. automethod:: detect_volumes
   .. automethod:: preload_volume_data

   .. automethod:: __iter__
   .. automethod:: __getitem__

   .. attribute:: volumes

      The list of all volumes in this system.

   .. attribute:: volume_source

      The source of the volumes of this system, either *single* or *multi*.

   .. attribute:: has_detected

      Boolean indicating whether this volume already ran its detection.

   .. attribute:: vstype
                  detection
                  args

      See the constructor of :class:`VolumeSystem`.

Unmounter
^^^^^^^^^

.. autoclass:: Unmounter

   .. automethod:: preview_unmount
   .. automethod:: unmount

   .. automethod:: find_bindmounts
   .. automethod:: find_mounts
   .. automethod:: find_base_images
   .. automethod:: find_volume_groups
   .. automethod:: find_loopbacks
   .. automethod:: find_clean_dirs

   .. automethod:: unmount_bindmounts
   .. automethod:: unmount_mounts
   .. automethod:: unmount_base_images
   .. automethod:: unmount_volume_groups
   .. automethod:: unmount_loopbacks
   .. automethod:: clean_dirs

   .. attribute:: re_pattern

      The regex pattern used to look for volume mountpoints.

   .. attribute:: glob_pattern

      The glob pattern used to look for volume mountpoints. Always used in conjunction with the :attr:`re_pattern`.

   .. attribute:: orig_re_pattern

      The regex pattern used to look for base mountpoints.

   .. attribute:: orig_glob_pattern

      The glob pattern used to look for base mountpoints. Always used in conjunction with the :attr:`orig_re_pattern`.

   .. attribute:: be_greedy

      If set, some more volumes and mountpoints may be found.
