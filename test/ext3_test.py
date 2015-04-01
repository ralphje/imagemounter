from .basetest import BaseTestFilesystemMount

class Ext3Test(BaseTestFilesystemMount):

    def setUp(self):
        self.filename = 'images/test.ext3'

    def validate_count(self, volumes):
        self.assertEqual(len(volumes), 1)

    def validate_types(self, volumes):
        self.assertEqual(volumes[0].fstype, "ext")
