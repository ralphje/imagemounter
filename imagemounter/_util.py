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

from imagemounter.exceptions import SubsystemError, CleanupError, NoNetworkBlockAvailableError

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
    elif not os.path.ismount(mountpoint):
        pass  # if is not a mount point, we can simply skip to removing it
    else:
        # Perform unmount
        # noinspection PyBroadException
        try:
            check_call_(cmd)
        except Exception as e:
            raise SubsystemError(e)

    # Remove mountpoint only if needed
    if not rmdir:
        return

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
        raise CleanupError()


def is_encase(path):
    return re.match(r'^.*\.[Ee][Xx]?\d\d$', path)


def is_compressed(path):
    return re.match(r'^.*\.((zip)|(rar)|((t(ar\.)?)?gz))$', path)


def is_vmware(path):
    return re.match(r'^.*\.vmdk', path)


def is_qcow2(path):
    return re.match(r'.*\.qcow2', path)


def expand_path(path):
    """
    Expand the given path to either an Encase image or a dd image
    i.e. if path is '/path/to/image.E01' then the result of this method will be
    /path/to/image.E*'
    and if path is '/path/to/image.001' then the result of this method will be
    '/path/to/image.[0-9][0-9]?'
    """
    if is_encase(path):
        return glob.glob(path[:-2] + '??') or [path]
    elif re.match(r'^.*\.\d{2,3}$', path):
        return glob.glob(path[:path.rfind('.')] + '.[0-9][0-9]?') or [path]
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


def check_call_(cmd, wrap_error=False, *args, **kwargs):
    logger.debug('$ {0}'.format(' '.join(cmd)))
    try:
        return subprocess.check_call(cmd, *args, **kwargs)
    except Exception as e:
        if wrap_error:
            raise SubsystemError(e)
        else:
            raise


def check_output_(cmd, *args, **kwargs):
    logger.debug('$ {0}'.format(' '.join(cmd)))
    try:
        result = subprocess.check_output(cmd, *args, **kwargs)
        if result:
            result = result.decode(encoding)
            logger.debug('< {0}'.format(result))
        return result
    except subprocess.CalledProcessError as e:
        if e.output:
            result = e.output.decode(encoding)
            logger.debug('< {0}'.format(result))
        raise


def get_free_nbd_device():
    for nbd_path in glob.glob("/sys/class/block/nbd*"):
        try:
            if check_output_(["cat", "{0}/size".format(nbd_path), ]).strip() == "0":
                return "/dev/{}".format(os.path.basename(nbd_path))
        except subprocess.CalledProcessError as e:
            if e.output:
                result = e.output.decode(encoding)
                logger.debug("< {0}".format(result))
    raise NoNetworkBlockAvailableError()


def determine_slot(table, slot):
    if int(table) >= 0:
        return int(table) * 4 + int(slot) + 1
    else:
        return int(slot) + 1


def terminal_supports_color():
    return (sys.platform != 'Pocket PC' and (sys.platform != 'win32' or 'ANSICON' in os.environ) and
            hasattr(sys.stdout, 'isatty') and sys.stdout.isatty())
