class ImageMounterError(Exception):
    pass


class NoRootFoundError(ImageMounterError):
    """Used by reconstruct when no root could be found."""
    pass


class NotMountedError(ImageMounterError):
    """Used by methods that require the volume to be mounted."""
    pass


class CommandNotFoundError(ImageMounterError):
    """Raised by methods that require a specific command to be available, but isn't."""
    def __init__(self, command):
        self.command = command


class ModuleNotFoundError(ImageMounterError):
    """Raised by methods that require a specific module to be available, but isn't."""
    def __init__(self, module):
        self.module = module


class ArgumentError(ImageMounterError):
    """Raised when a method requires a specific argument to be present, but isn't, or the format is incorrect."""
    pass


class MountFailedError(ImageMounterError):
    """Raised when the mount failed, but it is the result of multiple non-critical errors, or it is unclear why it
    exactly failed (e.g. the mountpoint is empty after all calls where successful.
    Typically a SubsystemError is raised instead.
    """
    pass


class MountpointEmptyError(MountFailedError):
    """Raised when a mountpoint is empty but shouldn't be."""
    pass


class KeyInvalidError(MountFailedError):
    """Raised when a key is invalid."""
    pass


class SubsystemError(ImageMounterError):
    """Generic exception raised by methods when an unknown error occurs in one of the subsystems."""
    def __init__(self, base_exception):
        self.base_exception = base_exception


class AvailabilityError(ImageMounterError):
    """Base class for NoMountpointAvailableError and NoLoopbackAvailableError"""
    pass


class NoMountpointAvailableError(AvailabilityError):
    """Raised when a mountpoint is required, but could not be created, or could not be accessed."""
    pass


class NoLoopbackAvailableError(AvailabilityError):
    """Raised when a loopback device is required, but could not be found, or could not be accessed."""
    pass


class CleanupError(ImageMounterError):
    """Raised by the unmounter when cleaning failed."""
    pass


class FilesystemError(ImageMounterError):
    """Base class for several filesystem errors."""
    pass


class UnsupportedFilesystemError(FilesystemError):
    """Raised when a filesystem is attempted to be mounted, but the filesystem is unsupported."""
    pass


class IncorrectFilesystemError(FilesystemError):
    """Raised when an incorrect filesystem type is attempted to be mounted."""
    pass

