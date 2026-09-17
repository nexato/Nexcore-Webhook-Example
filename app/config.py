"""Application configuration via environment variables (Pydantic Settings).

Field names map case-insensitively to the env vars documented in ``.env.example``
(e.g. ``nexcore_base_url`` ← ``NEXCORE_BASE_URL``). Keep the two in sync.

The ``.env`` file is located **independently of the process working directory** —
see :func:`resolve_env_file`. That matters for service installs (Windows/NSSM,
systemd), where the working directory is whatever the service manager sets and a
CWD-relative lookup silently falls back to the defaults below.

Note: the webhook ``secret`` is deliberately **not** here — it is app-generated
and persisted in the local state store, never configured via env.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

#: Env var holding an explicit path to the ``.env`` file. Set this (to an absolute
#: path) when the working directory is not under your control — e.g.
#: ``nssm set nexcoreWebhook AppEnvironmentExtra NEXCORE_ENV_FILE=C:\...\.env``.
ENV_FILE_VAR = "NEXCORE_ENV_FILE"

#: Directory the ``app`` package sits in. Equals the project root for a source
#: checkout or an editable install; for ``pip install .`` it is site-packages,
#: where no ``.env`` will ever be — harmless, it just won't match.
INSTALL_ROOT = Path(__file__).resolve().parent.parent


def env_file_candidates() -> list[Path]:
    """The ``.env`` locations considered, most specific first.

    If :data:`ENV_FILE_VAR` is set it is the **only** candidate: a typo in an
    explicit path must surface as "not found", not silently resolve to some other
    file that happens to exist.
    """
    explicit = os.environ.get(ENV_FILE_VAR, "").strip()
    if explicit:
        return [Path(explicit).expanduser()]
    return [Path.cwd() / ".env", INSTALL_ROOT / ".env"]


def resolve_env_file() -> Path | None:
    """First existing candidate from :func:`env_file_candidates`, else ``None``.

    ``None`` means "configure from real environment variables and defaults only",
    which is the normal case for container deployments.
    """
    for candidate in env_file_candidates():
        if candidate.is_file():
            return candidate
    return None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Nexcore connection (REST API) ---
    nexcore_base_url: str = ""
    nexcore_api_key: str = ""
    nexcore_api_key_id: str = ""

    # --- Subscription self-management ---
    subscription_external_id: str = "nexcore-webhook-example"
    subscription_event_types: str = "export.completed"
    public_webhook_url: str = ""
    auto_register: bool = False

    # --- Receiver & storage ---
    output_dir: Path = Path("./output")
    state_db_path: Path = Path("./state.sqlite")
    tenant_allowlist: str = ""

    # --- File naming ---
    # For `rental.order.completed` exports, look the order up via the REST API and
    # name the file `<orderNumber>_<timestamp>` instead of `<entityId>_<index>`.
    # Requires the NEXCORE_* credentials above; without them (and on any lookup
    # failure) the default entityId naming is used. See app/naming.py.
    order_number_filenames: bool = True

    # --- Download tuning ---
    download_timeout_seconds: int = 60
    download_max_retries: int = 3
    # Maximum size per downloaded file in bytes (0 = unlimited). Guards against a
    # runaway/oversized response filling the disk. Default 1 GiB.
    download_max_bytes: int = 1024 * 1024 * 1024

    # --- Operations ---
    log_level: str = "INFO"

    def __init__(self, **kwargs: Any) -> None:
        # Resolved per instantiation rather than baked into model_config at import
        # time, so the lookup honours the environment as it is when Settings is built.
        kwargs.setdefault("_env_file", resolve_env_file())
        super().__init__(**kwargs)

    @property
    def event_types(self) -> list[str]:
        """``SUBSCRIPTION_EVENT_TYPES`` parsed into a list."""
        return [t.strip() for t in self.subscription_event_types.split(",") if t.strip()]

    @property
    def allowed_tenants(self) -> set[str]:
        """``TENANT_ALLOWLIST`` parsed into a set (empty = accept all tenants)."""
        return {t.strip() for t in self.tenant_allowlist.split(",") if t.strip()}

    def missing_required(self) -> list[str]:
        """Names of env vars that are needed for the configured mode but unset.

        Only what the *current* configuration actually requires: the NEXCORE_*
        credentials matter for the subscription CLI, AUTO_REGISTER and the order
        number lookup, so they are not reported when none of those are in play.
        """
        missing = []
        if not self.public_webhook_url:
            missing.append("PUBLIC_WEBHOOK_URL")
        if self.auto_register or self.order_number_filenames:
            for name, value in (
                ("NEXCORE_BASE_URL", self.nexcore_base_url),
                ("NEXCORE_API_KEY", self.nexcore_api_key),
                ("NEXCORE_API_KEY_ID", self.nexcore_api_key_id),
            ):
                if not value:
                    missing.append(name)
        return missing
