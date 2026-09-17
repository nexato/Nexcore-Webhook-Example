"""nexcore webhook example receiver.

The version lives in ``pyproject.toml`` and nowhere else. It is read back from the
installed distribution's metadata rather than duplicated as a literal — duplicated
literals are what drifted to ``0.1.0`` while releases 1.0.0–1.0.6 shipped.
"""

from importlib.metadata import PackageNotFoundError, version

#: Distribution name as declared in ``pyproject.toml`` → ``[project].name``.
DIST_NAME = "nexcore-webhook-example"

#: Reported when running from a source checkout that was never ``pip install``ed
#: (e.g. pytest with ``pythonpath = ["."]``). Every deployment path installs the
#: package, so this value should not appear in a real deployment.
DEV_VERSION = "0.0.0+dev"


def resolve_version() -> str:
    """Return the installed distribution version, or ``DEV_VERSION`` if not installed."""
    try:
        return version(DIST_NAME)
    except PackageNotFoundError:
        return DEV_VERSION


__version__ = resolve_version()
