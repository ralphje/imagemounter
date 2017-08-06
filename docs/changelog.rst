Release notes
=============

We try to reduce backwards compatibility breakage only to major version releases, i.e. X.0.0. Minor releases (1.X.0) may include new features, whereas patch releases (1.0.X) will generally be used to fix bugs. Not all versions have followed these simple rules to date (and sometimes new features may creep up in patch releases), but we try to adhere them as much as possible :).

Release history
~~~~~~~~~~~~~~~

3.1.0 (2017-08-06)
------------------
New features:

* Support for exFAT filesystems (contributed by ldgriffin)
* Addition of ``force_clean`` method to :class:`ImageParser`
* Addition of :option:`--skip`, to complement :option:`--only-mount`
* Improved support for UFS / BSD volumes

Bugfixes:

* Updated :option:`--keys` to not parse commas (as these may be part of the key themselves) and properly support
  the asterisk key.
* Several fixes for ``fsstat`` call, including actually killing it after 3 seconds and optimizations by passing
  in the correct FS type, making mounting actually a lot faster.
* Fixes for path expanding (contributed by ruzzle)
* Re-index loopbacks prior to unmounting in the :class:`Unmounter` class (contributed by ldgriffin)
* Use ``--sizelimit`` for various mounts, for support in newer kernel versions (contributed by ldgriffin)
* Improved support for non-ASCII volume labels
* The parted detection method does not hang anymore when parted requests input
* Fix for communication of LUKS keys to the ``cryptsetup`` command
* Fixes for reconstruction when multiple roots exist


3.0.1 (2017-04-08)
------------------
* Add support for qcow2 (contributed by Jarmo van Lenthe)
* Allow use of lowercase e01 file extension when mounting a directory in imount CLI (contributed by sourcex)
* Add ADS support for NTFS volumes (contributed by Patrick Leedom)
* Ability to lazily call fusermount -uz when unmounting (contributed by Patrick Leedom)

* Fix regression in mounting LV volumes; the path was incorrectly detected in :func:`get_raw_path` for these volumes.
* Fix regression in detection of single volumes that would be detected as DOS/MBR based on file type.

3.0.0 (2016-12-11)
------------------
This new release includes several backwards-incompatible changes, mostly because features were removed from the public API or have been renamed to obtain a more consistent API.

It was released after a long time of development, and does not even contain all features that were originally planned to go into this release, but it contains some important bugfixes that warranted a release.

New major features:

* Add volume shadow copy support for NTFS
* Add BDE (Bitlocker) support
* Addition of :option:`--keys` CLI argument and corresponding argument to Volume class, allowing to specify key material for crypto mounts, supporting both BDE and LUKS.
* (Experimental) support for volume systems inside a volume. This is useful when e.g. a LVM volume contains in itself a MBR.
* A split between detection and initialization of volumes has been made. The basic way to access volumes as calling :func:`init`, but that mounted all volumes immediately. Now, ``detect_*`` methods have been added.
* Support ``blkid`` to retrieve FS type info
* Support for Linux RAID volumes
* (Still in development) interactive console, which will eventually become the primary means to interact with imagemounter.

Bugfixes:

* Calling :func:`init` will not automatically mount the volume when it is not ``alloc``.
* Fix a bug where ``.e01`` files (lowercase) would not be recognized as Encase
* Fixed support for newer versions of ``mmls``
* Fixed support for pytsk3 under Python 3 (contributed by insomniacslk)
* Fixed support for EnCase v7 (EX01) image files (contributed by pix)
* Improved detection of several volume types
* :attr:`index` is now always ``str``
* :attr:`Volume.size` is now always ``int``
* Improved the unmounter with generic loopback support

Removed and modified features:

