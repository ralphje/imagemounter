import io
import subprocess
import sys
import unittest
import unittest.mock as mock
import time

from imagemounter import FILE_SYSTEM_TYPES
from imagemounter._util import check_output_
from imagemounter.filesystems import UnknownFileSystem
from imagemounter.parser import ImageParser
from imagemounter.disk import Disk
from imagemounter.volume import Volume


class InitializationTest(unittest.TestCase):
    def test_key_material_read(self):
        volume = Volume(disk=Disk(ImageParser(keys={'3': 'hello'}), "..."), index='3')
        self.assertEqual(volume.key, "hello")
        volume = Volume(disk=Disk(ImageParser(keys={'3': 'hello', '*': 'ola'}), "..."), index='2')
        self.assertEqual(volume.key, "ola")
        volume = Volume(disk=Disk(ImageParser(keys={'3': 'hello'}), "..."), index='1')
        self.assertEqual(volume.key, "")


class FsTypeTest(unittest.TestCase):
    def test_valid_fstype(self):
        volume = Volume(disk=Disk(ImageParser(), "..."), fstype='ext')
        volume.determine_fs_type()
        self.assertEqual(FILE_SYSTEM_TYPES['ext'], volume.filesystem.__class__)

    def test_valid_vstype(self):
        volume = Volume(disk=Disk(ImageParser(), "..."), fstype="dos")
        volume.determine_fs_type()
        self.assertEqual("dos", volume.volumes.vstype)
        self.assertEqual(FILE_SYSTEM_TYPES["volumesystem"], volume.filesystem.__class__)

    def test_fsdescription(self):
        # Add names in here that are shown in the wild for output of mmls / gparted
        # !! Always try to add it also to test_combination

        descriptions = {
            # Names assigned by imagemounter
            "Logical Volume": "unknown",
            "LUKS Volume": "unknown",
            "BDE Volume": "unknown",
            "RAID Volume": "unknown",
            "VSS Store": "unknown",

            "NTFS / exFAT": "ntfs",  # mmls, should use fallback
            "Linux (0x83)": "unknown",  # should use unknown
            "4.2BSD": "ufs",
            "BSD/386, 386BSD, NetBSD, FreeBSD (0xa5)": "volumesystem",
            "DOS FAT16": "fat",
        }
        for description, fstype in descriptions.items():
            volume = Volume(disk=Disk(ImageParser(), "..."))
            volume._get_blkid_type = mock.Mock(return_value=None)
            volume._get_magic_type = mock.Mock(return_value=None)
            self.fstype = ""  # prevent fallback to unknown by default
            volume.info['fsdescription'] = description
            volume.determine_fs_type()
            self.assertEqual(FILE_SYSTEM_TYPES[fstype], volume.filesystem.__class__)

    def test_guid(self):

        FILE_SYSTEM_GUIDS = {
            '2AE031AA-0F40-DB11-9590-000C2911D1B8': 'vmfs',
            #'8053279D-AD40-DB11-BF97-000C2911D1B8': 'vmkcore-diagnostics',
            #'6A898CC3-1DD2-11B2-99A6-080020736631': 'zfs-member',
            #'C38C896A-D21D-B211-99A6-080020736631': 'zfs-member',
            #'0FC63DAF-8483-4772-8E79-3D69D8477DE4': 'linux',
            'E6D6D379-F507-44C2-A23C-238F2A3DF928': 'lvm',
            '79D3D6E6-07F5-C244-A23C-238F2A3DF928': 'lvm',
            'CA7D7CCB-63ED-4C53-861C-1742536059CC': 'luks'
        }

        for description, fstype in FILE_SYSTEM_GUIDS.items():
            volume = Volume(disk=Disk(ImageParser(), "..."))
            volume._get_blkid_type = mock.Mock(return_value=None)
            volume._get_magic_type = mock.Mock(return_value=None)
            volume.info['guid'] = description
            volume.determine_fs_type()
            self.assertEqual(FILE_SYSTEM_TYPES[fstype], volume.filesystem.__class__)

    def test_blkid(self):
        # Add values here that are shown in the wild for blkid
        # !! Always try to add it also to test_combination

        descriptions = {
            "cramfs": "cramfs",
            "ext4": "ext",
            "ext2": "ext",
            "vfat": "fat",
            "iso9660": "iso",
            "minix": "minix",
            "ntfs": "ntfs",
            "squashfs": "squashfs",
            "ufs": "ufs",

            "dos": "volumesystem",
        }

        for description, fstype in descriptions.items():
            volume = Volume(disk=Disk(ImageParser(), "..."))
            volume._get_blkid_type = mock.Mock(return_value=description)
            volume._get_magic_type = mock.Mock(return_value=None)
            volume.determine_fs_type()
            self.assertEqual(FILE_SYSTEM_TYPES[fstype], volume.filesystem.__class__)

    def test_magic(self):
        # Add values here that are shown in the wild for file magic output
        # !! Always try to add it also to test_combination

        descriptions = {
            "Linux Compressed ROM File System data": "cramfs",
            "Linux rev 1.0 ext2 filesystem data": "ext",

            'DOS/MBR boot sector, code offset 0x3c+2, OEM-ID "mkfs.fat", sectors/cluster 4, '
            'root entries 512, sectors 100 (volumes <=32 MB) , Media descriptor 0xf8, '
            'sectors/FAT 1, sectors/track 32, heads 64, serial number 0x3cb7474b, '
            'label: "TEST       ", FAT (12 bit)': "fat",

            "ISO 9660 CD-ROM filesystem data 'test'": "iso",
            "Minix filesystem, V1, 30 char names, 12800 zones": "minix",

            'DOS/MBR boot sector, code offset 0x52+2, OEM-ID "NTFS    ", sectors/cluster 8, '
            'Media descriptor 0xf8, sectors/track 0, dos < 4.0 BootSector (0x80), FAT (1Y bit '
            'by descriptor); NTFS, sectors 2048, $MFT start cluster 4, $MFTMirror start '
            'cluster 128, bytes/RecordSegment 2^(-1*246), clusters/index block 1, serial '
            'number 04e8742c12a96cecd; contains Microsoft Windows XP/VISTA bootloader BOOTMGR': "ntfs",

            "Squashfs filesystem, little endian, version 4.0": "squashfs",
        }

        for description, fstype in descriptions.items():
            volume = Volume(disk=Disk(ImageParser(), "..."))
            volume._get_blkid_type = mock.Mock(return_value=None)
            volume._get_magic_type = mock.Mock(return_value=description)
            volume.determine_fs_type()
            self.assertEqual(FILE_SYSTEM_TYPES[fstype], volume.filesystem.__class__)

    def test_combination(self):
        # Add values here to test full combinations of specific filesystem types
        # The _ as key is the expected result

        _ = "use as key for the expected result"
        definitions = [
            {_: "cramfs", "blkid": "cramfs", "magic": "Linux Compressed ROM File System data", "fsdescription": "???"},
            {_: "exfat", "blkid": "exfat", "fsdescription": "NTFS / exFAT", "statfstype": "exFAT"},
            {_: "ext", "blkid": "ext4", "fsdescription": "Linux (0x83)", "guid": "", "statfstype": "Ext2"},
            {_: "fat", "blkid": "vfat", "magic": "FAT (12 bit)", "fsdescription": "DOS FAT12 (0x04)",
                       "statfstype": "FAT12"},
            {_: "iso", "blkid": "iso9660", "magic": ".. ISO 9660 ..", "statfstype": "ISO9660"},
            {_: "minix", "blkid": "min  ix", "magic": "Minix filesystem", "fsdescription": "???"},
            {_: "ntfs", "blkid": "ntfs", "magic": ".. NTFS ..", "fsdescription": "NTFS / exFAT", "statfstype": "NTFS"},
            {_: "squashfs", "blkid": "squashfs", "magic": "Squashfs filesystem", "fsdescription": "???"},

            {_: "lvm", "guid": "79D3D6E6-07F5-C244-A23C-238F2A3DF928"},
            {_: "raid", "fsdescription": "Linux (0x83)", "blkid": "linux_raid_member"},

            {_: "volumesystem", "blkid": "dos", "fsdescription": "Logical Volume"},
            {_: "volumesystem", "blkid": "dos", "fsdescription": "RAID Volume"},
            {_: "volumesystem", "blkid": "dos", "magic": "DOS/MBR boot sector"},
            {_: "volumesystem", "fsdescription": "BSD/386, 386BSD, NetBSD, FreeBSD (0xa5)", "blkid": "ufs"},
            {_: "ufs", "fsdescription": "4.2BSD (0x07)", "blkid": "ufs"},
        ]

        for definition in definitions:
            volume = Volume(disk=Disk(ImageParser(), "..."))
            volume._get_blkid_type = mock.Mock(return_value=definition.get("blkid"))
            volume._get_magic_type = mock.Mock(return_value=definition.get("magic"))
            volume.info = definition
            volume.determine_fs_type()
            self.assertEqual(FILE_SYSTEM_TYPES[definition[_]], volume.filesystem.__class__)

    def test_no_clue_fstype(self):
        volume = Volume(disk=Disk(ImageParser(), "..."))
        volume._get_blkid_type = mock.Mock(return_value=None)
        volume._get_magic_type = mock.Mock(return_value=None)
        volume.determine_fs_type()
        self.assertEqual(UnknownFileSystem, volume.filesystem.__class__)

    def test_little_clue_fstype(self):
        volume = Volume(disk=Disk(ImageParser(), "..."))
        volume._get_blkid_type = mock.Mock(return_value="-")
        volume._get_magic_type = mock.Mock(return_value="-")
        volume.determine_fs_type()
        self.assertEqual(UnknownFileSystem, volume.filesystem.__class__)

    def test_fstype_fallback(self):
        volume = Volume(disk=Disk(ImageParser(), "..."))
        volume._get_blkid_type = mock.Mock(return_value=None)
        volume._get_magic_type = mock.Mock(return_value=None)
        volume._get_fstype_from_parser('?ufs')
        volume.determine_fs_type()
        self.assertEqual(FILE_SYSTEM_TYPES["ufs"], volume.filesystem.__class__)

    def test_fstype_fallback_unknown(self):
        volume = Volume(disk=Disk(ImageParser(), "..."))
        volume._get_blkid_type = mock.Mock(return_value=None)
        volume._get_magic_type = mock.Mock(return_value=None)
        volume.info['fsdescription'] = "Linux (0x83)"

        # If something more specific is set, we use that
        volume._get_fstype_from_parser('?ufs')
        volume.determine_fs_type()
        self.assertEqual(FILE_SYSTEM_TYPES["ufs"], volume.filesystem.__class__)

        # Otherwise we fallback to unknown if Linux (0x83) is set
        volume._get_fstype_from_parser('')
        volume.determine_fs_type()
        self.assertEqual(UnknownFileSystem, volume.filesystem.__class__)


