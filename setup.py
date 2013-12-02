from setuptools import setup

setup(
    name='image_mounter',
    version='1.0.3',
    packages=['imagemounter'],
    author='Peter Wagenaar, Ralph Broenink',
    description='Utility to mount partitions in Encase and dd images locally on Linux operating systems.',
    entry_points={'console_scripts': ['mount_images = imagemounter.mount_images:main']},
    install_requires=['pytsk3', 'termcolor']
)
