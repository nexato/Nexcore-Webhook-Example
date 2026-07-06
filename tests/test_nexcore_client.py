"""NexcoreClient HTTP behaviour tests, against a local mock server
emulating the subscription REST API (create 201 / update 200 / search / delete)."""

import json
import socketserver
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.nexcore_client import (
    API_KEY_HEADER,
    API_KEY_ID_HEADER,
    NexcoreClient,
)


class _SubscriptionHandler(BaseHTTPRequestHandler):
    # Class-level state shared across requests within a test.
    store: dict = {}
    requests: list = []
    counter = 0

    def log_message(self, *args: object) -> None:
        pass

    def _send_json(self, status: int, payload: dict | None) -> None:
        body = json.dumps(payload).encode() if payload is not None else b""
        self.send_response(status)
        if body:
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}
        type(self).requests.append({"headers": dict(self.headers), "body": body})
        ext = body.get("externalId")
        if ext in type(self).store:
            sub = type(self).store[ext]
            sub.update({"url": body.get("url"), "active": body.get("active")})
            self._send_json(200, sub)
        else:
            type(self).counter += 1
            sub = {"id": f"srv-{type(self).counter}", "externalId": ext, "url": body.get("url")}
            type(self).store[ext] = sub
            self._send_json(201, sub)

    def do_GET(self) -> None:  # noqa: N802
        prefix = "/api/v1/subscription/search/"
        if self.path.startswith(prefix):
            ext = self.path[len(prefix):]
            sub = type(self).store.get(ext)
            self._send_json(200, sub) if sub else self._send_json(404, None)
        else:
            self._send_json(404, None)

    def do_DELETE(self) -> None:  # noqa: N802
        sub_id = self.path.rsplit("/", 1)[-1]
        for ext, sub in list(type(self).store.items()):
            if sub["id"] == sub_id:
                del type(self).store[ext]
                self._send_json(204, None)
                return
        self._send_json(404, None)


class _FastServer(ThreadingHTTPServer):
    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)
        self.server_name = "127.0.0.1"
        self.server_port = self.server_address[1]


@pytest.fixture
def server():
    _SubscriptionHandler.store = {}
    _SubscriptionHandler.requests = []
    _SubscriptionHandler.counter = 0
    srv = _FastServer(("127.0.0.1", 0), _SubscriptionHandler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()


def make_client(base: str) -> NexcoreClient:
    return NexcoreClient(base, "api-key-data", "api-key-id")


def test_upsert_creates_then_updates(server: str) -> None:
    client = make_client(server)
    r1 = client.upsert_subscription(
        external_id="ext-1",
        url="https://h/webhook",
        event_types=["export.completed"],
        secret="sec-1",
    )
    assert r1.created is True
    assert r1.subscription_id == "srv-1"

    r2 = client.upsert_subscription(
        external_id="ext-1",
        url="https://h/webhook",
        event_types=["export.completed"],
        secret="sec-1",
    )
    assert r2.created is False  # update → 200
    assert r2.subscription_id == "srv-1"


def test_post_sends_api_key_headers_and_secret(server: str) -> None:
    client = make_client(server)
    client.upsert_subscription(
        external_id="ext-1",
        url="https://h/webhook",
        event_types=["export.completed"],
        secret="top-secret",
    )
    req = _SubscriptionHandler.requests[-1]
    headers = {k.lower(): v for k, v in req["headers"].items()}
    assert headers[API_KEY_HEADER.lower()] == "api-key-data"
    assert headers[API_KEY_ID_HEADER.lower()] == "api-key-id"
    # secret must be present in every POST body
    assert req["body"]["secret"] == "top-secret"
    assert req["body"]["type"] == "WEBHOOK"
    assert req["body"]["eventTypes"] == ["export.completed"]


def test_upsert_rejects_empty_secret(server: str) -> None:
    client = make_client(server)
    with pytest.raises(ValueError, match="secret"):
        client.upsert_subscription(
            external_id="ext-1", url="https://h/webhook", event_types=["e"], secret=""
        )


def test_find_returns_none_on_404(server: str) -> None:
    client = make_client(server)
    assert client.find_subscription("missing") is None


def test_find_returns_subscription(server: str) -> None:
    client = make_client(server)
    client.upsert_subscription(
        external_id="ext-1", url="https://h/webhook", event_types=["e"], secret="s"
    )
    found = client.find_subscription("ext-1")
    assert found is not None
    assert found["id"] == "srv-1"


def test_delete_existing_and_missing(server: str) -> None:
    client = make_client(server)
    client.upsert_subscription(
        external_id="ext-1", url="https://h/webhook", event_types=["e"], secret="s"
    )
    assert client.delete_subscription("srv-1") is True
    assert client.delete_subscription("srv-1") is False  # already gone → 404


def test_client_requires_credentials() -> None:
    with pytest.raises(ValueError):
        NexcoreClient("", "k", "kid")
    with pytest.raises(ValueError):
        NexcoreClient("https://h", "", "kid")
