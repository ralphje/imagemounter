#!/usr/bin/env python
import subprocess
import tempfile
import argparse
import pytsk3
import util
import glob
import pdb
import sys
import os


def main():
    if os.geteuid():  # Not run as root
        print u'[-] This script needs to be ran as root!'
        sys.exit(1)
    parser = argparse.ArgumentParser(usage=u'A program to mount partitions in Encase and dd images locally')
    parser.add_argument('-rw', '--read-write', action='store_true', default=False, help='Mount image read-write by creating a local write-cache file in a temp directory. WARNING: The user is responsible for deleting these temp files if they are non-empty!!')
    parser.add_argument('images', nargs='+', help='Path(s) to the image(s) that you want to mount. In case the image is split up in multiple files, just use the first file (e.g. the .E01 or .001 file).')
    args = parser.parse_args()
    for num, image in enumerate(args.images):
        if not os.path.exists(image):
            print "[-] Image {0} does not exist, aborting!".format(image)
            break
        try:
            p = ImageParser(image, args)
            # Mount the base image using ewfmount
            if not p.mount_base():
                continue

            if args.read_write:
                print u'[+] Created read-write cache at {0}'.format(p.rwpath)
            print u'[+] Mounted raw image [{num}/{total}], now mounting partitions...'.format(num=num + 1, total=len(args.images))
            for mountpoint in p.mount_partitions():
                raw_input('>>> Press a key to unmount the image...')
                util.unmount([u'umount'], mountpoint)
                p.partition_mountpoints.remove(mountpoint)
                continue

            print u'[+] Parsed all partitions for this image!'
            # write results
        except KeyboardInterrupt:
            print u'[+] User pressed ^C, aborting...'
            return None
        finally:
            p.clean()
        # All done with this image, unmount it
        print u'[+] Image processed, proceding with next image.'


class ImageParser(object):
    def __init__(self, path, args):
        path = os.path.expandvars(os.path.expanduser(path))
        if util.is_encase(path):
            self.type = 'encase'
        else:
            self.type = 'dd'
        self.paths = sorted(util.expand_path(path))
        self.args = args
        self.rwpath = tempfile.mkstemp(prefix="image_mounter_rw_cache_")[1]
        self.name = os.path.split(path)[1]
        self.basemountpoint = u''
        self.partition_mountpoints = []
        self.image = None
        self.volumes = None

    def mount_base(self):
        '''
        Mount the image at a remporary path for analysis
        '''
        self.basemountpoint = tempfile.mkdtemp(prefix=u'image_mounter_')

        def _mount_base(paths):
            try:
                print u'[+] Mounting image {0}'.format(paths[0])
                if self.args.read_write:
                    cmd = [u'xmount', '--rw', self.rwpath, '--in', 'ewf' if self.type == 'encase' else 'dd']
                else:
                    cmd = [u'xmount', '--in', 'ewf' if self.type == 'encase' else 'dd']
                cmd.extend(paths)
                cmd.append(self.basemountpoint)
                subprocess.check_call(cmd)
                return True
            except Exception as e:
                print (u'[-] Could not mount {0} (see below), will try '
                                  'multi-file method').format(paths[0])
                print e
                return False
        return _mount_base(self.paths) or _mount_base(self.paths[:1])

    def mount_partitions(self):
        '''
        Generator that mounts every partition of this image and yields the
        mountpoint
        '''
        # ewf raw image is now available on basemountpoint
        # either as ewf1 file or as .dd file
        raw_path = glob.glob(os.path.join(self.basemountpoint, u'ewf1'))
        raw_path.extend(glob.glob(os.path.join(self.basemountpoint, u'*.dd')))
        raw_path = raw_path[0]
        try:
            self.image = pytsk3.Img_Info(raw_path)
            self.volumes = pytsk3.Volume_Info(self.image)
        except:
            print u'[?] Could not determine volume information, possible empty image?'
            return

        for p in self.volumes:
            try:
                d = pytsk3.FS_Info(self.image, offset=p.start * 512)
                offset = p.start * 512
                mountpoint = tempfile.mkdtemp(prefix=u'image_mounter_' + str(offset)
                                              + u'_')

                #mount -t ext4 -o loop,ro,noexec,noload,offset=241790330880 \
                #/media/image/ewf1 /media/a
                cmd = None
                if u'0x83' in p.desc.lower():
                    # ext
                    cmd = [u'mount', raw_path,
                           mountpoint, u'-t', u'ext4', u'-o',
                           u'loop,noexec,offset=' + str(offset)]
                    print u'[+] Mounting ext volume on {0}.'.format(
                        mountpoint)
                elif u'bsd' in p.desc.lower():
                    # ufs
                    #mount -t ufs -o ufstype=ufs2,loop,ro,offset=4294967296 \
                    #/tmp/image/ewf1 /media/a
                    cmd = [u'mount', raw_path,
                           mountpoint, u'-t', u'ufs', u'-o',
                           u'ufstype=ufs2,loop,offset=' + str(offset)]
                    print u'[+] Mounting UFS volume on {0}.'.format(
                        mountpoint)
                elif u'0xFD' in p.desc.lower():
                    # ext
                    cmd = [u'mount', raw_path,
                           mountpoint, u'-t', u'ext4', u'-o',
                           u'loop,noexec,noload,offset=' + str(offset)]
                    print u'[+] Mounting ext volume on {0}.'.format(
                        mountpoint)
                elif u'0x07' in p.desc.lower():
                    # NTFS
                    cmd = [u'mount', raw_path,
                           mountpoint, u'-t', u'ntfs', u'-o',
                           u'loop,noexec,noload,offset=' + str(offset)]
                    print u'[+] Mounting ntfs volume on {0}.'.format(
                        mountpoint)
                else:
                    print u'[-] Unknown filesystem encountered: ' + p.desc
                if not self.args.read_write:
                    cmd[-1] += ',noload,ro'
                if not cmd:
                    os.rmdir(mountpoint)
                    continue

                subprocess.check_call(cmd, stdout=subprocess.PIPE)
                self.partition_mountpoints.append(mountpoint)
                yield mountpoint
                del d
            except Exception as e:
                print u'[-] Could not load partition {0}:{1}'.format(p.addr, p.desc)
                if isinstance(e, subprocess.CalledProcessError):
                    print e
                    raw_input('Press [enter] to continue...')

    def clean(self):
        '''
        Helper method that removes all ties to the filesystem, so the image can
        be unmounted successfully
        '''
        print u'[+] Analysis complete, unmounting...'

        if self.image:
            self.image.close()
        del self.image
        del self.volumes
        try:
            if not os.path.getsize(self.rwpath) or 'y' in raw_input('Would you like to delete the rw cache file? [y/N] ').lower():
                os.remove(self.rwpath)
        except KeyboardInterrupt:
            pass
        for m in self.partition_mountpoints:
            if not util.unmount([u'umount'], m):
                pdb.set_trace()

        if not util.unmount([u'fusermount', u'-u'], self.basemountpoint):
            pdb.set_trace()
        print u'[+] All cleaned up.'

if __name__ == '__main__':
    main()
