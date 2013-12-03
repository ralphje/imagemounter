imagemounter
============

imagemounter is a command-line utility and Python package to ease mounting and unmounting EnCase and dd disk images. It supports mounting disk images using xmount (with RW cache), affuse and ewfmount, and Ext, UFS, NTFS and LVM partitions contained within.

imagemounter will start mounting the base image on a temporary mount point and then mount each partition contained within separately.

Installation
------------
Basic installation is simple: use `python setup.py install` to install the Python package and CLI tool. However, there are some dependencies to be resolved; most notably two Python packages: pytsk3 and termcolor. Additionally, some command-line utilities are required, including xmount and fsstat. Run `install/install.sh` as root to automatically install dependencies and this utility.

Note: ewf-tools and afflib-tools are very useful, but not installed by the installation script. These packages provide affuse and ewfmount. If you do not install these packages, xmount is used by default to mount your disk images, with varying results. 

Installing ewf-tools does not guarantee that you obtain ewfmount on Ubuntu. You may want to get a recent package from https://launchpad.net/ubuntu/+source/libewf, 20130416-2ubuntu1 is known to provide ewfmount.

CLI usage
---------
In its most basic form, the installed command line utility (`mount_images`) accepts a positional argument pointing to the disk image, e.g.:

    mount_images disk.E01
    
You can pass multiple disks to the same command. This has the same effect as running `mount_images` multiple times.

The utility will by default mount each partition in /tmp/ and ask you whether you want to keep it mounted, or want to unmount this. After the entire image has been processed, all partitions must be unmounted.

If you wish to reconstruct an image with UFS/Ext partition with known former mountpoints, you can reconstruct the image with its former mountpoints using `--reconstruct`. For instance, if you have partitions previously mounted at /, /var and /home, /var and /home will be bind-mounted in /, providing you with a single filesystem to traverse.

More information about the partitions is provided by `--stats`. This uses `ffstat` to obtain more information about each partition. However, this may cause some random issues and is therefore disabled by default.

Use `mount_images --help` to discover more options.

Python package
--------------
Basic usage:

    >>> import imagemounter
    >>> parser = imagemounter.ImageParser("disk.E01", addsudo=True, stats=True)
    >>> parser.mount_base()
    True
    >>> for partition in parser.mount_partitions():
    ...     print partition.label, bool(partition.mountpoint)
    ...     partition.unmount()
    ...
    None False
    None False
    None False
    / True
    /var True
    >>> parser.clean()
    True

See the source for more information.