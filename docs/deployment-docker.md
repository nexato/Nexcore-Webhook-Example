# Deployment: Docker / Compose

The fastest way to run the receiver. A multi-stage [`Dockerfile`](../Dockerfile) builds a
slim image; [`docker-compose.yml`](../docker-compose.yml) runs it with a health check and a
bind-mounted data directory.

## Prerequisites

- Docker + Docker Compose v2
- A way for nexcore to reach the service over HTTPS (see the **Ingress** options below)

## 1. Configure

```bash
cp .env.example .env
# edit .env: NEXCORE_BASE_URL, NEXCORE_API_KEY, NEXCORE_API_KEY_ID,
# PUBLIC_WEBHOOK_URL, etc.
mkdir ./data
chown -R 10001:10001 ./data
```

The container always writes to `/data` inside the container, which is bind-mounted to
`./data` on the host:

- downloaded files → `./data/output/<tenantId>/<YYYY-MM-DD>/...`
- state DB → `./data/state.sqlite`

`OUTPUT_DIR` and `STATE_DB_PATH` are fixed to `/data/...` by Compose and override any values
in `.env` (so the volume mount always lines up).

## 2. Run

```bash
docker compose up -d --build
```

Check health:

```bash
docker compose ps                 # STATUS shows "healthy" once started
curl -fsS http://localhost:8000/healthz   # {"status":"ok"}
```

The image declares a `HEALTHCHECK` that polls `/healthz`, so `docker compose ps` reflects
real readiness.

## 3. Register the subscription

Run the CLI inside the container (it shares the same `.env` and state DB):

```bash
docker compose exec app python -m app.cli subscription register
docker compose exec app python -m app.cli subscription status
```

> The download of exported files goes **directly to Azure** from the container, so the
> container needs outbound HTTPS — but the files do **not** travel back through your ingress.

## 4. Self-test (optional)

Run it **inside the container** so the script shares the same `.env`, state DB and
`OUTPUT_DIR` (`/data`) as the service. (A run from the host would use a different state
DB and secret, so the service would reject the webhook with `401`.)

```bash
docker compose exec app python scripts/send_sample_webhook.py
```

The script seeds a local secret, serves a sample PDF inside the container, POSTs a
correctly-signed webhook to the app on `localhost:8000`, and the downloaded file appears
under `./data/output/...` on the host. Add `--bad-signature` to check a wrong signature is
rejected with `401`.

## Ingress

nexcore must reach `PUBLIC_WEBHOOK_URL` over HTTPS. Pick one:

- **Caddy auto-TLS** (bundled profile) — see [ingress-caddy.md](ingress-caddy.md).
- **Cloudflare Tunnel** (no open ports) — see [ingress-cloudflare-tunnel.md](ingress-cloudflare-tunnel.md).
- **Your own reverse proxy** — terminate TLS and `proxy_pass` to `app:8000`. It **must pass
  the request body through unchanged** (the signature is an HMAC over the raw bytes) and set
  the usual `X-Forwarded-*` headers.

## Updating / stopping

```bash
docker compose pull        # if using a registry image
docker compose up -d --build
docker compose down        # stop (keeps ./data)
```
