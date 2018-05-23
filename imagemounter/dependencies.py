from imagemounter import _util


class Dependency(object):

    def __init__(self, name, package="", why=""):
        self.name = name
        self.package = package
        self.why = why

    def __str__(self):
        return self.name

    @property
    def printable_status(self):
        return self.status_message.format(self)


class CommandDependency(Dependency):

    @property
    def is_available(self):
        """Check if the command is available on the system"""
        return _util.command_exists(self.name)

    @property
    def status_message(self):
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


class PythonModuleDependency(Dependency):

    @property
    def is_available(self):
        """Check if the Python module is available"""
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
    """This is a special case"""

    @property
    def _importable(self):
        """Check if there is an importable module named 'magic'.

        Don't rely on the is_available property, since if the source of the
        'magic' module is unknown, we should consider it missing
        """
        return _util.module_exists('magic')

    @property
    def is_available(self):
        return self.is_python_package or self.is_system_package

    @property
    def is_python_package(self):
        if not self._importable:
            return False

        import magic
        return hasattr(magic, 'from_file')

    @property
    def is_system_package(self):
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


class DependencySection(object):

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

mount_xfs = CommandDependency("mount.xfs", "xfsprogs", "XFS volumes")
mount_ntfs = CommandDependency("mount.ntfs", "ntfs-3g", "NTFS volumes")
lvm = CommandDependency("lvm", "lvm2", "LVM volumes")
vmfs_fuse = CommandDependency("vmfs-fuse", "vmfs-tools", "VMFS volumes")
mount_jffs2 = CommandDependency("mount.jffs2", "mtd-tools", "JFFS2 volumes")
mount_squashfs = CommandDependency("mount.squashfs", "squashfs-tools", "SquashFS volumes")
mdadm = CommandDependency("mdadm", "mdadm", "RAID volumes")
cryptsetup = CommandDependency("cryptsetup", "cryptsetup", "LUKS containers")
bdemount = CommandDependency("bdemount", "libbde-utils", "Bitlocker Drive Encryption volumes")
vshadowmount = CommandDependency("vshadowmount", "libvshadow-utils", "NTFS volume shadow copies")

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
                                        mount_squashfs, mdadm, cryptsetup, bdemount, vshadowmount])

ALL_SECTIONS = [
    mount_images,
    detect_volumes,
    detect_volume_types,
    mount_volumes,
]
