import io
import unittest
import mock
import time

from imagemounter.parser import ImageParser
from imagemounter.disk import Disk
from imagemounter.volume import Volume


class FsstatTest(unittest.TestCase):
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
