"""Derive the stored file's name from the exported order's number.

By default this app names files after the event's ``entityId`` (see
``app/downloader.py``). That is robust but not human-friendly: nobody filing an
export recognises a UUID. For order exports we can do better, because nexcore
tells us which event triggered the export and the ``entityId`` *is* the order's id.

The rule, in one place:

1. Only ``export.completed`` events whose ``data.sourceEvent`` is
   ``rental.order.completed`` qualify. Verified in ``de.nexato.nexcore``:
   ``RentalOrderCompletedEvent.getObjectId()`` returns ``order.getId()``, and
   ``ExportService``/``ExportFilesJob`` pass that through to the webhook's
   ``entityId`` unchanged — so it can be used as the order id directly.
   The ``rental.resourceAssignment.*`` events carry a *ResourceAssignment* id
   instead and are deliberately not handled here.
2. Look the order up via ``GET /api/v1/order/{id}`` and take its ``number``.
3. Append a timestamp: ``<number>_<YYYYMMDDTHHMMSS>``. ``number`` comes from the
   partner system and is not unique over time — the same order completing twice
   would otherwise overwrite the earlier export. The payload carries no timestamp
   of its own, so this is the local processing time.

**Every** failure falls back to the default ``entityId`` naming by returning
``None``. Naming is a convenience; it must never cost us the file. That is why the
lookup is wrapped broadly — an unexpected error here would otherwise propagate into
``process_event`` and abort a download that would have succeeded.

``Order.number`` is a nullable free-text column and ``Order`` is annotated
``@JsonInclude(NON_NULL)``, so a missing number means the key is simply absent.
The value is returned verbatim; ``build_target_path`` is the single point that
sanitizes it into a safe path segment.
"""

from __future__ import annotations

import logging
from datetime import datetime

from .config import Settings
from .models import WebhookEvent
from .nexcore_client import NexcoreClient

logger = logging.getLogger("nexcore_webhook")

#: The only source event whose ``entityId`` is an order id we can resolve.
ORDER_NUMBER_SOURCE_EVENT = "rental.order.completed"

#: Timestamp format for the filename suffix: sortable and filesystem-safe.
TIMESTAMP_FORMAT = "%Y%m%dT%H%M%S"


def resolve_order_basename(
    event: WebhookEvent,
    settings: Settings,
    *,
    client: NexcoreClient | None = None,
    now: datetime | None = None,
) -> str | None:
    """Return ``<orderNumber>_<timestamp>``, or ``None`` to use the default naming.

    Returning ``None`` is the normal outcome for every event that is not an order
    export, and the fallback for every lookup problem. Pass ``client`` to inject a
    pre-built client (tests); otherwise one is built from ``settings``.
    """
    if not settings.order_number_filenames:
        return None

    if event.data is None or event.data.source_event != ORDER_NUMBER_SOURCE_EVENT:
        return None

    order_id = event.entity_id
    if not order_id:
        logger.warning("event %s has no entityId — cannot look up the order", event.id)
        return None

    if client is None:
        if not (
            settings.nexcore_base_url
            and settings.nexcore_api_key
            and settings.nexcore_api_key_id
        ):
            # Expected when running the receiver without REST credentials (e.g. the
            # local self-test): stay quiet, just use the default naming.
            logger.debug(
                "no nexcore API credentials — naming event %s from entityId", event.id
            )
            return None
        client = NexcoreClient(
            settings.nexcore_base_url,
            settings.nexcore_api_key,
            settings.nexcore_api_key_id,
        )

    try:
        order = client.get_order(order_id)
    except Exception as exc:  # broad on purpose: naming must never break the download
        logger.warning(
            "order lookup failed for %s (%s) — naming event %s from entityId instead",
            order_id,
            exc,
            event.id,
        )
        return None

    if order is None:
        logger.warning(
            "order %s not found — naming event %s from entityId instead", order_id, event.id
        )
        return None

    number = (order.get("number") or "").strip()
    if not number:
        logger.warning(
            "order %s has no number — naming event %s from entityId instead",
            order_id,
            event.id,
        )
        return None

    return f"{number}_{(now or datetime.now()).strftime(TIMESTAMP_FORMAT)}"
