# Deployment: Linux (systemd)

Run the receiver as a native systemd service — no Docker required. A ready-made unit is in
[`deploy/systemd/nexcore-webhook.service`](../deploy/systemd/nexcore-webhook.service).

## Prerequisites

- Linux with systemd
- Python 3.11+
- A way for nexcore to reach the service over HTTPS (see **Ingress** below)

## 1. Install the app

```bash
sudo useradd --system --create-home --home-dir /opt/nexcore-webhook-example nexcore-webhook
sudo -u nexcore-webhook -H bash <<'EOF'
cd /opt/nexcore-webhook-example
git clone https://github.com/nexato/nexcore-Webhook-Example.git .
python3 -m venv .venv
. .venv/bin/activate
pip install .
EOF
```

## 2. Configure

```bash
sudo -u nexcore-webhook cp /opt/nexcore-webhook-example/.env.example /opt/nexcore-webhook-example/.env
sudo -u nexcore-webhook $EDITOR /opt/nexcore-webhook-example/.env
```

Set at least `NEXCORE_BASE_URL`, `NEXCORE_API_KEY`, `NEXCORE_API_KEY_ID`,
`PUBLIC_WEBHOOK_URL`, and `OUTPUT_DIR` / `STATE_DB_PATH` (absolute paths the service user can
write, e.g. under `/opt/nexcore-webhook-example`). systemd reads this file via
`EnvironmentFile`.

## 3. Install and start the service

```bash
sudo cp deploy/systemd/nexcore-webhook.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now nexcore-webhook
```

Check it:

```bash
systemctl status nexcore-webhook
curl -fsS http://localhost:8000/healthz     # {"status":"ok"}
journalctl -u nexcore-webhook -f            # follow logs
```

The unit uses `Restart=always`, so the service comes back after crashes and reboots.

> If `OUTPUT_DIR` / `STATE_DB_PATH` live outside `WorkingDirectory`, add a `ReadWritePaths=`
> line to the unit (`ProtectSystem=full` otherwise blocks writes). There is a commented
> example in the unit file.

## 4. Register the subscription

```bash
cd /opt/nexcore-webhook-example
sudo -u nexcore-webhook /opt/nexcore-webhook-example/.venv/bin/python \
    -m app.cli subscription register
```

The `cd` matters: the CLI reads `.env` from the current working directory, so running it
from elsewhere would find no config and fail with `NEXCORE_BASE_URL is required`.

## Ingress

nexcore must reach `PUBLIC_WEBHOOK_URL` over HTTPS. Put the service behind a reverse proxy
([Caddy](ingress-caddy.md), nginx, …) or a [Cloudflare Tunnel](ingress-cloudflare-tunnel.md).
The proxy/tunnel **must pass the body through unchanged** (the signature is an HMAC over the
raw bytes) and set `X-Forwarded-*` headers.

## Updating

```bash
cd /opt/nexcore-webhook-example && sudo -u nexcore-webhook git pull   # or re-copy files
sudo -u nexcore-webhook .venv/bin/pip install .
sudo systemctl restart nexcore-webhook
```
