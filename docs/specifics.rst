================================
File and volume system specifics
================================

This section contains specifics on different file systems and volume systems supported by imagemounter. This section is not complete and does not cover every edge case. You are invited to amend this section with additional details.

File systems
============

ext
---
ext2, ext3 and ext4 are all supported by imagemounter. All mounts use the ext4 drivers, allowing us to specify the ``noload`` argument to the mount subsystem.

UFS
---
Supported is UFS2, as we explicitly pass in the UFS2 driver type in the mount call. This may result in some UFS volumes not mounting. There is currently no workaround for that.

Normally, a volume can be detected as both a UFS volume, as well as a BSD partition table. When the former happens, it may appear as if there is only a single volume, as this hides the other UFS volumes. Although detections have been amended for this, it is important to note that you can explicitly override detection using :option:`--fstypes` if detection fails for some reason.

(See BSD volume system below for more information.)

Depending on your OS, you may need to run ``modprobe ufs`` to enable UFS support in your kernel.

NTFS
----
For mounting NTFS, you may need the *ntfs-3g* package. The ``show_sys_files`` option is enabled by default.

This file system type may (accidentally) be detected when a BDE volume should be used instead.

HFS / HFS+
----------
No additional details.

LUKS
----
For mounting LUKS volumes, the :command:`cryptsetup` command is used. At this point, it is not possible to specify more options to the cryptsetup subsystem. To specify keys, use :option:`--keys`. The following values are accepted::

    p:passphrase
    f:key-file
    m:master-key-file

Note that you can't provide multiple keys using a single --keys argument. Repeat the argument to accomplish this, e.g. ``--keys 0=p:passphrase --keys 1=p:passphrase``.

To determine whether a volume is a LUKS volume, ``cryptsetup isLuks`` is called. This method should return true; if it doesn't, imagemounter will also not be able to mount the volume. The next step is to create a loopback device that is used to call ``cryptsetup luksOpen <device> <name>``, where name is of the form ``image_mounter_luks_<number>``. Additional details of the volume are extracted by using ``cryptsetup status``. The actual dd image of the volume is mounted in ``/dev/mapper/<name>`` by the OS.

The LUKS volume will get a subvolume at index 0 with the file system description ``LUKS Volume``. When this volume is a LVM volume that is not be properly recognized by imagemounter, you could use something like the following to amend this::

    imount image.E01 --fstypes=1=luks,1.0=lvm,1.0.0=ext --keys=1=p:passphrase

LUKS volumes are automatically unmounted by ending the script normally, but can't be unmounted by :option:`--unmount`.

The LUKS volume type may not be automatically detected in some cases.

BDE (Bitlocker)
---------------
Bitlocker Drive Encrypted volumes are mounted using the :command:`bdemount` command. imagemounter allows you to provide the crypto material to the command using :option:`--keys`. Examples of valid commands are::

    imount image.E01 --fstypes=2=bde --keys=2=p:passphrase
    imount image.E01 --fstypes=2=bde --keys=2=r:recovery_password

See the manpage for :command:`bdemount` for all valid arguments that can be passed to the subsystem (crypto material is provided by replacing ``<key>:<value>`` with ``-<key> <value>``).

The BDE volume will get a subvolume at index 0 with the file system description ``BDE Volume``. imagemounter should normally correctly detect this subvolume to be a NTFS volume.

BDE volumes are automatically unmounted by ending the script normally, but in some cases may not be properly unmounted by :option:`--unmount`.

The BDE volume type may not be properly recognized and may instead by recognized as NTFS volume. You can override this by explicitly stating the volume type as in the examples above.

LVM
---
LVM systems host multiple volumes inside a single volume. imagemounter is able to detect these volumes on most occassions, though it may not always be possible to detect the file system type of the volumes inside the LVM.

Mounting an LVM is done by mounting the volume to a loopback device and running ``lvm pvscan``. This should return a list of all LVMs on the system, but by matching the mount point of the base image, the scirpt should be able to identify the volume group name. This name is then used to enable the LVM by running ``vgchange -a y <name>``. Using ``lvdisplay <name>``, the volumes inside the volume group are extracted. The volume themselves are found at the LV Path provided by this command.

Volumes inside a LVM are given the FS description ``Logical Volume``. The file system types should be recognized properly by the detection methods, and otherwise ``unknown`` should work, but otherwise you could explicitly specify the file system type as follows::

    imount image.E01 --fstypes=1=lvm,1.0=ext

Please note that many Linux based operating systems will try to mount LVMs for you. Although imagemounter tries to circumvent this automation, if you are unable to properly unmount, you should try to unmount through the interface of your OS first. Another useful command is ``vgchange -a n`` to disable all LVMs currently active (only use if you are not using a LVM for your own OS!).

