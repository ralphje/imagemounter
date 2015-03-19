imagemounter
============

imagemounter is a command-line utility and Python package to ease the mounting and unmounting of EnCase, Affuse and dd
disk images. It supports mounting disk images using xmount (with optional RW cache), affuse and ewfmount;
detecting DOS, BSD, Sun, Mac and GPT volume systems; mounting Ext, XFS, UFS, LUKS and NTFS volumes; detecting (nested)
LVM volume systems and mounting its subvolumes; and reconstructing RAID arrays.

In its default mode, imagemounter will try to start mounting the base image on a temporary mount point,
detect the volume system and then mount each volume seperately. If it fails finding a volume system,
it will try to mount the entire image as a whole if it succeeds in detecting what it actually is.

This package supports Python 2.6 and 2.7, and Python 3.2+. Versions before 1.5.0 depended on pytsk3, but 1.5.0
introduced the option to use the result of the `mmls` command instead.

Documentation
-------------
Full documentation of this project is available from http://imagemounter.readthedocs.org/ or in the `docs/` directory.

Installation
------------
Just perform the following commands for a full install, including all optional dependencies:

    apt-get install python-setuptools xmount ewf-tools afflib-tools sleuthkit lvm2 mdadm cryptsetup libmagic
    pip install imagemounter

### Python packages
This package does not require other packages, though _termcolor_ is recommended and _pytsk3_ is needed if you wish to
use this package for volume detection.

Important notes
---------------
Not all combinations of file and volume systems have been tested. If you encounter an issue, please try to change some
of your arguments first, before creating a new GitHub issue.

Please note that many Linux based operating systems will try to mount LVMs for you. Although imagemounter tries to
circumvent this automation, if you are unable to properly unmount, you should try to unmount through the interface of
your OS first. Another useful command is `vgchange -a n` to disable all LVMs currently active (only use if you are not
using a LVM for your own OS!).

With `imount --clear` you can clear MOST temporary files and mounts, though this will not clean everything. If you used
`--pretty` this tool can't do anything for you. It is therefore recommended to first try and mount your image without
`--pretty`, to allow you to easily clean up if something crashes.
