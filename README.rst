============
imagemounter
============

imagemounter is a command-line utility and Python package to ease the mounting and unmounting of EnCase, Affuse, vmdk
and dd disk images (and other formats supported by supported tools). It supports mounting disk images using xmount (with
optional RW cache), affuse, ewfmount and vmware-mount; detecting DOS, BSD, Sun, Mac and GPT volume systems; mounting
FAT, Ext, XFS UFS, HFS+, LUKS and NTFS volumes, in addition to some less known filesystems; detecting (nested) LVM
volume systems and mounting its subvolumes; and reconstructing RAID arrays.

In its default mode, imagemounter will try to start mounting the base image on a temporary mount point,
detect the volume system and then mount each volume seperately. If it fails finding a volume system,
it will try to mount the entire image as a whole if it succeeds in detecting what it actually is.

This package supports Python 2.7 and Python 3.2+.

Documentation
=============
Full documentation of this project is available from http://imagemounter.readthedocs.org/ or in the ``docs/`` directory.

Installation
============
Just perform the following commands for a full install, including all optional dependencies::

    apt-get install python-setuptools xmount ewf-tools afflib-tools sleuthkit lvm2 mdadm cryptsetup libmagic1 avfs disktype squashfs-tools mtd-tools vmfs-tools
    pip install imagemounter

You can install ``vmware-mount`` by installing VMware Workstation on your system.

Use ``imount --check`` to verify which packages are (not) installed.

Python packages
---------------
This package does not require other packages, though ``termcolor`` is recommended and ``pytsk3`` is needed if you wish to
use this package for volume detection.

Important notes
===============
Not all combinations of file and volume systems have been tested. If you encounter an issue, please try to change some
of your arguments first, before creating a new GitHub issue.

Please note that many Linux based operating systems will try to mount LVMs for you. Although imagemounter tries to
circumvent this automation, if you are unable to properly unmount, you should try to unmount through the interface of
your OS first. Another useful command is ``vgchange -a n`` to disable all LVMs currently active (only use if you are not
using a LVM for your own OS!).
