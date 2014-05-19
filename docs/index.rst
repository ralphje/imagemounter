.. imagemounter documentation master file, created by
   sphinx-quickstart on Mon May 19 14:34:55 2014.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

imagemounter
============
imagemounter is a command-line utility and Python package to ease the mounting and unmounting of EnCase, Affuse and dd
disk images. It supports mounting disk images using xmount (with optional RW cache), affuse and ewfmount;
detecting DOS, BSD, Sun, Mac and GPT volume systems; mounting Ext, UFS, LUKS and NTFS volumes; detecting (nested) LVM
volume systems and mounting its subvolumes; and reconstructing RAID arrays.

In its default mode, imagemounter will try to start mounting the base image on a temporary mount point,
detect the volume system and then mount each volume seperately. If it fails finding a volume system,
it will try to mount the entire image as a whole if it succeeds in detecting what it actually is.

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

Contents
--------

.. toctree::
   :maxdepth: 2

   installation
   commandline

