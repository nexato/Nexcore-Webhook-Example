# nexcore Webhook Example

A small, standalone example service that **receives nexcore `export.completed` webhooks** and
**downloads the exported files** (PDF and/or ZIP) into a local directory.

It exists for two audiences:

- **"How do I work with nexcore webhooks?"** — a didactic reference you can read and copy.
- **"Get it running with minimal effort"** — a technician can deploy it quickly.

Built with Python 3.11+, FastAPI, Pydantic and httpx. No database server required (state is a
local SQLite file).

# Disclaimer

## Purpose of this Repository

This repository provides example implementations and technical guidance on how to build a custom service that processes nexcore webhooks and downloads documents such as PDF files, images or ZIP archives.
The provided content is intended solely as technical guidance and an example implementation. It is **not** an officially supported product feature of nexcore and should not be considered production-ready software.

## Official Documentation

This repository is intended as supplementary technical guidance only.
It is **not** the official nexcore API specification.
In the event of any discrepancy between this repository and the official nexcore API documentation, the official documentation shall prevail.

## No Official Support

The contents of this repository are provided without technical support.
The Nexato GmbH support team does not provide assistance with implementing, customizing, troubleshooting or maintaining the example code contained in this repository.
Official support is limited to the standard functionality of nexcore.
GitHub Issues are **not** used as a support channel.
If you have questions regarding nexcore, please contact Nexato through the official support channels.

## Use at Your Own Risk

All information, source code, configuration examples and recommendations are provided **"as is"** and are used entirely at your own risk.
Nexato GmbH makes no warranties or representations regarding the completeness, accuracy, reliability, availability or fitness for any particular purpose of the provided materials.
Any implementation should be thoroughly reviewed and tested before being used in a production environment.

## Limitation of Liability

To the maximum extent permitted by applicable law, Nexato GmbH shall not be liable for any direct, indirect, incidental, consequential, special or exemplary damages, including but not limited to:
- data loss
- service interruptions
- security incidents
- loss of profits
- business interruption
- any other damages arising from the use of this repository or its contents

## Third-Party Software

The examples contained in this repository may reference or utilize third-party libraries, frameworks, services or tools.
Such references are provided solely as implementation examples and should not be interpreted as recommendations or endorsements.
Users are solely responsible for evaluating the suitability, security, licensing, maintenance and compliance of any third-party components they choose to use.
Nexato GmbH assumes no responsibility or liability for any third-party software.

## Security

The provided examples are intentionally simplified and do not represent production-ready security concepts.
It is the responsibility of each user to implement appropriate measures for:
- authentication
- authorization
- encryption
- secure credential management
- access control
- logging
- monitoring
- error handling
- backup and recovery

## API Compatibility

The examples in this repository are based on the nexcore API and webhook functionality available at the time of publication.
Future API changes may require modifications to the provided examples.

## Repository Maintenance

This repository may be modified, updated or discontinued at any time without prior notice.
Nexato GmbH does not guarantee:
- future updates
- bug fixes
- compatibility with future API versions
- continued availability of this repository

## Contributions

This repository is maintained by Nexato GmbH.
External pull requests, feature requests and implementation requests are currently not accepted.

<hr />

# How it works

1. nexcore POSTs a signed `export.completed` webhook to this service.
2. The service verifies the HMAC signature (over the **raw** body), then responds quickly
   with `200`.
3. In the background it downloads each file from the pre-signed (~24 h, read-only) Azure URL
   in the payload and stores it under `OUTPUT_DIR`:
   `OUTPUT_DIR/<tenantId>/<YYYY-MM-DD>/<entityId>_<index>.<ext>`.

Duplicate deliveries are de-duplicated by event id. The service can also **manage its own
webhook subscription** in nexcore via a small CLI
(`subscription register|status|delete|rotate-secret`).

> Note: Order exports produce a single PDF report. Resource-assignment exports (refuel, in/out)
> additionally produce a ZIP with the handover/return photos, but those same photos are also
> embedded in the PDF report. Because of that duplication, a future nexcore release will likely
> drop the ZIP file entirely, since the PDF alone already contains everything.

## Quickstart (local self-test, no nexcore)

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

> The self-test needs no nexcore: the script **seeds a local signing secret** if none exists,
> serves a sample PDF locally, signs the payload exactly like nexcore
> (`key = sha256hex(secret)`, UPPERCASE hex over the raw body), POSTs it to `/webhook`, and the
> running service downloads the file into `OUTPUT_DIR`. See
> [`scripts/send_sample_webhook.py`](scripts/send_sample_webhook.py) `--help`.

## Connecting to real nexcore

1. **Check the prerequisites** — four nexcore-side conditions must hold or no file is produced.
   See [docs/nexcore-prerequisites.md](docs/nexcore-prerequisites.md).
2. **Create an API key** (`apiKeyId` + `apiKeyData`).
   See [docs/generating-an-api-key.md](docs/generating-an-api-key.md).
3. **Configure** `.env`: `NEXCORE_BASE_URL`, `NEXCORE_API_KEY`, `NEXCORE_API_KEY_ID`,
   `PUBLIC_WEBHOOK_URL`, `OUTPUT_DIR`.
4. **Expose the service over HTTPS** (nexcore must reach `PUBLIC_WEBHOOK_URL`) — see
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
| [nexcore-prerequisites.md](docs/nexcore-prerequisites.md) | The 4 nexcore-side preconditions + the 8 supported events |
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

## Additional Information

| File | Description |
|------|-------------|
| [LICENSE](LICENCE) | MIT License |
| [NOTICE](NOTICE.md) | Legal notices and trademark information |
| [SECURITY](SECURITY.md) | Security vulnerability reporting |
| [CONTRIBUTING](CONTRIBUTING.md) | Contribution policy |
---

## License

Unless otherwise stated, the contents of this repository are licensed under the MIT License.
See the accompanying [**LICENSE**](LICENCE) file for details.
© 2026 Nexato GmbH