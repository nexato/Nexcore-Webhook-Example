"""/webhook endpoint tests."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import Settings
from app.main import TENANT_HEADER
from app.security import SIGNATURE_HEADER, compute_signature
from app.store import Store

EXT = "test-ext"
SECRET = "unit-test-secret"


@pytest.fixture(autouse=True)
def _clear_overrides() -> None:
    yield
    main.app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _stub_download(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep endpoint tests network-free; the real download is tested in test_downloader."""
    monkeypatch.setattr(main, "download_files", lambda *a, **k: [])


def make_client(tmp_path: Path, *, register: bool = True, allowlist: str = "") -> tuple:
    db = tmp_path / "state.sqlite"
    settings = Settings(
        state_db_path=db, subscription_external_id=EXT, tenant_allowlist=allowlist
    )
    store = Store(db)
    if register:
        store.save_subscription(EXT, "sub-uuid", SECRET)
    main.app.dependency_overrides[main.get_settings] = lambda: settings
    return TestClient(main.app), store


def export_body(event_id: str = "evt-1") -> bytes:
    return json.dumps(
        {
            "id": event_id,
            "eventType": "export.completed",
            "attempt": 0,
            "entityId": "entity-1",
            "subscriptionId": "sub-1",
            "subscriptionIdExternaId": EXT,
            "data": {
                "files": [
                    {"url": "https://example.test/f.pdf", "mimeType": "application/pdf"}
                ],
                "sourceEvent": "rental.order.completed",
            },
        }
    ).encode()


def headers(body: bytes, secret: str = SECRET, **extra: str) -> dict[str, str]:
    h = {"content-type": "application/json", SIGNATURE_HEADER: compute_signature(body, secret)}
    h.update(extra)
    return h


def test_healthz(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_valid_signed_export_event_accepted(tmp_path: Path) -> None:
    client, store = make_client(tmp_path)
    body = export_body("evt-accept")
    r = client.post("/webhook", content=body, headers=headers(body))
    assert r.status_code == 200
    assert r.json()["status"] == "accepted"
    # background task ran → event recorded as processed
    assert store.is_event_processed("evt-accept") is True


def test_invalid_signature_rejected(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)
    body = export_body()
    r = client.post(
        "/webhook",
        content=body,
        headers={"content-type": "application/json", SIGNATURE_HEADER: "DEADBEEF"},
    )
    assert r.status_code == 401


def test_missing_signature_rejected(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)
    body = export_body()
    r = client.post("/webhook", content=body, headers={"content-type": "application/json"})
    assert r.status_code == 401


def test_no_local_secret_rejected(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path, register=False)
    body = export_body()
    r = client.post("/webhook", content=body, headers=headers(body))
    assert r.status_code == 401


def test_tampered_body_rejected(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)
    body = export_body()
    h = headers(body)  # signature over the original body
    r = client.post("/webhook", content=body + b" ", headers=h)
    assert r.status_code == 401


def test_non_export_event_ignored(tmp_path: Path) -> None:
    client, store = make_client(tmp_path)
    body = json.dumps({"id": "evt-other", "eventType": "rental.order.completed"}).encode()
    r = client.post("/webhook", content=body, headers=headers(body))
    assert r.status_code == 200
    assert r.json()["status"] == "ignored"
    assert store.is_event_processed("evt-other") is False


def test_malformed_json_rejected(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)
    bad = b'{"id": "evt", "eventType": '  # invalid JSON, signed correctly
    r = client.post("/webhook", content=bad, headers=headers(bad))
    assert r.status_code == 400


def test_missing_required_field_rejected(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)
    body = json.dumps({"id": "evt-x"}).encode()  # no eventType
    r = client.post("/webhook", content=body, headers=headers(body))
    assert r.status_code == 400


def test_tenant_allowlist(tmp_path: Path) -> None:
    client, store = make_client(tmp_path, allowlist="tenant-A,tenant-B")
    allowed = export_body("evt-allowed")
    r = client.post(
        "/webhook", content=allowed, headers=headers(allowed, **{TENANT_HEADER: "tenant-A"})
    )
    assert r.status_code == 200 and r.json()["status"] == "accepted"

    denied = export_body("evt-denied")
    r2 = client.post(
        "/webhook", content=denied, headers=headers(denied, **{TENANT_HEADER: "tenant-X"})
    )
    assert r2.status_code == 200 and r2.json()["status"] == "ignored"
    assert store.is_event_processed("evt-denied") is False


def test_duplicate_event_acknowledged(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)
    body = export_body("evt-dup")
    r1 = client.post("/webhook", content=body, headers=headers(body))
    assert r1.json()["status"] == "accepted"
    r2 = client.post("/webhook", content=body, headers=headers(body))
    assert r2.status_code == 200
    assert r2.json()["status"] == "duplicate"


def test_download_failure_releases_idempotency_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store = make_client(tmp_path)

    def boom(*args: object, **kwargs: object) -> list:
        raise RuntimeError("network down")

    monkeypatch.setattr(main, "download_files", boom)
    body = export_body("evt-fail")
    r = client.post("/webhook", content=body, headers=headers(body))
    assert r.status_code == 200 and r.json()["status"] == "accepted"
    # claim was released so a redelivery can re-attempt
    assert store.is_event_processed("evt-fail") is False
