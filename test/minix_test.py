from .basetest import BaseTestFilesystemMount

class MinixTest(BaseTestFilesystemMount):

    def setUp(self):
        self.filename = 'images/test.minix'

    def validate_count(self, volumes):
        self.assertEqual(len(volumes), 1)

    def validate_types(self, volumes):
        self.assertEqual(volumes[0].fstype, "minix")
