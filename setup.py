#!/usr/bin/env python
import os
from setuptools import setup


def get_metadata():
    import re
    with open(os.path.join("imagemounter", "__init__.py")) as f:
        return dict(re.findall("__([a-z]+)__ = ['\"]([^'\"]+)['\"]", f.read()))

metadata = get_metadata()

setup(
    name='imagemounter',
    version=metadata['version'],
    packages=['imagemounter'],
    author='Peter Wagenaar, Ralph Broenink',
    url = 'https://github.com/ralphje/imagemounter',
    download_url = 'https://github.com/ralphje/imagemounter/tarball/v' + metadata['version'],
    description='Utility to mount partitions in Encase and dd images locally on Linux operating systems.',
    entry_points={'console_scripts': ['imount = imagemounter.mount_images:main']},
    install_requires=['pytsk3', 'termcolor']
)
