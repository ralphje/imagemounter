from __future__ import print_function
from __future__ import unicode_literals

__ALL__ = ['Volume', 'VolumeSystem', 'Disk', 'ImageParser', 'Unmounter']
__version__ = '3.1.0'

BLOCK_SIZE = 512
DISK_MOUNTERS = ('xmount', 'affuse', 'ewfmount', 'vmware-mount', 'avfs', 'auto', 'dummy')
VOLUME_SYSTEM_TYPES = ('detect', 'dos', 'bsd', 'sun', 'mac', 'gpt')
FILE_SYSTEM_TYPES = ('ext', 'ufs', 'ntfs', 'exfat', 'hfs', 'hfs+', 'xfs', 'iso', 'udf', 'fat',
                     'vmfs', 'squashfs', 'jffs2', 'cramfs', 'minix',
                     'luks', 'bde', 'lvm', 'raid',
                     'dir', 'volumesystem', 'unknown')

from imagemounter.parser import ImageParser  # NOQA
from imagemounter.disk import Disk  # NOQA
from imagemounter.volume import Volume  # NOQA
from imagemounter.unmounter import Unmounter  # NOQA
from imagemounter.volume_system import VolumeSystem  # NOQA
