import argparse
import logging
from imagemounter import _util


class CheckAction(argparse.Action):
    """Action that checks the current state of the system according to the command requirements that imount has."""

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
            if hasattr(magic, 'from_file'):
                print(" INSTALLED {:<20}(Python package)".format(pip_name))
            elif hasattr(magic, 'open'):
                print(" INSTALLED {:<20}(system package)".format(pip_name))
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
        self._check_command("mountavfs", "avfs", "compressed disk images")
        self._check_command("qemu-nbd", "qemu-utils", "Qcow2 images")
        print("-- Detecting volumes and volume types (at least one required) --")
        self._check_command("mmls", "sleuthkit")
        self._check_module("pytsk3")
        self._check_command("parted", "parted")
        print("-- Detecting volume types (all recommended, first two highly recommended) --")
        self._check_command("fsstat", "sleuthkit")
        self._check_command("file", "libmagic1")
        self._check_command("blkid")
        self._check_module("magic", "python-magic")
        self._check_command("disktype", "disktype")
        print("-- Mounting volumes (install when needed) --")
        self._check_command("mount.xfs", "xfsprogs", "XFS volumes")
        self._check_command("mount.ntfs", "ntfs-3g", "NTFS volumes")
        self._check_command("lvm", "lvm2", "LVM volumes")
        self._check_command("vmfs-fuse", "vmfs-tools", "VMFS volumes")
        self._check_command("mount.jffs2", "mtd-tools", "JFFS2 volumes")
        self._check_command("mount.squashfs", "squashfs-tools", "SquashFS volumes")
        self._check_command("mdadm", "mdadm", "RAID volumes")
        self._check_command("cryptsetup", "cryptsetup", "LUKS containers")
        self._check_command("bdemount", "libbde-utils", "Bitlocker Drive Encryption volumes")
        self._check_command("vshadowmount", "libvshadow-utils", "NTFS volume shadow copies")
        parser.exit()


class AppendDictAction(argparse.Action):
    """argparse method that parses a command-line dict to an actual dict::

        a=1      ->  {'a': '1'}
        a=1,b=2  ->  {'a': '1', 'b': '2'}
        123      ->  {'*': '123'}

    """

    def __init__(self, allow_commas=True, *args, **kwargs):
        self.allow_commas = allow_commas
        super(AppendDictAction, self).__init__(*args, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        items = getattr(namespace, self.dest, {}) or {}
        if ',' not in values and '=' not in values:
            items['*'] = values
        else:
            try:
                if self.allow_commas:
                    vals = values.split(',')
                    for t in vals:
                        k, v = t.split('=', 1)
                        items[k] = v
                else:
                    k, v = values.split('=', 1)
                    items[k] = v
            except ValueError:
                parser.error("could not parse {}".format(self.dest))
        setattr(namespace, self.dest, items)


class ImageMounterStreamHandler(logging.StreamHandler):
    terminator = "\n"

    def __init__(self, colored_func=None, verbosity=0, *args, **kwargs):
        super(ImageMounterStreamHandler, self).__init__(*args, **kwargs)
        self.setFormatter(ImageMounterFormatter(colored_func, verbosity=verbosity))

    def emit(self, record):
        if record.getMessage().startswith("<") and self.formatter.verbosity <= 3:
            return
        return super(ImageMounterStreamHandler, self).emit(record)


class ImageMounterFormatter(logging.Formatter):
    """Formats logging messages according to ImageMounter's format."""

    def __init__(self, colored_func, verbosity=0):
        super(ImageMounterFormatter, self).__init__()
        self.colored_func = colored_func
        self.verbosity = verbosity

    def format(self, record):
        msg = record.getMessage()
        if self.verbosity >= 4 and record.exc_info:
            if not record.exc_text:
                record.exc_text = self.formatException(record.exc_info)
            if msg[-1:] != "\n":
                msg += "\n"
            msg += record.exc_text
        if record.levelno >= logging.WARNING:
            return self.colored_func("[-] " + msg, 'cyan')
        elif record.levelno == logging.INFO:
            return self.colored_func("[+] " + msg, 'cyan')
        elif msg.startswith('$'):
            return self.colored_func("  " + msg, 'cyan')
        elif msg.startswith('<'):
            if self.verbosity >= 4:
                return self.colored_func("  " + "\n  < ".join(msg.splitlines()), 'cyan')
            else:
                return ""
        else:
            return self.colored_func("    " + msg, 'cyan')


def get_coloring_func(color=False, no_color=False):
    # Colorize the output by default if the terminal supports it
    if not color and no_color:
        color = False
    elif color:
        color = True
    else:
        color = _util.terminal_supports_color()

    if not color:
        # noinspection PyUnusedLocal,PyShadowingNames
        def col(s, *args, **kwargs):
            return s
        return col
    else:
        from termcolor import colored
        return colored