class FileMagicTest(unittest.TestCase):
    @mock.patch("io.open")
    def test_read_bytes_crash(self, mock_open):
        mock_open().__enter__().read.side_effect = IOError
        volume = Volume(disk=Disk(ImageParser(), "..."))
        volume.get_raw_path = mock.Mock(return_value="...")

        self.assertIsNone(volume._get_magic_type())


class FsstatTest(unittest.TestCase):
    @unittest.skipIf(sys.version_info < (3, 6), "This test uses assert_called() which is not present before Py3.6")
    def test_ext4(self):
        # Removed some items from this output as we don't use it in its entirety anyway
        result = b"""FILE SYSTEM INFORMATION
--------------------------------------------
File System Type: Ext4
Volume Name: Example
Volume ID: 2697f5b0479b15b1b4c81994387cdba

Last Written at: 2017-07-02 12:23:22 (CEST)
Last Checked at: 2016-07-09 20:27:28 (CEST)

Last Mounted at: 2017-07-02 12:23:23 (CEST)
Unmounted properly
Last mounted on: /

Source OS: Linux

BLOCK GROUP INFORMATION
--------------------------------------------"""
        with mock.patch('subprocess.Popen') as mock_popen:
            type(mock_popen()).stdout = mock.PropertyMock(return_value=io.BytesIO(result))

            volume = Volume(disk=Disk(ImageParser(), "..."))
            volume.get_raw_path = mock.Mock(return_value="...")

            volume._load_fsstat_data()

            self.assertEqual(volume.info['statfstype'], 'Ext4')
            self.assertEqual(volume.info['lastmountpoint'], '/')
            self.assertEqual(volume.info['label'], '/ (Example)')
            self.assertEqual(volume.info['version'], 'Linux')

            # must be called after reading BLOCK GROUP INFORMATION
            mock_popen().terminate.assert_called()

    def test_ntfs(self):
        # Removed some items from this output as we don't use it in its entirety anyway
        result = b"""FILE SYSTEM INFORMATION
--------------------------------------------
File System Type: NTFS
Volume Serial Number: 4E8742C12A96CECD
OEM Name: NTFS    
Version: Windows XP"""
        with mock.patch('subprocess.Popen') as mock_popen:
            type(mock_popen()).stdout = mock.PropertyMock(return_value=io.BytesIO(result))

            volume = Volume(disk=Disk(ImageParser(), "..."))
            volume.get_raw_path = mock.Mock(return_value="...")

            volume._load_fsstat_data()

            self.assertEqual(volume.info['statfstype'], 'NTFS')
            self.assertNotIn("lastmountpoint", volume.info)
            self.assertNotIn("label", volume.info)
            self.assertEqual(volume.info['version'], 'Windows XP')

    def test_utf8_label(self):
        # Removed some items from this output as we don't use it in its entirety anyway
        result = b"""FILE SYSTEM INFORMATION
--------------------------------------------
File System Type: Ext4
Volume Name: \xd0\xa0\xd0\xbe\xd1\x81\xd1\x81\xd0\xb8\xd0\xb8
Volume ID: 2697f5b0479b15b1b4c81994387cdba"""
        with mock.patch('subprocess.Popen') as mock_popen:
            type(mock_popen()).stdout = mock.PropertyMock(return_value=io.BytesIO(result))

            volume = Volume(disk=Disk(ImageParser(), "..."))
            volume.get_raw_path = mock.Mock(return_value="...")

            volume._load_fsstat_data()

            self.assertEqual(volume.info['statfstype'], 'Ext4')
            self.assertEqual(volume.info['label'], u'\u0420\u043e\u0441\u0441\u0438\u0438')

    @unittest.skipIf(sys.version_info < (3, 6), "This test uses assert_called() which is not present before Py3.6")
    def test_killed_after_timeout(self):
        def mock_side_effect(*args, **kwargs):
            time.sleep(0.2)
            return io.BytesIO(b"")

        with mock.patch('subprocess.Popen') as mock_popen:
            type(mock_popen()).stdout = mock.PropertyMock(side_effect=mock_side_effect)

            volume = Volume(disk=Disk(ImageParser(), "..."))
            volume.get_raw_path = mock.Mock(return_value="...")

            volume._load_fsstat_data(timeout=0.1)
            mock_popen().terminate.assert_called()


