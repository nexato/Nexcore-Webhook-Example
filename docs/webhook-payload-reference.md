# Webhook payload reference

Every nexcore webhook is a JSON object POSTed to your `PUBLIC_WEBHOOK_URL` with these headers:

| Header | Value |
|---|---|
| `content-type` | `application/json; charset=utf-8` |
| `user-agent` | `nexcore` |
| `x-nx-tenant-id` | the tenant id (**only in the header — not in the body**) |
| `x-auth-signature` | HMAC signature — see [signature-verification.md](signature-verification.md) |

The sender uses a **15 s read timeout** and retries non-`2xx` responses up to 4×, so respond
`2xx` quickly (this app does the file download in the background).

## Envelope fields

| JSON key | Type | Always present? | Notes |
|---|---|---|---|
| `id` | string (UUID) | yes | Event id — use it for **idempotency** |
| `attempt` | number | yes | Delivery attempt (0-based) |
| `entityId` | string (UUID) | yes | The entity the event is about; this app names files from it |
| `eventType` | string | yes | e.g. `export.completed` |
| `subscriptionId` | string (UUID) | yes | Your subscription's id |
| `entityExternalId` | string | only if set | External id of the entity, if any |
| `subscriptionIdExternaId` | string | only if set | Your subscription's `externalId`. **Yes, the key is misspelled** — `subscriptionIdExterna**I**d` (missing the “l”). It's a real upstream typo; match it verbatim. |
| `data` | object | only if `deliverableEvents_send_event_data_body = true` | Event payload — for exports, the files (see below) |

## `export.completed` `data`

```json
{
  "id": "…event-uuid…",
  "attempt": 0,
  "entityId": "…entity-uuid…",
  "eventType": "export.completed",
  "subscriptionId": "…subscription-uuid…",
  "subscriptionIdExternaId": "nexcore-webhook-example",
  "data": {
    "files": [
      { "url": "https://…blob.core.windows.net/…?<SAS>", "mimeType": "application/pdf" },
      { "url": "https://…blob.core.windows.net/…?<SAS>", "mimeType": "application/zip" }
    ],
    "sourceEvent": "rental.resourceAssignment.out.completed"
  }
}
```

- **`data.files[]`** — one or more files. Order exports yield a single PDF; ResourceAssignment
  exports yield a ZIP (plus a PDF when a related order exists). Handle each by its `mimeType`.
- **`data.files[].url`** — a pre-signed **Azure SAS URL**: read-only, valid ~24 hours, fetched
  with a plain `GET` and no extra auth. Download it **directly** (it goes to Azure, not back
  through your ingress). The blob name in the URL is a random UUID — this app names stored
  files from `entityId` instead.
- **`data.sourceEvent`** — the source event type that triggered the export (one of the
  [8 supported events](nexcore-prerequisites.md)).

> `data` is present **only** when `deliverableEvents_send_event_data_body = true`. Without it
> there are no file URLs to download — that's precondition #4 in
> [nexcore-prerequisites.md](nexcore-prerequisites.md).

## How this app processes it

1. Read the raw body, **verify the signature** over those exact bytes → `401` if invalid.
2. Ignore non-`export.completed` events with a friendly `200`.
3. Claim the `id` for idempotency (duplicates → `200`, processed once).
4. Respond `200`, then download every `data.files[]` entry into
   `OUTPUT_DIR/<tenantId>/<YYYY-MM-DD>/<entityId>_<index>.<ext>` in the background.
