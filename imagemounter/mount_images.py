#!/usr/bin/env python
import argparse
import sys
import os

from imagemounter import util, ImageParser
from termcolor import colored


def main():
    class MyParser(argparse.ArgumentParser):
        def error(self, message):
            sys.stderr.write('error: {0}\n'.format(message))
            self.print_help()
            sys.exit(2)

    parser = MyParser(description=u'Utility to mount partitions in Encase and dd images locally.')
    parser.add_argument('images', nargs='+',
                        help='Path(s) to the image(s) that you want to mount. In case the image is '
                             'split up in multiple files, just use the first file (e.g. the .E01 or .001 file).')
    parser.add_argument('-c', '--color', action='store_true', default=False, help='Colorize the output.')
    parser.add_argument('-w', '--wait', action='store_true', default=False, help='Pause on some additional warnings.')
    parser.add_argument('-r', '--reconstruct', action='store_true', default=False,
                        help='Attempt to reconstruct the full filesystem tree. Implies -s and mounts all partitions '
                             'at once.')
    parser.add_argument('-rw', '--read-write', action='store_true', default=False,
                        help='Mount image read-write by creating a local write-cache file in a temp directory. '
                             'Implies --method=xmount.')
    parser.add_argument('-s', '--stats', action='store_true', default=False,
                        help='Show limited information from fsstat. Will slow down mounting and may cause random '
                             'issues such as partitions being unreadable.')
    parser.add_argument('-m', '--method', choices=['xmount', 'affuse', 'ewfmount', 'auto'], default='auto',
                        help='Use "xmount", "ewfmount" or "affuse" to mount the initial images. Results may vary '
                             'between methods, if something doesn\'t work, try another method. Pick the best '
                             'automatically with "auto". Default=auto')
    parser.add_argument('-md', '--mountdir', default=None,
                        help='Specify directory for partition mountpoints. Default=temporary directory')
    parser.add_argument('-l', '--loopback', default='/dev/loop0',
                        help='Specify loopback device for LVM partitions. Default=/dev/loop0')
    parser.add_argument('-vs', '--vstype', choices=['detect', 'dos', 'bsd', 'sun', 'mac', 'gpt', 'dbfiller'],
                        default="detect", help='Specify type of volume system (partition table). Default=detect')
    parser.add_argument('-fs', '--fstype', choices=['ext', 'ufs', 'ntfs', 'lvm'], default=None,
                        help="Specify the type of the filesystem. Used to override automatic detection.")
    parser.add_argument('-v', '--verbose', action='store_true', default=False, help='Enable verbose output.')
    args = parser.parse_args()

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

    # Reconstruct implies use of fsstat
    if args.reconstruct:
        args.stats = True

    if args.stats and not util.command_exists('fsstat'):
        print "[-] To obtain stats, the fsstat command is used (part of sleuthkit package), but is not installed. " \
              "Stats will not be obtained during this session."
        args.stats = False

        if args.reconstruct:
            print "[-] Reconstruction is now impossible!"
            sys.exit(1)

    for num, image in enumerate(args.images):
        if not os.path.exists(image):
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
            print u'[+] Mounted raw image [{num}/{total}], now mounting partitions...'.format(num=num + 1,
                                                                                              total=len(args.images))

            sys.stdout.write("[+] Mounting partition 0...\r")
            sys.stdout.flush()

            i = 0
            has_left_mounted = False
            for partition in p.mount_partitions():
                i += 1

                if not partition.mountpoint and not partition.loopback:
                    if partition.exception:
                        print col(u'[-] Exception while mounting {0}'.format(partition), 'red')
                        raw_input(col('>>> Press [enter] to continue... ', attrs=['dark']))
                    else:
                        print col(u'[-] Could not mount partition {0}'.format(partition), 'yellow')
                        if args.wait:
                            raw_input(col('>>> Press [enter] to continue... ', attrs=['dark']))

                    continue

                try:
                    if partition.mountpoint:
                        print u'[+] Mounted partition {0} on {1}.'.format(col(partition.get_description(), attrs=['bold']),
                                                                          col(partition.mountpoint, 'green', attrs=['bold']))
                    elif partition.loopback:  # fallback, generally indicates error.
                        print u'[+] Mounted partition {0} as loopback on {1}.'.format(col(partition.get_description(), attrs=['bold']),
                                                                                      col(partition.loopback, 'green', attrs=['bold']))
                        print u'[+] Additional partitions may be available from this loopback device. These are not ' \
                              u'managed by this utility and you must unmount these manually before continuing.'

                    # Do not offer unmount when reconstructing
                    if args.reconstruct:
                        has_left_mounted = True
                        continue

                    raw_input(col('>>> Press [enter] to unmount the partition, or ^C to keep mounted... ', attrs=['dark']))

                    # Case where image should be unmounted, but has failed to do so. Keep asking whether the user wants
                    # to unmount.
                    while True:
                        if partition.unmount():
                            break
                        else:
                            try:
                                print col("[-] Error unmounting partition. Perhaps files are still open?", "red")
                                raw_input(col('>>> Press [enter] to retry unmounting, or ^C to skip... ', attrs=['dark']))
                            except KeyboardInterrupt:
                                has_left_mounted = True
                                print ""
                                break
                except KeyboardInterrupt:
                    has_left_mounted = True
                    print ""
                sys.stdout.write("[+] Mounting partition {0}{1}\r".format(i, col("...", attrs=['blink'])))
                sys.stdout.flush()
            if i == 0:
                print col(u'[?] Could not determine volume information, possible empty image?', 'yellow')
                if args.wait:
                    raw_input(col('>>> Press [enter] to continue... ', attrs=['dark']))

            print u'[+] Parsed all partitions for this image!'

            # Perform reconstruct if required
            if args.reconstruct:
                # Reverse order so '/' gets unmounted last
                p.partitions = list(reversed(sorted(p.partitions)))
                print "[+] Performing reconstruct... "
                root = p.reconstruct()
                if not root:
                    print col("[-] Failed reconstructing filesystem: could not find root directory.", 'red')
                else:
                    print "[+] The entire filesystem is reconstructed in {0}.".format(col(root.mountpoint, "green", attrs=["bold"]))
                    for m in filter(lambda x: not x.bindmount and x.mountpoint and x != root, p.partitions):
                        print "    {0} was not reconstructed".format(m.mountpoint)

                raw_input(col(">>> Press [enter] to unmount all partitions... ", attrs=['dark']))
            elif has_left_mounted:
                raw_input(col(">>> Some partitions were left mounted. Press [enter] to unmount all... ", attrs=['dark']))

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
                        print col("[-] Error unmounting base image. Perhaps partitions are still open?", 'red')
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
