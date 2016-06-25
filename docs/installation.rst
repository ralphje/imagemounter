Installation
============

If you need an installation with full support, including all optional dependencies, you could use the following commands::

    apt-get install python-setuptools xmount ewf-tools afflib-tools sleuthkit lvm2 mdadm cryptsetup
    pip install imagemounter

Python packages
---------------
This package does not require other packages, though the :mod:`termcolor` package is recommended if you are using the :command:`imount` command line utility with the :option:`--color` argument.

If you wish to use :mod:`pytsk3` support, you require *python-dev* and *libtsk-dev*. For compilation, the *build-essential*
package from your distribution is also required. After that, you can easily install the :mod:`pytsk3` package from PyPI
(:command:`pip` requires the :option:`--pre` flag to allow installing the package).

Other dependencies
------------------
This package highly depends on other utilities to be present on your system. For a full installation, you require more tools. YYou can run ``imount --check`` to get a full list of all required tools.

A basic installation contains at least one of the mount tools. Highly recommended is also ``fsstat``, others are required
for specific file system types.

ewfmount on Ubuntu 13.10
------------------------
Due to a bug with *ewf-tools* in Ubuntu <=13.10, it may be that :command:`ewfmount` is not properly provided. This bug has been
resolved in Ubuntu 14.04. If you are using Ubuntu 13.10, you can install *ewf-tools* with :command:`ewfmount` as follows:

1. Download a recent build of *ewf-tools* from https://launchpad.net/ubuntu/+source/libewf/20130416-2ubuntu1
   (choose your arch under 'Builds' and download all deb files under 'Built files')
2. Execute ``sudo apt-get install libbfio1``
3. Execute ``sudo dpkg -i ewf-tools_* libewf2_*``
