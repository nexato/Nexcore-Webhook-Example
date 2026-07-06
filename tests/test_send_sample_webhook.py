"""Self-test script tests.

Exercises the script's payload/signing helpers against the real app via TestClient
plus a local file server, covering the two documented outcomes: a correctly-signed
request stores a file (200), a wrong signature is rejected (401).
"""

from pathlib import Path

from fastapi.testclient import TestClient

from app import main
from app.config import Settings
from app.store import Store
from scripts import send_sample_webhook as sw

EXT = "self-test-ext"
SECRET = "self-test-secret"


def _configure_app(tmp_path: Path) -> tuple[TestClient, Path]:
    db = tmp_path / "state.sqlite"
    out = tmp_path / "output"
    settings = Settings(state_db_path=db, subscription_external_id=EXT, output_dir=out)
    Store(db).save_subscription(EXT, "sub-id", SECRET)
    main.app.dependency_overrides[main.get_settings] = lambda: settings
    return TestClient(main.app), out


def test_sample_webhook_stores_file(tmp_path: Path) -> None:
    client, out = _configure_app(tmp_path)
    server, base = sw.serve_files({"/sample.pdf": sw.SAMPLE_PDF})
    try:
        body = sw.build_payload(
            event_id="evt-self",
            entity_id="ent-self",
            file_urls=[(f"{base}/sample.pdf", "application/pdf")],
        )
        headers = sw.signed_headers(body, SECRET, "tenant-self")
        resp = client.post("/webhook", content=body, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "accepted"

        stored = [p for p in out.rglob("*.pdf")]
        assert len(stored) == 1
        assert stored[0].read_bytes() == sw.SAMPLE_PDF
    finally:
        server.shutdown()
        main.app.dependency_overrides.clear()


def test_sample_webhook_bad_signature_rejected(tmp_path: Path) -> None:
    client, _ = _configure_app(tmp_path)
    try:
        body = sw.build_payload(
            event_id="evt-bad",
            entity_id="ent",
            file_urls=[("http://127.0.0.1:1/x", "application/pdf")],
        )
        headers = sw.signed_headers(body, SECRET, "tenant", tamper=True)
        resp = client.post("/webhook", content=body, headers=headers)
        assert resp.status_code == 401
    finally:
        main.app.dependency_overrides.clear()


def test_ensure_local_secret_seeds_and_reuses(tmp_path: Path) -> None:
    settings = Settings(
        state_db_path=tmp_path / "state.sqlite", subscription_external_id="ext-x"
    )
    # No secret yet → one is generated and persisted.
    s1 = sw.ensure_local_secret(settings)
    assert s1 and Store(settings.state_db_path).get_subscription("ext-x").secret == s1
    # Called again → reuses the persisted secret.
    assert sw.ensure_local_secret(settings) == s1
    # Explicit override → persisted and returned.
    s2 = sw.ensure_local_secret(settings, "override-secret")
    assert s2 == "override-secret"
    assert Store(settings.state_db_path).get_subscription("ext-x").secret == "override-secret"


def test_signed_headers_uses_uppercase_recipe() -> None:
    body = sw.build_payload(
        event_id="e", entity_id="x", file_urls=[("http://h/f", "application/pdf")]
    )
    headers = sw.signed_headers(body, SECRET, "t")
    sig = headers[sw.SIGNATURE_HEADER]
    assert sig.isupper() and len(sig) == 64
