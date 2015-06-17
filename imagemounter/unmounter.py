from __future__ import unicode_literals

import glob
import os
import re
import tempfile
from imagemounter import _util


class Unmounter(object):
    """Allows easy unmounting of left-overs of ImageParser calls."""

    def __init__(self, casename=None, pretty=False, mountdir=None, allow_greedy=True, *args, **kwargs):
        """Instantiation of this class automatically indexes the mountpoints and loopbacks currently on the system.
        However, in the time between calling any ``find`` function and actually unmounting anything, the system may
        change. This can be especially painful when using :func:`preview_unmount`.

        :param str casename: The casename to be unmounted, see :class:`ImageParser`
        :param bool pretty: Whether the volumes were mounted using pretty mount, see :class:`Volume`
        :param str mountdir: The mountdir wheret he volumes were mounted, see :class:`Volume`
        :param bool allow_greedy: When none of the parameters are specified, by default, a greedy method will try to
                find as much possible mount points as possible.
        """

        self.mountpoints = {}
        self.loopbacks = {}

        # if any details provided, do not try to be greedy
        self.be_greedy = allow_greedy and not (casename or pretty or mountdir)

        mountdir = mountdir or tempfile.gettempdir()
        if casename:
            mountdir = os.path.join(mountdir, casename)

        if pretty:
            self.re_pattern = re.escape(mountdir) + r"/.*[0-9.]+-.+"
            self.glob_pattern = mountdir + "/*"
        else:
            self.re_pattern = re.escape(mountdir) + r"/im_[0-9.]+_.+"
            self.glob_pattern = mountdir + "/im_*"

        if casename:
            self.orig_re_pattern = re.escape(tempfile.gettempdir()) + r"/image_mounter_.*_" + re.escape(casename)
            self.orig_glob_pattern = tempfile.gettempdir() + "/image_mounter_*_" + casename
        else:
            self.orig_re_pattern = re.escape(tempfile.gettempdir()) + r"/image_mounter_.*"
            self.orig_glob_pattern = tempfile.gettempdir() + "/image_mounter_*"

        self._index_loopbacks()
        self._index_mountpoints()

    def preview_unmount(self):
        """Returns a list of all commands that would be executed if the :func:`unmount` method would be called.

        Note: any system changes between calling this method and calling :func:`unmount` aren't listed by this command.
        """

        commands = []
        for mountpoint in self.find_bindmounts():
            commands.append('umount {0}'.format(mountpoint))
        for mountpoint in self.find_mounts():
            commands.append('umount {0}'.format(mountpoint))
            commands.append('rm -Rf {0}'.format(mountpoint))
        for vgname, pvname in self.find_volume_groups():
            commands.append('lvchange -a n {0}'.format(vgname))
            commands.append('losetup -d {0}'.format(pvname))
        for mountpoint in self.find_base_images():
            commands.append('fusermount -u {0}'.format(mountpoint))
            commands.append('rm -Rf {0}'.format(mountpoint))
        for folder in self.find_clean_dirs():
            cmd = 'rm -Rf {0}'.format(folder)
            if cmd not in commands:
                commands.append(cmd)
        return commands

    def unmount(self):
        """Calls all unmount methods in the correct order."""

        self.unmount_bindmounts()
        self.unmount_mounts()
        self.unmount_volume_groups()
        self.unmount_base_images()
        self.clean_dirs()

    def _index_mountpoints(self):
        """Finds all mountpoints and stores them in :attr:`mountpoints`"""

        # find all mountponits
        self.mountpoints = {}
        # noinspection PyBroadException
        try:
            result = _util.check_output_(['mount'])
            for line in result.splitlines():
                m = re.match(r'(.+) on (.+) type (.+) \((.+)\)', line)
                if m:
                    self.mountpoints[m.group(2)] = (m.group(1), m.group(3), m.group(4))
        except Exception:
            pass

    def _index_loopbacks(self):
        """Finds all loopbacks and stores them in :attr:`loopbacks`"""

        self.loopbacks = {}
        try:
            result = _util.check_output_(['losetup', '-a'])
            for line in result.splitlines():
                m = re.match(r'(.+): (.+) \((.+)\).*', line)
                if m:
                    self.loopbacks[m.group(1)] = m.group(3)
        except Exception:
            pass

    def find_bindmounts(self):
        """Finds all bind mountpoints that are inside mounts that match the :attr:`re_pattern`"""

        for mountpoint, (orig, fs, opts) in self.mountpoints.items():
            if 'bind' in opts and re.match(self.re_pattern, mountpoint):
                yield mountpoint

    def find_mounts(self):
        """Finds all mountpoints that are mounted to a directory matching :attr:`re_pattern` or originate from a
        directory matching :attr:`orig_re_pattern`.
        """

        for mountpoint, (orig, fs, opts) in self.mountpoints.items():
            if 'bind' not in opts and (re.match(self.orig_re_pattern, orig) or
                                       (self.be_greedy and re.match(self.re_pattern, mountpoint))):
                yield mountpoint

    def find_base_images(self):
        """Finds all mountpoints that are mounted to a directory matching :attr:`orig_re_pattern`."""

        for mountpoint, _ in self.mountpoints.items():
            if re.match(self.orig_re_pattern, mountpoint):
                yield mountpoint

    def find_volume_groups(self):
        """Finds all volume groups that are mounted through a loopback originating from :attr:`orig_re_pattern`.

        Generator yields tuples of vgname, pvname
        """

        os.environ['LVM_SUPPRESS_FD_WARNINGS'] = '1'

        # find volume groups
        try:
            result = _util.check_output_(['pvdisplay'])
            pvname = vgname = None
            for line in result.splitlines():
                if '--- Physical volume ---' in line:
                    pvname = vgname = None
                elif "PV Name" in line:
                    pvname = line.replace("PV Name", "").strip()
                elif "VG Name" in line:
                    vgname = line.replace("VG Name", "").strip()

                if pvname and vgname:
                    try:
                        # unmount volume groups with a physical volume originating from a disk image
                        if re.match(self.orig_re_pattern, self.loopbacks[pvname]):
                            yield vgname, pvname
                    except Exception:
                        pass
                    pvname = vgname = None

        except Exception:
            pass

    def unmount_bindmounts(self):
        """Unmounts all bind mounts identified by :func:`find_bindmounts`"""

        for mountpoint in self.find_bindmounts():
            _util.clean_unmount(['umount'], mountpoint, rmdir=False)

    def unmount_mounts(self):
        """Unmounts all mounts identified by :func:`find_mounts`"""

        for mountpoint in self.find_mounts():
            _util.clean_unmount(['umount'], mountpoint)

    def unmount_base_images(self):
        """Unmounts all mounts identified by :func:`find_base_images`"""

        for mountpoint in self.find_base_images():
            _util.clean_unmount(['fusermount', '-u'], mountpoint)

    def unmount_volume_groups(self):
        """Unmounts all volume groups and related loopback devices as identified by :func:`find_volume_groups`"""

        for vgname, pvname in self.find_volume_groups():
            _util.check_output_(['lvchange', '-a', 'n', vgname])
            _util.check_output_(['losetup', '-d', pvname])

    def find_clean_dirs(self):
        """Finds all (temporary) directories according to the glob and re patterns that should be cleaned."""

        for folder in glob.glob(self.glob_pattern):
            if re.match(self.re_pattern, folder):
                yield folder
        for folder in glob.glob(self.orig_glob_pattern):
            if re.match(self.orig_re_pattern, folder):
                yield folder

    def clean_dirs(self):
        """Does a final cleaning of the (temporary) directories according to :func:`find_clean_dirs`."""

        for folder in self.find_clean_dirs():
            try:
                os.rmdir(folder)
            except Exception:
                pass