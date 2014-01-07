#!/usr/bin/env python
import argparse
import glob
import sys
import os

from imagemounter import util, ImageParser, __version__
from termcolor import colored


def main():
    class MyParser(argparse.ArgumentParser):
        def error(self, message):
            sys.stderr.write('error: {0}\n'.format(message))
            self.print_help()
            sys.exit(2)

    class CleanAction(argparse.Action):
        def __call__(self, parser, namespace, values, option_string=None):
            commands = ImageParser.force_clean(False)
            if not commands:
                print "[+] Nothing to do"
                parser.exit()
            print "[!] --clean will rigorously clean anything that looks like a mount or volume group originating " \
                  "from this utility. You may regret using this if you have other mounts or volume groups that are " \
                  "similarly named. The following commands will be executed:"
            for c in commands:
                print "    {0}".format(c)
            try:
                raw_input(">>> Press [enter] to continue or ^C to cancel... ")
                ImageParser.force_clean()
            except KeyboardInterrupt:
                print "\n[-] Aborted."
            parser.exit()

    parser = MyParser(description=u'Utility to mount volumes in Encase and dd images locally.')
    parser.add_argument('images', nargs='+',
                        help='path(s) to the image(s) that you want to mount; generally just the first file (e.g. '
                             'the .E01 or .001 file) or the folder containing the files is enough in the cast of '
                             'split files.')
    parser.add_argument('--version', action='version', version=__version__, help='display version and exit')
    parser.add_argument('--clean', action=CleanAction, nargs=0,
                        help='try to rigorously clean anything that resembles traces from previous runs of '
                             'this utility')
    parser.add_argument('-c', '--color', action='store_true', default=False, help='colorize the output')
    parser.add_argument('-w', '--wait', action='store_true', default=False, help='pause on some additional warnings')
    parser.add_argument('-r', '--reconstruct', action='store_true', default=False,
                        help='attempt to reconstruct the full filesystem tree; implies -s and mounts all partitions '
                             'at once')
    parser.add_argument('-rw', '--read-write', action='store_true', default=False,
                        help='mount image read-write by creating a local write-cache file in a temp directory; '
                             'implies --method=xmount')
    parser.add_argument('-s', '--stats', action='store_true', default=False,
                        help='show limited information from fsstat, which will slow down mounting and may cause '
                             'random issues such as partitions being unreadable')
    parser.add_argument('-m', '--method', choices=['xmount', 'affuse', 'ewfmount', 'auto'], default='auto',
                        help='use other tool to mount the initial images; results may vary between methods and if '
                             'something doesn\'t work, try another method (default: auto)')
    parser.add_argument('-md', '--mountdir', default=None,
                        help='specify other directory for volume mountpoints')
    parser.add_argument('-p', '--pretty', action='store_true', default=False,
                        help='use pretty names for mount points; useful in combination with --mountdir and does not '
                             'provide a fallback when the pretty mount name is unavailable')
    parser.add_argument('-vs', '--vstype', choices=['detect', 'dos', 'bsd', 'sun', 'mac', 'gpt', 'dbfiller', 'any'],
                        default="detect", help='specify type of volume system (partition table); if you don\'t know, '
                                               'use "detect" to try to detect, or "any" to loop over all VS types and '
                                               'use whatever works, which may produce unexpected results (default: '
                                               'detect)')
    parser.add_argument('-fs', '--fstype', choices=['ext', 'ufs', 'ntfs', 'lvm', 'unknown'], default=None,
                        help="specify fallback type of the filesystem, which is used when it could not be detected or "
                             "is unsupported; use unknown to mount without specifying type")
    parser.add_argument('-fsf', '--fsforce', action='store_true', default=False,
                        help="force the use of the filesystem type specified with --fstype for all partitions")
    parser.add_argument('-v', '--verbose', action='store_true', default=False, help='enable verbose output')
    args = parser.parse_args()

    # Check some prerequisites
    if os.geteuid():  # Not run as root
        print u'[-] This program needs to be ran as root! Requesting elevation... '
        os.execvp('sudo', ['sudo'] + sys.argv)
        #sys.exit(1)

    if not args.color:
        #noinspection PyUnusedLocal,PyShadowingNames
        def col(s, *args, **kwargs):
            return s
    else:
        col = colored

    if args.method not in ('xmount', 'auto') and args.read_write:
        print "[-] {0} does not support mounting read-write! Will mount read-only.".format(args.method)
        args.read_write = False

    if args.method != 'auto' and not util.command_exists(args.method):
        print "[-] {0} is not installed!".format(args.method)
        sys.exit(1)

    if args.method == 'auto' and not any(map(util.command_exists, ('xmount', 'affuse', 'ewfmount'))):
        print "[-] No tools installed to mount the image base!"
        sys.exit(1)

    if args.reconstruct:  # Reconstruct implies use of fsstat
        args.stats = True

    if args.stats and not util.command_exists('fsstat'):
        print "[-] To obtain stats, the fsstat command is used (part of sleuthkit package), but is not installed. " \
              "Stats will not be obtained during this session."
        args.stats = False

        if args.reconstruct:
            print "[-] Reconstruction is now impossible!"
            sys.exit(1)

    if args.fstype and not args.fsforce:
        print "[!] You are using the file system type {0} as fallback. This may cause unexpected results."\
            .format(args.fstype)
    elif args.fstype and args.fsforce:
        print "[!] You are forcing the file system type to {0}. This may cause unexpected results.".format(args.fstype)
    elif not args.fstype and args.fsforce:
        print "[-] You are forcing a file system type, but have not specified the type to use. Ignoring force."
        args.fsforce = False

    if args.vstype == 'any':
        print "[!] You are using the 'any' volume system type. This may cause unexpected results. It is recommended " \
              "to use either 'detect' or explicitly specify the correct volume system. However, 'any' may provide " \
              "some hints on the volume system to use (e.g. GPT mounted as DOS lists a GPT safety partition)."

    # Enumerate over all images in the CLI
    for num, image in enumerate(args.images):
        # If is a directory, find a E01 file in the directory
        if os.path.isdir(image):
            for f in glob.glob(os.path.join(image, '*.[E0]01')):
                image = f
                break
            else:
                print col("[-] {0} is a directory, aborting!".format(image), "red")
                break

        elif not os.path.exists(image):
            print col("[-] Image {0} does not exist, aborting!".format(image), "red")
            break

        try:
            p = ImageParser(image, **vars(args))
            print u'[+] Mounting image {0} using {1}...'.format(p.paths[0], p.method)

            # Mount the base image using the preferred method
            if not p.mount_base():
                print col("[-] Failed mounting base image.", "red")
                continue

            if args.read_write:
                print u'[+] Created read-write cache at {0}'.format(p.rwpath)
            print u'[+] Mounted raw image [{num}/{total}], now mounting volumes...'.format(num=num + 1,
                                                                                           total=len(args.images))

            sys.stdout.write("[+] Mounting partition 0...\r")
            sys.stdout.flush()

            i = 0
            has_left_mounted = False
            for volume in p.mount_volumes():
                i += 1

                if not volume.mountpoint and not volume.loopback:
                    if volume.exception and volume.size is not None and volume.size <= 1048576:
                        print col(u'[-] Exception while mounting small volume {0}'.format(volume.get_description()),
                                  'yellow')
                        if args.wait:
                            raw_input(col('>>> Press [enter] to continue... ', attrs=['dark']))

                    elif volume.exception:
                        print col(u'[-] Exception while mounting {0}'.format(volume.get_description()), 'red')
                        raw_input(col('>>> Press [enter] to continue... ', attrs=['dark']))
                    elif volume.flag != 'alloc':
                        print col(u'[-] Skipped {1} volume {0}' .format(volume.get_description(), volume.flag), 'yellow')
                        if args.wait:
                            raw_input(col('>>> Press [enter] to continue... ', attrs=['dark']))
                    else:
                        print col(u'[-] Could not mount volume {0}'.format(volume.get_description()), 'yellow')
                        if args.wait:
                            raw_input(col('>>> Press [enter] to continue... ', attrs=['dark']))

                    continue

                try:
                    if volume.mountpoint:
                        print u'[+] Mounted volume {0} on {1}.'.format(col(volume.get_description(), attrs=['bold']),
                                                                       col(volume.mountpoint, 'green', attrs=['bold']))
                    elif volume.loopback:  # fallback, generally indicates error.
                        print u'[+] Mounted volume {0} as loopback on {1}.'.format(col(volume.get_description(), attrs=['bold']),
                                                                                      col(volume.loopback, 'green', attrs=['bold']))
                        print col(u'[-] Could not detect further volumes in the loopback device.', 'red')

                    # Do not offer unmount when reconstructing
                    if args.reconstruct:
                        has_left_mounted = True
                        continue


                    raw_input(col('>>> Press [enter] to unmount the volume, or ^C to keep mounted... ', attrs=['dark']))

                    # Case where image should be unmounted, but has failed to do so. Keep asking whether the user wants
                    # to unmount.
                    while True:
                        if volume.unmount():
                            break
                        else:
                            try:
                                print col("[-] Error unmounting volume. Perhaps files are still open?", "red")
                                raw_input(col('>>> Press [enter] to retry unmounting, or ^C to skip... ', attrs=['dark']))
                            except KeyboardInterrupt:
                                has_left_mounted = True
                                print ""
                                break
                except KeyboardInterrupt:
                    has_left_mounted = True
                    print ""
                sys.stdout.write("[+] Mounting volume {0}{1}\r".format(i, col("...", attrs=['blink'])))
                sys.stdout.flush()
            if i == 0:
                if args.vstype != 'detect':
                    print col(u'[?] Could not determine volume information. Image may be empty, or volume system type '
                              u'{0} was incorrect.'.format(args.vstype.upper()), 'yellow')
                else:
                    print col(u'[?] Could not determine volume information. Image may be empty, or volume system type '
                              u'could not be detected. Try explicitly providing the volume system type with --vstype. ',
                              #u'Clues about what to use can be found by using:  parted {0} print'.format(p.get_raw_path()),
                              'yellow')
                if args.wait:
                    raw_input(col('>>> Press [enter] to continue... ', attrs=['dark']))

            print u'[+] Parsed all volumes for this image!'

            # Perform reconstruct if required
            if args.reconstruct:
                # Reverse order so '/' gets unmounted last
                p.partitions = list(reversed(sorted(p.partitions)))
                print "[+] Performing reconstruct... "
                root = p.reconstruct()
                if not root:
                    print col("[-] Failed reconstructing filesystem: could not find root directory.", 'red')
                else:
                    failed = filter(lambda x: not x.bindmountpoint and x.mountpoint and x != root, p.partitions)
                    if failed:
                        print "[+] Parts of the filesystem are reconstructed in {0}.".format(col(root.mountpoint, "green", attrs=["bold"]))
                        for m in failed:
                            print "    {0} was not reconstructed".format(m.mountpoint)
                    else:
                        print "[+] The entire filesystem is reconstructed in {0}.".format(col(root.mountpoint, "green", attrs=["bold"]))

                raw_input(col(">>> Press [enter] to unmount all volumes... ", attrs=['dark']))
            elif has_left_mounted:
                raw_input(col(">>> Some volumes were left mounted. Press [enter] to unmount all... ", attrs=['dark']))

        except KeyboardInterrupt:
            print u'\n[+] User pressed ^C, aborting...'
            return

        except Exception as e:
            print col("[-] {0}".format(e), 'red')
            raw_input(col(">>> Press [enter] to continue.", attrs=['dark']))

        finally:
            print u'[+] Analysis complete, unmounting...'

            # All done with this image, unmount it
            try:
                remove_rw = p.rw_active() and 'y' in raw_input('>>> Delete the rw cache file? [y/N] ').lower()
            except KeyboardInterrupt:
                remove_rw = False

            while True:
                if p.clean(remove_rw):
                    break
                else:
                    try:
                        print col("[-] Error unmounting base image. Perhaps volumes are still open?", 'red')
                        raw_input(col('>>> Press [enter] to retry unmounting, or ^C to cancel... ', attrs=['dark']))
                    except KeyboardInterrupt:
                        print ""  # ^C does not print \n
                        break
            print u"[+] All cleaned up"

            if num == len(args.images) - 1:
                print u'[+] Image processed, all done.'
            else:
                print u'[+] Image processed, proceeding with next image.'


if __name__ == '__main__':
    main()
