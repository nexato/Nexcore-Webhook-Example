# Nexcore Webhook Example

A small, standalone example service that **receives Nexcore `export.completed` webhooks** and
**downloads the exported files** (PDF and/or ZIP) into a local directory.

It exists for two audiences:

- **"How do I work with Nexcore webhooks?"** — a didactic reference you can read and copy.
- **"Get it running with minimal effort"** — a technician can deploy it quickly.

Built with Python 3.11+, FastAPI, Pydantic and httpx. No database server required (state is a
local SQLite file).

## How it works

1. Nexcore POSTs a signed `export.completed` webhook to this service.
2. The service verifies the HMAC signature (over the **raw** body), then responds quickly
   with `200`.
3. In the background it downloads each file from the pre-signed (~24 h, read-only) Azure URL
   in the payload and stores it under `OUTPUT_DIR`:
   `OUTPUT_DIR/<tenantId>/<YYYY-MM-DD>/<entityId>_<index>.<ext>`.

Duplicate deliveries are de-duplicated by event id. The service can also **manage its own
webhook subscription** in Nexcore via a small CLI
(`subscription register|status|delete|rotate-secret`).

> Note: Order exports produce a single PDF report. Resource-assignment exports (refuel, in/out)
> additionally produce a ZIP with the handover/return photos, but those same photos are also
> embedded in the PDF report. Because of that duplication, a future Nexcore release will likely
> drop the ZIP file entirely, since the PDF alone already contains everything.

## Quickstart (local self-test, no Nexcore)

Verify the whole receive → verify → download path on your machine:

```bash
# 1. Configure
cp .env.example .env            # defaults are fine for the local self-test

# 2. Install (Python 3.11+)
python -m venv .venv && . .venv/bin/activate
pip install .

# 3. Run the service
uvicorn app.main:app --port 8000

# 4. In another shell: send a correctly-signed sample webhook
python scripts/send_sample_webhook.py             # → 200 + a file under OUTPUT_DIR
python scripts/send_sample_webhook.py --bad-signature   # → 401 (rejected)
```

> The self-test needs no Nexcore: the script **seeds a local signing secret** if none exists,
> serves a sample PDF locally, signs the payload exactly like Nexcore
> (`key = sha256hex(secret)`, UPPERCASE hex over the raw body), POSTs it to `/webhook`, and the
> running service downloads the file into `OUTPUT_DIR`. See
> [`scripts/send_sample_webhook.py`](scripts/send_sample_webhook.py) `--help`.

## Connecting to real Nexcore

1. **Check the prerequisites** — four Nexcore-side conditions must hold or no file is produced.
   See [docs/nexcore-prerequisites.md](docs/nexcore-prerequisites.md).
2. **Create an API key** (`apiKeyId` + `apiKeyData`).
   See [docs/generating-an-api-key.md](docs/generating-an-api-key.md).
3. **Configure** `.env`: `NEXCORE_BASE_URL`, `NEXCORE_API_KEY`, `NEXCORE_API_KEY_ID`,
   `PUBLIC_WEBHOOK_URL`, `OUTPUT_DIR`.
4. **Expose the service over HTTPS** (Nexcore must reach `PUBLIC_WEBHOOK_URL`) — see
   **Deployment** below.
5. **Register the subscription**:
   ```bash
   python -m app.cli subscription register
   python -m app.cli subscription status
   ```
   See [docs/registering-a-subscription.md](docs/registering-a-subscription.md).

## Deployment

Three ways to run it (all support the ingress options):

- **Docker / Compose (recommended)** — [docs/deployment-docker.md](docs/deployment-docker.md)
- **Linux (systemd)** — [docs/deployment-linux.md](docs/deployment-linux.md)
- **Windows (NSSM / sc.exe)** — [docs/deployment-windows.md](docs/deployment-windows.md)

Ingress (getting public HTTPS to the service):

- **Caddy auto-TLS** — [docs/ingress-caddy.md](docs/ingress-caddy.md)
- **Cloudflare Tunnel** (no open ports) — [docs/ingress-cloudflare-tunnel.md](docs/ingress-cloudflare-tunnel.md)

> Whatever proxy/tunnel sits in front **must pass the request body through unchanged** — the
> signature is an HMAC over the raw bytes — and set `X-Forwarded-*` headers.

## Configuration

All configuration is via environment variables. See [.env.example](.env.example) for the full
list with placeholder values. The webhook **secret** is not configured here — it is
app-generated and kept in the local state DB.

## Documentation

| Doc | What |
|---|---|
| [nexcore-prerequisites.md](docs/nexcore-prerequisites.md) | The 4 Nexcore-side preconditions + the 8 supported events |
| [generating-an-api-key.md](docs/generating-an-api-key.md) | Create an API key + key id |
| [registering-a-subscription.md](docs/registering-a-subscription.md) | Subscribe via the REST API + self-management |
| [signature-verification.md](docs/signature-verification.md) | The HMAC signature recipe (and its traps) |
| [webhook-payload-reference.md](docs/webhook-payload-reference.md) | Payload fields, `data.files[]` |
| [deployment-docker.md](docs/deployment-docker.md) | Docker / Compose |
| [deployment-linux.md](docs/deployment-linux.md) | Linux systemd |
| [deployment-windows.md](docs/deployment-windows.md) | Windows service |
| [ingress-caddy.md](docs/ingress-caddy.md) | Caddy auto-TLS |
| [ingress-cloudflare-tunnel.md](docs/ingress-cloudflare-tunnel.md) | Cloudflare Tunnel |
| [office-power-automate.md](docs/office-power-automate.md) | No-code receiver: Power Automate + OneDrive |

## Development

```bash
pip install -e ".[dev]"
ruff check .
pytest
```

## License

[MIT](LICENSE) © 2026 nexato GmbH
