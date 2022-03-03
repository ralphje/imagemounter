import os

import pytest

from imagemounter import ImageParser, dependencies


def supportfs(fs):
    return dependencies.FileSystemTypeDependency(fs).is_available


@pytest.mark.parametrize("type,filename", [
    pytest.param('cramfs', 'images/test.cramfs', marks=pytest.mark.skipif(not supportfs("cramfs"), reason="cramfs not supported")),
    pytest.param('ext', 'images/test.ext3', marks=pytest.mark.skipif(not supportfs("ext3"), reason="ext3 not supported")),
    pytest.param('fat', 'images/test.fat12', marks=pytest.mark.skipif(not supportfs("vfat"), reason="vfat not supported")),
    pytest.param('iso', 'images/test.iso', marks=pytest.mark.skipif(not supportfs("iso9660"), reason="iso not supported")),
    pytest.param('minix', 'images/test.minix', marks=pytest.mark.skipif(not supportfs("minix"), reason="minix not supported")),
    pytest.param('ntfs', 'images/test.ntfs', marks=pytest.mark.skipif(not supportfs("ntfs"), reason="ntfs not supported")),
    pytest.param('squashfs', 'images/test.sqsh', marks=[pytest.mark.xfail(reason="squashfs support is currently broken"),
                                                        pytest.mark.skipif(not supportfs("squashfs"), reason="squashfs not supported")]),
    pytest.param('iso', 'images/test.zip', marks=pytest.mark.skipif(not supportfs("iso9660"), reason="iso not supported")),
])
def test_direct_mount(type, filename):
    volumes = []
    filename = os.path.join(os.path.dirname(os.path.realpath(__file__)), filename)
    parser = ImageParser([filename], None, False)
    for v in parser.init():
        if v.flag == "alloc":
            assert v.mountpoint is not None
        volumes.append(v)

    parser.force_clean()

    assert len(volumes) == 1
    assert volumes[0].filesystem.type == type
    

def test_filesystem_mount():
    filename = 'images/test.mbr'
    volumes = []
    filename = os.path.join(os.path.dirname(os.path.realpath(__file__)), filename)
    parser = ImageParser([filename], None, False)
    for v in parser.init():
        if v.flag == "alloc" and v.index != "4":
            assert v.mountpoint is not None
        volumes.append(v)

    parser.force_clean()

    assert len(volumes) == 13

    assert volumes[0].flag == "meta"
    assert volumes[1].flag == "unalloc"
    assert volumes[2].filesystem.type == "fat"
    assert volumes[3].filesystem.type == "ext"
    assert volumes[4].filesystem.type == "unknown"
    assert volumes[5].flag == "meta"
    assert volumes[6].flag == "meta"
    assert volumes[7].flag == "unalloc"
    assert volumes[8].filesystem.type == "ext"
    assert volumes[9].flag == "meta"
    assert volumes[10].flag == "meta"
    assert volumes[11].flag == "unalloc"
    assert volumes[12].filesystem.type == "fat"
