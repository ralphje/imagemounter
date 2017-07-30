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

.. cmdoption:: --check

   Shows which third-party utilities you have installed for a correct functioning of imagemounter.

.. cmdoption:: --unmount
               -u

   Option that will try to identify leftover files from previous :command:`imount` executions and try to delete these. This will, for instance, clean leftover :file:`/tmp/im_{...}` mounts and mountpoints. This command will allow you to review the actions that will be taken before they are done.

   Can be combined with :option:`--casename`, :option:`--mountdir` and :option:`--pretty` to specify which mount points to delete.

CLI behaviour
^^^^^^^^^^^^^
The next four command-line options alter the behaviour of the :command:`imount` utility, but does not affect the behaviour of the underlying :mod:`imagemounter` module.

.. cmdoption:: --wait
               -w

   Pauses the execution of the program on all warnings.

.. cmdoption:: --keep
               -k

   Skips the unmounting at the end of the program.

.. cmdoption:: --no-interaction

   Never ask for input from the user, implies :option:`--keep`.

.. cmdoption:: --only-mount

   Comma-separated list of volume indexes you want to mount. Other volumes are skipped.

.. cmdoption:: --skip

   Comma-separated list of volume indexes you do not want to mount.

.. cmdoption:: --verbose
               -v

   Show verbose output. Repeat for more verbosity (up to 4).

.. cmdoption:: --color
               --no-color

   Force toggle colorizing the output. Verbose message will be colored blue, for instance. Requires the :mod:`termcolor` package.


Additional features
^^^^^^^^^^^^^^^^^^^
This command-line option enables an additional and useful feature.

.. cmdoption:: --reconstruct
               -r

   Attempts to reconstruct the full filesystem tree by identifying the last mountpoint of each identified volume and bindmounting this in the previous root directory. For instance, if volumes have previously been mounted at :file:`/` , :file:`/var` and :file:`/home` ; :file:`/var` and :file:`/home` will be bind-mounted in :file:`/` , providing you with a single filesystem tree in the mount location of :file:`/` that is easily traversible.

   This only works with Linux-based filesystems and only if :file:`/` can be identified.

   Implies :option:`--stats`.

.. cmdoption:: --carve

   Carves the filesystem for missing files.

.. cmdoption:: --vshadow

   Also mounts volume shadow copies

Mount behaviour
^^^^^^^^^^^^^^^
These arguments alter some pieces of the mount behaviour of :mod:`imagemounter`, mostly to ease your work.

.. cmdoption:: --mountdir <directory>
               -md <directory>

   Specifies the directory to place volume mounts. Defaults to a temporary directory.

.. cmdoption:: --pretty
               -p

   Uses pretty names for volume mount points. This is useful in combination with :option:`--mountdir`, but you should be careful using this option. It does not provide a fallback when the mount point is not available or other issues arise. It can also not be cleaned with :option:`--clean`.

.. cmdoption:: --casename
               -cn

   Use to specify the case name, which is used in pretty mounts, but also for the location of the mountdir. Useful if you want to be able to identify the mountpoints later.

.. cmdoption:: --read-write
               -rw

   Will use read-write mounts. Written data will be stored using a local write cache.

   Implies :option:`--method xmount`.

Advanced options
^^^^^^^^^^^^^^^^
While :mod:`imagemounter` will try to automatically detect as much as possible, there are some cases where you may wish to override the automatically detected options. You can specify which detection methods should be used and override the volume system and file system types if needed.

.. cmdoption:: --disk-mounter <method>
               -m <method>

   Specifies the method to use to mount the base image(s). Defaults to automatic detection, though different methods deliver different results. Available options are `xmount`, `affuse` and `ewfmount` (defaulting to `auto`).

   If you provide `dummy`, the base is not mounted but used directly.

.. cmdoption:: --volume-detector <method>
               -d <method>

   Specifies the volume detection method. Available options are `pytsk3`, `mmls`, `parted` and `auto`, which is the default. Though `pytsk3` and `mmls` should in principle deliver identical results, `pytsk3` can be considered more reliable as this uses the C API of The Sleuth Kit (TSK). However, it also requires :mod:`pytsk3` to be installed, which is not possible with Py3K.

.. cmdoption:: --vstypes <types>

   Specifies the type of the volume system, defaulting to `detect`. However, detection may not always succeed and valid options are `dos`, `bsd`, `sun`, `mac`, `gpt` and `dbfiller`, though the exact available options depend on the detection method and installed modules on the operating system.

.. cmdoption:: --fstypes <types>

   Specifies the filesystem of a volume to use. Available options include `ext`, `ufs`, `ntfs`, `luks`, `lvm` and `unknown`, with the latter simply mounting the volume without specifying type. See the command-line help for all available volume types.

   Filesystem types are specified for each volume separately. You can use subvolumes, examples including::

       1=ntfs
       2=luks,2.0=lvm,2.0.1=ext

   If you wish to specify a fallback to use if automatic detection fails, you can use the special question mark (?) volume index. If you wish to override automatic detection at all for all unspecified volumes, you can use the asterisk (*) volume type. There is no point is specifying both a question mark and an asterisk.

.. cmdoption:: --keys <keys>

   Allows the specification of key information for each volume separately. This is similar to :option:`--fstypes`, except that you can only specify one key per argument (i.e. a comma is not interpreted as special). The format of the specifc value depends on the volume type:

   For BDE, you can use a single letter, followed by a colon, followed by the value. This leads to the following accepted formats, similar to how the :command:`bdemount` command interprets input::

        k:full volume encryption and tweak key
        p:passphrase
        r:recovery password
        s:file to startup key (.bek)

   For LUKS, you can use a similar format::

        p:passphrase
        f:key-file
        m:master-key-file


.. cmdoption:: --lazy-unmount

   Enables to unmount the volumes and disk lazily when the direct unmounting of the volumes fails.

Advanced toggles
^^^^^^^^^^^^^^^^
:command:`imount` has some facilities that automatically detect some types of disks and volumes. However, these facilities may sometimes fail and can be disabled if needed.

.. cmdoption:: --single
               --no-single

   :command:`imount` will, by default, try to detect whether the disk that is being mounted, contains an entire volume system, or only a single volume. If you know your volumes are not single volumes, or you know they are, use :option:`--no-single` and :option:`--single` respectively.

   Where :option:`--single` forces the mounting of the disk as a single volume, :option:`--no-single` will prevent the identification of the disk as a single volume if no volume system is found.
