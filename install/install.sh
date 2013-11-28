#!/bin/bash
if [[ $EUID -ne 0 ]]; then
	echo This script needs to be ran as root!
	exit 1
fi

echo Script to install the mount_images command line utility and imagemounter Python module and most importantly, its dependencies
echo

echo Installing dependencies...

# Install libtsk-dev, xmount
/usr/bin/apt-get install uuid-dev python-setuptools python-dev libtsk-dev g++ build-essential xmount sleuthkit

cd `dirname $0`

# Install pytsk
/bin/tar xvf ./pytsk-2013-09-10.tgz
cd ./pytsk
/usr/bin/python ./setup.py build
/usr/bin/python ./setup.py install
cd ..
rm -Rf ./pytsk

# Install termcolor
/bin/tar xvf ./termcolor-1.1.0.tar.gz
cd ./termcolor-1.1.0
/usr/bin/python ./setup.py install
cd ..
rm -Rf ./termcolor-1.1.0

echo
echo All dependencies installed!
echo Installing module and utility...
echo

cd ..

/usr/bin/python ./setup.py install
rm -Rf build
rm -Rf dist
rm -Rf image_mounter.egg-info

echo
echo All done!
echo
echo
echo You may also want to install:   afflib-tools  ewf-tools
echo
echo Note: if ewf-tools does not include ewfmount, go to the following url to obtain recent working deb packages:
echo https://launchpad.net/ubuntu/+source/libewf
echo Binary packages from 20130416-2ubuntu1 are known to provide ewfmount