imagemounter
============

imagemounter is a command-line utility and Python package to ease the mounting and unmounting of EnCase, Affuse and dd
disk images. It supports mounting disk images using xmount (with optional RW cache), affuse and ewfmount;
detecting DOS, BSD, Sun, Mac and GPT volume systems; mounting Ext, UFS, LUKS and NTFS volumes; detecting (nested) LVM
volume systems and mounting its subvolumes; and reconstructing RAID arrays.

In its default mode, imagemounter will try to start mounting the base image on a temporary mount point,
detect the volume system and then mount each volume seperately. If it fails finding a volume system,
it will try to mount the entire image as a whole if it succeeds in detecting what it actually is.

This package currently only supports Python 2.6 and 2.7. Although this module in fact should be ready for Python 3.2+,
it depends on pytsk3, which currently does not support Python 3.

Installation
------------
Just perform the following commands for a full install, including all optional dependencies (but see the note about Ubuntu 13.10 below):

    apt-get install python-setuptools python-dev libtsk-dev xmount ewf-tools afflib-tools sleuthkit lvm2 mdadm
    pip install imagemounter

### Python packages
This package depends on two other packages. 

- The _termcolor_ package is available from PyPI and is easily installed using tools such as `pip` or `easy_install`. 
- The _pytsk3_ package requires some additional packages to be installed: `python-dev` and `libtsk-dev`. For compilation, the `build-essential` package from your distribution is also required. After that, you can easily install the `pytsk3` package from PyPI (pip requires the --pre flag to allow installing the package).

### Other dependencies
This package highly depends on other utilities to be present on your system. For a full installation, you require the following tools:

- Mount tools
  - `xmount`
  - `ewfmount`, part of ewf-tools package, see note below
  - `affuse`, part of afflib-tools package
- Statistics, e.g. last mountpoint of volumes
  - `fsstat`, part of sleuthkit package
- LVM arrays
  - `lvm` et al, all part of lvm2 package
- RAID volumes
  - `mdadm`

#### ewfmount on Ubuntu 13.10
Due to a bug with ewf-tools in Ubuntu <=13.10, it may be that ewfmount is not properly provided. This bug will be resolved in Ubuntu 14.04. If you are using Ubuntu 13.10, you can install ewf-tools with ewfmount as follows:

1. Download a recent build of ewf-tools from https://launchpad.net/ubuntu/+source/libewf/20130416-2ubuntu1 (choose your arch under 'Builds' and download all deb files under 'Built files')
2. Execute `sudo apt-get install libbfio1`
3. Execute `sudo dpkg -i ewf-tools_* libewf2_*`


Commands and execution order
----------------------------
imagemounter utilizes many command line utilities to perform its actions. It does not actually do a lot by itself,
although it manages currently mounted sytems and provides the correct unmounting order. To gather a general idea of
what the tool does, the following is a non-exhaustive list of the commands used in what order in the default mode.

- `xmount`, `affuse` or `ewfmount` to mount the image
- `mdadm` to detect whether this image is part of a RAID array, and if so:
  - `losetup` to mount the image to a loopback device
  - `mdadm` to add the image to the RAID array
- Python equivalent of `mmls` to detect volumes (if none found, the image is mounted as one volume)
- `fsstat` to gather additional information about the volume
- `mount` to actually mount the volumes, or, in the case of a LVM:
  - `losetup` to mount the volume to a loopback device
  - `lvm pvscan` to scan for LVM systems
  - `vgchange` to activate the LVM system
  - `lvdisplay` to detect volumes (and again perform `fsstat` and `mount`, etc)
  or in the case of a LUKS volume:
  - `losetup` to mount the volume to a loopback device
  - `cryptsetup luksOpen` to open the volume

The same is performed in reverse (ish) order to unmount the image.

CLI usage
---------
In its most basic form, the installed command line utility (`imount`) accepts a positional argument pointing to
the disk image, e.g.:

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

By default, information about volumes is provided by `fsstat`. This may, however,
sometimes cause issues. You can disable this additional information gathering with `--no-stats`.

You can disable the RAID check with `--no-raid`. If you know your volumes are not single volumes, or you know they are,
use `--no-single` and `--single` respectively.

Some volumes may not be automatically detected. If you know the type, you could use --fstypes to specify for each volume
index the specific type, e.g. --fstypes=6=luks,6.0=lvm,6.0.0=ext. With --fsfallback you can specify a fallback if no
type was detected, e.g. --fstypes=ext (use unknown to just mount and see what happens). --fsforce can be used to
override automatic detection (--fstypes is not overriden).

Use `imount --help` to discover more options.

Python package
--------------
The Python package consists of three main parts:

- The ImageParser, maintaining a list of Disks, providing several methods that are carried out on all disks (e.g.
  mount) and reconstruct.
- The Disk, which represents a single disk iamge and can be mounted, added to RAID,
  and detect and maintain volumes. It is also responsible for maintaining the write cache.
- The Volume, which can detect its own type and fill its stats, can be mounted, and detect LVM (sub)volumes.

All three classes maintain an init() method that yields the volumes below it. You should call clean on the parser if
you are done; you may also unmount separate volumes or disks, which will also unmount all volumes below it. Warning:
unmounting one of the RAID volumes in a RAID array, causes the entire array to be unmounted.

The constructor of ImageParser allows most of the command-line arguments to be passed (note that e.g. --no-raid is
passed as raid=False, and that arguments such as --color are not known), with the notable exception of --single and
--no-single, which distinguishes between disk.mount_* methods.

Basic usage:

    >>> import imagemounter
    >>> parser = imagemounter.ImageParser(["disk.E01"])  # similar arguments as imount are possible
    >>> for volume in parser.init():
    ...     print volume.label, bool(volume.mountpoint)
    ...     volume.unmount()
    ...
    None False
    None False
    None False
    / True
    /var True
    >>> parser.clean()
    True

`imount` utilizes the same API, so you should be able to figure it out yourself.