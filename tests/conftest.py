"""Shared test setup.

``Settings`` loads the developer's local ``.env``, which normally contains working
nexcore credentials. ``app/naming.py`` makes an outbound REST call driven by exactly
those settings, so a test that builds ``Settings()`` without overriding them could
hit a live tenant. Neutralise them for the whole suite: real env vars take precedence
over the dotenv file in pydantic-settings, so setting them empty wins.

Tests that need credentials pass them explicitly (see test_naming.py) or point at a
local mock server (see test_downloader.py, test_nexcore_client.py).
"""

import pytest

NEXCORE_ENV_VARS = ("NEXCORE_BASE_URL", "NEXCORE_API_KEY", "NEXCORE_API_KEY_ID")


@pytest.fixture(autouse=True)
def _no_real_nexcore_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in NEXCORE_ENV_VARS:
        monkeypatch.setenv(var, "")
