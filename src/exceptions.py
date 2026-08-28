"""Application-specific exception hierarchy."""


class QwenASRDesktopError(Exception):
    """Base class for errors that can be presented to the user."""


class FFmpegNotFoundError(QwenASRDesktopError):
    """FFmpeg or FFprobe could not be found."""


class NoAudioStreamError(QwenASRDesktopError):
    """The selected media does not contain an audio stream."""


class MediaProcessingError(QwenASRDesktopError):
    """FFmpeg or FFprobe failed to process media."""


class ModelLoadError(QwenASRDesktopError):
    """The local ASR model could not be loaded."""


class TranscriptionError(QwenASRDesktopError):
    """A segment could not be transcribed."""


class UserCancelledError(QwenASRDesktopError):
    """The user cancelled the active task."""
