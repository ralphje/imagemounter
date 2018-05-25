Dependencies
============

The ``imagemounter.dependencies`` module defines several optional and required
dependencies to use ``imagemounter``. This data is used by the ``imount --check``
command, and can also be accessed via Python code:

.. code-block:: python

    from imagemounter.dependencies import ewfmount

    ...

    if ewfmount.is_available:
        do_something_with_ewfmount()
    else:
        print(ewfmount.printable_status)


Full list of dependencies:

- ``imagemounter.dependencies.affuse``
- ``imagemounter.dependencies.bdemount``
- ``imagemounter.dependencies.blkid``
- ``imagemounter.dependencies.cryptsetup``
- ``imagemounter.dependencies.disktype``
- ``imagemounter.dependencies.ewfmount``
- ``imagemounter.dependencies.file``
- ``imagemounter.dependencies.fsstat``
- ``imagemounter.dependencies.lvm``
- ``imagemounter.dependencies.magic``
- ``imagemounter.dependencies.mdadm``
- ``imagemounter.dependencies.mmls``
- ``imagemounter.dependencies.mount_jffs2``
- ``imagemounter.dependencies.mount_ntfs``
- ``imagemounter.dependencies.mount_squashfs``
- ``imagemounter.dependencies.mount_xfs``
- ``imagemounter.dependencies.mountavfs``
- ``imagemounter.dependencies.parted``
- ``imagemounter.dependencies.pytsk3``
- ``imagemounter.dependencies.qemu_nbd``
- ``imagemounter.dependencies.vmfs_fuse``
- ``imagemounter.dependencies.vmware_mount``
- ``imagemounter.dependencies.vshadowmount``
- ``imagemounter.dependencies.xmount``

API
---

The following classes are how dependencies are represented within imagemounter:

.. autoclass:: Dependency
    :members:
.. autoclass:: CommandDependency
    :members:
.. autoclass:: PythonModuleDependency
    :members:
.. autoclass:: MagicDependency
    :members:
.. autoclass:: DependencySection
    :members:
