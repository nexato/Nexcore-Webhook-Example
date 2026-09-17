"""The app must report one version, and it must come from the package metadata.

`pyproject.toml` is the single source of truth. Nothing else may carry a version
literal — that is what drifted to `0.1.0` across releases 1.0.0–1.0.6.

Both branches are exercised explicitly because which one runs depends on the
environment: CI installs the package (`pip install ".[dev]"`), while a plain source
checkout run by pytest (`pythonpath = ["."]`) does not.
"""

from importlib.metadata import PackageNotFoundError

import app as app_pkg
from app import main


def test_reports_the_installed_distribution_version(monkeypatch) -> None:
    monkeypatch.setattr(app_pkg, "version", lambda name: "9.9.9")

    assert app_pkg.resolve_version() == "9.9.9"


def test_asks_for_the_distribution_named_in_pyproject(monkeypatch) -> None:
    asked: list[str] = []
    monkeypatch.setattr(app_pkg, "version", lambda name: asked.append(name) or "1.2.3")

    app_pkg.resolve_version()

    assert asked == ["nexcore-webhook-example"]


def test_falls_back_when_running_from_an_uninstalled_checkout(monkeypatch) -> None:
    def not_installed(name: str) -> str:
        raise PackageNotFoundError(name)

    monkeypatch.setattr(app_pkg, "version", not_installed)

    # Must not raise — running from source is a supported way to work on this.
    assert app_pkg.resolve_version() == app_pkg.DEV_VERSION


def test_the_fastapi_app_does_not_carry_its_own_version_literal() -> None:
    assert main.app.version == app_pkg.__version__
