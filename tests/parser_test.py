import unittest
import unittest.mock as mock

from imagemounter.exceptions import NoRootFoundError
from imagemounter.parser import ImageParser
from imagemounter.volume import Volume


class ReconstructionTest(unittest.TestCase):
    def test_no_volumes(self):
        parser = ImageParser()
        parser.add_disk("...")
        with self.assertRaises(NoRootFoundError):
            parser.reconstruct()

    def test_no_root(self):
        parser = ImageParser()
        disk = parser.add_disk("...")
        v1 = Volume(disk)
        v1.mountpoint = '...'
        v1.info['lastmountpoint'] = '/etc/x'
        v2 = Volume(disk)
        v2.mountpoint = '....'
        v2.info['lastmountpoint'] = '/etc'
        disk.volumes.volumes = [v1, v2]
        with self.assertRaises(NoRootFoundError):
            parser.reconstruct()

    def test_simple(self):
        parser = ImageParser()
        disk = parser.add_disk("...")
        v1 = Volume(disk)
        v1.mountpoint = '...'
        v1.info['lastmountpoint'] = '/'
        v2 = Volume(disk)
        v2.mountpoint = '....'
        v2.info['lastmountpoint'] = '/etc'
        disk.volumes.volumes = [v1, v2]
        with mock.patch.object(v2, "bindmount") as v2_bm:
            parser.reconstruct()
            v2_bm.assert_called_once_with(".../etc")

    def test_multiple_roots(self):
        parser = ImageParser()
        disk = parser.add_disk("...")
        v1 = Volume(disk)
        v1.index = '1'
        v1.mountpoint = '...'
        v1.info['lastmountpoint'] = '/'
        v2 = Volume(disk)
        v2.index = '2'
        v2.mountpoint = '....'
        v2.info['lastmountpoint'] = '/'
        v3 = Volume(disk)
        v3.index = '3'
        v3.mountpoint = '.....'
        v3.info['lastmountpoint'] = '/etc'
        disk.volumes.volumes = [v1, v2, v3]
        with mock.patch.object(v1, "bindmount") as v1_bm, mock.patch.object(v2, "bindmount") as v2_bm, \
                mock.patch.object(v3, "bindmount") as v3_bm:
            parser.reconstruct()
            v1_bm.assert_not_called()
            v2_bm.assert_not_called()
            v3_bm.assert_called_with('.../etc')
