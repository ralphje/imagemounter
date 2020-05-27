import argparse
import io
import unittest
import time

from imagemounter.cli import AppendDictAction


class AppendDictActionTest(unittest.TestCase):
    def test_with_comma(self):
        parser = argparse.ArgumentParser()
        parser.add_argument('--test', action=AppendDictAction)

        self.assertDictEqual(parser.parse_args(["--test", "x"]).test, {"*": 'x'})
        self.assertDictEqual(parser.parse_args(["--test", "y=x"]).test, {"y": 'x'})
        self.assertDictEqual(parser.parse_args(["--test", "y=x,z=a"]).test, {"y": 'x', "z": 'a'})
        self.assertDictEqual(parser.parse_args(["--test", "*=x"]).test, {"*": 'x'})
        self.assertDictEqual(parser.parse_args(["--test", "*=x", "--test", "y=a"]).test, {"*": 'x', 'y': 'a'})
        self.assertDictEqual(parser.parse_args(["--test", "x=x", "--test", "x=y"]).test, {'x': 'y'})
        self.assertDictEqual(parser.parse_args(["--test", "*=x", "--test", "y"]).test, {"*": 'y'})
        self.assertDictEqual(parser.parse_args(["--test", "y", "--test", "*=3"]).test, {"*": '3'})
        with self.assertRaises(SystemExit):
            parser.parse_args(["--test", "y=x,z"])

    def test_with_comma_multiple_times(self):
        parser = argparse.ArgumentParser()
        parser.add_argument('--test', action=AppendDictAction)
        self.assertDictEqual(parser.parse_args(["--test", "*=x", "--test", "y=a"]).test, {"*": 'x', 'y': 'a'})
        self.assertDictEqual(parser.parse_args(["--test", "x=x", "--test", "x=y"]).test, {'x': 'y'})
        self.assertDictEqual(parser.parse_args(["--test", "*=x", "--test", "y"]).test, {"*": 'y'})
        self.assertDictEqual(parser.parse_args(["--test", "y", "--test", "*=3"]).test, {"*": '3'})
        with self.assertRaises(SystemExit):
            parser.parse_args(["--test", "y=x,z", "--test", "x"])

    def test_without_comma(self):
        parser = argparse.ArgumentParser()
        parser.add_argument('--test', action=AppendDictAction, allow_commas=False)

        self.assertDictEqual(parser.parse_args(["--test", "x"]).test, {"*": 'x'})
        self.assertDictEqual(parser.parse_args(["--test", "y=x"]).test, {"y": 'x'})
        self.assertDictEqual(parser.parse_args(["--test", "y=x,z=a"]).test, {"y": 'x,z=a'})
        self.assertDictEqual(parser.parse_args(["--test", "*=x"]).test, {"*": 'x'})
        self.assertDictEqual(parser.parse_args(["--test", "y=x,z"]).test, {"y": 'x,z'})

    def test_without_comma_multiple_times(self):
        parser = argparse.ArgumentParser()
        parser.add_argument('--test', action=AppendDictAction, allow_commas=False)

        self.assertDictEqual(parser.parse_args(["--test", "x", "--test", "y"]).test, {"*": 'y'})
        self.assertDictEqual(parser.parse_args(["--test", "y=x", "--test", "x=y"]).test, {"y": 'x', 'x': 'y'})
        self.assertDictEqual(parser.parse_args(["--test", "y=x,z=a", "--test", "b=c"]).test, {"y": 'x,z=a', 'b': 'c'})

    def test_with_default(self):
        parser = argparse.ArgumentParser()
        parser.add_argument('--test', action=AppendDictAction, default={"aa": "bb"})

        self.assertDictEqual(parser.parse_args(["--test", "x"]).test, {"*": 'x', 'aa': 'bb'})