Unmounting LVMs is supported both by properly closing from the script as well as by using :option:`--unmount`

Linux Software RAID
-------------------
Linux RAID volume support is provided by the ``mdadm`` command. A volume is added to a RAID array incrementally; the ``mdadm`` command is responsible for adding the volume to the correct array. The location of the RAID array is captured by imagemounter so it can be unmounted again. A subvolume will be added with the description ``RAID volume`` at index 0.

If the RAID volume can not be started directly after adding the volume, mounting will have succeeded, but the mountpoint will not be available yet. When another volume is added to the same RAID array, it will get the same (identical) subvolume as the original RAID volume. You should not mount it again. ``init`` will take care of both cases for you.

.. warning::

   If, for any reason, you have multiple RAID volumes in the same RAID array, unmounting one of the volumes will also immediately unmount all other RAID volumes in the same array. Because of this, you should ensure that you keep all RAID volumes mounted until you are done building and examining a specific array.

RAID volumes are sometimes correctly detected, but there are also cases where the volume appears to *successfully* mount as another volume type. You should be very careful with this.

.. note::

   A disk leveraging full disk RAID can be mounted as a single volume with the RAID filesystem type.

XFS
---
XFS is supported through the *xfsprogs* package.

ISO (ISO9660)
-------------
No additional details.

UDF
---
No additional details.

FAT
---
FAT volumes, independent of type, are mounted through the VFAT driver.

exFAT
-----
exFAT volumes are mounted by teh exFAT driver. Note that exFAT volumes are sometimes recognized as NTFS volumes.

Another quirk may be that parted recognizes a single exFAT volume as a DOS partition table with some free space (also see `this comment <https://github.com/ralphje/imagemounter/pull/18/files/bcfdc26b954c4831e93a1afd0a2b7763de851328#r125325626>`_). Use another detection method or an explicit :option:`--single` to amend this.

VMFS
----
VMFS is supported through the *vmfs-tools* package. Mounting is performed by finding a loopback device and using the ``vmfs-fuse`` command to mount this loopback on the mountpoint.

SquashFS
--------
SquashFS is supported through the *squashfs-tools* package.

JFFS2
-----
JFFS2 is supported through the *mtd-tools* package. JFFS2 is sometimes used by BIOS images and the like.

The following commands are executed to open a JFFS2 image, where ``<size>`` is given a buffer of 1.2 times the size of the volume::

    modprobe -v mtd
    modprobe -v jffs2
    modprobe -v mtdram total_size=<size> erase_size=256
    modprobe -v mtdblock
    dd if=<path> of=/dev/mtd0
    mount -t jffs2 /dev/mtdblock0 <mountpoint>

.. warning::

   This filesystem type may not work while mounting multiple images of the same type at the same time.

Unmounting for this filesystem type is not fully supported.

CramFS
------
No additional details.

Minix
-----
No additional details.

Dir
---
The dir filesystem type is not an actual mount type, but is used by imagemounter to indicate directories. This can be used in conjunction with the AVFS mount method, but basically just symlinks a directory to the mount location. It is provided for abstraction purposes.

Unknown
-------
The unknown filesystem type is not an actual mount type, but used by imagemounter to indicate that the volume should be mounted without specifying the volume type. This is less specific and does not work in most cases (since it lacks the ability to provide additional options to the mount subsystem) but may result in the volume actually being able to be used.

The unknown filesystem type is used as fallback by default, and is for instance used if no specific volume type is provided by any of the detection methods other than 'Linux'. If you wish to override this default, and choose skipping mounting instead, you can also use the ``none`` filesystem type::

    imount image.dd --fstypes=?=none


Volume systems
==============

DOS (MBR)
---------
In some cases, the DOS volume system is recognized as either a DOS or a GPT volume system. This appears to be a bug in The Sleuth Kit used by some detection methods. imagemounter works around this by choosing in this case for the GPT volume system and will log a warning. In the case that this is not the right choice, you must use :option:`--vstype` to explicitly provide the correct volume system.

In the case you have picked the wrong volume system, you can easily spot this. If you see ``GPT Safety Partition`` popping up, you should have chosen GPT.

GPT
---
See the DOS/MBR volume system.

BSD
---
The BSD volume system (BSD disklabel) is commonly used in conjunction with UFS.

BSD volume c (BSD disk label uses letters to indicate the volumes, imagemounter will number this as volume 3) may appear to contain the entire volume set, and have the same offset as UFS volume a. The correct volume is volume a, and you should skip volume c. This is currently not fixed by imagemounter.

Sun
---
No additional details.

MAC
---
No additional details.

Detect
------
Lets the subsystem automatically decide the correct volume system type.
