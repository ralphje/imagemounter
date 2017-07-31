# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import argparse
import cmd
import logging
import os
import shlex

import pickle

from imagemounter import __version__, DISK_MOUNTERS, FILE_SYSTEM_TYPES
from imagemounter.cli import CheckAction, get_coloring_func, ImageMounterStreamHandler
from imagemounter.disk import Disk
from imagemounter.parser import ImageParser


SAVE_PATH = os.path.expanduser("~/.imountshell")


class ShellArgumentParser(argparse.ArgumentParser):
    _exit = False

    def exit(self, status=0, message=None):
        if message:
            self._print_message(message)
        raise Exception()  # stop the loop and lookup.


class ArgumentParsedShell(cmd.Cmd):
    def __init__(self):
        cmd.Cmd.__init__(self)
        self._make_argparser()

    def _make_argparser(self):
        """Makes a new argument parser."""
        self.argparser = ShellArgumentParser(prog='')
        subparsers = self.argparser.add_subparsers()

        for name in self.get_names():
            if name.startswith('parser_'):
                parser = subparsers.add_parser(name[7:])
                parser.set_defaults(func=getattr(self, 'arg_' + name[7:]))
                getattr(self, name)(parser)

        self.argparser_completer = None

        try:
            import argcomplete
        except ImportError:
            pass
        else:
            os.environ.setdefault("_ARGCOMPLETE_COMP_WORDBREAKS", " \t\"'")
            self.argparser_completer = argcomplete.CompletionFinder(self.argparser)

    def postcmd(self, stop, line):
        self._make_argparser()  # load argparser again to reload options
        return stop

    def complete(self, text, state):
        """Overridden to reset the argument parser after every completion (argcomplete fails :()"""
        result = cmd.Cmd.complete(self, text, state)
        if self.argparser_completer:
            self._make_argparser()
            # argparser screws up with internal states, this is the best way to fix it for now
        return result

    def default(self, line):
        """Overriding default to get access to any argparse commands we have specified."""

        if any((line.startswith(x) for x in self.argparse_names())):
            try:
                args = self.argparser.parse_args(shlex.split(line))
            except Exception:  # intentionally catches also other errors in argparser
                pass
            else:
                args.func(args)
        else:
            cmd.Cmd.default(self, line)

    def completedefault(self, text, line, begidx, endidx):
        """Accessing the argcompleter if available."""
        if self.argparser_completer and any((line.startswith(x) for x in self.argparse_names())):
            self.argparser_completer.rl_complete(line, 0)
            return [x[begidx:] for x in self.argparser_completer._rl_matches]
        else:
            return []

    def argparse_names(self, prefix=""):
        return [a[4:] for a in self.get_names() if a.startswith("arg_" + prefix)]

    def completenames(self, text, *ignored):
        """Patched to also return argparse commands"""
        return sorted(cmd.Cmd.completenames(self, text, *ignored) + self.argparse_names(text))

    def do_help(self, arg):
        """Patched to show help for arparse commands"""
        if not arg or arg not in self.argparse_names():
            cmd.Cmd.do_help(self, arg)
        else:
            try:
                self.argparser.parse_args([arg, '--help'])
            except Exception:
                pass

    def print_topics(self, header, cmds, cmdlen, maxcol):
        """Patched to show all argparse commands as being documented"""
        if header == self.doc_header:
            cmds.extend(self.argparse_names())
        cmd.Cmd.print_topics(self, header, sorted(cmds), cmdlen, maxcol)


