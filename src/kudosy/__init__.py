"""Kudosy — automatically give kudos on Strava, with human-like timing."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("kudosy")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "0.0.0.dev0"

__all__ = ["__version__"]
