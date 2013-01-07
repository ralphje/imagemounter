#!/bin/bash
if [[ $EUID -ne 0 ]]; then
	echo This script needs to be ran as root!
	exit 1
fi
/usr/bin/apt-get install uuid-dev python-dev libtsk-dev g++ build-essential xmount

/bin/tar xvf ./pytsk-2012-11-10.tgz

cd ./pytsk
/usr/bin/python ./setup.py build
/usr/bin/python ./setup.py install
cd ..
echo All dependencies installed, you can now remove the pytsk folder
