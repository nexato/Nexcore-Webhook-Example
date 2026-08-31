"""Tests for the order-number file naming rule.

HTTP behaviour of ``get_order`` is covered in test_nexcore_client.py against a real
server; here we test the *rule* — when a lookup happens, and what every failure
branch falls back to — with an injected client, as in test_subscription_cli.py.
"""

import logging
from datetime import datetime
from pathlib import Path

import httpx

from app.config import Settings
from app.models import WebhookEvent
from app.naming import ORDER_NUMBER_SOURCE_EVENT, resolve_order_basename

NOW = datetime(2026, 8, 31, 14, 25, 30)


class FakeOrderClient:
    """Duck-typed stand-in for NexcoreClient; records every lookup."""

    def __init__(self, orders: dict | None = None, error: Exception | None = None) -> None:
        self.orders = orders or {}
        self.error = error
        self.requested: list[str] = []

    def get_order(self, order_id: str) -> dict | None:
        self.requested.append(order_id)
        if self.error:
            raise self.error
        return self.orders.get(order_id)


def make_settings(tmp_path: Path, **over) -> Settings:
    base = {
        "state_db_path": tmp_path / "state.sqlite",
        "nexcore_base_url": "https://api.example",
        "nexcore_api_key": "key-data",
        "nexcore_api_key_id": "key-id",
        "order_number_filenames": True,
    }
    base.update(over)
    return Settings(**base)


def make_event(
    source_event: str | None = ORDER_NUMBER_SOURCE_EVENT,
    entity_id: str | None = "ord-1",
    with_data: bool = True,
) -> WebhookEvent:
    payload: dict = {
        "id": "evt-1",
        "eventType": "export.completed",
        "entityId": entity_id,
    }
    if with_data:
        payload["data"] = {
            "files": [{"url": "https://blob/x", "mimeType": "application/pdf"}],
            "sourceEvent": source_event,
        }
    return WebhookEvent.model_validate(payload)


# --- happy path -------------------------------------------------------------


def test_returns_number_with_timestamp(tmp_path: Path) -> None:
    client = FakeOrderClient({"ord-1": {"id": "ord-1", "number": "4711"}})

    result = resolve_order_basename(
        make_event(), make_settings(tmp_path), client=client, now=NOW
    )

    assert result == "4711_20260831T142530"
    assert client.requested == ["ord-1"]


def test_looks_the_order_up_by_the_event_entity_id(tmp_path: Path) -> None:
    client = FakeOrderClient({"ord-42": {"number": "A-1"}})

    result = resolve_order_basename(
        make_event(entity_id="ord-42"), make_settings(tmp_path), client=client, now=NOW
    )

    assert result == "A-1_20260831T142530"


# --- events that must not trigger a lookup ----------------------------------


def test_other_source_events_are_left_alone(tmp_path: Path) -> None:
    client = FakeOrderClient({"ord-1": {"number": "4711"}})

    result = resolve_order_basename(
        make_event(source_event="rental.resourceAssignment.out.completed"),
        make_settings(tmp_path),
        client=client,
        now=NOW,
    )

    assert result is None
    assert client.requested == []  # no pointless API call


def test_disabled_by_configuration(tmp_path: Path) -> None:
    client = FakeOrderClient({"ord-1": {"number": "4711"}})

    result = resolve_order_basename(
        make_event(),
        make_settings(tmp_path, order_number_filenames=False),
        client=client,
        now=NOW,
    )

    assert result is None
    assert client.requested == []


def test_event_without_data_block(tmp_path: Path) -> None:
    client = FakeOrderClient({"ord-1": {"number": "4711"}})

    result = resolve_order_basename(
        make_event(with_data=False), make_settings(tmp_path), client=client, now=NOW
    )

    assert result is None
    assert client.requested == []


def test_event_without_entity_id(tmp_path: Path) -> None:
    client = FakeOrderClient({})

    result = resolve_order_basename(
        make_event(entity_id=None), make_settings(tmp_path), client=client, now=NOW
    )

    assert result is None
    assert client.requested == []


