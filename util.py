import time
import subprocess
import logging
import re
import glob
import os


def unmount(cmd, mountpoint, tries=20):
    '''
    A method that unmounts the given mountpoint using the given unmounting
    command, giving it a couple of tries if necessary
    '''
    cmd.append(mountpoint)
    while True:
        try:
            subprocess.check_call(cmd)
            break
        except:
            try:
                print u'There are still files open in the mountpoint! Press [enter] to try again. If you want to skip unmounting, press ^C!'
                raw_input('>>>')
            except KeyboardInterrupt:
                break

    for _ in range(tries):
        if os.listdir(mountpoint) == []:
            # Unmount was successful, remove mountpoint
            os.rmdir(mountpoint)
            break
        else:
            time.sleep(1)
    if os.path.isdir(mountpoint):
        logging.warning(u'Could not unmount "{0}"!'.format(mountpoint))
    else:
        return True
    return False


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
