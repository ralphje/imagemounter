import argparse

import pytest

from imagemounter.cli import AppendDictAction


class TestAppendDictAction:
    @pytest.mark.parametrize("args,result", [
        (["--test", "x"], {"*": 'x'}),
        (["--test", "y=x"], {"y": 'x'}),
        (["--test", "y=x,z=a"], {"y": 'x', "z": 'a'}),
        (["--test", "*=x"], {"*": 'x'}),

        (["--test", "*=x", "--test", "y=a"], {"*": 'x', 'y': 'a'}),
        (["--test", "x=x", "--test", "x=y"], {'x': 'y'}),
        (["--test", "*=x", "--test", "y"], {"*": 'y'}),
        (["--test", "y", "--test", "*=3"], {"*": '3'}),
    ])
    def test_with_comma(self, args, result):
        parser = argparse.ArgumentParser()
        parser.add_argument('--test', action=AppendDictAction)

        assert parser.parse_args(args).test == result

    @pytest.mark.parametrize("args", [
        (["--test", "y=x,z"]),
        (["--test", "y=x,z", "--test", "x"]),
    ])
    def test_with_comma_error(self, args):
        parser = argparse.ArgumentParser()
        parser.add_argument('--test', action=AppendDictAction)

        with pytest.raises(SystemExit):
            parser.parse_args(args)

    @pytest.mark.parametrize("args,result", [
        (["--test", "x"], {"*": 'x'}),
        (["--test", "y=x"], {"y": 'x'}),
        (["--test", "y=x,z=a"], {"y": 'x,z=a'}),
        (["--test", "*=x"], {"*": 'x'}),
        (["--test", "y=x,z"], {"y": 'x,z'}),

        (["--test", "x", "--test", "y"], {"*": 'y'}),
        (["--test", "y=x", "--test", "x=y"], {"y": 'x', 'x': 'y'}),
        (["--test", "y=x,z=a", "--test", "b=c"], {"y": 'x,z=a', 'b': 'c'}),
    ])
    def test_without_comma(self, args, result):
        parser = argparse.ArgumentParser()
        parser.add_argument('--test', action=AppendDictAction, allow_commas=False)

        assert parser.parse_args(args).test == result

    def test_with_default(self):
        parser = argparse.ArgumentParser()
        parser.add_argument('--test', action=AppendDictAction, default={"aa": "bb"})

        assert parser.parse_args(["--test", "x"]).test == {"*": 'x', 'aa': 'bb'}
