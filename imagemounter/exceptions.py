class ImageMounterError(Exception):
    """Base class for all exceptions::

    ImageMounterError
    |- PrerequisiteFailedError
       |- CommandNotFoundError
       |- ModuleNotFoundError
       |- ArgumentError
       |- NotMountedError
    |- MountError
       |- MountpointEmptyError
       |- KeyInvalidError
       |- FilesystemError
          |- UnsupportedFilesystemError
          |- IncorrectFilesystemError
       |- AvailabilityError
          |- NoMountpointAvailableError
          |- NoLoopbackAvailableError
          |- NoNetworkBlockAvailableError
    |- CleanupError
    |- NoRootFoundError
    |- DiskIndexError
    |- SubsystemError

    """

    pass


class NoRootFoundError(ImageMounterError):
    """Used by reconstruct when no root could be found."""
    pass


class DiskIndexError(ImageMounterError):
    """Used by add_disk if a disk is being added when the previous disk had no index."""
    pass


class PrerequisiteFailedError(ImageMounterError):
    """Base class for several errors that are thrown when a method could not execute due to failing prerequisites
    e.g. specific arguments, a specific state or a specific command/module.
    """
    pass


class NotMountedError(PrerequisiteFailedError):
    """Used by methods that require a volume or disk to be mounted."""
    pass


class CommandNotFoundError(PrerequisiteFailedError):
    """Raised by methods that require a specific command to be available, but isn't."""
    pass


class ModuleNotFoundError(PrerequisiteFailedError):
    """Raised by methods that require a specific module to be available, but isn't."""


class ArgumentError(PrerequisiteFailedError):
    """Raised when a method requires a specific argument to be present, but isn't, or the format is incorrect."""
    pass


class MountError(ImageMounterError):
    """Raised when the mount failed, but it is the result of multiple non-critical errors, or it is unclear why it
    exactly failed (e.g. the mountpoint is empty after all calls where successful.
    Typically a SubsystemError is raised instead.
    """
    pass


class MountpointEmptyError(MountError):
    """Raised when a mountpoint is empty but shouldn't be."""
    pass


class KeyInvalidError(MountError):
    """Raised when a key is invalid."""
    pass


class FilesystemError(MountError):
    """Base class for several filesystem errors."""
    pass


class UnsupportedFilesystemError(FilesystemError):
    """Raised when a filesystem is attempted to be mounted, but the filesystem is unsupported."""
    pass


class IncorrectFilesystemError(FilesystemError):
    """Raised when an incorrect filesystem type is attempted to be mounted."""
    pass


class AvailabilityError(MountError):
    """Base class for NoMountpointAvailableError and NoLoopbackAvailableError"""
    pass


class NoMountpointAvailableError(AvailabilityError):
    """Raised when a mountpoint is required, but could not be created, or could not be accessed."""
    pass


class NoLoopbackAvailableError(AvailabilityError):
    """Raised when a loopback device is required, but could not be found, or could not be accessed."""
    pass


class NoNetworkBlockAvailableError(AvailabilityError):
    """Raised when a network block device is required, but could not be found, or could not be accessed."""
    pass


class SubsystemError(ImageMounterError):
    """Generic exception raised by methods when an unknown error occurs in one of the subsystems."""


class CleanupError(ImageMounterError):
    """Raised by the unmounter when cleaning failed."""
    pass
