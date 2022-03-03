import io
import subprocess
import sys
import time

import pytest

from imagemounter import FILE_SYSTEM_TYPES
from imagemounter.disk import Disk
from imagemounter.filesystems import UnknownFileSystem
from imagemounter.parser import ImageParser
from imagemounter.volume import Volume


def test_key_material_read():
    volume = Volume(disk=Disk(ImageParser(keys={'3': 'hello'}), "..."), index='3')
    assert volume.key == "hello"
    volume = Volume(disk=Disk(ImageParser(keys={'3': 'hello', '*': 'ola'}), "..."), index='2')
    assert volume.key == "ola"
    volume = Volume(disk=Disk(ImageParser(keys={'3': 'hello'}), "..."), index='1')
    assert volume.key == ""


class TestFsType:
    def test_valid_fstype(self):
        volume = Volume(disk=Disk(ImageParser(), "..."), fstype='ext')
        volume.determine_fs_type()
        assert volume.filesystem.__class__ is FILE_SYSTEM_TYPES['ext']

    def test_valid_vstype(self):
        volume = Volume(disk=Disk(ImageParser(), "..."), fstype="dos")
        volume.determine_fs_type()
        assert volume.volumes.vstype == "dos"
        assert volume.filesystem.__class__ is FILE_SYSTEM_TYPES["volumesystem"]

    # Add names in here that are shown in the wild for output of mmls / gparted
    # !! Always try to add it also to test_combination
    @pytest.mark.parametrize("description,fstype", [
        # Names assigned by imagemounter
        ('Logical Volume', 'unknown'),
        ('LUKS Volume', 'unknown'),
        ('BDE Volume', 'unknown'),
        ('RAID Volume', 'unknown'),
        ('VSS Store', 'unknown'),

        ('NTFS / exFAT', 'ntfs'),   # mmls, should use fallback
        ('Linux (0x83)', 'unknown'),  # should use unknown
        ('4.2BSD', 'ufs'),
        ('BSD/386, 386BSD, NetBSD, FreeBSD (0xa5)', 'volumesystem'),
        ('DOS FAT16', 'fat'),
    ])
    def test_fsdescription(self, description, fstype, mocker):
        volume = Volume(disk=Disk(ImageParser(), "..."))
        volume._get_blkid_type = mocker.Mock(return_value=None)
        volume._get_magic_type = mocker.Mock(return_value=None)
        self.fstype = ""  # prevent fallback to unknown by default
        volume.info['fsdescription'] = description
        volume.determine_fs_type()
        assert volume.filesystem.__class__ is FILE_SYSTEM_TYPES[fstype]

    @pytest.mark.parametrize("description,fstype", [
        ('2AE031AA-0F40-DB11-9590-000C2911D1B8', 'vmfs'),
        # '8053279D-AD40-DB11-BF97-000C2911D1B8': 'vmkcore-diagnostics',
        # '6A898CC3-1DD2-11B2-99A6-080020736631': 'zfs-member',
        # 'C38C896A-D21D-B211-99A6-080020736631': 'zfs-member',
        # '0FC63DAF-8483-4772-8E79-3D69D8477DE4': 'linux',
        ('E6D6D379-F507-44C2-A23C-238F2A3DF928', 'lvm'),
        ('79D3D6E6-07F5-C244-A23C-238F2A3DF928', 'lvm'),
        ('CA7D7CCB-63ED-4C53-861C-1742536059CC', 'luks'),
    ])
    def test_guid(self, description, fstype, mocker):
        volume = Volume(disk=Disk(ImageParser(), "..."))
        volume._get_blkid_type = mocker.Mock(return_value=None)
        volume._get_magic_type = mocker.Mock(return_value=None)
        volume.info['guid'] = description
        volume.determine_fs_type()
        assert volume.filesystem.__class__ is FILE_SYSTEM_TYPES[fstype]

    # Add values here that are shown in the wild for blkid
    # !! Always try to add it also to test_combination
    @pytest.mark.parametrize("description,fstype", [
        ('cramfs', 'cramfs'),
        ('ext4', 'ext'),
        ('ext2', 'ext'),
        ('vfat', 'fat'),
        ('iso9660', 'iso'),
        ('minix', 'minix'),
        ('ntfs', 'ntfs'),
        ('squashfs', 'squashfs'),
        ('ufs', 'ufs'),

        ('dos', 'volumesystem'),
    ])
    def test_blkid(self, description, fstype, mocker):
        volume = Volume(disk=Disk(ImageParser(), "..."))
        volume._get_blkid_type = mocker.Mock(return_value=description)
        volume._get_magic_type = mocker.Mock(return_value=None)
        volume.determine_fs_type()
        assert volume.filesystem.__class__ is FILE_SYSTEM_TYPES[fstype]

    # Add values here that are shown in the wild for file magic output
    # !! Always try to add it also to test_combination
    @pytest.mark.parametrize("description,fstype", [
        ('Linux Compressed ROM File System data', 'cramfs'),
        ('Linux rev 1.0 ext2 filesystem data', 'ext'),

        ('DOS/MBR boot sector, code offset 0x3c+2, OEM-ID "mkfs.fat", sectors/cluster 4, '
         'root entries 512, sectors 100 (volumes <=32 MB) , Media descriptor 0xf8, '
         'sectors/FAT 1, sectors/track 32, heads 64, serial number 0x3cb7474b, '
         'label: "TEST       ", FAT (12 bit)', "fat"),

        ("ISO 9660 CD-ROM filesystem data 'test'", 'iso'),
        ('Minix filesystem, V1, 30 char names, 12800 zones', 'minix'),
        ('DOS/MBR boot sector, code offset 0x52+2, OEM-ID "NTFS    ", sectors/cluster 8, '
         'Media descriptor 0xf8, sectors/track 0, dos < 4.0 BootSector (0x80), FAT (1Y bit '
         'by descriptor); NTFS, sectors 2048, $MFT start cluster 4, $MFTMirror start '
         'cluster 128, bytes/RecordSegment 2^(-1*246), clusters/index block 1, serial '
         'number 04e8742c12a96cecd; contains Microsoft Windows XP/VISTA bootloader BOOTMGR', "ntfs"),

        ('Squashfs filesystem, little endian, version 4.0', 'squashfs'),
    ])
    def test_magic(self, description, fstype, mocker):
        volume = Volume(disk=Disk(ImageParser(), "..."))
        volume._get_blkid_type = mocker.Mock(return_value=None)
        volume._get_magic_type = mocker.Mock(return_value=description)
        volume.determine_fs_type()
        assert volume.filesystem.__class__ is FILE_SYSTEM_TYPES[fstype]

    # Add values here to test full combinations of specific filesystem types
    # The _ as key is the expected result
    @pytest.mark.parametrize("definition,fstype", [
        ({"blkid": "cramfs", "magic": "Linux Compressed ROM File System data", "fsdescription": "???"}, "cramfs"),
        ({"blkid": "exfat", "fsdescription": "NTFS / exFAT", "statfstype": "exFAT"}, "exfat"),
        ({"blkid": "ext4", "fsdescription": "Linux (0x83)", "guid": "", "statfstype": "Ext2"}, "ext"),
        ({"blkid": "vfat", "magic": "FAT (12 bit)", "fsdescription": "DOS FAT12 (0x04)", "statfstype": "FAT12"}, "fat"),
        ({"blkid": "iso9660", "magic": ".. ISO 9660 ..", "statfstype": "ISO9660"}, "iso"),
        ({"blkid": "min  ix", "magic": "Minix filesystem", "fsdescription": "???"}, "minix"),
        ({"blkid": "ntfs", "magic": ".. NTFS ..", "fsdescription": "NTFS / exFAT", "statfstype": "NTFS"}, "ntfs"),
        ({"blkid": "squashfs", "magic": "Squashfs filesystem", "fsdescription": "???"}, "squashfs"),
        ({"guid": "79D3D6E6-07F5-C244-A23C-238F2A3DF928"}, "lvm"),
        ({"fsdescription": "Linux (0x83)", "blkid": "linux_raid_member"}, "raid"),
        ({"blkid": "dos", "fsdescription": "Logical Volume"}, "volumesystem"),
        ({"blkid": "dos", "fsdescription": "RAID Volume"}, "volumesystem"),
        ({"blkid": "dos", "magic": "DOS/MBR boot sector"}, "volumesystem"),
        ({"fsdescription": "BSD/386, 386BSD, NetBSD, FreeBSD (0xa5)", "blkid": "ufs"}, "volumesystem"),
        ({"fsdescription": "4.2BSD (0x07)", "blkid": "ufs"}, "ufs"),
    ])
    def test_combination(self, definition, fstype, mocker):
        volume = Volume(disk=Disk(ImageParser(), "..."))
        volume._get_blkid_type = mocker.Mock(return_value=definition.get("blkid"))
        volume._get_magic_type = mocker.Mock(return_value=definition.get("magic"))
        volume.info = definition
        volume.determine_fs_type()
        assert volume.filesystem.__class__ is FILE_SYSTEM_TYPES[fstype]

    def test_no_clue_fstype(self, mocker):
        volume = Volume(disk=Disk(ImageParser(), "..."))
        volume._get_blkid_type = mocker.Mock(return_value=None)
        volume._get_magic_type = mocker.Mock(return_value=None)
        volume.determine_fs_type()
        assert volume.filesystem.__class__ is UnknownFileSystem 

    def test_little_clue_fstype(self, mocker):
        volume = Volume(disk=Disk(ImageParser(), "..."))
        volume._get_blkid_type = mocker.Mock(return_value="-")
        volume._get_magic_type = mocker.Mock(return_value="-")
        volume.determine_fs_type()
        assert volume.filesystem.__class__ is UnknownFileSystem

    def test_fstype_fallback(self, mocker):
        volume = Volume(disk=Disk(ImageParser(), "..."))
        volume._get_blkid_type = mocker.Mock(return_value=None)
        volume._get_magic_type = mocker.Mock(return_value=None)
        volume._get_fstype_from_parser('?ufs')
        volume.determine_fs_type()
        assert volume.filesystem.__class__ is FILE_SYSTEM_TYPES["ufs"]

    def test_fstype_fallback_unknown(self, mocker):
        volume = Volume(disk=Disk(ImageParser(), "..."))
        volume._get_blkid_type = mocker.Mock(return_value=None)
        volume._get_magic_type = mocker.Mock(return_value=None)
        volume.info['fsdescription'] = "Linux (0x83)"

        # If something more specific is set, we use that
        volume._get_fstype_from_parser('?ufs')
        volume.determine_fs_type()
        assert volume.filesystem.__class__ is FILE_SYSTEM_TYPES["ufs"]

        # Otherwise we fallback to unknown if Linux (0x83) is set
        volume._get_fstype_from_parser('')
        volume.determine_fs_type()
        assert volume.filesystem.__class__ is UnknownFileSystem


