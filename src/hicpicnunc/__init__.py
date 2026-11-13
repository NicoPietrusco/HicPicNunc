"""Hic Pic Nunc: export photos from Google Photos while keeping their capture metadata."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("hicpicnunc")
except PackageNotFoundError:  # running from a source tree that was never installed
    # Not an X.Y.Z version, so release-please leaves it alone when it bumps the version.
    __version__ = "0+unknown"
