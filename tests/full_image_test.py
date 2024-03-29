import os

import pytest

from imagemounter import ImageParser, dependencies


def supportfs(fs):
    return dependencies.FileSystemTypeDependency(fs).is_available


def fullpath(fn):
    return os.path.join(os.path.dirname(os.path.realpath(__file__)), fn)


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
    parser = ImageParser([fullpath(filename)])
    for v in parser.init():
        if v.flag == "alloc":
            assert v.mountpoint is not None
        volumes.append(v)

    parser.force_clean()

    assert len(volumes) == 1
    assert volumes[0].filesystem.type == type


@pytest.mark.skipif(not supportfs("ntfs"), reason="ntfs not supported")
@pytest.mark.skipif(not dependencies.bdemount.is_available, reason="bdemount not available")
# identifier should be B8992A09-3AE9-47E3-8FD0-4A5B8389B0A4
@pytest.mark.parametrize("key", ["p:test1234", "r:391798-523787-614746-034969-107921-412302-401654-479457"])
def test_bde_mount(key):
    parser = ImageParser([fullpath('images/bdetest.E01')], keys={"0": key})
    for i, v in enumerate(parser.init()):
        assert v.mountpoint is not None
        assert v.flag == "alloc"
        assert v.filesystem.type == "ntfs"
        assert v.index == "0.0"
        assert i == 0  # ensures we only have a single item in this iteration

    parser.force_clean()


@pytest.mark.skipif(not dependencies.lvm.is_available, reason="lvm not available")
def test_lvm_mount():
    parser = ImageParser([fullpath('images/lvm.raw')])

    volumes = []
    for v in parser.init():
        volumes.append(v)

    assert len(volumes) == 2
    assert volumes[0].mountpoint is not None
    assert volumes[0].flag == "alloc"
    assert volumes[0].filesystem.type == "ext"
    assert volumes[0].index == "0.0"

    parser.force_clean()


def test_filesystem_mount():
    filename = 'images/test.mbr'
    volumes = []
    parser = ImageParser([fullpath(filename)])
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
