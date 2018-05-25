import argparse
import logging
from imagemounter import _util, dependencies


class CheckAction(argparse.Action):
    """Action that checks the current state of the system according to the command requirements that imount has."""

    # noinspection PyShadowingNames
    def __call__(self, parser, namespace, values, option_string=None):
        print("The following commands are used by imagemounter internally. Without most commands, imagemounter "
              "works perfectly fine, but may lack some detection or mounting capabilities.")

        for section in dependencies.ALL_SECTIONS:
            print(section.printable_status)

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
