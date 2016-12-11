Installation
============

If you need an installation with basic support, you are suggested to run the following commands::

    apt-get install python-setuptools xmount ewf-tools afflib-tools sleuthkit
    pip install imagemounter
    imount --check

The latter command will list all other packages you could install to expand the capabilities of imagemounter.

Python packages
---------------
This package does not require other packages, though the :mod:`termcolor` package is recommended if you are using the :command:`imount` command line utility with the :option:`--color` argument.

If you wish to use :mod:`pytsk3` support, you require *python-dev* and *libtsk-dev*. For compilation, the *build-essential*
package from your distribution is also required. After that, you can easily install the :mod:`pytsk3` package from PyPI
(:command:`pip` requires the :option:`--pre` flag to allow installing the package).

Other dependencies
------------------
This package highly depends on other utilities to be present on your system. For a full installation, you require more tools. You can run ``imount --check`` to get a full list of all required tools.

A basic installation contains at least one of the mount tools. Highly recommended is also ``fsstat``, others are required
for specific file system types.

You can install ``vmware-mount`` by installing VMware Workstation on your system.
