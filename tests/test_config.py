"""Locating the `.env` file must not depend on the process working directory.

This is the regression guard for a silent production failure: a Windows/NSSM
install whose working directory was not the project folder loaded no `.env` at
all and started happily on the defaults.
"""

from pathlib import Path

import pytest

from app.config import ENV_FILE_VAR, Settings, resolve_env_file


def _write_env(path: Path, url: str) -> Path:
    path.write_text(f"PUBLIC_WEBHOOK_URL={url}\n", encoding="utf-8")
    return path


def test_env_file_found_in_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(ENV_FILE_VAR, raising=False)
    _write_env(tmp_path / ".env", "https://from-cwd.example/webhook")
    monkeypatch.chdir(tmp_path)

    assert resolve_env_file() == tmp_path / ".env"
    assert Settings().public_webhook_url == "https://from-cwd.example/webhook"


def test_explicit_path_is_used_from_any_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    env_file = _write_env(project / ".env", "https://from-explicit.example/webhook")

    monkeypatch.setenv(ENV_FILE_VAR, str(env_file))
    monkeypatch.chdir(elsewhere)

    assert resolve_env_file() == env_file
    assert Settings().public_webhook_url == "https://from-explicit.example/webhook"


def test_explicit_path_does_not_fall_back_to_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A typo'd NEXCORE_ENV_FILE must read as "not found", never as another file."""
    _write_env(tmp_path / ".env", "https://from-cwd.example/webhook")
    monkeypatch.setenv(ENV_FILE_VAR, str(tmp_path / "typo.env"))
    monkeypatch.chdir(tmp_path)

    assert resolve_env_file() is None
    assert Settings().public_webhook_url == ""


def test_no_env_file_anywhere_is_not_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(ENV_FILE_VAR, raising=False)
    monkeypatch.chdir(tmp_path)

    assert resolve_env_file() is None
    assert Settings().public_webhook_url == ""


def test_missing_required_reports_names_for_the_configured_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(ENV_FILE_VAR, raising=False)
    monkeypatch.chdir(tmp_path)

    # conftest blanks the NEXCORE_* credentials for the whole suite.
    bare = Settings(order_number_filenames=False)
    assert bare.missing_required() == ["PUBLIC_WEBHOOK_URL"]

    # The credentials only matter once something actually needs them.
    needs_lookup = Settings(order_number_filenames=True)
    assert "NEXCORE_BASE_URL" in needs_lookup.missing_required()

    complete = Settings(
        public_webhook_url="https://example.test/webhook",
        order_number_filenames=False,
    )
    assert complete.missing_required() == []
