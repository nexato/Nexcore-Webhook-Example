"""The test suite must never reach a real nexcore instance.

`Settings` reads the developer's local `.env`, which normally holds working
credentials. Since app/naming.py performs an outbound lookup driven by those
settings, a test that builds `Settings()` without overriding them could POST/GET
against a live tenant. conftest.py neutralises them for every test.
"""

from app.config import Settings


def test_settings_carry_no_real_credentials_under_test() -> None:
    settings = Settings()

    assert settings.nexcore_base_url == ""
    assert settings.nexcore_api_key == ""
    assert settings.nexcore_api_key_id == ""
