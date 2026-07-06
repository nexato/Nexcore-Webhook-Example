"""Application configuration via environment variables (Pydantic Settings).

Field names map case-insensitively to the env vars documented in ``.env.example``
(e.g. ``nexcore_base_url`` ← ``NEXCORE_BASE_URL``). Keep the two in sync.

Note: the webhook ``secret`` is deliberately **not** here — it is app-generated
and persisted in the local state store, never configured via env.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
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

    # --- Download tuning ---
    download_timeout_seconds: int = 60
    download_max_retries: int = 3
    # Maximum size per downloaded file in bytes (0 = unlimited). Guards against a
    # runaway/oversized response filling the disk. Default 1 GiB.
    download_max_bytes: int = 1024 * 1024 * 1024

    # --- Operations ---
    log_level: str = "INFO"

    @property
    def event_types(self) -> list[str]:
        """``SUBSCRIPTION_EVENT_TYPES`` parsed into a list."""
        return [t.strip() for t in self.subscription_event_types.split(",") if t.strip()]

    @property
    def allowed_tenants(self) -> set[str]:
        """``TENANT_ALLOWLIST`` parsed into a set (empty = accept all tenants)."""
        return {t.strip() for t in self.tenant_allowlist.split(",") if t.strip()}
