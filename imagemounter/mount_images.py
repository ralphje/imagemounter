#!/usr/bin/env python

from __future__ import print_function
from __future__ import unicode_literals

import argparse
import glob
import sys
import os

from imagemounter import util, ImageParser, __version__, FILE_SYSTEM_TYPES, VOLUME_SYSTEM_TYPES

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

    class CleanAction(argparse.Action):
        # noinspection PyShadowingNames
        def __call__(self, parser, namespace, values, option_string=None):
            commands = ImageParser.force_clean(False)
            if not commands:
                print("[+] Nothing to do")
                parser.exit()
            print("[!] --clean will rigorously clean anything that looks like a mount or volume group originating "
                  "from this utility. You may regret using this if you have other mounts or volume groups that are "
                  "similarly named. The following commands will be executed:")
            for c in commands:
                print("    {0}".format(c))
            try:
                input(">>> Press [enter] to continue or ^C to cancel... ")
                ImageParser.force_clean()
            except KeyboardInterrupt:
                print("\n[-] Aborted.")
            parser.exit()

    parser = MyParser(description='Utility to mount volumes in Encase and dd images locally.')
    parser.add_argument('images', nargs='+',
                        help='path(s) to the image(s) that you want to mount; generally just the first file (e.g. '
                             'the .E01 or .001 file) or the folder containing the files is enough in the case of '
                             'split files')

    # Special options
    parser.add_argument('--version', action='version', version=__version__, help='display version and exit')
    parser.add_argument('--clean', action=CleanAction, nargs=0,
                        help='try to rigorously clean anything that resembles traces from previous runs of '
                             'this utility (is not able to detect RAID volumes)')

    # Utility specific
    parser.add_argument('-c', '--color', action='store_true', default=False, help='colorize the output')
    parser.add_argument('-w', '--wait', action='store_true', default=False, help='pause on some additional warnings')
    parser.add_argument('-k', '--keep', action='store_true', default=False,
                        help='keep volumes mounted after program exits')
    parser.add_argument('-v', '--verbose', action='store_true', default=False, help='enable verbose output')

    # Additional options
    parser.add_argument('-r', '--reconstruct', action='store_true', default=False,
                        help='attempt to reconstruct the full filesystem tree; implies -s and mounts all partitions '
                             'at once')

    # Specify options to the subsystem
    parser.add_argument('-md', '--mountdir', default=None,
                        help='specify other directory for volume mountpoints')
    parser.add_argument('-p', '--pretty', action='store_true', default=False,
                        help='use pretty names for mount points; useful in combination with --mountdir and does not '
                             'provide a fallback when the pretty mount name is unavailable')
    parser.add_argument('-rw', '--read-write', action='store_true', default=False,
                        help='mount image read-write by creating a local write-cache file in a temp directory; '
                             'implies --method=xmount')
    parser.add_argument('-m', '--method', choices=['xmount', 'affuse', 'ewfmount', 'auto', 'dummy'], default='auto',
                        help='use other tool to mount the initial images; results may vary between methods and if '
                             'something doesn\'t work, try another method; dummy can be used when base should not be '
                             'mounted (default: auto)')
    parser.add_argument('-d', '--detection', choices=['pytsk3', 'mmls', 'auto'], default='auto',
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
    parser.add_argument('-s', '--stats', action='store_true', default=False,
                        help='show limited information from fsstat, which will slow down mounting and may cause '
                             'random issues such as partitions being unreadable (default)')
    parser.add_argument('-n', '--no-stats', action='store_true', default=False,
                        help='do not show limited information from fsstat')
    parser.add_argument('--raid', action='store_true', default=False,
                        help="try to detect whether the volume is part of a RAID array (default)")
    parser.add_argument('--no-raid', action='store_true', default=False,
                        help="prevent trying to mount the volume in a RAID array")
    parser.add_argument('--single', action='store_true', default=False,
                        help="do not try to find a volume system, but assume the image contains a single volume")
    parser.add_argument('--no-single', action='store_true', default=False,
                        help="prevent trying to mount the image as a single volume if no volume system was found")
    args = parser.parse_args()

    # Check some prerequisites
    if os.geteuid():  # Not run as root
        print('[-] This program needs to be ran as root!')
        #os.execvp('sudo', ['sudo'] + sys.argv)
        sys.exit(1)

    if not args.color:
        #noinspection PyUnusedLocal,PyShadowingNames
        def col(s, *args, **kwargs):
            return s
    else:
        from termcolor import colored
        col = colored

    if __version__.endswith('a') or __version__.endswith('b'):
        print(col("Development release v{0}. Please report any bugs you encounter.".format(__version__),
                  attrs=['dark']))
        print(col("Critical bug? Use git tag to list all versions and use git checkout <version>", attrs=['dark']))

    # Always assume stats, except when --no-stats is present, and --stats is not.
    if not args.stats and args.no_stats:
        args.stats = False
    else:
        args.stats = True

    # Make args.raid default to True
    if not args.raid and args.no_raid:
        args.raid = False
    else:
        args.raid = True

    # Make args.single default to None
    if args.single == args.no_single:
        args.single = None
    elif args.single:
        args.single = True
    elif args.no_single:
        args.single = False

    # Check if mount method supports rw
    if args.method not in ('xmount', 'auto') and args.read_write:
        print(col("[!] {0} does not support mounting read-write! Will mount read-only.".format(args.method), 'yellow'))
        args.read_write = False

    # Check if mount method is available
    if args.method not in ('auto', 'dummy') and not util.command_exists(args.method):
        print(col("[-] {0} is not installed!".format(args.method), 'red'))
        sys.exit(1)
    elif args.method == 'auto' and not any(map(util.command_exists, ('xmount', 'affuse', 'ewfmount'))):
        print(col("[-] No tools installed to mount the image base!", 'red'))
        sys.exit(1)

    # Check if detection method is available
    if args.detection == 'pytsk3' and not util.module_exists('pytsk3'):
        print(col("[-] pytsk3 module does not exist!", 'red'))
        sys.exit(1)
    elif args.detection == 'mmls' and not util.command_exists(args.detection):
        print(col("[-] {0} is not installed!".format(args.detection), 'red'))
        sys.exit(1)
    elif args.detection == 'auto' and not util.module_exists('pytsk3') and not util.command_exists('mmls'):
        print(col("[-] No tools installed to detect volumes!", 'red'))
        sys.exit(1)

    # Check if raid is available
    if args.raid and not util.command_exists('mdadm'):
        print(col("[!] RAID mount requires the mdadm command.", 'yellow'))
        args.raid = False

    if args.reconstruct and not args.stats:  # Reconstruct implies use of fsstat
        print("[!] You explicitly disabled stats, but --reconstruct implies the use of stats. Stats are re-enabled.")
        args.stats = True

    if args.stats and not util.command_exists('fsstat'):
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

    elif args.vstype == 'any':
        print("[!] You are using the 'any' volume system type. This may cause unexpected results. It is recommended "
              "to use either 'detect' or explicitly specify the correct volume system. However, 'any' may provide "
              "some hints on the volume system to use (e.g. GPT mounted as DOS lists a GPT safety partition).")

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
                print('[+] Mounted raw image [{num}/{total}]'.format(num=num, total=len(args.images)))

            sys.stdout.write("[+] Mounting volume...\r")
            sys.stdout.flush()
            has_left_mounted = False

            for volume in p.mount_volumes(args.single):

                if not volume.mountpoint and not volume.loopback:
                    if volume.exception and volume.size is not None and volume.size <= 1048576:
                        print(col('[-] Exception while mounting small volume {0}'.format(volume.get_description()),
                                  'yellow'))
                        if args.wait:
                            input(col('>>> Press [enter] to continue... ', attrs=['dark']))

                    elif volume.exception:
                        print(col('[-] Exception while mounting {0}'.format(volume.get_description()), 'red'))
                        input(col('>>> Press [enter] to continue... ', attrs=['dark']))
                    elif volume.flag != 'alloc':
                        print(col('[-] Skipped {0} {1} volume' .format(volume.get_description(), volume.flag),
                                  'yellow'))
                        if args.wait:
                            input(col('>>> Press [enter] to continue... ', attrs=['dark']))
                    else:
                        print(col('[-] Could not mount volume {0}'.format(volume.get_description()), 'yellow'))
                        if args.wait:
                            input(col('>>> Press [enter] to continue... ', attrs=['dark']))

                    continue

                try:
                    if volume.mountpoint:
                        print('[+] Mounted volume {0} on {1}.'.format(col(volume.get_description(), attrs=['bold']),
                                                                      col(volume.mountpoint, 'green', attrs=['bold'])))
                    elif volume.loopback:  # fallback, generally indicates error.
                        print('[+] Mounted volume {0} as loopback on {1}.'.format(col(volume.get_description(),
                                                                                      attrs=['bold']),
                                                                                  col(volume.loopback, 'green',
                                                                                      attrs=['bold'])))
                        print(col('[-] Could not detect further volumes in the loopback device.', 'red'))

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
