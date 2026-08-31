# Ingress: Cloudflare Tunnel

A [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/)
exposes the receiver on a stable public HTTPS hostname **without opening any inbound ports** —
`cloudflared` makes an **outbound** connection to Cloudflare and forwards requests to the local
service. This is the easiest option behind a corporate firewall or NAT, and it runs **alongside
any** of the deployment paths (Docker, Linux systemd, Windows).

Example config: [`deploy/cloudflared/config.example.yml`](../deploy/cloudflared/config.example.yml).

## Prerequisites

- A domain managed in Cloudflare (free plan is fine)
- `cloudflared` installed on the host running the receiver

## Setup

```bash
cloudflared tunnel login
cloudflared tunnel create nexcore-webhook          # → Tunnel UUID + credentials JSON
cloudflared tunnel route dns nexcore-webhook hooks.example.com
```

Copy the example config to `/etc/cloudflared/config.yml` and fill in the Tunnel UUID, the
credentials-file path, and your hostname. Point `service` at the local receiver:

- host install: `http://localhost:8000`
- if `cloudflared` runs in the same Docker network as the app: `http://app:8000`

Test it:

```bash
cloudflared tunnel run nexcore-webhook
curl -fsS https://hooks.example.com/healthz        # {"status":"ok"}
```

## Run it as a service

So the tunnel survives reboots:

- **Linux:** `sudo cloudflared service install` (uses `/etc/cloudflared/config.yml`), then
  `sudo systemctl enable --now cloudflared`.
- **Windows:** `cloudflared.exe service install` registers it as a Windows service.

Then set `PUBLIC_WEBHOOK_URL=https://hooks.example.com/webhook` in your `.env` and
(re)register the subscription.

## ⚠️ Pass the body through unchanged

The webhook signature is an HMAC over the **raw request body bytes**. `cloudflared` forwards
the body verbatim and adds `X-Forwarded-For` / `X-Forwarded-Proto`, so verification works
unchanged. Do **not** insert anything between Cloudflare and the service that rewrites or
re-encodes the body (e.g. a transforming WAF/Worker), or signatures will fail.

> The download of exported files goes **directly from the service to Azure** — it does **not**
> travel back through the tunnel, so tunnel bandwidth is not a factor for large files.
