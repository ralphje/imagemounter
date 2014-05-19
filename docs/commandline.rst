Command-line usage
==================

In its most basic form, the installed command line utility (`imount`) accepts a positional argument pointing to
the disk image, e.g.::

    imount disk.E01

You can pass multiple disks to the same command. This allows the command to mount across multiple disks,
which is useful when you wish to reconstruct volumes split across multiple disks, or for reconstructing a RAID array.

imount will by default mount each volume in /tmp/ and ask you whether you want to keep it mounted, or want to unmount
this. After the entire image has been processed, all volumes must be unmounted. You can change the default mount point
with `--mountdir`. You can prettify the automatically generated name with `--pretty`.

You can use `--keep` to not unmount the volume after the program stops. However, you are recommended to not use this in
combination with `--mountdir` or `--pretty`, as `--clean` can not detect volumes with non-default naming.

If you wish to reconstruct an image with UFS/Ext volumes with known former mountpoints, you can reconstruct the image
with its former mountpoints using `--reconstruct`. For instance, if you have partitions previously mounted at /, /var
and /home, /var and /home will be bind-mounted in /, providing you with a single filesystem tree.





Some volumes may not be automatically detected. If you know the type, you could use --fstypes to specify for each volume
index the specific type, e.g. --fstypes=6=luks,6.0=lvm,6.0.0=ext. With --fsfallback you can specify a fallback if no
type was detected, e.g. --fstypes=ext (use unknown to just mount and see what happens). --fsforce can be used to
override automatic detection (--fstypes is not overriden).

Use ``imount --help`` to discover more options.

Arguments
---------

The :command:`imount` utility requires one (or more) positional arguments and offers the ability to pass several optional arguments.

.. cmdoption:: <image> [<image> ...]

   The positional argument(s) should provide the path(s) to the disk images you want to mount. Many different formats are supported, including the EnCase evidence format, split dd files, mounted hard drives, etc. In the case of split files, you can refer to the folder containing these files.

   If you specify more than one file, all files are considered to be part of the same originating system, which is relevant for the ``--reconstruct`` command-line option.

Arguments that immediately exit
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. cmdoption:: --help
               -h

   Shows a help message and exits.

.. cmdoption:: --version

   Shows the current version and exits.

.. cmdoption:: --clean

   Option that will try to identify leftover files from previous :command:`imount` executions and try to delete these. This will, for instance, clean leftover :file:`/tmp/im_{...}` mounts and mountpoints. This command will allow you to review the actions that will be taken before they are done.

CLI behaviour
^^^^^^^^^^^^^

.. cmdoption:: --color
               -c

   Colorizes the output. Verbose message will be colored blue, for instance. Requires the :mod:`termcolor` package.

.. cmdoption:: --wait
               -w

   Pauses the execution of the program on all warnings.

.. cmdoption:: --keep
               -k

   Skips the unmounting at the end of the program.

.. cmdoption:: --verbose
               -v

   Show verbose output

Additional features
^^^^^^^^^^^^^^^^^^^

.. cmdoption:: --reconstruct
               -r

   Attempts to reconstruct the full filesystem tree by identifying the last mountpoint of each identified volume and bindmounting this in the previous root directory. This only works with Linux-based filesystems and only if :file:`/` can be identified.

   Implies :option:`--stats`.

Mount behaviour
^^^^^^^^^^^^^^^

.. cmdoption:: --mountdir <directory>
               -md <directory>

   Specifies the directory to place volume mounts. Defaults to a temporary directory.

.. cmdoption:: --pretty
               -p

   Uses pretty names for volume mount points. This is useful in combination with :option:`--mountdir`, but you should be careful using this option. It does not provide a fallback when the mount point is not available or other issues arise. It can also not be cleaned with :option:`--clean`.

.. cmdoption:: --read-write
               -rw

   Will use read-write mounts. Written data will be stored using a local write cache.

   Implies :option:`--method xmount`.

Advanced options
^^^^^^^^^^^^^^^^

.. cmdoption:: --method <method>
               -m <method>

   Specifies the method to use to mount the base image(s). Defaults to automatic detection, though different methods deliver different results. Available options are `xmount`, `affuse` and `ewfmount` (defaulting to `auto`).

   If you provide `dummy`, the base is not mounted but used directly.

.. cmdoption:: --detection <method>
               -d <method>

   Specifies the volume detection method. Available options are `pytsk3`, `mmls` and `auto`, which is the default. Though `pytsk3` and `mmls` should in principle deliver identical results, `pytsk3` can be considered more reliable as this uses the C API of The Sleuth Kit (TSK). However, it also requires :mod:`pytsk3` to be installed, which is not possible with Py3K.

.. cmdoption:: --vstype <type>

   Specifies the type of the volume system, defaulting to `detect`. However, detection may not always succeed and valid options are `dos`, `bsd`, `sun`, `mac`, `gpt` and `dbfiller`, though the exact available options depend on the detection method and installed modules on the operating system.

.. cmdoption:: --fsfallback <type>

   Specifies a fallback option for the filesystem of a volume if automatic detection fails. Available options are `ext`, `ufs`, `ntfs`, `luks`, `lvm` and `unknown`, with the latter simply mounting the volume without specifying type.

.. cmdoption:: --fsforce

   Forces the use of the filesystem type specified with :option:`--fsfallback` for all volumes. In other words, disables the automatic filesystem detection.

.. cmdoptions:: --fstypes

   Allows the specification of filesystem type for each volume separately. You can use subvolumes, examples including::

       1=ntfs
       2=luks,2.0=lvm,2.0.1=ext


Advanced toggles
^^^^^^^^^^^^^^^^

If :option:`--stats` is enabled, additional volume information is obtained from the :command:`fsstat` command. This could possibly slow down mounting and may cause random issues such as partitions being unreadable. However, this additional information will probably include some useful information related to the volume system and is required for commands such as :option:`--reconstruct`.

.. cmdoption:: --stats
               -s

   Although stats retrieval is enabled by default, :option:`--stats` can be used to override :option:`--no-stats`.

.. cmdoption:: --no-stats
               -n

   Disables the retrieval of statistics (see :option:`--stats`)

By default, a detection is ran to detect whether the volume is part of a (former) RAID array. You can disable the RAID check with :option:`--no-raid`.

.. cmdoption:: --raid

   Enables the detection of RAID arrays, which is enabled by default (can be used to override :option:`--no-raid`).

.. cmdoption:: --no-raid

   Disables the detection of RAID arrays.

:command:`imount` will, by default, try to detect whether the disk that is being mounted, contains an entire volume system, or only a single volume. If you know your volumes are not single volumes, or you know they are, use :option:`--no-single` and :option:`--single` respectively.

.. cmdoption:: --single

   Forces the mounting of the disk as a single volume.

.. cmdoption:: --no-single

   Prevents trying to identify the disk as a single volume if no volume system is found.