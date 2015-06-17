#!/usr/bin/env python

from __future__ import print_function
from __future__ import unicode_literals

import argparse
import glob
import logging
import sys
import os

from imagemounter import _util, ImageParser, Unmounter, __version__, FILE_SYSTEM_TYPES, VOLUME_SYSTEM_TYPES

# Python 2 compatibility

try:
    input = raw_input
except NameError:
    pass


def main():
    class MyParser(argparse.ArgumentParser):
        def error(self, message):
            sys.stderr.write('error: {0}\n'.format(message))
            self.print_help()
            sys.exit(2)

    class CheckAction(argparse.Action):
        def _check_command(self, command, package="", why=""):
            if _util.command_exists(command):
                print(" INSTALLED {}".format(command))
            elif why and package:
                print(" MISSING   {:<20}needed for {}, part of the {} package".format(command, why, package))
            elif why:
                print(" MISSING   {:<20}needed for {}".format(command, why))
            elif package:
                print(" MISSING   {:<20}part of the {} package".format(command, package))
            else:
                print(" MISSING   {}".format(command))

        def _check_module(self, module, pip_name="", why=""):
            if not pip_name:
                pip_name = module

            if module == "magic" and _util.module_exists(module):
                import magic
                if hasattr(magic, 'from_filez'):
                    print(" INSTALLED {}".format(pip_name))
                else:
                    print(" ERROR     {:<20}expecting {}, found other module named magic".format(pip_name, pip_name))
            elif module != "magic" and _util.module_exists(module):
                print(" INSTALLED {}".format(pip_name))
            elif why:
                print(" MISSING   {:<20}needed for {}, install using pip".format(pip_name, why))
            else:
                print(" MISSING   {:<20}install using pip".format(pip_name, why))

        # noinspection PyShadowingNames
        def __call__(self, parser, namespace, values, option_string=None):
            print("The following commands are used by imagemounter internally. Without most commands, imagemounter "
                  "works perfectly fine, but may lack some detection or mounting capabilities.")
            print("-- Mounting base disk images (at least one required, first three recommended) --")
            self._check_command("xmount", "xmount", "several types of disk images")
            self._check_command("ewfmount", "ewf-tools", "EWF images (partially covered by xmount)")
            self._check_command("affuse", "afflib-tools", "AFF images (partially covered by xmount)")
            self._check_command("vmware-mount", why="VMWare disks")
            print("-- Detecting volumes and volume types (at least one required) --")
            self._check_command("mmls", "sleuthkit")
            self._check_module("pytsk3")
            self._check_command("parted", "parted")
            print("-- Detecting volume types (all recommended, first two highly recommended) --")
            self._check_command("fsstat", "sleuthkit")
            self._check_command("file", "libmagic1")
            self._check_module("magic", "python-magic")
            self._check_command("disktype", "disktype")
            print("-- Enhanced mounting and detecting disks (install when needed) --")
            self._check_command("mdadm", "mdadm", "RAID disks")
            self._check_command("cryptsetup", "cryptsetup", "LUKS containers")
            self._check_command("mountavfs", "avfs", "compressed disk images")
            print("-- Mounting volumes (install when needed) --")
            self._check_command("mount.xfs", "xfsprogs", "XFS volumes")
            self._check_command("mount.ntfs", "ntfs-3g", "NTFS volumes")
            self._check_command("lvm", "lvm2", "LVM volumes")
            self._check_command("vmfs-fuse", "vmfs-tools", "VMFS volumes")
            self._check_command("mount.jffs2", "mtd-tools", "JFFS2 volumes")
            self._check_command("mount.squashfs", "squashfs-tools", "SquashFS volumes")
            parser.exit()

    parser = MyParser(description='Utility to mount volumes in Encase and dd images locally.')
    parser.add_argument('images', nargs='*',
                        help='path(s) to the image(s) that you want to mount; generally just the first file (e.g. '
                             'the .E01 or .001 file) or the folder containing the files is enough in the case of '
                             'split files')

    # Special options
    parser.add_argument('--version', action='version', version=__version__, help='display version and exit')
    parser.add_argument('--check', action=CheckAction, nargs=0,
                        help='do a system check and list which tools are installed')

    # Utility specific
    parser.add_argument('-u', '--unmount', action='store_true', default=False,
                        help='try to unmount left-overs of previous imount runs; may occasionally not be able to '
                             'detect all mountpoints or detect too much mountpoints; use --casename to limit '
                             'the unmount options')
    parser.add_argument('-w', '--wait', action='store_true', default=False, help='pause on some additional warnings')
    parser.add_argument('-k', '--keep', action='store_true', default=False,
                        help='keep volumes mounted after program exits')
    parser.add_argument('--no-interaction', action='store_true', default=False,
                        help="do not ask for any user input, implies --keep")
    parser.add_argument('-v', '--verbose', action='count', default=False, help='enable verbose output')
    parser.add_argument('-c', '--color', action='store_true', default=False, help='force colorizing the output')
    parser.add_argument('--no-color', action='store_true', default=False, help='prevent colorizing the output')

    # Additional options
    parser.add_argument('-r', '--reconstruct', action='store_true', default=False,
                        help='attempt to reconstruct the full filesystem tree; implies -s and mounts all partitions '
                             'at once')
    parser.add_argument('--carve', action='store_true', default=False,
                        help='automatically carve the free space of a mounted volume for deleted files')

    # Specify options to the subsystem
    parser.add_argument('-md', '--mountdir', default=None,
                        help='specify other directory for volume mountpoints')
    parser.add_argument('-p', '--pretty', action='store_true', default=False,
                        help='use pretty names for mount points; useful in combination with --mountdir')
    parser.add_argument('-cn', '--casename', default=None,
                        help='name to add to the --mountdir, often used in conjunction with --pretty')
    parser.add_argument('-rw', '--read-write', action='store_true', default=False,
                        help='mount image read-write by creating a local write-cache file in a temp directory; '
                             'implies --method=xmount')
    parser.add_argument('-m', '--method', choices=['xmount', 'affuse', 'ewfmount', 'vmware-mount', 'avfs',
                                                   'auto', 'dummy'],
                        default='auto',
                        help='use other tool to mount the initial images; results may vary between methods and if '
                             'something doesn\'t work, try another method; dummy can be used when base should not be '
                             'mounted (default: auto)')
    parser.add_argument('-d', '--detection', choices=['pytsk3', 'mmls', 'parted', 'auto'], default='auto',
                        help='use other volume detection method; pytsk3 and mmls should provide identical results, '
                             'though pytsk3 is using the direct C API of mmls, but requires pytsk3 to be installed; '
                             'auto distinguishes between pytsk3 and mmls only '
                             '(default: auto)')
    parser.add_argument('--vstype', choices=VOLUME_SYSTEM_TYPES,
                        default="detect", help='specify type of volume system (partition table); if you don\'t know, '
                                               'use "detect" to try to detect (default: detect)')
    parser.add_argument('--fsfallback', choices=FILE_SYSTEM_TYPES, default=None,
                        help="specify fallback type of the filesystem, which is used when it could not be detected or "
                             "is unsupported; use unknown to mount without specifying type")
    parser.add_argument('--fsforce', action='store_true', default=False,
                        help="force the use of the filesystem type specified with --fsfallback for all volumes")
    parser.add_argument('--fstypes', default=None,
                        help="allows the specification of the filesystem type per volume number; format: 0.1=lvm, ...")

    # Toggles for default settings you may perhaps want to override
    parser.add_argument('--stats', action='store_true', default=False,
                        help='show limited information from fsstat, which will slow down mounting and may cause '
                             'random issues such as partitions being unreadable (default)')
    parser.add_argument('--no-stats', action='store_true', default=False,
                        help='do not show limited information from fsstat')
    parser.add_argument('--disktype', action='store_true', default=False,
                        help='use the disktype command to get even more information about the volumes (default)')
    parser.add_argument('--no-disktype', action='store_true', default=False,
                        help='do not use disktype to get more information')
    parser.add_argument('--raid', action='store_true', default=False,
                        help="try to detect whether the volume is part of a RAID array (default)")
    parser.add_argument('--no-raid', action='store_true', default=False,
                        help="prevent trying to mount the volume in a RAID array")
    parser.add_argument('--single', action='store_true', default=False,
                        help="do not try to find a volume system, but assume the image contains a single volume")
    parser.add_argument('--no-single', action='store_true', default=False,
                        help="prevent trying to mount the image as a single volume if no volume system was found")
    args = parser.parse_args()

    # Colorize the output by default if the terminal supports it
    if not args.color and args.no_color:
        args.color = False
    elif args.color:
        args.color = True
    else:
        args.color = _util.terminal_supports_color()

    if not args.color:
        # noinspection PyUnusedLocal,PyShadowingNames
        def col(s, *args, **kwargs):
            return s
    else:
        from termcolor import colored
        col = colored

    class ImageMounterFormatter(logging.Formatter):
        def format(self, record):
            msg = record.getMessage()
            if args.verbose >= 4 and record.exc_info:
                if not record.exc_text:
                    record.exc_text = self.formatException(record.exc_info)
                if msg[-1:] != "\n":
                    msg += "\n"
                msg += record.exc_text
            if record.levelno >= logging.WARNING:
                return col("[-] " + msg, 'cyan')
            elif record.levelno == logging.INFO:
                return col("[+] " + msg, 'cyan')
            elif msg.startswith('$'):
                return col("  " + msg, 'cyan')
            else:
                return col("    " + msg, 'cyan')

    # Set logging level for internal Python
    handler = logging.StreamHandler()
    handler.setFormatter(ImageMounterFormatter())
    logger = logging.getLogger("imagemounter")
    logger.setLevel({0: logging.CRITICAL, 1: logging.WARNING, 2: logging.INFO}.get(args.verbose, logging.DEBUG))
    logger.addHandler(handler)

    # Check some prerequisites
    if os.geteuid():  # Not run as root
        print(col('[!] Not running as root!', 'yellow'))

    if 'a' in __version__ or 'b' in __version__:
        print(col("Development release v{0}. Please report any bugs you encounter.".format(__version__),
                  attrs=['dark']))
        print(col("Critical bug? Use git tag to list all versions and use git checkout <version>", attrs=['dark']))

    # Always assume stats, except when --no-stats is present, and --stats is not.
    if not args.stats and args.no_stats:
        args.stats = False
    else:
        args.stats = True

    # Make args.disktype default to True
    explicit_disktype = False
    if not args.disktype and args.no_disktype:
        args.disktype = False
    else:
        if args.disktype:
            explicit_disktype = True
        args.disktype = True

    # Make args.raid default to True
    explicit_raid = False
    if not args.raid and args.no_raid:
        args.raid = False
    else:
        if args.raid:
            explicit_raid = True
        args.raid = True

    # Make args.single default to None
    if args.single == args.no_single:
        args.single = None
    elif args.single:
        args.single = True
    elif args.no_single:
        args.single = False

    # If --no-interaction is specified, imply --keep and not --wait
    if args.no_interaction:
        args.keep = True
        if args.wait:
            print(col("[!] --no-interaction can't be used in conjunction with --wait", 'yellow'))
            args.wait = False

    # Check if mount method supports rw
    if args.method not in ('xmount', 'auto') and args.read_write:
        print(col("[!] {0} does not support mounting read-write! Will mount read-only.".format(args.method), 'yellow'))
        args.read_write = False

    # Check if mount method is available
    mount_command = 'avfsd' if args.method == 'avfs' else args.method
    if args.method not in ('auto', 'dummy') and not _util.command_exists(mount_command):
        print(col("[-] {0} is not installed!".format(args.method), 'red'))
        sys.exit(1)
    elif args.method == 'auto' and not any(map(_util.command_exists, ('xmount', 'affuse', 'ewfmount', 'vmware-mount',
                                                                     'avfsd'))):
        print(col("[-] No tools installed to mount the image base! Please install xmount, affuse (afflib-tools), "
                  "ewfmount (ewf-tools), vmware-mount or avfs first.", 'red'))
        sys.exit(1)

    # Check if detection method is available
    if args.detection == 'pytsk3' and not _util.module_exists('pytsk3'):
        print(col("[-] pytsk3 module does not exist!", 'red'))
        sys.exit(1)
    elif args.detection in ('mmls', 'parted') and not _util.command_exists(args.detection):
        print(col("[-] {0} is not installed!".format(args.detection), 'red'))
        sys.exit(1)
    elif args.detection == 'auto' and not any((_util.module_exists('pytsk3'), _util.command_exists('mmls'),
                                               _util.command_exists('parted'))):
        print(col("[-] No tools installed to detect volumes! Please install mmls (sleuthkit), pytsk3 or parted first.",
                  'red'))
        sys.exit(1)

    # Check if raid is available
    if args.raid and not _util.command_exists('mdadm'):
        if explicit_raid:
            print(col("[!] RAID mount requires the mdadm command.", 'yellow'))
        args.raid = False

    if args.reconstruct and not args.stats:  # Reconstruct implies use of fsstat
        print("[!] You explicitly disabled stats, but --reconstruct implies the use of stats. Stats are re-enabled.")
        args.stats = True

    # Check if raid is available
    if args.disktype and not _util.command_exists('disktype'):
        if explicit_disktype:
            print(col("[-] The disktype command can not be used in this session, as it is not installed.", 'yellow'))
        args.disktype = False

    if args.stats and not _util.command_exists('fsstat'):
        print(col("[-] The fsstat command (part of sleuthkit package) is required to obtain stats, but is not "
                  "installed. Stats can not be obtained during this session.", 'yellow'))
        args.stats = False

        if args.reconstruct:
            print(col("[-] Reconstruction requires stats to be obtained, but stats can not be enabled.", 'red'))
            sys.exit(1)

    if args.fsfallback and not args.fsforce:
        print("[!] You are using the file system type {0} as fallback. This may cause unexpected results."
              .format(args.fsfallback))
    elif args.fsfallback and args.fsforce:
        print("[!] You are forcing the file system type to {0}. This may cause unexpected results."
              .format(args.fsfallback))
    elif not args.fsfallback and args.fsforce:
        print("[-] You are forcing a file system type, but have not specified the type to use. Ignoring force.")
        args.fsforce = False

    if args.fstypes:
        try:
            fstypes = {}
            # noinspection PyUnresolvedReferences
            types = args.fstypes.split(',')
            for typ in types:
                idx, fstype = typ.split('=', 1)
                if fstype.strip() not in FILE_SYSTEM_TYPES:
                    print("[!] Error while parsing --fstypes: {} is invalid".format(fstype))
                else:
                    fstypes[idx.strip()] = fstype.strip()
            args.fstypes = fstypes
        except Exception as e:
            print("[!] Failed to parse --fstypes: {}".format(e))

    if args.vstype != 'detect' and args.single:
        print("[!] There's no point in using --single in combination with --vstype.")

    if args.carve and not _util.command_exists('photorec'):
        print(col("[-] The photorec command (part of testdisk package) is required to carve, but is not "
                  "installed. Carving will be disabled.", 'yellow'))
        args.carve = False

    if not args.images and not args.unmount:
        print(col("[-] You must specify at least one path to a disk image", 'red'))
        sys.exit(1)

    if args.unmount:
        unmounter = Unmounter(**vars(args))
        commands = unmounter.preview_unmount()
        if not commands:
            print("[+] Nothing to do")
            parser.exit()
        print("[!] --unmount will rigorously clean anything that looks like a mount or volume group originating "
              "from this utility. You may regret using this if you have other mounts or volume groups that are "
              "similarly named. The following commands will be executed:")
        for c in commands:
            print("    {0}".format(c))
        try:
            input(">>> Press [enter] to continue or ^C to cancel... ")
            unmounter.unmount()
        except KeyboardInterrupt:
            print("\n[-] Aborted.")
        sys.exit(0)

    # Enumerate over all images in the CLI
    images = []
    for num, image in enumerate(args.images):
        # If is a directory, find a E01 file in the directory
        if os.path.isdir(image):
            for f in glob.glob(os.path.join(image, '*.[E0]01')):
                images.append(f)
                break
            else:
                print(col("[-] {0} is a directory not containing a .001 or .E01 file, aborting!".format(image), "red"))
                break
            continue

        elif not os.path.exists(image):
            print(col("[-] Image {0} does not exist, aborting!".format(image), "red"))
            break

        images.append(image)

    else:
        p = None
        try:
            p = ImageParser(images, **vars(args))
            num = 0
            found_raid = False

            # Mount all disks. We could use .init, but where's the fun in that?
            for disk in p.disks:
                num += 1
                print('[+] Mounting image {0} using {1}...'.format(p.paths[0], disk.method))

                # Mount the base image using the preferred method
                if not disk.mount():
                    print(col("[-] Failed mounting base image. Perhaps try another mount method than {0}?"
                              .format(disk.method), "red"))
                    return

                if args.raid:
                    if disk.add_to_raid():
                        found_raid = True

                if args.read_write:
                    print('[+] Created read-write cache at {0}'.format(disk.rwpath))

                if args.disktype:
                    disk.load_disktype_data()
                print('[+] Mounted raw image [{num}/{total}]'.format(num=num, total=len(args.images)))

            sys.stdout.write("[+] Mounting volume...\r")
            sys.stdout.flush()
            has_left_mounted = False

            for volume in p.mount_volumes(args.single):
                try:
                    # something failed?
                    if not volume.mountpoint and not volume.loopback:
                        if volume.exception and volume.size is not None and volume.size <= 1048576:
                            print(col('[-] Exception while mounting small volume {0}'.format(volume.get_description()),
                                      'yellow'))
                            if args.wait:
                                input(col('>>> Press [enter] to continue... ', attrs=['dark']))

                        elif volume.exception:
                            print(col('[-] Exception while mounting {0}'.format(volume.get_description()), 'red'))
                            if not args.no_interaction:
                                input(col('>>> Press [enter] to continue... ', attrs=['dark']))
                        elif volume.flag != 'alloc':
                            if args.wait or args.verbose:  # do not show skipped messages by default
                                print(col('[-] Skipped {0} {1} volume' .format(volume.get_description(), volume.flag),
                                          'yellow'))
                            if args.wait:
                                input(col('>>> Press [enter] to continue... ', attrs=['dark']))
                        else:
                            print(col('[-] Could not mount volume {0}'.format(volume.get_description()), 'yellow'))
                            if args.wait:
                                input(col('>>> Press [enter] to continue... ', attrs=['dark']))

                        if args.carve and volume.flag in ('alloc', 'unalloc'):
                            sys.stdout.write("[+] Carving volume...\r")
                            sys.stdout.flush()
                            if volume.carve(freespace=False):
                                print('[+] Carved data is available at {0}.'.format(col(volume.carvepoint, 'green',
                                                                                        attrs=['bold'])))
                            else:
                                print(col('[-] Carving failed.', 'red'))
                        else:
                            continue  # we do not need the unmounting sequence

                    else:
                        # it all was ok
                        if volume.mountpoint:
                            print('[+] Mounted volume {0} on {1}.'.format(col(volume.get_description(), attrs=['bold']),
                                                                          col(volume.mountpoint, 'green',
                                                                              attrs=['bold'])))
                        elif volume.loopback:  # fallback, generally indicates error.
                            print('[+] Mounted volume {0} as loopback on {1}.'.format(col(volume.get_description(),
                                                                                          attrs=['bold']),
                                                                                      col(volume.loopback, 'green',
                                                                                          attrs=['bold'])))
                            print(col('[-] Could not detect further volumes in the loopback device.', 'red'))

                        if args.carve:
                            sys.stdout.write("[+] Carving volume...\r")
                            sys.stdout.flush()
                            if volume.carve():
                                print('[+] Carved data is available at {0}.'.format(col(volume.carvepoint, 'green',
                                                                                        attrs=['bold'])))
                            else:
                                print(col('[-] Carving failed.', 'red'))

                    # Do not offer unmount when reconstructing
                    if args.reconstruct or args.keep:
                        has_left_mounted = True
                        continue

                    input(col('>>> Press [enter] to unmount the volume, or ^C to keep mounted... ', attrs=['dark']))

                    # Case where image should be unmounted, but has failed to do so. Keep asking whether the user wants
                    # to unmount.
                    while True:
                        if volume.unmount():
                            break
                        else:
                            try:
                                print(col("[-] Error unmounting volume. Perhaps files are still open?", "red"))
                                input(col('>>> Press [enter] to retry unmounting, or ^C to skip... ', attrs=['dark']))
                            except KeyboardInterrupt:
                                has_left_mounted = True
                                print("")
                                break
                except KeyboardInterrupt:
                    has_left_mounted = True
                    print("")
                sys.stdout.write("[+] Mounting volume...\r")
                sys.stdout.flush()

            for disk in p.disks:
                if [x for x in disk.volumes if x.was_mounted] == 0:
                    if args.vstype != 'detect':
                        print(col('[?] Could not determine volume information of {0}. Image may be empty, '
                                  'or volume system type {0} was incorrect.'.format(args.vstype.upper()), 'yellow'))
                    elif found_raid:
                        print(col('[?] Could not determine volume information. Image may be empty, or volume system '
                                  'type could not be detected. Try explicitly providing the volume system type with '
                                  '--vstype, or providing more volumes to complete the RAID array.', 'yellow'))
                    elif not args.raid or args.single is False:
                        print(col('[?] Could not determine volume information. Image may be empty, or volume system '
                                  'type could not be detected. Try explicitly providing the volume system type with '
                                  '--vstype, mounting as RAID with --raid and/or mounting as a single volume with '
                                  '--single', 'yellow'))
                    else:
                        print(col('[?] Could not determine volume information. Image may be empty, or volume system '
                                  'type could not be detected. Try explicitly providing the volume system type with '
                                  '--vstype.', 'yellow'))
                    if args.wait:
                        input(col('>>> Press [enter] to continue... ', attrs=['dark']))

            print('[+] Parsed all volumes!')

            # Perform reconstruct if required
            if args.reconstruct:
                # Reverse order so '/' gets unmounted last

                print("[+] Performing reconstruct... ")
                root = p.reconstruct()
                if not root:
                    print(col("[-] Failed reconstructing filesystem: could not find root directory.", 'red'))
                else:
                    failed = []
                    for disk in p.disks:
                        failed.extend([x for x in disk.volumes if not x.bindmountpoint and x.mountpoint and x != root])
                    if failed:
                        print("[+] Parts of the filesystem are reconstructed in {0}.".format(col(root.mountpoint,
                                                                                                 "green",
                                                                                                 attrs=["bold"])))
                        for m in failed:
                            print("    {0} was not reconstructed".format(m.mountpoint))
                    else:
                        print("[+] The entire filesystem is reconstructed in {0}.".format(col(root.mountpoint,
                                                                                              "green", attrs=["bold"])))
                if not args.keep:
                    input(col(">>> Press [enter] to unmount all volumes... ", attrs=['dark']))
            elif has_left_mounted and not args.keep:
                input(col(">>> Some volumes were left mounted. Press [enter] to unmount all... ", attrs=['dark']))

        except KeyboardInterrupt:
            print('\n[+] User pressed ^C, aborting...')
            return

        except Exception as e:
            import traceback
            traceback.print_exc()
            print(col("[-] {0}".format(e), 'red'))
            if not args.no_interaction:
                input(col(">>> Press [enter] to continue.", attrs=['dark']))

        finally:
            if args.keep:
                print("[+] Analysis complete.")
            elif not p:
                print("[-] Crashed before creating parser")
            else:
                print('[+] Analysis complete, unmounting...')

                # All done with this image, unmount it
                try:
                    remove_rw = p.rw_active() and 'y' in input('>>> Delete the rw cache file? [y/N] ').lower()
                except KeyboardInterrupt:
                    remove_rw = False

                while True:
                    if p.clean(remove_rw):
                        break
                    else:
                        try:
                            print(col("[-] Error unmounting base image. Perhaps volumes are still open?", 'red'))
                            input(col('>>> Press [enter] to retry unmounting, or ^C to cancel... ', attrs=['dark']))
                        except KeyboardInterrupt:
                            print("")  # ^C does not print \n
                            break
                print("[+] All cleaned up")


if __name__ == '__main__':
    main()