* Stopped providing :const:`None` and :const:`False` results when things go wrong for most methods. Instead, numerous exceptions have been added. These exceptions should be catched instead, or when using ``mount_volumes`` or ``init``, you can specify ``swallow_exceptions`` (default) to restore previous behaviour. This is useful, since iteration will continue regardless of exceptions.
* Moved the attributes ``fstypes``, ``vstypes``, ``keys``, ``mountdir`` and ``pretty`` to the ``ImageParser`` instance, so it does not need to get passed down through the ``*args`` hack anymore. For instance, ``fstypes`` has been moved; the dict will be inspected upon Volume instantiation and stored in the ``fstype`` attribute. Other arguments and attributes have been eliminated completely, or have been replaced by arguments to specific methods.
* Added an intermediary class :class:`VolumeSystem`. Both :class:`Volume` and :class:`Disk` now use this (iterable) base class in their :attr:`volumes` attribute. If you relied on :attr:`volumes` being a ``list``, you should now use ``list(volumes)``. If you relied on indexing of the attribute, you could now also use ``disk[0]`` or ``volume[0]`` for finding the correct volume index. :attr:`volume_source` was moved to this class, as have :attr:`vstype` and :attr:`volume_detector`.

* Changes to the CLI:
   * Removed :option:`--fsforce` and :option:`--fsfallback`. Use ``*`` and ``?`` as fstypes instead for the same effect. This should make the CLI more sensible, especially regarding the :option:`--fsforce` argument. The default FS fallback is still ``unknown``, which can only be overridden by specifying ``--fstypes=?=none``. (You can now specify ``--fstypes=TYPE``, which equals to ``--fstypes=*=TYPE``)
   * Removed ``--stats`` and ``--no-stats``. These only complicated things and ``fsstat`` has been working fine for years now.
   * Removed ``--raid`` and ``--no-raid`` (due to Volume RAID support)
   * Removed ``--disktype`` and ``--no-disktype``.
   * Renamed ``--method`` to ``--disk-mounter``.
   * Renamed ``--detection`` to ``--volume-detector``.
   * Renamed ``--vstype`` to ``--vstypes``, now accepting a dict, similar to ``--fstypes``
   * Moved the ``imount.py`` file into a new ``cli`` module, where also a new experimental shell-style CLI is under development.

* Changes specific to :class:`ImageParser`:
   * Added ``add_disk`` and made ``paths`` optional in constructor.
   * Added indexing of the `ImageParser` and added ``get_volume_by_index`` method.
   * Removed ``mount_single_volume`` and ``mount_multiple_volumes``. Use ``init_volumes`` instead, or use a custom loop for more control.
   * Dropped support for a single string argument for ``paths`` in ``__init__``. Additionally, dropped the ``paths`` attribute entirely.

* Changes specific to :class:`Disk`:
   * Renamed ``method`` to ``disk_mounter`` (see also CLI)
   * Removed ``name``, ``avfs_mountpoint`` and ``md_device`` from public API.
   * Removed Linux RAID Disk support. Instead, mount as a single volume, with the type of this volume being RAID. This greatly simplifies the :class:`Disk` class. (This means that :attr:`loopback` has also been dropped from Disk)
   * Added ``detect_volumes`` method, which can be used to detect volumes.
   * Removed most ``mount_*`` methods. Moved ``mount_volumes`` to ``init_volumes``. Functionality from the other methods can be restored with only a few lines of code.
   * Removed the need for the rather obsure ``multifile`` attribute of ``mount``. Only ``xmount`` actually required this, so we just implicitly use it there.
   * Moved the ``type`` attribute to a method ``get_disk_type``.

* Changes specific to :class:`Volume`:
   * Renamed ``get_raw_base_path`` to ``get_raw_path``
   * Renamed ``get_size_gib`` to ``get_formatted_size``
   * Removed ``get_magic_type``, ``fill_stats``, ``open_jffs2``, ``find_lvm_volumes`` and ``open_luks_container`` from public API.
   * Removed the ``*_path``, ``carvepoint`` and ``bindmountpoint`` attributes from the public API. For ``carvepoint``, the ``carve`` method now returns the path to the carvepoint. All data has been moved to the private ``_paths`` attribute. The ``mountpoint`` and ``loopback`` attributes are kept.
   * Removed ``fsforce`` and ``fsfallback`` arguments and attributes from Volume (see also CLI)
   * Added ``init_volume``, which only mounts the single volume. It is used by ``init`` and the preferred way of mounting a single volume (instead of using ``mount``)
   * Moved several attributes of :class:`Volume` to a new :attr:`info` attribute, which is publicly accessible, but its contents are not part of a stable public API.