class ImageMounterShell(ArgumentParsedShell):
    prompt = '(imount) '
    file = None
    parser = None
    args = None
    saved = False

    def save(self):
        with open(SAVE_PATH, 'wb') as f:
            pickle.dump(self.parser, f)
        self.saved = True

    def load(self):
        with open(SAVE_PATH, 'rb') as f:
            self.parser = pickle.load(f)

    def preloop(self):
        """if the parser is not already set, loads the parser."""
        if not self.parser:
            self.stdout.write("Welcome to imagemounter {version}".format(version=__version__))
            self.stdout.write("\n")

            self.parser = ImageParser()
            for p in self.args.paths:
                self.onecmd('disk "{}"'.format(p))

    def onecmd(self, line):
        """Do not crash the entire program when a single command fails."""
        try:
            return cmd.Cmd.onecmd(self, line)
        except Exception as e:
            print("Critical error.", e)

    def error(self, error):
        """Writes an error to the console"""
        self.stdout.write('*** %s\n' % error)

    def _get_all_indexes(self):
        """Returns all indexes available in the parser"""
        if self.parser:
            return [v.index for v in self.parser.get_volumes()] + [d.index for d in self.parser.disks]
        else:
            return None

    def _get_by_index(self, index):
        """Returns a volume,disk tuple for the specified index"""
        volume_or_disk = self.parser.get_by_index(index)
        volume, disk = (volume_or_disk, None) if not isinstance(volume_or_disk, Disk) else (None, volume_or_disk)
        return volume, disk

    ######################################################################
    # disk command
    ######################################################################

    def parser_disk(self, parser):
        parser.description = "Add a disk to the current parser"
        p = parser.add_argument('path', help='path to the disk image that you want to mount')
        try:
            from argcomplete.completers import FilesCompleter
            p.completer = FilesCompleter([".dd", ".e01", ".aff", ".DD", ".E01", ".AFF"])
        except ImportError:
            pass
        parser.add_argument("--mounter", choices=DISK_MOUNTERS, help="the method to mount with")

    def arg_disk(self, args):
        args.path = os.path.expanduser(args.path)
        if not os.path.exists(args.path):
            return self.error("The path {path} does not exist".format(path=args.path))
        disk = self.parser.add_disk(args.path, disk_mounter=args.mounter)
        disk.mount()
        for _ in disk.detect_volumes():
            pass
        print("Added {path} to the image mounter as index {index}".format(path=args.path, index=disk.index))

    ######################################################################
    # mount command
    ######################################################################

    def parser_mount(self, parser):
        parser.description = "Mount a volume or disk by its index"
        parser.add_argument('index', help='volume or disk index', choices=self._get_all_indexes())
        parser.add_argument('-r', '--recursive', action='store_true',
                            help='recursively mount all volumes under this index')
        parser.add_argument('-f', '--fstype', default=None, choices=FILE_SYSTEM_TYPES,
                            help='specify the file system type for the volume')
        parser.add_argument('-k', '--key', default=None,
                            help='specify the key for the volume')

    def arg_mount(self, args):
        col = get_coloring_func()
        volume, disk = self._get_by_index(args.index)

        if not args.recursive:
            if disk:
                if not disk.is_mounted:
                    try:
                        disk.mount()
                    except Exception as e:
                        pass
                else:
                    print(col("Disk {} is already mounted.".format(disk.index), 'red'))
            else:
                if not volume.is_mounted:
                    try:
                        if args.key is not None:
                            volume.key = args.key
                        volume.init_volume(fstype=args.fstype)
                        if volume.is_mounted:
                            if volume.mountpoint:
                                print("Mounted volume {index} at {path}"
                                      .format(path=col(volume.mountpoint, "green", attrs=['bold']),
                                              index=volume.index))
                            else:
                                print("Mounted volume {index} (no mountpoint available)".format(index=volume.index))
                        else:
                            print("Refused to mount volume {index}.".format(index=volume.index))
                    except Exception as e:
                        print(col("An error occurred while mounting volume {index}: {type}: {args}"
                                  .format(type=type(e).__name__,
                                          args=" ".join(map(str, e.args)),
                                          index=volume.index), "red"))
                else:
                    if volume.mountpoint:
                        print(col("Volume {} is already mounted at {}.".format(volume.index, volume.mountpoint), 'red'))
                    else:
                        print(col("Volume {} is already mounted.".format(volume.index), 'red'))
        else:
            if disk:
                if not disk.is_mounted:
                    try:
                        disk.mount()
                    except Exception as e:
                        pass
                it = disk.init_volumes
            else:
                it = volume.init
            for v in it():
                if v.mountpoint:
                    print("Mounted volume {index} at {path}"
                          .format(path=col(v.mountpoint, "green", attrs=['bold']),
                                  index=v.index))
                elif v.exception:
                    e = v.exception
                    print(col("An error occurred while mounting volume {index}: {type}: {args}"
                              .format(type=type(e).__name__,
                                      args=" ".join(map(str, e.args)),
                                      index=v.index), "red"))

    ######################################################################
    # unmount command
    ######################################################################

    def parser_unmount(self, parser):
        parser.description = "Unmount a disk or volume by its index. Is recursive by design."
        parser.add_argument('index', help='volume index', nargs='?', choices=self._get_all_indexes())

    def arg_unmount(self, args):
        if args.index:
            volume = self.parser.get_by_index(args.index)
            volume.unmount()
            print("Unmounted {index}".format(index=volume.index))
        else:
            self.parser.clean()
            print("Unmounted everything")

    ######################################################################
    # show command
    ######################################################################

    def parser_show(self, parser):
        parser.description = "Without arguments, displays a tree view of all known volumes and disks. With an " \
                             "argument, it provides details about the referenced volume or disk."
        parser.add_argument('index', help='volume index', nargs='?', choices=self._get_all_indexes())

    def arg_show(self, args):
        if not args.index:
            self._show_tree()
        else:
            col = get_coloring_func()
            volume, disk = self._get_by_index(args.index)

            # displays a volume's details
            if volume:
                print(col("Details of volume {description}".format(description=volume.get_description()),
                          attrs=['bold']))
                if volume.is_mounted:
                    print(col("Currently mounted", 'green'))

                print("\nAttributes:")
                for attr in ['size', 'offset', 'slot', 'flag', 'block_size', 'fstype', 'key']:
                    print(" - {name:<15} {value}".format(name=attr, value=getattr(volume, attr)))

                if volume.mountpoint or volume.loopback or volume._paths:
                    print("\nPaths:")
                    if volume.mountpoint:
                        print(" - mountpoint      {value}".format(value=volume.mountpoint))
                    if volume.loopback:
                        print(" - loopback        {value}".format(value=volume.loopback))
                    for k, v in volume._paths.items():
                        print(" - {name:<15} {value}".format(name=k, value=v))

                if volume.info:
                    print("\nAdditional information:")
                    for k, v in volume.info.items():
                        print(" - {name:<15} {value}".format(name=k, value=v))

            else:  # displays a disk's details
                print(col("Details of disk {description}".format(description=disk.paths[0]), attrs=['bold']))
                if disk.is_mounted:
                    print(col("Currently mounted", 'green'))

                print("\nAttributes:")
                for attr in ['offset', 'block_size', 'read_write', 'disk_mounter']:
                    print(" - {name:<15} {value}".format(name=attr, value=getattr(disk, attr)))

                if disk.mountpoint or disk.rwpath or disk._paths:
                    print("\nPaths:")
                    if disk.mountpoint:
                        print(" - mountpoint      {value}".format(value=disk.mountpoint))
                    if disk.rwpath:
                        print(" - rwpath          {value}".format(value=disk.rwpath))
                    for k, v in disk._paths.items():
                        print(" - {name:<15} {value}".format(name=k, value=v))

    def _show_tree(self):
        col = get_coloring_func()

        for disk in self.parser.disks:
            print("- {index:<5}  {type} {filename}".format(
                index=col("{:<5}".format(disk.index), 'green' if disk.is_mounted else None, attrs=['bold']),
                type=col("{:<10}".format(disk.volumes.vstype), attrs=['dark']),
                filename=disk.paths[0]
            ))

            def _show_volume_system(volumes, level=0):
                level += 1
                for i, v in enumerate(volumes):
                    level_str = "  " * level + ("└ " if i == len(volumes) - 1 else "├ ")
                    tp = v.volumes.vstype if v.fstype == 'volumesystem' else v.fstype if v.flag == 'alloc' else v.flag

                    print("{level_str}{index}  {type} {size:<10}  {description}".format(
                        level_str=level_str,
                        index=col("{:<5}".format(v.index), 'green' if v.is_mounted else None, attrs=['bold']),
                        type=col("{:<10}".format(tp), attrs=['dark']),
                        description=v.get_description(with_index=False, with_size=False)[:30],
                        size=v.get_formatted_size()
                    ))
                    _show_volume_system(v.volumes, level)

            _show_volume_system(disk.volumes)

    ######################################################################
    # set command
    ######################################################################

    def parser_set(self, parser):
        parser.description = "Modifies a property of a volume or disk. This is for advanced usage only."
        parser.add_argument('index', help='volume index', choices=self._get_all_indexes())
        parser.add_argument('name', help='property name', choices=['size', 'offset', 'slot', 'flag', 'block_size',
                                                                   'fstype', 'key', 'disk_mounter'])
        parser.add_argument('value', help='property value')

    def arg_set(self, args):
        col = get_coloring_func()
        volume, disk = self._get_by_index(args.index)

        if volume:
            if args.name in ['size', 'offset', 'block_size']:
                try:
                    setattr(volume, args.name, int(args.value))
                except ValueError:
                    print(col("Invalid value provided for {}".format(args.name), 'red'))
                else:
                    print(col("Updated value for {}".format(args.name), 'green'))
            elif args.name in ['slot', 'flag', 'fstype', 'key']:
                setattr(volume, args.name, args.value)
                print(col("Updated value for {}".format(args.name), 'green'))
            else:
                print(col("Property {} can't be set for a volume".format(args.name), 'red'))

        else:
            if args.name in ['offset', 'block_size']:
                try:
                    setattr(disk, args.name, int(args.value))
                except ValueError:
                    print(col("Invalid value provided for {}".format(args.name), 'red'))
                else:
                    print(col("Updated value for {}".format(args.name), 'green'))
            elif args.name in ['disk_mounter']:
                setattr(disk, args.name, args.value)
                print(col("Updated value for {}".format(args.name), 'green'))
            else:
                print(col("Property {} can't be set for a disk".format(args.name), 'red'))

    ######################################################################
    # quit command
    ######################################################################

    def do_save(self, arg):
        self.save()

    def do_EOF(self, arg):
        self.save()
        return True

    def do_quit(self, arg):
        """Quits the program."""
        if self.saved:
            self.save()
        else:
            self.parser.clean()
        return True


