#!/bin/bash
if [[ $EUID -ne 0 ]]; then
	echo This script needs to be ran as root!
	exit 1
fi

tar xvf ./pytsk-2012-11-10.tgz