* Changes specific to :class:`VolumeSystem` (if you consider it on par with the functionality moved from Disk):
   * Renamed ``detection`` to ``volume_detector`` (see also CLI)
   * Added a :func:`VolumeSystem.detect_volumes` iterable, which is the basic functionality of this class.
   * Moved ``mount_single_volume`` code from :class:`Disk` to this class, adding the ``single`` volume detection method. The directory detection method has been incorporated in this new method.

* Dropped support for Python 3.2, since everyone seems to be doing that these days.

2.0.4 (2016-03-15)
------------------
* Add HFS+ support

2.0.3 (2015-08-02)
------------------
* Remove error prefix (``[-]``) from some of the warnings
* Do not warn about using unknown as fsfallback anymore
* Also work properly with the ``python-magic`` system package (in addition to the totally different ``python-magic`` PyPI package)
* *vmware-mount* Add ``-r`` to vmware-mount for readonly mounts
* *ntfs* Add force to mount options

2.0.2 (2015-06-17)
------------------
* Bugfix in :option:`--check` regarding the ``python-magic`` module
* *vmware-mount* Fix vmware-mount support

2.0.1 (2015-06-17)
------------------
* Changed the default ``fsfallback`` to ``unknown``, instead of ``none``.

2.0.0 (2015-06-17)
------------------
* Introduce support for XFS, ISO, JFFS2, FAT, SquashFS, CramFS, VMFS, UDF and Minix (cheers martinvw!)
* Add ability to read the disk GUID using disktype, and read the filesystem magic for better detection of filesystems (cheers martinvw!)
* Add support for 'mounting' directories and compressed files using avfs (cheers martinvw!)
* Add support for detecting volumes using parted
* Introduce facility to carve filesystems for removed files, even in unallocated spaces
* Add :option:`--no-interaction` for scripted access to the CLI
* Add :option:`--check` for access to an overview of all dependencies of imagemounter
* Add :option:`--casename` (and corresponding Python argument) to easily recognize and organize multiple mounts on the same system
* Change :option:`--clean` to :option:`--unmount`, supporting arguments such as :option:`--mountdir` and :option:`--pretty`, and made the code more robust and easier to read and extend
* Detect terminal color support and show color by default


* BSD is now called UFS
* :option:`--stats` is now the default in the Python script
* NTFS mount now also shows the system files by default
* Do not stop when not running as root, but warn and probably fail miserably later on
* :attr:`fstype` now stores the detected file system type, instead of the :attr:`fstype` as determined by :func:`fill_stats`
* Logging now properly uses the Python logging framework, and there are now 4 verbosity levels
* Changes to how the pretty names are formatted
* Some Py2/Py3 compatibility fixes

1.5.3 (2015-04-08)
------------------
* Add support for ``vmware-mount``

1.5.2 (2015-04-08)
------------------
* Ensure ``Volume.size`` is always int
* Fixed a GPT/DOS bug caused by TSK
* Add FAT support

1.5.1 (2014-05-22)
------------------
* Add disk index for multi-disk mounts

1.5.0 (2014-05-14)
------------------
* Add support for volume detection using mmls
* Python 3 support
* Bugfix in luksOpen

1.4.3 (2014-04-26)
------------------
* Experimental LUKS support

1.4.2 (2014-04-26)
------------------
* Bugfix that would prevent proper unmounting

1.4.1 (2014-02-10)
------------------
* Initial Py3K support
* Included script is now called ``imount`` instead of ``mount_images``

