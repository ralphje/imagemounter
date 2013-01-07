from collections import defaultdict
import simplejson
import subprocess
import tempfile
import logging
import pytsk3
import time
import util
import glob
import pdb
import os

def parse_images(images, plugins, args):
    '''
    Convenience method that helps parsing all the images. It mounts all the
    partitions for every given image and runs all plugins for each partition. It
    builds a result dictionary which it returns upon successful completion
    '''
    # Make sure the results dir exists and build a name for the output
    d = u'results/'
    if not os.path.exists(d):
        os.makedirs(d)

    name = d + str(int(time.time())) + u'.json'

    # Store a filedescriptor to the old root, so we can chroot back if needed
    old_root = os.open("/", os.O_RDONLY)
    old_cwd = os.getcwdu()
    # Store all results in a multidimensional array
    for num, image in enumerate(images):
        if not os.path.exists(image):
            logging.error("Image {0} does not exist, aborting!".format(image))
            break
        try:
            results = defaultdict(lambda : {})
            p = ImageParser(image)
            # Mount the base image using ewfmount
            if not p.mount_base():
                continue

            logging.info(u'Mounted raw image [{num}/{total}], now mounting partitions...'.format(num=num + 1, total=len(images)))
            for mountpoint in p.mount_partitions():
                if args.noopt:
                    raw_input('Press a key to unmount the image...')
                    util.unmount([u'umount'], mountpoint)
                    p.partition_mountpoints.remove(mountpoint)
                    continue

                try:
                    # Image was mounted successfully, start analysis
                    logging.info(u'Initializing chroot and starting analysis...')
                    # Run the plugins in a chroot
                    new_root = util.find_root(mountpoint)
                    os.chroot(new_root)
                    for plugin in plugins:
                        n, result = plugin()
                        if result:
                            results[image][n] = result
                    logging.info(u'All plugins done, unmounting')
                except KeyboardInterrupt:
                    raise
                except Exception:
                    logging.exception(u'Something went wrong:')
                finally:
                    logging.info(u'Undoing chroot...')
                    os.fchdir(old_root)
                    os.chroot(".")
                    os.chdir(old_cwd)
                    unmount_result = util.unmount([u'umount'], mountpoint)
                    if not unmount_result:
                        pdb.set_trace()
                    p.partition_mountpoints.remove(mountpoint)
                    logging.info(u'Partition analysis complete, proceding with next partition.')
            logging.info(u'Parsed all partitions for this image, building report')
            # write results
            if not results:
                continue
            with open(name, 'a') as w:
                formatted = simplejson.dumps(results, sort_keys=True, indent=4)
                w.write(formatted)
        except KeyboardInterrupt:
            logging.info(u'User pressed ^C, aborting...')
            return None
        finally:
            p.clean()
        # All done with this image, unmount it
        logging.info(u'Image processed, proceding with next image.')
    os.close(old_root)

class ImageParser(object):
    def __init__(self, path):
        path = os.path.expandvars(os.path.expanduser(path))
        self.paths = sorted(util.encase_path_expand(path))
        self.name = os.path.split(path)[1]
        self.basemountpoint = u''
        self.partition_mountpoints = []
        self.image = None
        self.volumes = None

    def mount_base(self):
        '''
        Mount the image at a remporary path for analysis
        '''
        self.basemountpoint = tempfile.mkdtemp(prefix=u'bredolab_')
        def _mount_base(paths):
            try:
                logging.info(u'Mounting image {0}'
                        .format(paths[0]))
                #cmd = [u'/home/peter/src/libewf-20120715/ewftools/ewfmount']
                cmd = [u'xmount', '--in', 'ewf']  # <-- use _only_ with all .E?? paths
                cmd.extend(paths)
                cmd.append(self.basemountpoint)
                logging.debug(u'Calling command "{0}"'.format(
                    u' '.join(cmd)[:150] + '...'))
                subprocess.check_call(cmd) #, stdout=subprocess.PIPE)
                return True
            except Exception:
                logging.exception((u'Could not mount {0} (see below), will try '
                'multi-file method').format(paths[0]))
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
            logging.warning(u'Could not determine volume information, returning')
            return

        for p in self.volumes:
            try:
                d = pytsk3.FS_Info(self.image, offset=p.start * 512)
                offset = p.start * 512
                mountpoint = tempfile.mkdtemp(prefix=u'bredolab_' + str(offset)
                        + u'_')

                #mount -t ext4 -o loop,ro,noexec,noload,offset=241790330880 \
                #/media/image/ewf1 /media/a
                cmd = None
                if u'0x83' in p.desc.lower():
                    # ext
                    cmd = [u'mount', raw_path,
                            mountpoint, u'-t', u'ext4', u'-o',
                            u'loop,ro,noexec,noload,offset=' + str(offset)]
                    logging.info(u'Mounting ext volume on {0}.'.format(
                        mountpoint))
                elif u'bsd' in p.desc.lower():
                    # ufs
                    #mount -t ufs -o ufstype=ufs2,loop,ro,offset=4294967296 \
                    #/tmp/image/ewf1 /media/a
                    cmd = [u'mount', raw_path,
                            mountpoint, u'-t', u'ufs', u'-o',
                            u'ufstype=ufs2,loop,ro,offset=' + str(offset) ]
                    logging.info(u'Mounting UFS volume on {0}.'.format(
                        mountpoint))
                elif u'0xFD' in p.desc.lower():
                    # ext
                    cmd = [u'mount', raw_path,
                            mountpoint, u'-t', u'ext4', u'-o',
                            u'loop,ro,noexec,noload,offset=' + str(offset)]
                    logging.info(u'Mounting ext volume on {0}.'.format(
                        mountpoint))
                elif u'0x07' in p.desc.lower():
                    # NTFS
                    # We can't process windows, unfortunately
                    logging.warning(u'Found windows filesystem in ' +
                            self.paths[0])
                else:
                    logging.warning(u'Unknown filesystem encountered: ' + p.desc)
                if not cmd:
                    os.rmdir(mountpoint) 
                    continue

                logging.debug(u'Calling command "{0}"'.format(u' '.join(cmd)))
                subprocess.check_call(cmd, stdout=subprocess.PIPE)
                self.partition_mountpoints.append(mountpoint)
                yield mountpoint
                del d
            except IOError:
                logging.debug(u'Could not load partition {0}:{1}'
                        .format(p.addr, p.desc))

    def clean(self):
        '''
        Helper method that removes all ties to the filesystem, so the image can
        be unmounted successfully
        '''
        logging.info(u'Analysis complete, unmounting...')
        
        if self.image:
            self.image.close()
        del self.image
        del self.volumes
        for m in self.partition_mountpoints:
            if not util.unmount([u'umount'], m):
                pdb.set_trace()

        if not util.unmount([u'fusermount', u'-u'], self.basemountpoint):
            pdb.set_trace()
        logging.info(u'All cleaned up.')
