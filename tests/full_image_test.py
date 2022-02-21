import os
import unittest
from imagemounter import ImageParser, _util

try:
    _util.check_output_(['losetup', '-f']).strip()
except Exception:
    loop_supported = False
else:
    loop_supported = True


with open("/proc/filesystems", "r") as f:
    supported_filesystems = [l.split()[-1] for l in f]


class FilesystemDirectMountTestBase(object):
    ignored_volumes = []

    @unittest.skipUnless(loop_supported, "loopback devices not supported")
    def test_mount(self):
        volumes = []
        self.filename = os.path.join(os.path.dirname(os.path.realpath(__file__)), self.filename)
        parser = ImageParser([self.filename], None, False)
        for v in parser.init():
            if v.flag == "alloc" and v.index not in self.ignored_volumes:
                self.assertIsNotNone(v.mountpoint)
            volumes.append(v)

        parser.force_clean()

        self.validate_count(volumes)
        self.validate_types(volumes)


@unittest.skipUnless("cramfs" in supported_filesystems, "cramfs unsupported")
class CramFSDirectMountTest(FilesystemDirectMountTestBase, unittest.TestCase):
    def setUp(self):
        self.filename = 'images/test.cramfs'

    def validate_count(self, volumes):
        self.assertEqual(len(volumes), 1)

    def validate_types(self, volumes):
        self.assertEqual(volumes[0].filesystem.type, "cramfs")


class ExtDirectMountTest(FilesystemDirectMountTestBase, unittest.TestCase):
    def setUp(self):
        self.filename = 'images/test.ext3'

    def validate_count(self, volumes):
        self.assertEqual(len(volumes), 1)

    def validate_types(self, volumes):
        self.assertEqual(volumes[0].filesystem.type, "ext")


class Fat12DirectMountTest(FilesystemDirectMountTestBase, unittest.TestCase):
    def setUp(self):
        self.filename = 'images/test.fat12'

    def validate_count(self, volumes):
        self.assertEqual(len(volumes), 1)

    def validate_types(self, volumes):
        self.assertEqual(volumes[0].filesystem.type, "fat")


class IsoDirectMountTest(FilesystemDirectMountTestBase, unittest.TestCase):
    def setUp(self):
        self.filename = 'images/test.iso'

    def validate_count(self, volumes):
        self.assertEqual(len(volumes), 1)

    def validate_types(self, volumes):
        self.assertEqual(volumes[0].filesystem.type, "iso")


class MbrDirectMountTest(FilesystemDirectMountTestBase, unittest.TestCase):
    ignored_volumes = ["4"]

    def setUp(self):
        self.filename = 'images/test.mbr'

    def validate_count(self, volumes):
        self.assertEqual(len(volumes), 13)

    def validate_types(self, volumes):
        self.assertEqual(volumes[0].flag, "meta")
        self.assertEqual(volumes[1].flag, "unalloc")
        self.assertEqual(volumes[2].filesystem.type, "fat")
        self.assertEqual(volumes[3].filesystem.type, "ext")
        self.assertEqual(volumes[4].filesystem.type, "unknown")
        self.assertEqual(volumes[5].flag, "meta")
        self.assertEqual(volumes[6].flag, "meta")
        self.assertEqual(volumes[7].flag, "unalloc")
        self.assertEqual(volumes[8].filesystem.type, "ext")
        self.assertEqual(volumes[9].flag, "meta")
        self.assertEqual(volumes[10].flag, "meta")
        self.assertEqual(volumes[11].flag, "unalloc")
        self.assertEqual(volumes[12].filesystem.type, "fat")


@unittest.skipUnless("minix" in supported_filesystems, "minix unsupported")
class MinixDirectMountTest(FilesystemDirectMountTestBase, unittest.TestCase):
    def setUp(self):
        self.filename = 'images/test.minix'

    def validate_count(self, volumes):
        self.assertEqual(len(volumes), 1)

    def validate_types(self, volumes):
        self.assertEqual(volumes[0].filesystem.type, "minix")


class NtfsDirectMountTest(FilesystemDirectMountTestBase, unittest.TestCase):
    def setUp(self):
        self.filename = 'images/test.ntfs'

    def validate_count(self, volumes):
        self.assertEqual(len(volumes), 1)

    def validate_types(self, volumes):
        self.assertEqual(volumes[0].filesystem.type, "ntfs")


@unittest.skipUnless("squashfs" in supported_filesystems, "squashfs unsupported")
class SquashDirectMountTest(FilesystemDirectMountTestBase, unittest.TestCase):
    def setUp(self):
        self.filename = 'images/test.sqsh'

    @unittest.skip("temporary disable test")
    def test_mount(self):
        super().test_mount()

    def validate_count(self, volumes):
        self.assertEqual(len(volumes), 1)

    def validate_types(self, volumes):
        self.assertEqual(volumes[0].filesystem.type, "squashfs")


class ZipDirectMountTest(FilesystemDirectMountTestBase, unittest.TestCase):
    def setUp(self):
        self.filename = 'images/test.zip'

    @unittest.skipIf(os.geteuid(), "requires root")
    def test_mount(self):
        super(ZipDirectMountTest, self).test_mount()

    def validate_count(self, volumes):
        self.assertEqual(len(volumes), 1)

    def validate_types(self, volumes):
        self.assertEqual(volumes[0].filesystem.type, "iso")
