Python interface
================

While :command:`imount` heavily utilizes the Python API of :mod:`imagemounter`, this API is also available for other classes.

Data structure
--------------

The basic structure of :mod:`imagemounter` is the :class:`imagemounter.ImageParser` class, which provides access to underlying :class:`imagemounter.Disk` and :class:`imagemounter.Volume` objects. Each file name passed to a new :class:`imagemounter.ImageParser` object results in one :class:`imagemounter.Disk` object. :class:`imagemounter.Volume` objects are created by analysis of the :class:`Disk` object (each volume generates one object, even if it is not mountable), and each :class:`imagemounter.Volume` can have one or more subvolumes.

For instance, a LUKS volume may contain a LVM system that contains a Ext volume. This would create a :class:`Disk` with a :class:`Volume` containing a :class:`Volume` which contains the actual Ext :class:`Volume`.

Most operations are managed on a :class:`Volume` level, although RAIDs (and volume detection) are managed on a :class:`Disk` level and reconstruction is performed on a :class:`ImageParser` level. This means the following main parts make up the Python package:

- :class:`imagemounter.ImageParser`, maintaining a list of Disks, providing several methods that are carried out on all disks (e.g. mount) and reconstruct.
- :class:`imagemounter.Disk`, which represents a single disk iamge and can be mounted, added to RAID, and detect and maintain volumes. It is also responsible for maintaining the write cache.
- :class:`imagemounter.Volume`, which can detect its own type and fill its stats, can be mounted, and detect LVM (sub)volumes.

All three classes maintain an ``init()`` method that yields the volumes below it. You should call clean on the parser if
you are done; you may also unmount separate volumes or disks, which will also unmount all volumes below it. Warning:
unmounting one of the RAID volumes in a RAID array, causes the entire array to be unmounted.

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

.. autoclass:: ImageParser

   .. automethod:: init
   .. automethod:: reconstruct
   .. automethod:: clean
   .. automethod:: force_clean


   Most methods above, especially :func:`init`, handle most complicated tasks. However, you may need some more fine-grained control over the mount process, which may require you to use the following methods. Each of these methods passes their activities down to all disks in the parser and return whether it succeeded.

   .. automethod:: rw_active
   .. automethod:: get_volumes

   .. automethod:: mount_disks
   .. automethod:: mount_raid
   .. automethod:: mount_single_volume
   .. automethod:: mount_multiple_volumes
   .. automethod:: mount_volumes

   For completeness, this is a list of all attributes of :class:`ImageParser`:

   .. attribute:: disks

      List of all :class:`Disk` objects.

   .. attribute:: paths
                  out
                  verbose
                  verbose_color
                  args

      See the constructor of :class:`ImageParser`.

.. autoclass:: Disk

   .. automethod:: init
   .. automethod:: unmount

   The following methods are only required if you want some fine-grained control, typically if you are not using :func:`init`.

   .. automethod:: rw_active
   .. automethod:: get_fs_path
   .. automethod:: get_raw_path
   .. automethod:: get_volumes

   .. automethod:: mount
   .. automethod:: mount_volumes
   .. automethod:: mount_multiple_volumes
   .. automethod:: mount_single_volume
   .. automethod:: is_raid
   .. automethod:: add_to_raid

   The following attributes are also available:

   .. attribute:: name

      Pretty name of the disk.

   .. attribute:: mountpoint

      The mountpoint of the disk, after a call to :func:`mount`.

   .. attribute:: rwpath

      The path to the read-write cache, filled after a call to :func:`mount`.

   .. attribute:: volumes

      List of all direct child volumes of this disk, excluding all subvolumes. See :func:`get_volumes`.

   .. attribute:: volume_source

      The source of the volumes of this disk, either *single* or *multi*, filled after a call to :func:`mount_volumes`.

   .. attribute:: loopback
                  md_device

      Used for RAID support.

   .. attribute:: parser
                  path
                  offset
                  vstype
                  read_write
                  method
                  detection
                  multifile
                  args

      See the constructor of :class:`Disk`.

.. autoclass:: Volume


   .. automethod:: init
   .. automethod:: unmount

   The following methods offer some more information about the volume:

   .. automethod:: get_description
   .. automethod:: get_safe_label
   .. automethod:: get_size_gib
   .. automethod:: get_volumes

   These functions offer access to some internals:

   .. automethod:: get_fs_type
   .. automethod:: get_raw_base_path
   .. automethod:: mount
   .. automethod:: bindmount
   .. automethod:: fill_stats
   .. automethod:: detect_mountpoint
   .. automethod:: find_lvm_volumes
   .. automethod:: open_luks_container

   The following details may also be available as attributes:

   .. attribute:: size

      The size of the volume in bytes.

   .. attribute:: offset

      The offset of the volume in the disk in bytes.

   .. attribute:: index

      The index of the volume in the disk. If there are subvolumes, the index is separated by periods, though the exact
      format depends on the detection method and its format.

   .. attribute:: flag

      Indicates whether this volume is allocated (*alloc*), unallocated (*unalloc*) or a meta volume (*meta*).

   .. attribute:: fsdescription

      A description of the file system type.

   .. attribute:: lastmountpoint

      The last mountpoint of this volume. Set by :func:`fill_stats` or :func:`detect_mountpoint` and only available
      for UFS and Ext volumes.

   .. attribute:: label

      The volume label as detected by :func:`fill_stats`.

   .. attribute:: version

      The volume version as detected by :func:`fill_stats`.

   .. attribute:: fstype

      The volume file system type as detected by :func:`fill_stats`.

   .. attribute:: mountpoint

      The mountpoint of the volume after :func:`mount` has been called.

   .. attribute:: bindmountpoint

      The mountpoint of the volume after :func:`bindmount` has been called.

   .. attribute:: loopback

      The loopback device used by the volume after :func:`mount` (or related methods) has been called.

   .. attribute:: exception

      Contains an exception that occurred during a call to :func:`mount`.

   .. attribute:: was_mounted

      Boolean indicating that the volume has successfully been mounted during its lifetime.

   .. attribute:: volumes
                  parent

      :attr:`volumes` contains a list of all subvolumes of this volume; :attr:`parent` contains the parent volume (if
      any).

   .. attribute:: volume_group
                  lv_path

      Attributes used for LVM support

   .. attribute:: luks_path

      Attribute used for LUKS support

   .. attribute:: disk
                  stats
                  fsforce
                  fsfallback
                  fstypes
                  pretty
                  mountdir
                  args

      See the constructor of :class:`Volume`.