def test_missing_credentials_skips_the_lookup(tmp_path: Path) -> None:
    # No client injected: the real credential guard must stop us before we build one.
    settings = make_settings(tmp_path, nexcore_api_key="", nexcore_api_key_id="")

    assert resolve_order_basename(make_event(), settings, now=NOW) is None


# --- lookup failures all fall back ------------------------------------------


def test_order_not_found(tmp_path: Path) -> None:
    client = FakeOrderClient({})  # 404 → get_order returns None

    result = resolve_order_basename(
        make_event(), make_settings(tmp_path), client=client, now=NOW
    )

    assert result is None
    assert client.requested == ["ord-1"]


def test_order_without_number_field(tmp_path: Path) -> None:
    # Order.number is nullable and @JsonInclude(NON_NULL) omits the key entirely.
    client = FakeOrderClient({"ord-1": {"id": "ord-1"}})

    result = resolve_order_basename(
        make_event(), make_settings(tmp_path), client=client, now=NOW
    )

    assert result is None


def test_order_with_blank_number(tmp_path: Path) -> None:
    client = FakeOrderClient({"ord-1": {"number": "   "}})

    result = resolve_order_basename(
        make_event(), make_settings(tmp_path), client=client, now=NOW
    )

    assert result is None


def test_transport_error(tmp_path: Path) -> None:
    client = FakeOrderClient(error=httpx.ConnectError("boom"))

    result = resolve_order_basename(
        make_event(), make_settings(tmp_path), client=client, now=NOW
    )

    assert result is None


def test_server_error(tmp_path: Path) -> None:
    response = httpx.Response(500, request=httpx.Request("GET", "https://api.example/x"))
    client = FakeOrderClient(error=httpx.HTTPStatusError("500", request=response.request,
                                                         response=response))

    result = resolve_order_basename(
        make_event(), make_settings(tmp_path), client=client, now=NOW
    )

    assert result is None


# --- the raw number is passed through; sanitizing happens in the downloader --


def test_number_with_path_characters_is_passed_through_verbatim(tmp_path: Path) -> None:
    # build_target_path is the single sanitizing point (see test_downloader.py).
    client = FakeOrderClient({"ord-1": {"number": "A/B"}})

    result = resolve_order_basename(
        make_event(), make_settings(tmp_path), client=client, now=NOW
    )

    assert result == "A/B_20260831T142530"


# --- log levels: a missing-credentials skip is routine, a failed lookup is not
# (guards the deliberate quiet/loud split; the behaviour itself is built above)


def test_missing_credentials_is_logged_quietly(tmp_path: Path, caplog) -> None:
    settings = make_settings(tmp_path, nexcore_api_key="", nexcore_api_key_id="")

    with caplog.at_level(logging.DEBUG, logger="nexcore_webhook"):
        resolve_order_basename(make_event(), settings, now=NOW)

    # Running without REST credentials is a supported setup — it must not warn.
    assert [r.levelno for r in caplog.records] == [logging.DEBUG]


def test_failed_lookup_is_logged_as_a_warning(tmp_path: Path, caplog) -> None:
    client = FakeOrderClient(error=httpx.ConnectError("boom"))

    with caplog.at_level(logging.DEBUG, logger="nexcore_webhook"):
        resolve_order_basename(make_event(), make_settings(tmp_path), client=client, now=NOW)

    assert [r.levelno for r in caplog.records] == [logging.WARNING]


def test_order_without_number_is_logged_as_a_warning(tmp_path: Path, caplog) -> None:
    client = FakeOrderClient({"ord-1": {"id": "ord-1"}})

    with caplog.at_level(logging.DEBUG, logger="nexcore_webhook"):
        resolve_order_basename(make_event(), make_settings(tmp_path), client=client, now=NOW)

    assert [r.levelno for r in caplog.records] == [logging.WARNING]
