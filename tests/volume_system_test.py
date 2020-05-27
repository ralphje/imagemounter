import unittest
import unittest.mock as mock

from imagemounter._util import check_output_
from imagemounter.parser import ImageParser
from imagemounter.disk import Disk


class PartedTest(unittest.TestCase):
    @mock.patch("imagemounter.volume_system._util.check_output_")
    def test_parted_requests_input(self, check_output):
        def modified_command(cmd, *args, **kwargs):
            if cmd[0] == 'parted':
                # A command that requests user input
                return check_output_(["python2", "-c", "exec \"try: raw_input('>> ')\\nexcept: pass\""],
                                     *args, **kwargs)
            return mock.DEFAULT
        check_output.side_effect = modified_command

        disk = Disk(ImageParser(), path="...")

        list(disk.volumes.detect_volumes(method='parted'))
        check_output.assert_called()
        # TODO: kill process when test fails
