import time
import subprocess
import logging
import re
import glob
import os
import pdb


def unmount(cmd, mountpoint, tries=20):
    '''
    A method that unmounts the given mountpoint using the given unmounting
    command, giving it a couple of tries if necessary
    '''
    cmd.append(mountpoint)
    try_persistent(cmd, tries=tries)
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


def try_persistent(cmd, tries=20, wait=1):
    '''
    A subprocess helper method that will try a given command a few times, each
    with a given wait period between the commands and starting with one wait
    period. This helps with commands that require some time before they can be
    handled successfully, such as unmounting images
    '''
    for i in range(tries):
        try:
            time.sleep(wait)
            subprocess.check_call(cmd)
            break
        except subprocess.CalledProcessError:
            pass
        except OSError:
            logging.exception('Error while calling external program:')
            pdb.set_trace()


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
        return path
