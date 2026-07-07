"""FastAPI receiver: ``POST /webhook`` and ``GET /healthz``.

Request flow for ``/webhook`` (see the README "How it works" and
docs/webhook-payload-reference.md):

1. Read the **raw** body bytes (before any JSON parsing).
2. Verify the HMAC signature with the locally stored secret. Invalid/missing → 401.
3. Parse + validate the payload (Pydantic). Malformed → 400.
4. Non-``export.completed`` event → friendly 200 (ignored).
5. Optional tenant allowlist → not allowed → friendly 200 (ignored).
6. Atomically **claim** the event id (idempotency). Already claimed → 200 (duplicate).
7. Respond **200 fast** and download the files in a background task.

Responding quickly matters: Nexcore's webhook client uses a 15s read timeout and
retries non-2xx up to 4×. Because we answer 200 immediately, a *failed* background
download is **not** recovered by a Nexcore redelivery (Nexcore already saw 2xx);
we therefore log it loudly and release the idempotency claim so that, if a
duplicate of the same event does arrive, it will be re-attempted.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request

from .config import Settings
from .downloader import download_files
from .models import WebhookEvent
from .security import SIGNATURE_HEADER, verify_signature
from .store import Store

#: Header carrying the tenant id (the tenant is NOT in the payload body).
TENANT_HEADER = "x-nx-tenant-id"

logger = logging.getLogger("nexcore_webhook")

_settings = Settings()
logging.basicConfig(
    level=_settings.log_level.upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


def get_settings() -> Settings:
    """Settings provider (overridable in tests)."""
    return _settings


SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_store(settings: SettingsDep) -> Store:
    """Store provider bound to the configured DB path (overridable in tests)."""
    return Store(settings.state_db_path)


StoreDep = Annotated[Store, Depends(get_store)]


def process_event(
    event: WebhookEvent, tenant_id: str | None, settings: Settings, store: Store
) -> None:
    """Background processing of an accepted export event.

    The event id was already claimed in the request handler (race-free dedup).
    Here we download every file; if a download fails we **release the claim** so a
    duplicate redelivery (if any) can re-attempt, and log the failure at error
    level. On success the claim stands.
    """
    files = event.data.files if event.data else []
    logger.info(
        "processing event %s eventType=%s tenant=%s files=%d",
        event.id,
        event.event_type,
        tenant_id,
        len(files),
    )
    if not files:
        logger.info("event %s has no files to download", event.id)
        return

    try:
        stored = download_files(
            files,
            output_dir=settings.output_dir,
            tenant_id=tenant_id,
            entity_id=event.entity_id,
            timeout=settings.download_timeout_seconds,
            max_retries=settings.download_max_retries,
            max_bytes=settings.download_max_bytes,
        )
    except Exception:
        logger.error(
            "download failed for event %s — releasing idempotency claim; "
            "the export will NOT be retried automatically by Nexcore (already 2xx'd)",
            event.id,
            exc_info=True,
        )
        store.unmark_event_processed(event.id)
        return
    logger.info("event %s processed: stored %d file(s)", event.id, len(stored))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Optionally register/reconcile the subscription on startup (AUTO_REGISTER)."""
    if _settings.auto_register:
        try:
            from .cli import register

            result = register(_settings, Store(_settings.state_db_path))
            logger.info("AUTO_REGISTER: subscription %s", result.get("action"))
        except Exception:
            logger.exception("AUTO_REGISTER failed — register manually with the CLI")
    yield


app = FastAPI(title="Nexcore Webhook Example", version="0.1.0", lifespan=lifespan)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/webhook")
async def webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    settings: SettingsDep,
    store: StoreDep,
) -> dict[str, str]:
    # 1. Raw body — verify over the exact received bytes, never re-serialize.
    raw = await request.body()

    # 2. Signature verification against the locally stored secret.
    subscription = store.get_subscription(settings.subscription_external_id)
    secret = subscription.secret if subscription else None
    if not secret:
        logger.warning(
            "no local secret for externalId=%s — run 'subscription register' first",
            settings.subscription_external_id,
        )
        raise HTTPException(status_code=401, detail="No subscription secret configured")

    signature = request.headers.get(SIGNATURE_HEADER)
    if not verify_signature(raw, secret, signature):
        logger.warning("rejected webhook: invalid or missing signature")
        raise HTTPException(status_code=401, detail="Invalid signature")

    # 3. Validate payload.
    try:
        event = WebhookEvent.model_validate_json(raw)
    except ValueError as exc:
        logger.warning("rejected webhook: invalid payload: %s", exc)
        raise HTTPException(status_code=400, detail="Invalid payload") from exc

    # 4. Ignore non-export events (friendly 200 so Nexcore stops retrying).
    if not event.is_export_completed:
        logger.info("ignoring event %s of type %s", event.id, event.event_type)
        return {"status": "ignored"}

    # 5. Optional tenant allowlist.
    tenant_id = request.headers.get(TENANT_HEADER)
    allowed = settings.allowed_tenants
    if allowed and tenant_id not in allowed:
        logger.info("ignoring event %s from tenant %s (not in allowlist)", event.id, tenant_id)
        return {"status": "ignored"}

    # 6. Idempotency: atomically claim the event id BEFORE scheduling. If the
    # claim fails it was already processed (or is in-flight) → acknowledge.
    if not store.mark_event_processed(event.id):
        logger.info("duplicate event %s — already claimed/processed", event.id)
        return {"status": "duplicate"}

    # 7. Fast 200 + background download (process_event releases the claim on failure).
    background_tasks.add_task(process_event, event, tenant_id, settings, store)
    return {"status": "accepted"}
