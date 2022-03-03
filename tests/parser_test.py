import pytest

from imagemounter.exceptions import NoRootFoundError
from imagemounter.parser import ImageParser
from imagemounter.volume import Volume


class TestReconstruction:
    def test_no_volumes(self):
        parser = ImageParser()
        parser.add_disk("...")
        with pytest.raises(NoRootFoundError):
            parser.reconstruct()

    def test_no_root(self):
        parser = ImageParser()
        disk = parser.add_disk("...")
        v1 = Volume(disk)
        v1.filesystem.mountpoint = 'xxx'
        v1.info['lastmountpoint'] = '/etc/x'
        v2 = Volume(disk)
        v2.filesystem.mountpoint = 'xxx'
        v2.info['lastmountpoint'] = '/etc'
        disk.volumes.volumes = [v1, v2]
        with pytest.raises(NoRootFoundError):
            parser.reconstruct()

    def test_simple(self, mocker):
        parser = ImageParser()
        disk = parser.add_disk("...")
        v1 = Volume(disk)
        v1.filesystem.mountpoint = 'xxx'
        v1.info['lastmountpoint'] = '/'
        v2 = Volume(disk)
        v2.filesystem.mountpoint = 'xxx'
        v2.info['lastmountpoint'] = '/etc'
        disk.volumes.volumes = [v1, v2]

        v2_bm = mocker.patch.object(v2, "bindmount")
        parser.reconstruct()
        v2_bm.assert_called_once_with("xxx/etc")

    def test_multiple_roots(self, mocker):
        parser = ImageParser()
        disk = parser.add_disk("...")
        v1 = Volume(disk)
        v1.index = '1'
        v1.filesystem.mountpoint = 'xxx'
        v1.info['lastmountpoint'] = '/'
        v2 = Volume(disk)
        v2.index = '2'
        v2.filesystem.mountpoint = 'xxx'
        v2.info['lastmountpoint'] = '/'
        v3 = Volume(disk)
        v3.index = '3'
        v3.filesystem.mountpoint = 'xxx'
        v3.info['lastmountpoint'] = '/etc'
        disk.volumes.volumes = [v1, v2, v3]

        v1_bm = mocker.patch.object(v1, "bindmount")
        v2_bm = mocker.patch.object(v2, "bindmount")
        v3_bm = mocker.patch.object(v3, "bindmount")
        parser.reconstruct()
        v1_bm.assert_not_called()
        v2_bm.assert_not_called()
        v3_bm.assert_called_with('xxx/etc')
