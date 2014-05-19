Installation
============

If you need a full installation, including all optional dependencies, you could use the following commands::

    apt-get install python-setuptools xmount ewf-tools afflib-tools sleuthkit lvm2 mdadm cryptsetup
    pip install imagemounter

Python packages
---------------
This package does not require other packages, though the `termcolor` package is recommended if you are using the `imount` command line utility with the `--color` argument.

If you wish to use _pytsk3_ support, you require `python-dev` and `libtsk-dev`. For compilation, the `build-essential`
package from your distribution is also required. After that, you can easily install the `pytsk3` package from PyPI
(pip requires the --pre flag to allow installing the package).

Other dependencies
------------------
This package highly depends on other utilities to be present on your system. For a full installation, you require the
following tools:

* Mount tools

  * `xmount`
  * `ewfmount`, part of ewf-tools package, see note below
  * `affuse`, part of afflib-tools package

* Volume detection

  * `mmls`, part of sleuthkit package
  * `pytsk3`

* Statistics, e.g. last mountpoint of volumes

  * `fsstat`, part of sleuthkit package

* LVM volumes

  * `lvm` et al, all part of lvm2 package

* RAID arrays

  * `mdadm`

* LUKS volumes

  * `cryptsetup`

A basic installation contains at least one of the mount tools. Highly recommended is also `fsstat`, others are required
for specific file system types.

ewfmount on Ubuntu 13.10
------------------------
Due to a bug with ewf-tools in Ubuntu <=13.10, it may be that ewfmount is not properly provided. This bug has been
resolved in Ubuntu 14.04. If you are using Ubuntu 13.10, you can install ewf-tools with ewfmount as follows:

1. Download a recent build of ewf-tools from https://launchpad.net/ubuntu/+source/libewf/20130416-2ubuntu1
   (choose your arch under 'Builds' and download all deb files under 'Built files')
2. Execute `sudo apt-get install libbfio1`
3. Execute `sudo dpkg -i ewf-tools_* libewf2_*`