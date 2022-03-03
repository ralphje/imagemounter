import sys

from imagemounter._util import check_output_
from imagemounter.disk import Disk
from imagemounter.parser import ImageParser


class TestParted:
    def test_parted_requests_input(self, mocker):
        check_output = mocker.patch("imagemounter.volume_system._util.check_output_")
        def modified_command(cmd, *args, **kwargs):
            if cmd[0] == 'parted':
                # A command that requests user input
                return check_output_([sys.executable, "-c", "exec(\"try: input('>> ')\\nexcept: pass\")"],
                                     *args, **kwargs)
            return mocker.DEFAULT
        check_output.side_effect = modified_command

        disk = Disk(ImageParser(), path="...")

        list(disk.volumes.detect_volumes(method='parted'))
        check_output.assert_called()
        # TODO: kill process when test fails
