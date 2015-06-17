from __future__ import print_function
from __future__ import unicode_literals

import logging
import time
import subprocess
import re
import glob
import os
import sys
import locale


logger = logging.getLogger(__name__)
encoding = locale.getdefaultlocale()[1]


def clean_unmount(cmd, mountpoint, tries=5, rmdir=True):
    cmd.append(mountpoint)

    # AVFS mounts are not actually unmountable, but are symlinked.
    if os.path.exists(os.path.join(mountpoint, 'avfs')):
        os.remove(os.path.join(mountpoint, 'avfs'))
        # noinspection PyProtectedMember
        logger.debug("Removed {}".format(os.path.join(mountpoint, 'avfs')))
    elif os.path.islink(mountpoint):
        pass  # if it is a symlink, we can simply skip to removing it
    else:
        # Perform unmount
        # noinspection PyBroadException
        try:
            check_call_(cmd)
        except:
            return False

    # Remove mountpoint only if needed
    if not rmdir:
        return True

    for _ in range(tries):
        if not os.path.ismount(mountpoint):
            # Unmount was successful, remove mountpoint
            if os.path.islink(mountpoint):
                os.unlink(mountpoint)
            else:
                os.rmdir(mountpoint)
            break
        else:
            time.sleep(1)

    if os.path.isdir(mountpoint):
        return False
    else:
        return True


def is_encase(path):
    return re.match(r'^.*\.E\w\w$', path)


def is_compressed(path):
    return re.match(r'^.*\.((zip)|(rar)|((t(ar\.)?)?gz))$', path)


def is_vmware(path):
    return re.match(r'^.*\.vmdk', path)


def expand_path(path):
    """
    Expand the given path to either an Encase image or a dd image
    i.e. if path is '/path/to/image.E01' then the result of this method will be
    /path/to/image.E*'
    and if path is '/path/to/image.001' then the result of this method will be
    '/path/to/image.[0-9][0-9]?'
    """
    if is_encase(path):
        return glob.glob(path[:-2] + '??')
    elif re.match(r'^.*\.\d{2,3}$', path):
        return glob.glob(path[:path.rfind('.')] + '.[0-9][0-9]?')
    else:
        return [path]


def command_exists(cmd):
    fpath, fname = os.path.split(cmd)
    if fpath:
        return os.path.isfile(cmd) and os.access(cmd, os.X_OK)
    else:
        for p in os.environ['PATH'].split(os.pathsep):
            p = p.strip('"')
            fp = os.path.join(p, cmd)
            if os.path.isfile(fp) and os.access(fp, os.X_OK):
                return True

    return False


def module_exists(mod):
    import importlib
    try:
        importlib.import_module(mod)
        return True
    except ImportError:
        return False


def check_call_(cmd, *args, **kwargs):
    logger.debug('$ {0}'.format(' '.join(cmd)))
    return subprocess.check_call(cmd, *args, **kwargs)


def check_output_(cmd, *args, **kwargs):
    logger.debug('$ {0}'.format(' '.join(cmd)))
    result = subprocess.check_output(cmd, *args, **kwargs)
    if result:
        result = result.decode(encoding)
    return result


def determine_slot(table, slot):
    if int(table) >= 0:
        return int(table) * 4 + int(slot) + 1
    else:
        return int(slot) + 1


def terminal_supports_color():
    return (sys.platform != 'Pocket PC' and (sys.platform != 'win32' or 'ANSICON' in os.environ)
            and hasattr(sys.stdout, 'isatty') and sys.stdout.isatty())