def main():
    parser = argparse.ArgumentParser(description='Shell to mount disk images locally.')
    parser.add_argument('--version', action='version', version=__version__, help='display version and exit')
    parser.add_argument('--check', action=CheckAction, nargs=0,
                        help='do a system check and list which tools are installed')
    parser.add_argument('-v', '--verbose', action='count', default=False, help='enable verbose output')
    parser.add_argument('-i', '--interactive', action='store_true', default=False, help='ignored option')
    parser.add_argument('paths', nargs='*', help='path(s) to the image(s) that you want to mount')

    args = parser.parse_args()
    col = get_coloring_func()

    print(col("WARNING: the interactive console is still in active development.", attrs=['dark']))

    handler = ImageMounterStreamHandler(col, args.verbose)
    logger = logging.getLogger("imagemounter")
    logger.setLevel({0: logging.CRITICAL, 1: logging.WARNING, 2: logging.INFO}.get(args.verbose, logging.DEBUG))
    logger.handlers = []
    logger.addHandler(handler)

    shell = ImageMounterShell()
    shell.args = args
    if os.path.exists(SAVE_PATH):
        try:
            inp = raw_input
        except NameError:
            inp = input
        if 'n' not in inp('>>> Do wish to continue your previous session? [Y/n] ').lower():
            shell.load()
        os.unlink(SAVE_PATH)

    while True:
        try:
            shell.cmdloop()
        except KeyboardInterrupt:
            print("Please exit using the 'quit' command.")
        else:
            break


if __name__ == '__main__':
    main()
