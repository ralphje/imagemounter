from basetest import BaseTestFilesystemMount

class Fat12Test(BaseTestFilesystemMount):

    def setUp(self):
        self.filename = 'images/test.fat12' 

    def validate_count(self, volumes):
        self.assertTrue(len(volumes) == 1)

    def validate_types(self, volumes):
        self.assertTrue(volumes[0].fstype == "vfat")

