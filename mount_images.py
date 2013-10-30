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
    class MyParser(argparse.ArgumentParser):
        def error(self, message):
            sys.stderr.write('error: {0}\n'.format(message))
            self.print_help()
            sys.exit(2)
    parser = MyParser(usage=u'A program to mount partitions in Encase and dd images locally')
    parser.add_argument('-rw', '--read-write', action='store_true', default=False, help='Mount image read-write by creating a local write-cache file in a temp directory.')
    parser.add_argument('-m', '--method', choices=['xmount', 'affuse'], default='xmount', help='Use either "xmount" or "affuse" to mount the initial images. Results may vary between both methods, if something doesn\'t work, try the other method. Default=xmount')
    parser.add_argument('-s', '--stats', action='store_true', default=False, help='Show limited information from fsstat.')
    parser.add_argument('-v', '--verbose', action='store_true', default=False, help='Verbose output')
    parser.add_argument('images', nargs='+', help='Path(s) to the image(s) that you want to mount. In case the image is split up in multiple files, just use the first file (e.g. the .E01 or .001 file).')
    args = parser.parse_args()

    if args.method == 'affuse' and args.read_write:
        print "[-] affuse does not support mounting read-write! Will mount read-only."
        args.read_write = False

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
                print u'[+] Mounting image {0} using {1}'.format(paths[0], self.args.method)
                if self.args.method == 'xmount':
                    if self.args.read_write:
                        cmd = [u'xmount', '--rw', self.rwpath, '--in', 'ewf' if self.type == 'encase' else 'dd']
                    else:
                        cmd = [u'xmount', '--in', 'ewf' if self.type == 'encase' else 'dd']
                else:
                    cmd = [u'affuse']
                cmd.extend(paths)
                cmd.append(self.basemountpoint)
                if self.args.verbose:
                    print '    {0}'.format(' '.join(cmd))
                subprocess.check_call(cmd)
                return True
            except Exception as e:
                print (u'[-] Could not mount {0} (see below), will try multi-file method').format(paths[0])
                print e
                return False
        return _mount_base(self.paths[:1]) or _mount_base(self.paths)

    def mount_partitions(self):
        '''
        Generator that mounts every partition of this image and yields the
        mountpoint
        '''
        # ewf raw image is now available on basemountpoint
        # either as ewf1 file or as .dd file
        raw_path = glob.glob(os.path.join(self.basemountpoint, u'*.dd'))
        raw_path.extend(glob.glob(os.path.join(self.basemountpoint, u'*.raw')))
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
                mountpoint = tempfile.mkdtemp(prefix=u'image_mounter_' + str(offset) + u'_')
                #mount -t ext4 -o loop,ro,noexec,noload,offset=241790330880 \
                #/media/image/ewf1 /media/a
                cmd = fstype = None
                if u'0x83' in p.desc.lower():
                    # ext
                    cmd = [u'mount', raw_path, mountpoint, u'-t', u'ext4', u'-o', u'loop,noexec,noload,offset=' + str(offset)]
                    fstype = 'ext'
                elif u'bsd' in p.desc.lower():
                    # ufs
                    #mount -t ufs -o ufstype=ufs2,loop,ro,offset=4294967296 \
                    #/tmp/image/ewf1 /media/a
                    cmd = [u'mount', raw_path, mountpoint, u'-t', u'ufs', u'-o', u'ufstype=ufs2,loop,offset=' + str(offset)]
                    fstype = 'UFS'
                elif u'0xFD' in p.desc.lower():
                    # ext
                    cmd = [u'mount', raw_path, mountpoint, u'-t', u'ext4', u'-o', u'loop,noexec,noload,offset=' + str(offset)]
                    fstype = 'ext'
                elif u'0x07' in p.desc.lower():
                    # NTFS
                    cmd = [u'mount', raw_path, mountpoint, u'-t', u'ntfs', u'-o', u'loop,noexec,offset=' + str(offset)]
                    fstype = 'NTFS'
                else:
                    print u'[-] Unknown filesystem encountered: ' + p.desc
                    os.rmdir(mountpoint)
                    continue

                if not self.args.read_write:
                    cmd[-1] += ',ro'

                if self.args.verbose:
                    print '    {0}'.format(' '.join(cmd))

                if self.args.stats:
                    try:
                        stat = subprocess.Popen([u'fsstat', raw_path, u'-o', str(p.start)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                        stdout, stderr = stat.communicate()
                        last_mount = label = ''
                        for line in stdout.splitlines():
                             if line.startswith("File System Type:"):
                                 fstype = line[line.index(':')+2:]
                             if line.startswith("Last Mount Point:") or line.startswith("Last mounted on:"):
                                 last_mount = line[line.index(':')+2:]
                             if line.startswith("Volume Name:"):
                                 label = line[line.index(':')+2:]
                             if line == 'CYLINDER GROUP INFORMATION':
                                 break
                        
                        if label and last_mount:
                           last_mount = ' ({0})'.format(last_mount)                        

                        print u'[+] Mounting {0} volume {1}{2} on {3}.'.format(fstype, label, last_mount, mountpoint)
                    except Exception as e:
                        print u'[+] Mounting {0} volume on {1}.'.format(fstype, mountpoint)
                else:
                    print u'[+] Mounting {0} volume on {1}.'.format(fstype, mountpoint)


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
