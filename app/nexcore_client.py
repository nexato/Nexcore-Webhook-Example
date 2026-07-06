"""Minimal REST client for the Nexcore subscription API.

Auth is via API key: two headers, ``x-auth-apiKey`` and ``x-auth-apiKeyId``
(the tenant is derived from the key server-side, so no tenant header is needed).
This only works against ``/api/**`` — not ``/graphql`` — which is why the app
uses REST rather than Keycloak/OAuth.

Endpoints (verified against ``de.nexato.framework`` ``SubscriptionController``):

- ``POST   /api/v1/subscription``            create-or-update (201 / 200), returns the subscription
- ``GET    /api/v1/subscription/search/{externalId}``  200 / 404
- ``GET    /api/v1/subscription/{id}``        200 / 404
- ``DELETE /api/v1/subscription/{id}``        204 / 404

⚠️ The ``secret`` MUST be sent on **every** POST. If an update POST omits it, the
server clears the stored ``secretHash`` and signature verification breaks. So
``upsert_subscription`` always includes it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

API_KEY_HEADER = "x-auth-apiKey"
API_KEY_ID_HEADER = "x-auth-apiKeyId"
SUBSCRIPTION_PATH = "/api/v1/subscription"


@dataclass
class UpsertResult:
    """Result of a create-or-update POST."""

    created: bool  # True for 201 (created), False for 200 (updated)
    subscription: dict[str, Any]

    @property
    def subscription_id(self) -> str | None:
        value = self.subscription.get("id")
        return str(value) if value is not None else None


class NexcoreClient:
    """Thin httpx-based client for the subscription REST API."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        api_key_id: str,
        *,
        timeout: float = 15.0,
    ) -> None:
        if not base_url:
            raise ValueError("NEXCORE_BASE_URL is required")
        if not api_key or not api_key_id:
            raise ValueError("NEXCORE_API_KEY and NEXCORE_API_KEY_ID are required")
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._headers = {
            API_KEY_HEADER: api_key,
            API_KEY_ID_HEADER: api_key_id,
            "Accept": "application/json",
        }

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self._base_url, headers=self._headers, timeout=self._timeout
        )

    def upsert_subscription(
        self,
        *,
        external_id: str,
        url: str,
        event_types: list[str],
        secret: str,
        active: bool = True,
    ) -> UpsertResult:
        """Create or update the subscription. Always sends ``secret`` (see module note)."""
        if not secret:
            raise ValueError("secret must always be sent on a subscription POST")
        body = {
            "externalId": external_id,
            "url": url,
            "eventTypes": event_types,
            "active": active,
            "type": "WEBHOOK",
            "secret": secret,
        }
        with self._client() as client:
            resp = client.post(SUBSCRIPTION_PATH, json=body)
            resp.raise_for_status()
            data = resp.json() if resp.content else {}
        return UpsertResult(created=resp.status_code == 201, subscription=data)

    def find_subscription(self, external_id: str) -> dict[str, Any] | None:
        """Return the subscription for ``external_id`` (200) or ``None`` (404)."""
        with self._client() as client:
            resp = client.get(f"{SUBSCRIPTION_PATH}/search/{external_id}")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()

    def delete_subscription(self, subscription_id: str) -> bool:
        """Delete by id. Returns ``True`` if deleted, ``False`` if it didn't exist (404)."""
        with self._client() as client:
            resp = client.delete(f"{SUBSCRIPTION_PATH}/{subscription_id}")
            if resp.status_code == 404:
                return False
            resp.raise_for_status()
            return True
