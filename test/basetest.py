import os
import unittest

from imagemounter import ImageParser

class BaseTestFilesystemMount(unittest.TestCase):

    def setUp(self):
        self.filename = None

    def test_mount(self):
        volumes = []
        self.filename = os.path.join(os.path.dirname(os.path.realpath(__file__)), self.filename)
        parser = ImageParser([self.filename], None, False)
        for v in parser.init():
            volumes.append(v)

        parser.clean()

        self.validate_count(volumes)
        self.validate_types(volumes)


    def validate_count(self, volumes):
        self.assertTrue(False)


    def validate_types(self, volumes):
        self.assertTrue(False)


if __name__ == '__main__':
    unittest.main()
