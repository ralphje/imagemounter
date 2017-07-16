import io
import unittest
import mock
import time

from imagemounter.parser import ImageParser
from imagemounter.disk import Disk
from imagemounter.volume import Volume


class FsstatTest(unittest.TestCase):
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