class LuksTest(unittest.TestCase):
    @mock.patch("imagemounter.volume._util.check_call_")
    @mock.patch("imagemounter.volume._util.check_output_")
    def test_luks_key_communication(self, check_call, check_output):
        def modified_check_call(cmd, *args, **kwargs):
            if cmd[0:2] == ['cryptsetup', 'isLuks']:
                return True
            if cmd[0:1] == ['losetup']:
                return "/dev/loop0"
            return mock.DEFAULT
        check_call.side_effect = modified_check_call

        def modified_check_output(cmd, *args, **kwargs):
            if cmd[0:1] == ['losetup']:
                return "/dev/loop0"
            return mock.DEFAULT
        check_output.side_effect = modified_check_output

        original_popen = subprocess.Popen
        def modified_popen(cmd, *args, **kwargs):
            if cmd[0:3] == ['cryptsetup', '-r', 'luksOpen']:
                # A command that requests user input
                x = original_popen([sys.executable, "-c", "print(input(''))"],
                                   *args, **kwargs)
                return x
            return mock.DEFAULT

        with mock.patch("subprocess.Popen", side_effect=modified_popen) as popen:
            disk = Disk(ImageParser(keys={'1': 'p:passphrase'}), "...")
            disk.is_mounted = True
            volume = Volume(disk=disk, fstype='luks', index='1', parent=disk)
            volume.mount()

            self.assertTrue(volume.is_mounted)
            self.assertEqual(len(volume.volumes), 1)
            self.assertEqual(volume.volumes[0].info['fsdescription'], "LUKS Volume")
