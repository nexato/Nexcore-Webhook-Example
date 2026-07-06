"""Downloader tests, including a real local HTTP server and an
end-to-end /webhook → file-on-disk integration test."""

import functools
import json
import socketserver
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import Settings
from app.downloader import (
    DownloadError,
    build_target_path,
    download_files,
    extension_for_mime,
    safe_path_component,
)
from app.models import ExportFile
from app.security import SIGNATURE_HEADER, compute_signature
from app.store import Store

PDF_BYTES = b"%PDF-1.4 fake pdf body"
ZIP_BYTES = b"PK\x03\x04 fake zip body"


class _FastHTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer without the slow socket.getfqdn() reverse lookup
    that HTTPServer.server_bind() does (≈35s on macOS for 127.0.0.1)."""

    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)
        self.server_name = "127.0.0.1"
        self.server_port = self.server_address[1]


class _QuietFileHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args: object) -> None:  # silence test output
        pass


@pytest.fixture
def file_server(tmp_path: Path):
    serve_dir = tmp_path / "remote"
    serve_dir.mkdir()
    (serve_dir / "doc.pdf").write_bytes(PDF_BYTES)
    (serve_dir / "archive.zip").write_bytes(ZIP_BYTES)
    handler = functools.partial(_QuietFileHandler, directory=str(serve_dir))
    server = _FastHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()


# --- extension mapping ------------------------------------------------------


def test_extension_for_mime() -> None:
    assert extension_for_mime("application/pdf") == ".pdf"
    assert extension_for_mime("application/zip") == ".zip"
    assert extension_for_mime("application/x-zip-compressed") == ".zip"
    assert extension_for_mime("application/pdf; charset=binary") == ".pdf"
    assert extension_for_mime("") == ".bin"
    assert extension_for_mime(None) == ".bin"
    assert extension_for_mime("application/unknown-xyz") == ".bin"


# --- naming -----------------------------------------------------------------


def test_build_target_path_derives_from_entity_id() -> None:
    p = build_target_path("/out", "tenantA", "entity-123", 0, "application/pdf")
    today = date.today().isoformat()
    assert p == Path("/out/tenantA") / today / "entity-123_0.pdf"


def test_build_target_path_fallbacks() -> None:
    p = build_target_path("/out", None, None, 1, "application/zip")
    today = date.today().isoformat()
    assert p == Path("/out/unknown-tenant") / today / "unknown_1.zip"


# --- path-traversal hardening -----------------------------------------------


def test_safe_path_component() -> None:
    assert safe_path_component("tenant-A", "fb") == "tenant-A"
    assert safe_path_component("../../etc", "fb") == ".._.._etc".strip(". ")
    assert safe_path_component("..", "fb") == "fb"
    assert safe_path_component("/etc/cron.d", "fb") == "_etc_cron.d"
    assert safe_path_component("a/b\\c", "fb") == "a_b_c"
    assert safe_path_component("", "fb") == "fb"
    assert safe_path_component(None, "fb") == "fb"


def test_build_target_path_blocks_tenant_traversal(tmp_path: Path) -> None:
    out = tmp_path / "output"
    # All of these must stay inside out; none may escape via .. or absolute paths.
    for tenant in ["../../../../etc", "/etc/cron.d", "..", "a/../../b"]:
        dest = build_target_path(out, tenant, "entity", 0, "application/pdf")
        assert dest.resolve().is_relative_to(out.resolve())


def test_build_target_path_blocks_entity_traversal(tmp_path: Path) -> None:
    out = tmp_path / "output"
    for entity in ["../../../../tmp/evil", "/tmp/evil", ".."]:
        dest = build_target_path(out, "tenant", entity, 0, "application/pdf")
        assert dest.resolve().is_relative_to(out.resolve())


# --- download (real local server) -------------------------------------------


def test_downloads_multiple_files(file_server: str, tmp_path: Path) -> None:
    out = tmp_path / "output"
    files = [
        ExportFile(url=f"{file_server}/doc.pdf", mimeType="application/pdf"),
        ExportFile(url=f"{file_server}/archive.zip", mimeType="application/zip"),
    ]
    paths = download_files(
        files, output_dir=out, tenant_id="tenantA", entity_id="ent-1", timeout=10, max_retries=2
    )
    today = date.today().isoformat()
    assert paths == [
        out / "tenantA" / today / "ent-1_0.pdf",
        out / "tenantA" / today / "ent-1_1.zip",
    ]
    assert paths[0].read_bytes() == PDF_BYTES
    assert paths[1].read_bytes() == ZIP_BYTES
    # filenames derived from entityId, not the SAS blob name
    assert "doc" not in paths[0].name
    assert "archive" not in paths[1].name


def test_no_part_files_left_behind(file_server: str, tmp_path: Path) -> None:
    out = tmp_path / "output"
    files = [ExportFile(url=f"{file_server}/doc.pdf", mimeType="application/pdf")]
    download_files(files, output_dir=out, tenant_id="t", entity_id="e", max_retries=1)
    assert list(out.rglob("*.part")) == []


# --- retry behaviour --------------------------------------------------------


class _FlakyHandler(BaseHTTPRequestHandler):
    """Fails with 503 for the first `fail_times` requests, then serves 200."""

    fail_times = 1
    seen = 0

    def log_message(self, *args: object) -> None:
        pass

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        type(self).seen += 1
        if type(self).seen <= type(self).fail_times:
            self.send_error(503, "temporary")
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Length", str(len(PDF_BYTES)))
        self.end_headers()
        self.wfile.write(PDF_BYTES)


@pytest.fixture
def flaky_server():
    _FlakyHandler.seen = 0
    _FlakyHandler.fail_times = 1
    server = _FastHTTPServer(("127.0.0.1", 0), _FlakyHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()


def test_download_retries_then_succeeds(flaky_server: str, tmp_path: Path) -> None:
    files = [ExportFile(url=f"{flaky_server}/x", mimeType="application/pdf")]
    paths = download_files(
        files,
        output_dir=tmp_path / "out",
        tenant_id="t",
        entity_id="e",
        max_retries=3,
        retry_backoff_seconds=0.01,
    )
    assert paths[0].read_bytes() == PDF_BYTES
    assert _FlakyHandler.seen == 2  # one 503, one success


def test_download_raises_after_exhausting_retries(tmp_path: Path) -> None:
    # 127.0.0.1:1 refuses connections → all attempts fail.
    files = [ExportFile(url="http://127.0.0.1:1/nope", mimeType="application/pdf")]
    with pytest.raises(DownloadError):
        download_files(
            files,
            output_dir=tmp_path / "out",
            tenant_id="t",
            entity_id="e",
            max_retries=2,
            retry_backoff_seconds=0.01,
        )


class _StatusHandler(BaseHTTPRequestHandler):
    status = 500
    seen = 0

    def log_message(self, *args: object) -> None:
        pass

    def do_GET(self) -> None:  # noqa: N802
        type(self).seen += 1
        self.send_error(type(self).status, "err")


@pytest.fixture
def status_server():
    _StatusHandler.seen = 0
    _StatusHandler.status = 500
    server = _FastHTTPServer(("127.0.0.1", 0), _StatusHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()


def test_non_retriable_4xx_not_retried(status_server: str, tmp_path: Path) -> None:
    _StatusHandler.status = 404  # permanent (e.g. deleted SAS blob)
    files = [ExportFile(url=f"{status_server}/x", mimeType="application/pdf")]
    with pytest.raises(DownloadError, match="non-retriable HTTP 404"):
        download_files(
            files,
            output_dir=tmp_path / "out",
            tenant_id="t",
            entity_id="e",
            max_retries=3,
            retry_backoff_seconds=0.01,
        )
    assert _StatusHandler.seen == 1  # not retried


def test_retriable_5xx_is_retried(status_server: str, tmp_path: Path) -> None:
    _StatusHandler.status = 503
    files = [ExportFile(url=f"{status_server}/x", mimeType="application/pdf")]
    with pytest.raises(DownloadError):
        download_files(
            files,
            output_dir=tmp_path / "out",
            tenant_id="t",
            entity_id="e",
            max_retries=2,  # 3 attempts total
            retry_backoff_seconds=0.01,
        )
    assert _StatusHandler.seen == 3


def test_no_part_left_after_failure(status_server: str, tmp_path: Path) -> None:
    _StatusHandler.status = 500
    out = tmp_path / "out"
    files = [ExportFile(url=f"{status_server}/x", mimeType="application/pdf")]
    with pytest.raises(DownloadError):
        download_files(
            files, output_dir=out, tenant_id="t", entity_id="e",
            max_retries=1, retry_backoff_seconds=0.01,
        )
    assert list(out.rglob("*.part")) == []


def test_size_cap_aborts_download(file_server: str, tmp_path: Path) -> None:
    out = tmp_path / "out"
    files = [ExportFile(url=f"{file_server}/doc.pdf", mimeType="application/pdf")]
    with pytest.raises(DownloadError, match="exceeds max size"):
        download_files(
            files, output_dir=out, tenant_id="t", entity_id="e", max_bytes=5
        )
    assert list(out.rglob("*.pdf")) == []
    assert list(out.rglob("*.part")) == []


# --- end-to-end: signed webhook → file on disk ------------------------------


def test_webhook_downloads_to_disk(file_server: str, tmp_path: Path) -> None:
    ext_id, secret = "e2e-ext", "e2e-secret"
    db = tmp_path / "state.sqlite"
    out = tmp_path / "output"
    settings = Settings(state_db_path=db, subscription_external_id=ext_id, output_dir=out)
    store = Store(db)
    store.save_subscription(ext_id, "sub-uuid", secret)
    main.app.dependency_overrides[main.get_settings] = lambda: settings
    try:
        body = json.dumps(
            {
                "id": "evt-e2e",
                "eventType": "export.completed",
                "entityId": "order-777",
                "data": {
                    "files": [
                        {"url": f"{file_server}/doc.pdf", "mimeType": "application/pdf"},
                        {"url": f"{file_server}/archive.zip", "mimeType": "application/zip"},
                    ]
                },
            }
        ).encode()
        headers = {
            "content-type": "application/json",
            SIGNATURE_HEADER: compute_signature(body, secret),
            main.TENANT_HEADER: "tenant-9",
        }
        client = TestClient(main.app)
        r = client.post("/webhook", content=body, headers=headers)
        assert r.status_code == 200 and r.json()["status"] == "accepted"

        today = date.today().isoformat()
        pdf = out / "tenant-9" / today / "order-777_0.pdf"
        zip_ = out / "tenant-9" / today / "order-777_1.zip"
        assert pdf.read_bytes() == PDF_BYTES
        assert zip_.read_bytes() == ZIP_BYTES
        assert store.is_event_processed("evt-e2e") is True
    finally:
        main.app.dependency_overrides.clear()
