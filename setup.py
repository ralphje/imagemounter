#!/usr/bin/env python
import os
from setuptools import setup


def get_metadata():
    import re
    with open(os.path.join("imagemounter", "__init__.py")) as f:
        return dict(re.findall("__([a-z]+)__ = ['\"]([^'\"]+)['\"]", f.read()))

metadata = get_metadata()

try:
    long_description = open("README.rst", "r").read()
except Exception:
    long_description = None

setup(
    name='imagemounter',
    version=metadata['version'],
    license='MIT',
    packages=['imagemounter'],
    author='Peter Wagenaar, Ralph Broenink',
    author_email='ralph@ralphbroenink.net',
    url='https://github.com/ralphje/imagemounter',
    download_url='https://github.com/ralphje/imagemounter/tarball/v' + metadata['version'],
    description='Utility to mount partitions in Encase, AFF and dd images locally on Linux operating systems.',
    long_description=long_description,
    entry_points={'console_scripts': ['imount = imagemounter.imount:main']},
    install_requires=['termcolor>=1.0.0'],
    extras={"magic": ["python-magic>=0.4"]},
    keywords=['encase', 'aff', 'dd', 'disk image', 'ewfmount', 'affuse', 'xmount', 'imount'],
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Environment :: Console',
        'Intended Audience :: Developers',
        'Intended Audience :: Legal Industry',
        'Intended Audience :: System Administrators',
        'License :: OSI Approved :: MIT License',
        'Operating System :: POSIX :: Linux',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3.2',
        'Programming Language :: Python :: 3.3',
        'Programming Language :: Python :: 3.4',
        'Topic :: Scientific/Engineering :: Information Analysis',
        'Topic :: System :: Filesystems',
        'Topic :: Terminals',
        'Topic :: Utilities',
    ],
)
