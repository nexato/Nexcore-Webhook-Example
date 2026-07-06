"""Subscription self-management orchestration tests.

Uses a FakeClient so we exercise the register/status/delete/rotate logic without
a network. The HTTP client itself is tested in test_nexcore_client.py.
"""

from pathlib import Path

import pytest

from app import cli
from app.config import Settings
from app.nexcore_client import UpsertResult
from app.store import Store


class FakeClient:
    def __init__(self) -> None:
        self.upserts: list[dict] = []
        self.deleted: list[str] = []
        self.remote: dict[str, dict] = {}
        self._counter = 0

    def upsert_subscription(self, *, external_id, url, event_types, secret, active=True):
        self.upserts.append(
            {"external_id": external_id, "url": url, "secret": secret, "active": active}
        )
        created = external_id not in self.remote
        if created:
            self._counter += 1
            sid = f"srv-id-{self._counter}"
        else:
            sid = self.remote[external_id]["id"]
        sub = {"id": sid, "externalId": external_id, "url": url, "active": active}
        self.remote[external_id] = sub
        return UpsertResult(created=created, subscription=sub)

    def find_subscription(self, external_id):
        return self.remote.get(external_id)

    def delete_subscription(self, subscription_id):
        self.deleted.append(subscription_id)
        for key, value in list(self.remote.items()):
            if value["id"] == subscription_id:
                del self.remote[key]
                return True
        return False


def make_settings(tmp_path: Path, **over) -> Settings:
    base = {
        "state_db_path": tmp_path / "state.sqlite",
        "subscription_external_id": "ext-1",
        "public_webhook_url": "https://host.example/webhook",
        "subscription_event_types": "export.completed",
    }
    base.update(over)
    return Settings(**base)


def test_register_is_idempotent_and_reuses_secret(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    store = Store(settings.state_db_path)
    client = FakeClient()

    first = cli.register(settings, store, client=client)
    assert first["action"] == "created"
    assert first["reused_existing_secret"] is False
    secret1 = store.get_subscription("ext-1").secret
    assert secret1  # persisted locally

    second = cli.register(settings, store, client=client)
    assert second["action"] == "updated"
    assert second["reused_existing_secret"] is True
    # same secret reused on update
    assert store.get_subscription("ext-1").secret == secret1
    assert {u["secret"] for u in client.upserts} == {secret1}


def test_every_post_includes_a_secret(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    store = Store(settings.state_db_path)
    client = FakeClient()
    cli.register(settings, store, client=client)
    cli.rotate_secret(settings, store, client=client)
    assert all(u["secret"] for u in client.upserts)


def test_register_persists_server_id(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    store = Store(settings.state_db_path)
    client = FakeClient()
    result = cli.register(settings, store, client=client)
    assert result["id"] == "srv-id-1"
    assert store.get_subscription("ext-1").subscription_id == "srv-id-1"


def test_delete_resolves_id_via_external_id_then_deletes(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    store = Store(settings.state_db_path)
    client = FakeClient()
    cli.register(settings, store, client=client)

    # Simulate lost local id → must resolve via find_subscription(externalId).
    store.save_subscription("ext-1", None, store.get_subscription("ext-1").secret)

    result = cli.delete(settings, store, client=client)
    assert result["deleted"] is True
    assert result["id"] == "srv-id-1"
    assert client.deleted == ["srv-id-1"]
    assert store.get_subscription("ext-1") is None  # local state cleared


def test_rotate_secret_generates_new_secret(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    store = Store(settings.state_db_path)
    client = FakeClient()
    cli.register(settings, store, client=client)
    secret1 = store.get_subscription("ext-1").secret

    cli.rotate_secret(settings, store, client=client)
    secret2 = store.get_subscription("ext-1").secret
    assert secret2 != secret1
    assert client.upserts[-1]["secret"] == secret2


def test_status_compares_local_and_remote(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    store = Store(settings.state_db_path)
    client = FakeClient()
    cli.register(settings, store, client=client)

    result = cli.status(settings, store, client=client)
    assert result["registered"] is True
    assert result["id_matches"] is True
    assert result["local"]["has_secret"] is True
    assert result["remote"]["id"] == "srv-id-1"


def test_register_requires_public_webhook_url(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, public_webhook_url="")
    store = Store(settings.state_db_path)
    with pytest.raises(ValueError, match="PUBLIC_WEBHOOK_URL"):
        cli.register(settings, store, client=FakeClient())


def test_generate_secret_is_unique_and_hex() -> None:
    s1, s2 = cli.generate_secret(), cli.generate_secret()
    assert s1 != s2
    assert len(s1) == 64
    int(s1, 16)  # valid hex
