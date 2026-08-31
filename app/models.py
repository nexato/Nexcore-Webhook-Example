"""Pydantic models for the incoming webhook payload.

Mirrors ``Event.getEventDTOMap()`` in ``de.nexato.framework``. The JSON keys are
camelCase; we keep snake_case Python attributes with explicit aliases.

⚠️ The key ``subscriptionIdExternaId`` is a **real upstream typo** (missing the
``l`` in "External"). We reproduce it verbatim so the model actually matches the
wire format — do not "fix" it.

The model is intentionally lenient (``extra="ignore"``, most fields optional) so
that non-``export.completed`` events and future added fields still parse; the
endpoint only deeply relies on ``data.files`` for export events.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

#: The only event type this service acts on.
EXPORT_COMPLETED_EVENT_TYPE = "export.completed"


class ExportFile(BaseModel):
    """One exported file: a pre-signed Azure URL plus its MIME type."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    url: str
    mime_type: str = Field(alias="mimeType")


class EventData(BaseModel):
    """The ``data`` block (present only when ``send_event_data_body=true``).

    For ``export.completed`` this carries the exported files and the source event
    that triggered the export.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    files: list[ExportFile] = Field(default_factory=list)
    source_event: str | None = Field(default=None, alias="sourceEvent")


class WebhookEvent(BaseModel):
    """A Nexcore webhook event envelope."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: str
    event_type: str = Field(alias="eventType")
    attempt: int | None = None
    entity_id: str | None = Field(default=None, alias="entityId")
    subscription_id: str | None = Field(default=None, alias="subscriptionId")
    entity_external_id: str | None = Field(default=None, alias="entityExternalId")
    # Real upstream typo — keep verbatim (missing 'l' in "External").
    subscription_id_externa_id: str | None = Field(
        default=None, alias="subscriptionIdExternaId"
    )
    data: EventData | None = None

    @property
    def is_export_completed(self) -> bool:
        return self.event_type == EXPORT_COMPLETED_EVENT_TYPE
