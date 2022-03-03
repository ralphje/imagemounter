"""Dependencies (optional and required) for the imagemounter package."""
import subprocess
from builtins import NotImplementedError

from imagemounter import _util
from imagemounter.exceptions import PrerequisiteFailedError, CommandNotFoundError, ModuleNotFoundError
import functools


def require(*requirements, none_on_failure=False):
    """Decorator that can be used to require requirements.

    :param requirements: List of requirements that should be verified
    :param none_on_failure: If true, does not raise a PrerequisiteFailedError, but instead returns None
    """

    def inner(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            for req in requirements:
                if none_on_failure:
                    if not req.is_available:
                        return None
                else:
                    req.require()
            return f(*args, **kwargs)
        return wrapper
    return inner


class Dependency:
    """An abstract class representing external tools imagemounter depends on.

    Subclasses of this class should define :attr:`is_available` and :attr:`status_message`.

    :param str name: name for the dependency; used in status messages and as the ``__str__()`` representation.
    :param str package: the package that can be installed to provide this dependency.
    :param str why: description of why this dependency is useful; used in status messages to help user decide if they
        need to install the dependency package.
    """

    def __init__(self, name, package="", why=""):
        self.name = name
        self.package = package
        self.why = why

    def __str__(self):
        return self.name

    @property
    def is_available(self):
        """Returns whether the dependency is available on the system.

        "Available" generally means that the system has this dependency installed and configured correctly to be used.

        :rtype: bool
        """
        raise NotImplementedError()

    @property
    def status_message(self):
        """Detailed message about whether the dependency is installed.

        This message may specify it is installed or not, how and why to install it, etc.

        The string may contain format specifiers; the ``printable_status`` property interpolates the current
        dependency object as ``{0}``.

        :rtype: str
        """
        if self.is_available:
            return "INSTALLED {0!s}"
        elif self.why and self.package:
            return "MISSING   {0!s:<20}needed for {0.why}, part of the {0.package} package"
        elif self.why:
            return "MISSING   {0!s:<20}needed for {0.why}"
        elif self.package:
            return "MISSING   {0!s:<20}part of the {0.package} package"
        else:
            return "MISSING   {0!s:<20}"

    def require(self, *a, **kw):
        """Raises an error when the specified requirement is not available.
        """
        if not self.is_available:
            raise PrerequisiteFailedError(str(self))

    @property
    def printable_status(self):
        """A printable message about the status of the dependency.

        :return: the status of the dependency
        :rtype: str
        """
        return self.status_message.format(self)


class CommandDependency(Dependency):
    """A dependency on a CLI command"""

    def require(self):
        if not self.is_available:
            raise CommandNotFoundError(str(self))

    @property
    def is_available(self):
        return _util.command_exists(self.name)


class FileSystemTypeDependency(Dependency):
    """A dependency on the fact that an entry is available in /proc/filesystems or the fact that a kernel module exists
    that can be dynamically loaded to support this. In other words, ``mount -t xxx`` should work.
    """

    def _is_loaded(self):
        """check the filesystem is loaded directly"""
        with open("/proc/filesystems", "r") as f:
            for l in f:
                if l.split()[-1] == self.name:
                    return True
        return False

    def _is_module(self):
        """check the kernel module exists by executing modinfo and checking for an exception"""
        try:
            _util.check_call_(['modinfo', "fs-" + self.name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            return False
        else:
            return True

    def _is_helper(self):
        """check a helper exists for this mount type"""
        return _util.command_exists('mount.' + self.name)

    @property
    def is_available(self):
        return any((x() for x in (self._is_loaded, self._is_module, self._is_helper)))


class PythonModuleDependency(Dependency):
    def require(self):
        if not self.is_available:
            raise ModuleNotFoundError(str(self))

    @property
    def is_available(self):
        return _util.module_exists(self.name)

    @property
    def status_message(self):
        if self.is_available:
            return "INSTALLED {0!s}"
        elif self.why:
            return "MISSING   {0!s:<20}needed for {0.why}, install using pip"
        else:
            return "MISSING   {0!s:<20}install using pip"


class MagicDependency(PythonModuleDependency):
    """A special case of PythonModuleDependency

    The ``magic`` Python module can be provided by either the ``python-magic`` PyPI package
    or the ``python-magic`` apt package (on debian-based systems). They have
    different APIs, but ``imagemounter`` supports either.
    """

    @property
    def _importable(self):
        """Check if there is an importable module named 'magic'.

        Don't rely on the is_available property, since if the source of the
        'magic' module is unknown, we should consider it missing
        """
        return _util.module_exists('magic')

    @property
    def is_available(self):
        """Whether an acceptable version of the ``magic`` module is available on the system.

        :rtype: bool
        """
        return self.is_python_package or self.is_system_package

    @property
    def is_python_package(self):
        """Whether the ``magic`` module is provided by the ``python-magic`` PyPI package.

        :rtype: bool
        """
        if not self._importable:
            return False

        import magic
        return hasattr(magic, 'from_file')

    @property
    def is_system_package(self):
        """Whether the ``magic`` module is provided by the ``python-magic`` system package.

        :rtype: bool
        """
        if not self._importable:
            return False

        import magic
        return hasattr(magic, 'open')

    @property
    def status_message(self):
        if self.is_python_package:
            return "INSTALLED {0!s:<20}(Python package)"
        elif self.is_system_package:
            return "INSTALLED {0!s:<20}(system package)"
        elif self._importable:
            return "ERROR     {0!s:<20}expecting {0}, found other module named magic"
        else:
            return "MISSING   {0!s:<20}install using pip"


class DependencySection:
    """Group of dependencies that are displayed together in ``imount --check``.

    :param str name: name for the group
    :param str description: explanation of which dependencies in the group are needed.
    :param list[Dependency] deps: dependencies that are part of this group.
    """

    def __init__(self, name, description, deps):
        self.name = name
        self.description = description
        self.deps = deps

    @property
    def printable_status(self):
        lines = [
            "-- {0.name} ({0.description}) --".format(self)
        ]
        for dep in self.deps:
            lines.append(" " + dep.printable_status)
        return "\n".join(lines)


xmount = CommandDependency("xmount", "xmount", "several types of disk images")
ewfmount = CommandDependency("ewfmount", "ewf-tools", "EWF images (partially covered by xmount)")
affuse = CommandDependency("affuse", "afflib-tools", "AFF images (partially covered by xmount)")
vmware_mount = CommandDependency("vmware-mount", why="VMWare disks")
mountavfs = CommandDependency("mountavfs", "avfs", "compressed disk images")
qemu_nbd = CommandDependency("qemu-nbd", "qemu-utils", "Qcow2 images")

mmls = CommandDependency("mmls", "sleuthkit")
pytsk3 = PythonModuleDependency("pytsk3")
parted = CommandDependency("parted", "parted")

fsstat = CommandDependency("fsstat", "sleuthkit")
file = CommandDependency("file", "libmagic1")
blkid = CommandDependency("blkid")
magic = MagicDependency('python-magic')
disktype = CommandDependency("disktype", "disktype")

mount_xfs = FileSystemTypeDependency("xfs", "xfsprogs", "XFS volumes")
mount_ntfs = FileSystemTypeDependency("ntfs", "ntfs-3g", "NTFS volumes")
lvm = CommandDependency("lvm", "lvm2", "LVM volumes")
vmfs_fuse = CommandDependency("vmfs-fuse", "vmfs-tools", "VMFS volumes")
mount_jffs2 = FileSystemTypeDependency("jffs2", "mtd-tools", "JFFS2 volumes")
mount_squashfs = FileSystemTypeDependency("squashfs", "squashfs-tools", "SquashFS volumes")
mdadm = CommandDependency("mdadm", "mdadm", "RAID volumes")
cryptsetup = CommandDependency("cryptsetup", "cryptsetup", "LUKS containers")
bdemount = CommandDependency("bdemount", "libbde-utils", "Bitlocker Drive Encryption volumes")
vshadowmount = CommandDependency("vshadowmount", "libvshadow-utils", "NTFS volume shadow copies")
photorec = CommandDependency("photorec", "testdisk", "carving free space")

mount_images = DependencySection(name="Mounting base disk images",
                                 description="at least one required, first three recommended",
                                 deps=[xmount, ewfmount, affuse, vmware_mount, mountavfs, qemu_nbd])

detect_volumes = DependencySection(name="Detecting volumes and volume types",
                                   description="at least one required",
                                   deps=[mmls, pytsk3, parted])

detect_volume_types = DependencySection(name="Detecting volume types",
                                        description="all recommended, first two highly recommended",
                                        deps=[fsstat, file, blkid, magic, disktype])

mount_volumes = DependencySection(name="Mounting volumes",
                                  description="install when needed",
                                  deps=[mount_xfs, mount_ntfs, lvm, vmfs_fuse, mount_jffs2,
                                        mount_squashfs, mdadm, cryptsetup, bdemount, vshadowmount, photorec])

ALL_SECTIONS = [
    mount_images,
    detect_volumes,
    detect_volume_types,
    mount_volumes,
]