class TestFileMagic:
    def test_read_bytes_crash(self, mocker):
        mock_open = mocker.patch("io.open")
        mock_open().__enter__().read.side_effect = IOError
        volume = Volume(disk=Disk(ImageParser(), "..."))
        volume.get_raw_path = mocker.Mock(return_value="...")

        assert volume._get_magic_type() is None


class TestFsstat:
    def test_ext4(self, mocker):
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
        mock_popen = mocker.patch('subprocess.Popen')
        type(mock_popen()).stdout = mocker.PropertyMock(return_value=io.BytesIO(result))

        volume = Volume(disk=Disk(ImageParser(), "..."))
        volume.get_raw_path = mocker.Mock(return_value="...")

        volume._load_fsstat_data()

        assert volume.info['statfstype'] == 'Ext4'
        assert volume.info['lastmountpoint'] == '/'
        assert volume.info['label'] == '/ (Example)'
        assert volume.info['version'] == 'Linux'

        # must be called after reading BLOCK GROUP INFORMATION
        mock_popen().terminate.assert_called()

    def test_ntfs(self, mocker):
        # Removed some items from this output as we don't use it in its entirety anyway
        result = b"""FILE SYSTEM INFORMATION
--------------------------------------------
File System Type: NTFS
Volume Serial Number: 4E8742C12A96CECD
OEM Name: NTFS    
Version: Windows XP"""
        mock_popen = mocker.patch('subprocess.Popen')
        type(mock_popen()).stdout = mocker.PropertyMock(return_value=io.BytesIO(result))

        volume = Volume(disk=Disk(ImageParser(), "..."))
        volume.get_raw_path = mocker.Mock(return_value="...")

        volume._load_fsstat_data()

        assert volume.info['statfstype'] == 'NTFS'
        assert "lastmountpoint" not in volume.info
        assert "label" not in volume.info
        assert volume.info['version'] == 'Windows XP'

    def test_utf8_label(self, mocker):
        # Removed some items from this output as we don't use it in its entirety anyway
        result = b"""FILE SYSTEM INFORMATION
--------------------------------------------
File System Type: Ext4
Volume Name: \xd0\xa0\xd0\xbe\xd1\x81\xd1\x81\xd0\xb8\xd0\xb8
Volume ID: 2697f5b0479b15b1b4c81994387cdba"""
        mock_popen = mocker.patch('subprocess.Popen')
        type(mock_popen()).stdout = mocker.PropertyMock(return_value=io.BytesIO(result))

        volume = Volume(disk=Disk(ImageParser(), "..."))
        volume.get_raw_path = mocker.Mock(return_value="...")

        volume._load_fsstat_data()

        assert volume.info['statfstype'] == 'Ext4'
        assert volume.info['label'] == u'\u0420\u043e\u0441\u0441\u0438\u0438'

    def test_killed_after_timeout(self, mocker):
        def mock_side_effect(*args, **kwargs):
            time.sleep(0.2)
            return io.BytesIO(b"")

        mock_popen = mocker.patch('subprocess.Popen')
        type(mock_popen()).stdout = mocker.PropertyMock(side_effect=mock_side_effect)

        volume = Volume(disk=Disk(ImageParser(), "..."))
        volume.get_raw_path = mocker.Mock(return_value="...")

        volume._load_fsstat_data(timeout=0.1)
        mock_popen().terminate.assert_called()


class TestLuks:
    def test_luks_key_communication(self, mocker):
        check_call = mocker.patch("imagemounter.volume._util.check_call_")
        def modified_check_call(cmd, *args, **kwargs):
            if cmd[0:2] == ['cryptsetup', 'isLuks']:
                return True
            if cmd[0:1] == ['losetup']:
                return "/dev/loop0"
            return mock.DEFAULT
        check_call.side_effect = modified_check_call

        check_output = mocker.patch("imagemounter.volume._util.check_output_")
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
        popen = mocker.patch("subprocess.Popen", side_effect=modified_popen)

        disk = Disk(ImageParser(keys={'1': 'p:passphrase'}), "...")
        disk.is_mounted = True
        volume = Volume(disk=disk, fstype='luks', index='1', parent=disk)
        volume.mount()

        assert volume.is_mounted
        assert len(volume.volumes) == 1
        assert volume.volumes[0].info['fsdescription'] == "LUKS Volume"
