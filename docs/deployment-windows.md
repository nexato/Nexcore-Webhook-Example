# Deployment: Windows (NSSM / sc.exe)

Run the receiver as a native Windows service. We use a standard supervisor
([NSSM](https://nssm.cc/), recommended) or the built-in `sc.exe` — there is **no bespoke
service-wrapper code** to maintain. Quick command reference:
[`deploy/windows/README.md`](../deploy/windows/README.md).

## Prerequisites

- Windows with Python 3.11+ (`python --version`)
- Admin PowerShell/CMD for service registration
- A way for Nexcore to reach the service over HTTPS (see **Ingress** below)

## 1. Install the app

```bat
mkdir C:\nexcore-webhook-example
cd C:\nexcore-webhook-example   
git clone https://github.com/nexato/Nexcore-Webhook-Example.git .   :: copy/clone the project here first
python -m venv .venv
.venv\Scripts\pip install .
```

## 2. Configure

```bat
copy .env.example .env
notepad .env
```

Set `NEXCORE_BASE_URL`, `NEXCORE_API_KEY`, `NEXCORE_API_KEY_ID`, `PUBLIC_WEBHOOK_URL`, and
`OUTPUT_DIR` / `STATE_DB_PATH` (paths the service account can write).

## 3. Register the service

Use **NSSM** (recommended) or **sc.exe** — full commands in
[`deploy/windows/README.md`](../deploy/windows/README.md). In short, with NSSM:

```bat
nssm install NexcoreWebhook "C:\nexcore-webhook-example\.venv\Scripts\python.exe" ^
    "-m" "uvicorn" "app.main:app" "--host" "0.0.0.0" "--port" "8000"
nssm set NexcoreWebhook AppDirectory "C:\nexcore-webhook-example"
nssm set NexcoreWebhook Start SERVICE_AUTO_START
nssm start NexcoreWebhook
```

`AppDirectory` ensures the service finds `.env` and writes output/state under the project
folder.

## 4. Verify and register the subscription

```bat
curl http://localhost:8000/healthz
.venv\Scripts\python -m app.cli subscription register
```

## Ingress

Nexcore must reach `PUBLIC_WEBHOOK_URL` over HTTPS. Options:

- A reverse proxy on the host (IIS/Caddy/nginx) terminating TLS → `http://localhost:8000`.
- A [Cloudflare Tunnel](ingress-cloudflare-tunnel.md) running as its own Windows service —
  no inbound ports needed (good behind corporate firewalls/NAT).

Whatever sits in front **must pass the request body through unchanged** (the signature is an
HMAC over the raw bytes) and set `X-Forwarded-*` headers.

## Updating

```bat
:: update files (git pull / re-copy), then:
.venv\Scripts\pip install .
nssm restart NexcoreWebhook
```
