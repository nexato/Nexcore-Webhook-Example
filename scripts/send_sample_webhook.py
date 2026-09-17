#!/usr/bin/env python3
"""Send a correctly-signed ``export.completed`` webhook to a local instance.

This lets you self-test the receiver **without Nexcore**: it serves a sample PDF
from a tiny local HTTP server, builds an ``export.completed`` payload pointing at
it, signs it with the exact Nexcore recipe (HMAC-SHA256 over the raw body, key =
``sha256hex(secret)``, UPPERCASE hex), and POSTs it to ``/webhook``. The running
service then downloads the sample file into ``OUTPUT_DIR``.

Usage::

    # 1. start the service (it must have a registered subscription / local secret)
    uvicorn app.main:app --port 8000

    # 2. in another shell:
    python scripts/send_sample_webhook.py                  # expect 200 + a stored file
    python scripts/send_sample_webhook.py --bad-signature  # expect 401

The secret is read from the local state store (the same one the service uses); a
different one can be supplied with ``--secret``.
"""

from __future__ import annotations

import argparse
import json
import secrets
import socketserver
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx

# Allow running as a standalone script (`python scripts/send_sample_webhook.py`).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings  # noqa: E402
from app.security import SIGNATURE_HEADER, compute_signature  # noqa: E402
from app.store import Store  # noqa: E402

TENANT_HEADER = "x-nx-tenant-id"

#: A tiny but valid-enough PDF body to download.
SAMPLE_PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def build_payload(
    *,
    event_id: str,
    entity_id: str,
    file_urls: list[tuple[str, str]],
    source_event: str = "rental.order.completed",
) -> bytes:
    """Build a raw ``export.completed`` JSON body (bytes)."""
    return json.dumps(
        {
            "id": event_id,
            "eventType": "export.completed",
            "attempt": 0,
            "entityId": entity_id,
            "subscriptionId": "sample-subscription",
            "data": {
                "files": [{"url": url, "mimeType": mime} for url, mime in file_urls],
                "sourceEvent": source_event,
            },
        }
    ).encode()


def signed_headers(
    body: bytes, secret: str, tenant_id: str, *, tamper: bool = False
) -> dict[str, str]:
    """Build request headers with a correct (or intentionally wrong) signature."""
    signature = compute_signature(body, secret if not tamper else secret + "-wrong")
    return {
        "content-type": "application/json",
        SIGNATURE_HEADER: signature,
        TENANT_HEADER: tenant_id,
    }


class _FastFileServer(ThreadingHTTPServer):
    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)
        self.server_name = "127.0.0.1"
        self.server_port = self.server_address[1]


def serve_files(files: dict[str, bytes]) -> tuple[ThreadingHTTPServer, str]:
    """Serve ``{path: bytes}`` on an ephemeral local port. Returns (server, base_url)."""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: object) -> None:
            pass

        def do_GET(self) -> None:  # noqa: N802
            data = files.get(self.path)
            if data is None:
                self.send_error(404, "not found")
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = _FastFileServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def ensure_local_secret(settings: Settings, override: str | None = None) -> str:
    """Return a secret the running service will also use, persisting it locally.

    Resolution: explicit ``override`` → the secret already in the store → a freshly
    generated one. The chosen secret is saved to the state store so the (separately
    running) service verifies incoming signatures with the same secret — this is
    what makes the self-test work without Nexcore.
    """
    store = Store(settings.state_db_path)
    external_id = settings.subscription_external_id
    existing = store.get_subscription(external_id)
    secret = override or (existing.secret if existing else None) or secrets.token_hex(32)
    if not existing or existing.secret != secret:
        existing_id = existing.subscription_id if existing else None
        store.save_subscription(external_id, existing_id, secret)
    return secret


def _wait_for_new_file(output_dir: Path, before: set[Path], timeout: float) -> Path | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = {p for p in output_dir.rglob("*") if p.is_file() and p.suffix != ".part"}
        new = current - before
        if new:
            return sorted(new)[0]
        time.sleep(0.1)
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000/webhook")
    parser.add_argument("--secret", default=None, help="override the local-store secret")
    parser.add_argument("--tenant", default="sample-tenant")
    parser.add_argument("--entity-id", default="sample-entity")
    parser.add_argument("--bad-signature", action="store_true", help="send a wrong signature")
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args(argv)

    settings = Settings()
    # Ensure the running service and this script share a secret (seeds one locally
    # if needed) so the self-test works without Nexcore.
    secret = ensure_local_secret(settings, args.secret)

    output_dir = Path(settings.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    before = {p for p in output_dir.rglob("*") if p.is_file()}

    server, base_url = serve_files({"/sample.pdf": SAMPLE_PDF})
    try:
        body = build_payload(
            event_id=f"sample-{uuid.uuid4()}",
            entity_id=args.entity_id,
            file_urls=[(f"{base_url}/sample.pdf", "application/pdf")],
        )
        headers = signed_headers(body, secret, args.tenant, tamper=args.bad_signature)
        resp = httpx.post(args.url, content=body, headers=headers, timeout=args.timeout)
        print(f"POST {args.url} -> {resp.status_code} {resp.text}")

        if args.bad_signature:
            ok = resp.status_code == 401
            print("PASS: wrong signature rejected with 401" if ok else "FAIL: expected 401")
            return 0 if ok else 1

        if resp.status_code != 200:
            print("FAIL: expected 200", file=sys.stderr)
            return 1

        stored = _wait_for_new_file(output_dir, before, args.timeout)
        if stored:
            print(f"PASS: file stored at {stored}")
            return 0
        print("FAIL: no file appeared in OUTPUT_DIR (is the service running?)", file=sys.stderr)
        return 1
    finally:
        server.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
