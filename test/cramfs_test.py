from .basetest import BaseTestFilesystemMount

class CramFSTest(BaseTestFilesystemMount):

    def setUp(self):
        self.filename = 'images/test.cramfs'

    def validate_count(self, volumes):
        self.assertEqual(len(volumes), 1)

    def validate_types(self, volumes):
        self.assertEqual(volumes[0].fstype, "cramfs")
