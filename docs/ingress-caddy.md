# Ingress: Caddy (automatic TLS)

[Caddy](https://caddyserver.com/) is the simplest way to put the receiver behind HTTPS with
automatically issued and renewed Let's Encrypt certificates. It ships as an optional Compose
profile, so it runs alongside the Docker deployment.

## Prerequisites

- A public DNS record (A/AAAA) for your domain pointing at this host
- Inbound ports **80 and 443** reachable from the internet (Caddy needs them for the ACME
  HTTP/TLS challenge and to serve traffic)

If you can't open ports 80/443 (firewall/NAT), use the
[Cloudflare Tunnel](ingress-cloudflare-tunnel.md) option instead.

## Configure

The [`Caddyfile`](../Caddyfile) uses the `WEBHOOK_DOMAIN` environment variable:

```caddyfile
{$WEBHOOK_DOMAIN} {
	reverse_proxy app:8000
}
```

Set it and start the `caddy` profile:

```bash
export WEBHOOK_DOMAIN=hooks.example.com
docker compose --profile caddy up -d --build
```

Caddy obtains a certificate on first start and proxies `https://hooks.example.com` →
`app:8000`. Set `PUBLIC_WEBHOOK_URL=https://hooks.example.com/webhook` in your `.env` and
(re)register the subscription.

## Important: pass the body through unchanged

The webhook signature is an HMAC over the **raw request body bytes**. Caddy's `reverse_proxy`
forwards the body verbatim (no rewriting) and sets `X-Forwarded-*` headers, so it works out of
the box. Do **not** add directives that transform or re-encode the request body, or signature
verification will fail.

## Verify

```bash
curl -fsS https://hooks.example.com/healthz   # {"status":"ok"}
```

Certificates and Caddy's state persist in the `caddy-data` / `caddy-config` named volumes, so
renewals survive restarts.
