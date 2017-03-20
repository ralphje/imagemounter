.. imagemounter documentation master file, created by
   sphinx-quickstart on Mon May 19 14:34:55 2014.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

imagemounter
============
imagemounter is a command-line utility and Python package to ease the mounting and unmounting of EnCase, Affuse, vmdk
and dd disk images (and other formats supported by supported tools). It supports mounting disk images using xmount (with
optional RW cache), affuse, ewfmount, vmware-mount and qemu-nbd; detecting DOS, BSD, Sun, Mac and GPT volume systems;
mounting FAT, Ext, XFS UFS, HFS+, LUKS and NTFS volumes, in addition to some less known filesystems; detecting (nested)
LVM volume systems and mounting its subvolumes; and reconstructing Linux Software RAID arrays.

In its default mode, imagemounter will try to start mounting the base image on a temporary mount point,
detect the volume system and then mount each volume seperately. If it fails finding a volume system,
it will try to mount the entire image as a whole if it succeeds in detecting what it actually is.

.. note::
   Not all combinations of file and volume systems have been tested. If you encounter an issue, please try to change
   some of your arguments first, before creating a new GitHub issue.

.. warning::
   Mounting disks and volumes from unknown sources may pose an important security risk (especially since you probably
   need to run imagemounter as root).

Contents
--------

.. toctree::
   :maxdepth: 2

   installation
   commandline
   python
   specifics
   changelog
