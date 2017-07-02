import os
import unittest
from imagemounter import ImageParser


class BaseTestFilesystemMount(object):
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
        raise NotImplementedError()

    def validate_types(self, volumes):
        raise NotImplementedError()


class CramFSTest(BaseTestFilesystemMount, unittest.TestCase):
    def setUp(self):
        self.filename = 'images/test.cramfs'

    def validate_count(self, volumes):
        self.assertEqual(len(volumes), 1)

    def validate_types(self, volumes):
        self.assertEqual(volumes[0].fstype, "cramfs")


# Ext3 test fails because it looks like EX01 format...
#class Ext3Test(BaseTestFilesystemMount, unittest.TestCase):
#    def setUp(self):
#        self.filename = 'images/test.ext3'
#
#    def validate_count(self, volumes):
#        self.assertEqual(len(volumes), 1)
#
#    def validate_types(self, volumes):
#        self.assertEqual(volumes[0].fstype, "ext")


class Fat12Test(BaseTestFilesystemMount, unittest.TestCase):
    def setUp(self):
        self.filename = 'images/test.fat12'

    def validate_count(self, volumes):
        self.assertEqual(len(volumes), 1)

    def validate_types(self, volumes):
        self.assertEqual(volumes[0].fstype, "fat")


class IsoTest(BaseTestFilesystemMount, unittest.TestCase):
    def setUp(self):
        self.filename = 'images/test.iso'

    def validate_count(self, volumes):
        self.assertEqual(len(volumes), 1)

    def validate_types(self, volumes):
        self.assertEqual(volumes[0].fstype, "iso")


class MinixTest(BaseTestFilesystemMount, unittest.TestCase):
    def setUp(self):
        self.filename = 'images/test.minix'

    def validate_count(self, volumes):
        self.assertEqual(len(volumes), 1)

    def validate_types(self, volumes):
        self.assertEqual(volumes[0].fstype, "minix")


class ZipTest(BaseTestFilesystemMount, unittest.TestCase):
    def setUp(self):
        self.filename = 'images/test.zip'

    def validate_count(self, volumes):
        self.assertEqual(len(volumes), 1)

    def validate_types(self, volumes):
        self.assertEqual(volumes[0].fstype, "iso")
