from imagemounter import _util


class Dependency(object):
    installed_explanation = "INSTALLED {!s}"

    def __init__(self, name, package="", why=""):
        self.name = name
        self.package = package
        self.why = why

    @property
    def printable_status(self):
        if self.is_available:
            return self.installed_explanation.format(self)
        else:
            return "MISSING   {!s:<20}".format(self) + self.missing_explanation


class CommandDependency(Dependency):

    def __str__(self):
        return self.name

    @property
    def is_available(self):
        """Check if the command is available on the system"""
        return _util.command_exists(self.name)

    @property
    def missing_explanation(self):
        if self.why and self.package:
            return "needed for {}, part of the {} package".format(self.why, self.package)
        elif self.why:
            return "needed for {}".format(self.why)
        elif self.package:
            return "part of the {} package".format(self.package)
        else:
            return ""


class PythonModuleDependency(Dependency):

    def __str__(self):
        # Fall back to name if not provided (in case it's the same as the package)
        return self.package or self.name

    @property
    def is_available(self):
        """Check if the Python module is available"""
        return _util.module_exists(self.name)

    @property
    def missing_explanation(self):
        if self.why:
            return "needed for {}, install using pip".format(self.why)
        else:
            return "install using pip"


class MagicDependency(PythonModuleDependency):
    """This is a special case"""

    def __init__(self):
        super(MagicDependency, self).__init__("magic", "python-magic")
        self.source = None

    @property
    def is_available(self):
        try:
            import magic
        except ImportError:
            return False

        if hasattr(magic, 'from_file'):
            self.source = "Python package"
        elif hasattr(magic, 'open'):
            self.source = "system package"
        else:
            self.source = "unknown"

        return True

    @property
    def installed_explanation(self):
        if not self.source:
            self.check()
        if self.source == "unknown":
            return "ERROR     {0!s:<20}expecting {0}, found other module named {0.name}"
        return "INSTALLED {!s:<20}" + "({})".format(self.source)


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
magic = MagicDependency()
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
