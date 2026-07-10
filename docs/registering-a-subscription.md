# Registering a subscription

The receiver manages its **own** webhook subscription in nexcore over the REST API. You don't
have to craft requests by hand — the built-in CLI does it idempotently — but this page also
documents the underlying REST calls.

## Prerequisites

- An API key (`apiKeyId` + `apiKeyData`) — see [generating-an-api-key.md](generating-an-api-key.md)
- `.env` filled in:

  ```dotenv
  NEXCORE_BASE_URL=https://<your-nexcore-host>
  NEXCORE_API_KEY=<apiKeyData>
  NEXCORE_API_KEY_ID=<apiKeyId>
  SUBSCRIPTION_EXTERNAL_ID=nexcore-webhook-example
  PUBLIC_WEBHOOK_URL=https://<your-public-host>/webhook
  ```

## Using the CLI (recommended)

```bash
python -m app.cli subscription register        # create-or-update, idempotent
python -m app.cli subscription status          # compare local vs. server
python -m app.cli subscription rotate-secret   # generate + set a new secret
python -m app.cli subscription delete          # delete remotely + clear local state
```

`register`:

1. Generates a webhook **secret** if one isn't stored locally yet.
2. POSTs the subscription (create or update) over `externalId`, **always sending the secret**.
3. Persists `{externalId, id, secret}` locally (in the state DB) so signatures can be verified.

Set `AUTO_REGISTER=true` to register/reconcile automatically on service startup (off by
default — registering is an outward-facing action).

## The REST API directly

Auth headers on every `/api/**` request:

```
x-auth-apiKey:   <apiKeyData>
x-auth-apiKeyId: <apiKeyId>
```

### Create or update — `POST /api/v1/subscription`

Idempotent: the server matches an existing subscription by `id` → `externalId`. Not found ⇒
**create (201)**; found ⇒ **update (200)**.

```json
{
  "externalId": "nexcore-webhook-example",
  "url": "https://<your-public-host>/webhook",
  "eventTypes": ["export.completed"],
  "active": true,
  "type": "WEBHOOK",
  "secret": "<app-generated-secret>"
}
```

### Other endpoints

| Method & path | Purpose |
|---|---|
| `GET /api/v1/subscription/search/{externalId}` | Reconcile — "do I already have one?" (200/404) |
| `GET /api/v1/subscription/{id}` | Fetch by id (200/404) |
| `DELETE /api/v1/subscription/{id}` | Delete by id (204/404) |

## ⚠️ Two gotchas (they shape the app's behaviour)

1. **Send the `secret` on every POST.** If an update POST omits `secret`, the server **clears
   the stored secret hash** and signature verification breaks. The app always includes it on
   create *and* update.
2. **The plaintext secret lives only locally.** The server stores only `sha256hex(secret)` and
   can never return it. The app keeps the plaintext in its state DB to verify incoming
   signatures. If you lose local state you can recover the subscription `id` via
   `search/{externalId}`, **but not the secret** — generate a new one with
   `subscription rotate-secret`.

Next: make sure the [nexcore prerequisites](nexcore-prerequisites.md) are set, then verify
[signature handling](signature-verification.md).
