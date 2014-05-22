Command-line usage
==================

One of the core functionalities of :mod:`imagemounter` is  the command-line utility :command:`imount` that eases the mounting and unmounting of different types of disks and volumes. In its most basic form, the utility accepts a positional argument pointing to a disk image, disk or volume, e.g.::

    imount disk.E01

Multiple files can be passed to this command, allowing the mounting of volume systems that span multiple disks, which can be useful for those wishing to reconstruct a system that entailed multiple disks or for reconstructing RAID arrays.

By default, :command:`imount` will mount each single volume in :file:`/tmp` and wait until you confirm an unmount operation. Common usage is therefore to keep :command:`imount` running in a separate window and perform other operations in a second window.

Arguments
---------

The :command:`imount` utility requires one (or more) positional arguments and offers the ability to pass several optional arguments.

.. cmdoption:: <image> [<image> ...]

   The positional argument(s) should provide the path(s) to the disk images you want to mount. Many different formats are supported, including the EnCase evidence format, split dd files, mounted hard drives, etc. In the case of split files, you can refer to the folder containing these files.

   If you specify more than one file, all files are considered to be part of the same originating system, which is relevant for the :option:`--reconstruct` command-line option.

Arguments that immediately exit
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Some useful facilities.

.. cmdoption:: --help
               -h

   Shows a help message and exits.

.. cmdoption:: --version

   Shows the current version and exits.

.. cmdoption:: --clean

   Option that will try to identify leftover files from previous :command:`imount` executions and try to delete these. This will, for instance, clean leftover :file:`/tmp/im_{...}` mounts and mountpoints. This command will allow you to review the actions that will be taken before they are done.

CLI behaviour
^^^^^^^^^^^^^
The next four command-line options alter the behaviour of the :command:`imount` utility, but does not affect the behaviour of the underlying :mod:`imagemounter` module.

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
This command-line option enables an additional and useful feature.

.. cmdoption:: --reconstruct
               -r

   Attempts to reconstruct the full filesystem tree by identifying the last mountpoint of each identified volume and bindmounting this in the previous root directory. For instance, if volumes have previously been mounted at :file:`/` , :file:`/var` and :file:`/home` ; :file:`/var` and :file:`/home` will be bind-mounted in :file:`/` , providing you with a single filesystem tree in the mount location of :file:`/` that is easily traversible.

   This only works with Linux-based filesystems and only if :file:`/` can be identified.

   Implies :option:`--stats`.

Mount behaviour
^^^^^^^^^^^^^^^
These arguments alter some pieces of the mount behaviour of :mod:`imagemounter`, mostly to ease your work.

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
While :mod:`imagemounter` will try to automatically detect as much as possible, there are some cases where you may wish to override the automatically detected options. You can specify which detection methods should be used and override the volume system and file system types if needed.

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

.. cmdoption:: --fstypes

   Allows the specification of filesystem type for each volume separately. You can use subvolumes, examples including::

       1=ntfs
       2=luks,2.0=lvm,2.0.1=ext


Advanced toggles
^^^^^^^^^^^^^^^^
:command:`imount` has some facilities that automatically detect some types of disks and volumes. However, these facilities may sometimes fail and can be disabled if needed.

.. cmdoption:: --stats
               --no-stats

   With stats rerieval is enabled, additional volume information is obtained from the :command:`fsstat` command. This could possibly slow down mounting and may cause random issues such as partitions being unreadable. However, this additional information will probably include some useful information related to the volume system and is required for commands such as :option:`--reconstruct`.

   Stats retrieval is enabled by default, but :option:`--stats` can be used to override :option:`--no-stats`.

.. cmdoption:: --raid
               --no-raid

   By default, a detection is ran to detect whether the volume is part of a (former) RAID array. You can disable the RAID check with :option:`--no-raid`. If you provide both :option:`--raid` and :option:`--no-raid`, :option:`raid` wins.

.. cmdoption:: --single
               --no-single

   :command:`imount` will, by default, try to detect whether the disk that is being mounted, contains an entire volume system, or only a single volume. If you know your volumes are not single volumes, or you know they are, use :option:`--no-single` and :option:`--single` respectively.

   Where :option:`--single` forces the mounting of the disk as a single volume, :option:`--no-single` will prevent the identification of the disk as a single volume if no volume system is found.