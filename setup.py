from setuptools import setup

print "Note: install/install.sh is also provided."

setup(
    name='image_mounter',
    version='1.0.0',
    packages=['imagemounter'],
    author='Peter Wagenaar, Ralph Broenink',
    description='Utility to mount partitions in Encase and dd images locally on Linux operating systems.',
    entry_points={'console_scripts': ['mount_images = imagemounter.mount_images:main']},
    install_requires=['pytsk3', 'termcolor']
)
