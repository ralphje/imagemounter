#!/usr/bin/env python
#
# This CLI is a total mess. If you want a simple example, please refer to simple_cli.py
#

from __future__ import print_function
from __future__ import unicode_literals

import argparse
import glob
import logging
import sys
import os

from imagemounter import _util, ImageParser, Unmounter, __version__, FILE_SYSTEM_TYPES, VOLUME_SYSTEM_TYPES, \
    DISK_MOUNTERS
from imagemounter.cli import CheckAction, get_coloring_func, AppendDictAction, ImageMounterStreamHandler
from imagemounter.exceptions import NoRootFoundError, ImageMounterError, UnsupportedFilesystemError

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

    parser = MyParser(description='Utility to mount volumes in Encase and dd images locally.')
    parser.add_argument('images', nargs='*',
                        help='path(s) to the image(s) that you want to mount; generally just the first file (e.g. '
                             'the .E01 or .001 file) or the folder containing the files is enough in the case of '
                             'split files')

    # Special options
    parser.add_argument('--version', action='version', version=__version__, help='display version and exit')
    parser.add_argument('--check', action=CheckAction, nargs=0,
                        help='do a system check and list which tools are installed')
    parser.add_argument('-i', '--interactive', action='store_true', default=False,
                        help='enter the interactive shell')

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
    parser.add_argument('-o', '--only-mount', default=None,
                        help="specify which volume(s) you want to mount, comma-separated")
    parser.add_argument('--skip', default=None,
                        help="specify which volume(s) you do not want to mount, comma-separated")
    parser.add_argument('-v', '--verbose', action='count', default=False, help='enable verbose output')
    parser.add_argument('-c', '--color', action='store_true', default=False, help='force colorizing the output')
    parser.add_argument('--no-color', action='store_true', default=False, help='prevent colorizing the output')

    # Additional options
    parser.add_argument('-r', '--reconstruct', action='store_true', default=False,
                        help='attempt to reconstruct the full filesystem tree; implies -s and mounts all partitions '
                             'at once')
    parser.add_argument('--carve', action='store_true', default=False,
                        help='automatically carve the free space of a mounted volume for deleted files')
    parser.add_argument('--vshadow', action='store_true', default=False,
                        help='automatically mount volume shadow copies')

    # Specify options to the subsystem
    parser.add_argument('-md', '--mountdir', default=None,
                        help='specify other directory for volume mountpoints')
    parser.add_argument('-p', '--pretty', action='store_true', default=False,
                        help='use pretty names for mount points; useful in combination with --mountdir')
    parser.add_argument('-cn', '--casename', default=None,
                        help='name to add to the --mountdir, often used in conjunction with --pretty')
    parser.add_argument('-rw', '--read-write', action='store_true', default=False,
                        help='mount image read-write by creating a local write-cache file in a temp directory; '
                             'implies --disk-mounter=xmount')
    parser.add_argument('-m', '--disk-mounter', choices=DISK_MOUNTERS,
                        default='auto',
                        help='use other tool to mount the initial images; results may vary between methods and if '
                             'something doesn\'t work, try another method; dummy can be used when base should not be '
                             'mounted (default: auto)')
    parser.add_argument('-d', '--volume-detector', choices=['pytsk3', 'mmls', 'parted', 'auto'], default='auto',
                        help='use other volume detection method; pytsk3 and mmls should provide identical results, '
                             'though pytsk3 is using the direct C API of mmls, but requires pytsk3 to be installed; '
                             'auto distinguishes between pytsk3 and mmls only '
                             '(default: auto)')
    parser.add_argument('--vstypes', action=AppendDictAction, default={'*': 'detect'},
                        help='specify type of volume system (partition table); if you don\'t know, '
                             'use "detect" to try to detect (default: detect)')
    parser.add_argument('--fstypes', action=AppendDictAction, default={'?': 'unknown'},
                        help="allows the specification of the file system type per volume number; format: 0.1=lvm,...; "
                             "use volume number ? for all undetected file system types and * for all file systems; "
                             "accepted file systems types are {}".format(", ".join(FILE_SYSTEM_TYPES)) +
                             ", and none only for the ? volume (defaults to unknown)")
    parser.add_argument('--keys', action=AppendDictAction, default={},
                        help="allows the specification of key material per volume number; format: 0.1=p:pass,...; "
                             "exact format depends on volume type", allow_commas=False)
    parser.add_argument('--lazy-unmount', action='store_true', default=False,
                        help="enables lazily unmounting volumes and disks if direct unmounting fails")

    # Toggles for default settings you may perhaps want to override

    toggroup = parser.add_argument_group('toggles')
    toggroup.add_argument('--single', action='store_true', default=False,
                          help="do not try to find a volume system, but assume the image contains a single volume")
    toggroup.add_argument('--no-single', action='store_true', default=False,
                          help="prevent trying to mount the image as a single volume if no volume system was found")

    args = parser.parse_args()
    col = get_coloring_func(color=args.color, no_color=args.color)

    # Set logging level for internal Python
    handler = ImageMounterStreamHandler(col, args.verbose)
    logger = logging.getLogger("imagemounter")
    logger.setLevel({0: logging.CRITICAL, 1: logging.WARNING, 2: logging.INFO}.get(args.verbose, logging.DEBUG))
    logger.addHandler(handler)

    # Check some prerequisites
    if os.geteuid():  # Not run as root
        print(col('[!] Not running as root!', 'yellow'))

    if 'a' in __version__ or 'b' in __version__:
        print(col("Development release v{0}. Please report any bugs you encounter.".format(__version__),
                  attrs=['dark']))
        print(col("Bug reports: use -vvvv to get maximum verbosity and include  imount --check  output in your report",
                  attrs=['dark']))
        print(col("Critical bug? Use git tag to list all versions and use git checkout <version>", attrs=['dark']))

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
    if args.disk_mounter not in ('xmount', 'auto') and args.read_write:
        print(col("[!] {0} does not support mounting read-write! Will mount read-only.".format(args.disk_mounter), 'yellow'))
        args.read_write = False

    # Check if mount method is available
    mount_command = 'avfsd' if args.disk_mounter == 'avfs' else args.disk_mounter
    if args.disk_mounter not in ('auto', 'dummy') and not _util.command_exists(mount_command):
        print(col("[-] {0} is not installed!".format(args.disk_mounter), 'red'))
        sys.exit(1)
    elif args.disk_mounter == 'auto' and not any(map(_util.command_exists, ('xmount', 'affuse', 'ewfmount', 'vmware-mount',
                                                                            'avfsd'))):
        print(col("[-] No tools installed to mount the image base! Please install xmount, affuse (afflib-tools), "
                  "ewfmount (ewf-tools), vmware-mount or avfs first.", 'red'))
        sys.exit(1)

    # Check if detection method is available
    if args.volume_detector == 'pytsk3' and not _util.module_exists('pytsk3'):
        print(col("[-] pytsk3 module does not exist!", 'red'))
        sys.exit(1)
    elif args.volume_detector in ('mmls', 'parted') and not _util.command_exists(args.volume_detector):
        print(col("[-] {0} is not installed!".format(args.volume_detector), 'red'))
        sys.exit(1)
    elif args.volume_detector == 'auto' and not any((_util.module_exists('pytsk3'), _util.command_exists('mmls'),
                                                     _util.command_exists('parted'))):
        print(col("[-] No tools installed to detect volumes! Please install mmls (sleuthkit), pytsk3 or parted first.",
                  'red'))
        sys.exit(1)

    if args.fstypes:
        for k, v in args.fstypes.items():
            if v.strip() not in FILE_SYSTEM_TYPES and v.strip() not in VOLUME_SYSTEM_TYPES \
                    and not (k == '?' and v.strip().lower() == 'none'):
                print("[!] Error while parsing --fstypes: {} is invalid".format(v))
                sys.exit(1)

    if '*' in args.fstypes:
        print("[!] You are forcing the file system type to {0}. This may cause unexpected results."
              .format(args.fstypes['*']))
    elif '?' in args.fstypes and args.fstypes['?'] not in ('unknown', 'none'):
        print("[!] You are using the file system type {0} as fallback. This may cause unexpected results."
              .format(args.fstypes['?']))

    if args.only_mount:
        args.only_mount = args.only_mount.split(',')
    if args.skip:
        args.skip = args.skip.split(',')

    if args.vstypes:
        for k, v in args.vstypes.items():
            if v.strip() not in VOLUME_SYSTEM_TYPES:
                print("[!] Error while parsing --vstypes: {} is invalid".format(v))
                sys.exit(1)

    if args.carve and not _util.command_exists('photorec'):
        print(col("[-] The photorec command (part of testdisk package) is required to carve, but is not "
                  "installed. Carving will be disabled.", 'yellow'))
        args.carve = False

    if args.vshadow and not _util.command_exists('vshadowmount'):
        print(col("[-] The vhadowmount command is required to mount volume shadow copies, but is not "
                  "installed. Mounting volume shadow copies will be disabled.", 'yellow'))
        args.vshadow = False

    if (args.interactive or not args.images) and not args.unmount:
        from imagemounter.cli.shell import main
        main()
        return

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
            for f in glob.glob(os.path.join(image, '*.[Ee0]01')):
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

            # Mount all disks. We could use .init, but where's the fun in that?
            for disk in p.disks:
                num += 1
                print('[+] Mounting image {0} using {1}...'.format(disk.paths[0], disk.disk_mounter))

                # Mount the base image using the preferred method
                try:
                    disk.mount()
                except ImageMounterError:
                    print(col("[-] Failed mounting base image. Perhaps try another mount method than {0}?"
                              .format(disk.disk_mounter), "red"))
                    return

                if args.read_write:
                    print('[+] Created read-write cache at {0}'.format(disk.rwpath))

                disk.volumes.preload_volume_data()
                print('[+] Mounted raw image [{num}/{total}]'.format(num=num, total=len(args.images)))

            sys.stdout.write("[+] Mounting volume...\r")
            sys.stdout.flush()
            has_left_mounted = False

            for volume in p.init_volumes(args.single, args.only_mount, args.skip, swallow_exceptions=True):
                try:
                    # something failed?
                    if not volume.mountpoint and not volume.loopback:
                        if volume.exception and volume.size is not None and volume.size <= 1048576:
                            print(col('[-] Exception while mounting small volume {0}'.format(volume.get_description()),
                                      'yellow'))
                            if args.wait:
                                input(col('>>> Press [enter] to continue... ', attrs=['dark']))

                        elif isinstance(volume.exception, UnsupportedFilesystemError) and volume.fstype == 'swap':
                            print(col('[-] Exception while mounting swap volume {0}'.format(volume.get_description()),
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
                        elif not volume._should_mount(args.only_mount):
                            print(col('[-] Skipped {0}'.format(volume.get_description()), 'yellow'))
                        else:
                            print(col('[-] Could not mount volume {0}'.format(volume.get_description()), 'yellow'))
                            if args.wait:
                                input(col('>>> Press [enter] to continue... ', attrs=['dark']))

                        if args.carve and volume.flag in ('alloc', 'unalloc'):
                            sys.stdout.write("[+] Carving volume...\r")
                            sys.stdout.flush()
                            try:
                                path = volume.carve(freespace=False)
                            except ImageMounterError:
                                print(col('[-] Carving failed.', 'red'))
                            else:
                                print('[+] Carved data is available at {0}.'.format(col(path, 'green', attrs=['bold'])))
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
                            try:
                                path = volume.carve()
                            except ImageMounterError:
                                print(col('[-] Carving failed.', 'red'))
                            else:
                                print('[+] Carved data is available at {0}.'.format(col(path, 'green', attrs=['bold'])))

                        if args.vshadow and volume.fstype == 'ntfs':
                            sys.stdout.write("[+] Mounting volume shadow copies...\r")
                            sys.stdout.flush()
                            try:
                                volumes = volume.detect_volume_shadow_copies()
                            except ImageMounterError:
                                print(col('[-] Volume shadow copies could not be mounted.', 'red'))
                            else:
                                for v in volumes:
                                    try:
                                        v.init_volume()
                                    except ImageMounterError:
                                        print(col('[-] Volume shadow copy {} not mounted'.format(v), 'red'))
                                    else:
                                        print('[+] Volume shadow copy available at {0}.'.format(col(v.mountpoint,
                                                                                                    'green',
                                                                                                    attrs=['bold'])))

                    # Do not offer unmount when reconstructing
                    if args.reconstruct or args.keep:
                        has_left_mounted = True
                        continue

                    input(col('>>> Press [enter] to unmount the volume, or ^C to keep mounted... ', attrs=['dark']))

                    # Case where image should be unmounted, but has failed to do so. Keep asking whether the user wants
                    # to unmount.
                    while True:
                        try:
                            volume.unmount(allow_lazy=args.lazy_unmount)
                            break
                        except ImageMounterError:
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
                    if disk.vstype != 'detect':
                        print(col('[?] Could not determine volume information of {0}. Image may be empty, '
                                  'or volume system type {0} was incorrect.'.format(disk.vstype.upper()), 'yellow'))
                    elif args.single is False:
                        print(col('[?] Could not determine volume information. Image may be empty, or volume system '
                                  'type could not be detected. Try explicitly providing the volume system type with '
                                  '--vstypes or mounting as a single volume with --single', 'yellow'))
                    else:
                        print(col('[?] Could not determine volume information. Image may be empty, or volume system '
                                  'type could not be detected. Try explicitly providing the volume system type with '
                                  '--vstypes.', 'yellow'))
                    if args.wait:
                        input(col('>>> Press [enter] to continue... ', attrs=['dark']))

            print('[+] Parsed all volumes!')

            # Perform reconstruct if required
            if args.reconstruct:
                # Reverse order so '/' gets unmounted last

                print("[+] Performing reconstruct... ")
                try:
                    root = p.reconstruct()
                except NoRootFoundError:
                    print(col("[-] Failed reconstructing filesystem: could not find root directory.", 'red'))
                else:
                    failed = []
                    for disk in p.disks:
                        failed.extend([x for x in disk.volumes if 'bindmounts' not in x._paths and x.mountpoint and x != root])
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
                    try:
                        p.clean(remove_rw, allow_lazy=args.lazy_unmount)
                        print("[+] All cleaned up")
                        break
                    except ImageMounterError:
                        try:
                            print(col("[-] Error unmounting base image. Perhaps volumes are still open?", 'red'))
                            input(col('>>> Press [enter] to retry unmounting, or ^C to cancel... ', attrs=['dark']))
                        except KeyboardInterrupt:
                            print("")  # ^C does not print \n
                            break


if __name__ == '__main__':
    main()
