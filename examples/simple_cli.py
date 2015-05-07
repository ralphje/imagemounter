"""This is a very basic CLI interface. This CLI is only provided as a concrete example for how to use the Python
interface of imagemounter. This is by no means a complete representation of the feature set of imagemounter. More
advanced options are available in the mount_images script.

However, the mount_images has become bloated, with additional checks for commands, manual overrides, etc. You
should use that script if you need some control, but this script should work perfectly too for very basic
functions.

Note that it doesn't unmount.
"""

from __future__ import absolute_import
from __future__ import print_function
import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

import argparse
import logging
import sys
from imagemounter import ImageParser, __version__
from termcolor import colored


def main():
    # We use argparse to parse arguments from the command line.
    parser = argparse.ArgumentParser(description='Simple CLI to mount disk images.')
    parser.add_argument('--version', action='version', version=__version__, help='display version and exit')
    parser.add_argument("-i", "--in", action='append', required=True, metavar='IN',
                        help="path(s) to the files you want to mount", dest='images')
    parser.add_argument("-o", "--out", help="directory to mount the volumes in", dest="mountdir")
    parser.add_argument("-c", "--casename", help="the name of the case (this is appended to the output dir)")
    parser.add_argument("-r", "--restore", action="store_true", help="carve unallocated space", dest="carve")
    parser.add_argument("-v", "--verbose", action="store_true", help="enable verbose output")
    args = parser.parse_args()

    # This sets up the logger. This is somewhat huge part of this example
    class ImageMounterFormatter(logging.Formatter):
        def format(self, record):
            msg = record.getMessage()
            if args.verbose and record.exc_info:
                if not record.exc_text:
                    record.exc_text = self.formatException(record.exc_info)
                if msg[-1:] != "\n":
                    msg += "\n"
                msg += record.exc_text
            if record.levelno >= logging.WARNING:
                return colored("[-] " + msg, 'cyan')
            elif record.levelno == logging.INFO:
                return colored("[+] " + msg, 'cyan')
            elif msg.startswith('$'):
                return colored("  " + msg, 'cyan')
            else:
                return colored("    " + msg, 'cyan')

    # Set logging level for internal Python
    handler = logging.StreamHandler()
    handler.setFormatter(ImageMounterFormatter())
    logger = logging.getLogger("imagemounter")
    logger.setLevel(logging.WARNING if not args.verbose else logging.DEBUG)
    logger.addHandler(handler)

    # This is the basic parser.
    parser = ImageParser(args.images, pretty=True, **vars(args))
    for volume in parser.init():
        # parser.init() loops over all volumes and mounts them
        if volume.mountpoint:
            # If the mountpoint is set, we have successfully mounted it
            print('[+] Mounted volume {0} on {1}.'.format(colored(volume.get_description(), attrs=['bold']),
                                                          colored(volume.mountpoint, 'green', attrs=['bold'])))

        elif volume.loopback:
            # If the mountpoint is not set, but a loopback is used, this is probably something like an LVM that did
            # not work properly.
            print('[+] Mounted volume {0} as loopback on {1}.'.format(colored(volume.get_description(), attrs=['bold']),
                                                                      colored(volume.loopback, 'green', attrs=['bold'])))
            print(colored('[-] Could not detect further volumes in the loopback device.', 'red'))

        elif volume.exception and volume.size is not None and volume.size <= 1048576:
            # If an exception occurred, but the volume is small, this is just a warning
            print(colored('[-] Exception while mounting small volume {0}'.format(volume.get_description()), 'yellow'))

        elif volume.exception:
            # Other exceptions are a bit troubling. Should never happen, actually.
            print(colored('[-] Exception while mounting {0}'.format(volume.get_description()), 'red'))

        elif volume.flag != 'meta' or args.verbose:
            # Meta volumes are not interesting enough to always show a warning about
            # Other volumes, we just print a warning that we couldn't mount it.
            print(colored('[-] Could not mount volume {0}'.format(volume.get_description()), 'yellow'))

        if args.carve and volume.flag != 'meta':
            # Carving is not neccesary on meta volumes, other volumes are carved for their unallocated space
            # or their entire space, depending on whether we could mount it.
            sys.stdout.write("[+] Carving volume...\r")
            sys.stdout.flush()
            if volume.carve(freespace=not volume.mountpoint):
                print('[+] Carved data is available at {0}.'.format(colored(volume.carvepoint, 'green', attrs=['bold'])))
            else:
                print(colored('[-] Carving failed.', 'red'))

if __name__ == '__main__':
    main()
