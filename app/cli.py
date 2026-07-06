"""Subscription self-management CLI.

Usage::

    python -m app.cli subscription register
    python -m app.cli subscription status
    python -m app.cli subscription delete
    python -m app.cli subscription rotate-secret

The app manages its **own** subscription: it generates a secret, registers
idempotently over ``externalId`` (always sending the secret), and persists
``{externalId, id, secret}`` locally. The plaintext secret only ever lives
locally — the server keeps just ``sha256hex(secret)`` and cannot return it.
"""

from __future__ import annotations

import argparse
import json
import logging
import secrets
import sys
from typing import Any

from .config import Settings
from .nexcore_client import NexcoreClient
from .store import Store

logger = logging.getLogger("nexcore_webhook")


def generate_secret() -> str:
    """Generate a fresh webhook secret (256-bit, hex)."""
    return secrets.token_hex(32)


def _build_client(settings: Settings) -> NexcoreClient:
    return NexcoreClient(
        settings.nexcore_base_url,
        settings.nexcore_api_key,
        settings.nexcore_api_key_id,
    )


def register(
    settings: Settings, store: Store, *, client: NexcoreClient | None = None
) -> dict[str, Any]:
    """Create-or-update the subscription idempotently and persist its state."""
    if not settings.public_webhook_url:
        raise ValueError("PUBLIC_WEBHOOK_URL is required to register")
    client = client or _build_client(settings)
    external_id = settings.subscription_external_id

    existing = store.get_subscription(external_id)
    secret = existing.secret if existing and existing.secret else generate_secret()

    result = client.upsert_subscription(
        external_id=external_id,
        url=settings.public_webhook_url,
        event_types=settings.event_types,
        secret=secret,
    )
    subscription_id = result.subscription_id
    if subscription_id is None:  # fall back to a search if the POST body lacked the id
        found = client.find_subscription(external_id)
        subscription_id = str(found["id"]) if found and found.get("id") else None

    store.save_subscription(external_id, subscription_id, secret)
    return {
        "action": "created" if result.created else "updated",
        "externalId": external_id,
        "id": subscription_id,
        "secret_persisted": True,
        "reused_existing_secret": bool(existing and existing.secret),
    }


def status(
    settings: Settings, store: Store, *, client: NexcoreClient | None = None
) -> dict[str, Any]:
    """Compare locally stored state against the server."""
    client = client or _build_client(settings)
    external_id = settings.subscription_external_id
    local = store.get_subscription(external_id)
    remote = client.find_subscription(external_id)
    return {
        "externalId": external_id,
        "registered": remote is not None,
        "local": (
            {"id": local.subscription_id, "has_secret": bool(local.secret)} if local else None
        ),
        "remote": (
            {"id": str(remote.get("id")), "active": remote.get("active")} if remote else None
        ),
        "id_matches": bool(
            local and remote and local.subscription_id == str(remote.get("id"))
        ),
    }


def delete(
    settings: Settings, store: Store, *, client: NexcoreClient | None = None
) -> dict[str, Any]:
    """Resolve the id via externalId, delete remotely, then clear local state."""
    client = client or _build_client(settings)
    external_id = settings.subscription_external_id
    local = store.get_subscription(external_id)
    subscription_id = local.subscription_id if local and local.subscription_id else None
    if subscription_id is None:
        remote = client.find_subscription(external_id)
        subscription_id = str(remote["id"]) if remote and remote.get("id") else None

    deleted = client.delete_subscription(subscription_id) if subscription_id else False
    store.delete_subscription(external_id)
    return {"externalId": external_id, "id": subscription_id, "deleted": deleted}


def rotate_secret(
    settings: Settings, store: Store, *, client: NexcoreClient | None = None
) -> dict[str, Any]:
    """Generate a new secret, push it (POST always carries the secret), persist it."""
    if not settings.public_webhook_url:
        raise ValueError("PUBLIC_WEBHOOK_URL is required to rotate the secret")
    client = client or _build_client(settings)
    external_id = settings.subscription_external_id
    new_secret = generate_secret()
    result = client.upsert_subscription(
        external_id=external_id,
        url=settings.public_webhook_url,
        event_types=settings.event_types,
        secret=new_secret,
    )
    subscription_id = result.subscription_id
    if subscription_id is None:
        existing = store.get_subscription(external_id)
        subscription_id = existing.subscription_id if existing else None
    store.save_subscription(external_id, subscription_id, new_secret)
    return {"externalId": external_id, "id": subscription_id, "rotated": True}


_ACTIONS = {
    "register": register,
    "status": status,
    "delete": delete,
    "rotate-secret": rotate_secret,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nexcore-webhook")
    groups = parser.add_subparsers(dest="group", required=True)
    sub = groups.add_parser("subscription", help="Manage this app's webhook subscription")
    actions = sub.add_subparsers(dest="action", required=True)
    for name in _ACTIONS:
        actions.add_parser(name)

    args = parser.parse_args(argv)
    settings = Settings()
    logging.basicConfig(level=settings.log_level.upper())
    store = Store(settings.state_db_path)

    try:
        result = _ACTIONS[args.action](settings, store)
    except Exception as exc:  # surface a clean message, non-zero exit
        logger.error("subscription %s failed: %s", args.action, exc)
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
