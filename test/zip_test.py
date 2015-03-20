from basetest import BaseTestFilesystemMount

class ZipTest(BaseTestFilesystemMount):

    def setUp(self):
        self.filename = 'images/test.zip' 

    def validate_count(self, volumes):
        self.assertTrue(len(volumes) == 1)

    def validate_types(self, volumes):
        self.assertTrue(volumes[0].fstype == "iso9660")