1.4.0 (2014-02-03)
------------------
* :class:`Disk` is now a seperate class
* Some huge refactoring
* Numerous bugfixes, including resolving issues with unmounting
* Rename ``image_mounter`` to ``imagemounter``
* Remove ``mount_images`` alias

1.3.1 (2014-01-23)
------------------
* More verbosity with respect to failing mounts

1.3.0 (2014-01-23)
------------------
* Add support for single volume mounts
* Add support for dummy base mounting
* Add support for RAID detection and mounting

1.2.9 (2014-01-21)
------------------
* Improve support for some types of disk images
* Some changes in the way some command-line arguments work (removed :option:`-vs`, :option:`-fs` and :option:`-fsf`)

1.2.8 (2014-01-08)
------------------
* Make :option:`--stats the default
* Print the volume size and offset in verbose mode in the CLI
* Add imount as command line utility name

1.2.7 (2014-01-08)
------------------
* Add :option:`--keep`

1.2.6 (2014-01-08)
------------------
* Use fallback commands for base image mounting if the normal one fails
* Add multifile option to Volume to control whether multifile argument passing should be attempted
* Fix error in backwards compatibility of mount_partitions
* Copy the label of a volume to the last mountpoint if it looks like a mountpoint

1.2.5 (2014-01-07)
------------------
* Ability to automatically detect the mountpoint based on files in the filesystem

1.2.4 (2013-12-16)
------------------
* Partition is now Volume
* Store the volume flag (alloc, unalloc, meta)

1.2.3 (2013-12-10)
------------------
* Add support for pretty mount point names

1.2.2 (2013-12-09)
------------------
* Fix issue where 'extended' is detected as ext (again)

1.2.1 (2013-12-09)
------------------
* Fix issue where 'extended' is detected as ext
* ImagePartition is now Volume

1.2.0 (2013-12-05)
------------------
* ImagePartition is now responsible for mounting and obtaining its stats, and detecting lvm volumes
* LVM partitions are now mounted using this new mount method
* Utilize the partition size for disk size, which is more reliable
* Renamed ImagePartition to Volume (no backwards compatibility is provided)
* Add unknown mount type, for use with :option:`--fstype`, which mounts without knowing anything
* Support mounting a directory containing \*.001/\*.E01 files

1.1.2 (2013-12-05)
------------------
* Resolve bug with respect to determining free loopback device

1.1.1 (2013-12-04)
------------------
* Improve :option:`--clean` by showing the commands to be executed beforehand

1.1.0 (2013-12-04)
------------------
* Do not add sudo to internal commands anymore
* :option:`--loopback` is removed, detects it automatically now
* :option:`--clean` is added; will remove all traces of an unsuccessful previous run

1.0.4 (2013-12-03)
------------------
* Add the any vstype
* Fix some errors in the ``mount_images`` script

1.0.3 (2013-12-02)
------------------
* Support forcing the fstype
* Improved LVM support
* Added some warnings to CLI

1.0.2 (2013-11-28)
------------------
* Improved NTFS support

1.0.1 (2013-11-28)
------------------
* ``command_exists`` now works properly

1.0.0 (2013-11-28)
------------------
* Now includes proper setup.py and versioning
* Add support for reconstructing the filesystem using bindmounts
* More reliable use of fsstat
* Overhauled Python API with more transparency and less CLI requirements

  * Store yielded information in a ImagePartition
  * Remove dependency on args and add them to the class explicitly
  * Do not depend on user interaction or CLI output in ImageParser or util, but do CLI in ``__main__``

* Support for LVM
* Support for ewfmount
* Retrieve stats more reliably
* New CLI arguments:

  * Colored output with :option:`--color`
  * Wait for warnings with :option:`--wait`
  * Support for automatic method with ``--method=auto``
  * Specify custom mount dir with :option:`--mountdir`
  * Specify explicit volume system type with :option:`--vstype`
  * Specify explicit file system type with :option:`--fstype`
  * Specify loopback device with :option:`--loopback` (required by LVM support)
