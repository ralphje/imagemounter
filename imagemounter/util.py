import time
import subprocess
import re
import glob
import os


def clean_unmount(cmd, mountpoint, tries=20, rmdir=True):
    cmd.append(mountpoint)

    # Perform unmount
    try:
        subprocess.check_call(cmd)
    except:
        return False

    # Remove mountpoint only if needed
    if not rmdir:
        return True

    for _ in range(tries):
        if not os.listdir(mountpoint):
            # Unmount was successful, remove mountpoint
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


def expand_path(path):
    '''
    Expand the given path to either an Encase image or a dd image
    i.e. if path is '/path/to/image.E01' then the result of this method will be
    /path/to/image.E*'
    and if path is '/path/to/image.001' then the result of this method will be
    '/path/to/image.[0-9][0-9]?'
    '''
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


def check_call_(cmd, parser=None, *args, **kwargs):
    if parser:
        parser._debug('    {0}'.format(' '.join(cmd)))
    return subprocess.check_call(cmd, *args, **kwargs)


def check_output_(cmd, parser=None, *args, **kwargs):
    if parser:
        parser._debug('    {0}'.format(' '.join(cmd)))
    return subprocess.check_output(cmd, *args, **kwargs)
