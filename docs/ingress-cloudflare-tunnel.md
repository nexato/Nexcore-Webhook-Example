# Ingress: Cloudflare Tunnel

A [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/)
exposes the receiver on a stable public HTTPS hostname **without opening any inbound ports** —
`cloudflared` makes an **outbound** connection to Cloudflare and forwards requests to the local
service. This is the easiest option behind a corporate firewall or NAT, and it runs **alongside
any** of the deployment paths (Docker, Linux systemd, Windows).

Example config: [`deploy/cloudflared/config.example.yml`](../deploy/cloudflared/config.example.yml).

## Prerequisites

- `cloudflared` installed on the host running the receiver
- A domain in your Cloudflare account, with **Cloudflare as its authoritative DNS**

The second one is the part that needs planning, and it is not something this guide can do for
you — see the next section. Cloudflare's **Free plan is enough**; what you cannot skip is the
domain itself.

## Getting a domain into Cloudflare

A tunnel is reached by hostname, and Cloudflare can only answer for that hostname if it is
authoritative for the zone the hostname belongs to. There are two ways to get there, and which
one applies depends on whether you already own a suitable domain.

### Option A — register a domain with Cloudflare

Register through [Cloudflare Registrar](https://developers.cloudflare.com/registrar/get-started/register-domain/).
This is **paid** — a yearly registration fee, as with any registrar. In return there is nothing
further to configure: domains registered with Cloudflare use Cloudflare nameservers
automatically.

Worth knowing before you choose this: a domain held at Cloudflare Registrar **cannot be moved to a
different DNS provider** while it stays there, and registration requires a verified account email
plus complete ASCII contact data (internationalized/Unicode domain names are not supported).

### Option B — bring your own domain and delegate it to Cloudflare

Free, and the usual choice if you already have a company domain. The domain stays with your
current registrar; you only change its **nameservers** so that Cloudflare answers DNS for it.
Cloudflare's reference for this is
[Nameservers](https://developers.cloudflare.com/dns/nameservers/); the procedure is:

1. Add the domain in the Cloudflare dashboard and pick a plan (Free is fine).
2. **Review the imported DNS records.** Cloudflare scans your existing zone, but the scan is not
   guaranteed to find everything. Compare it against your current provider — apex records, mail
   (MX, SPF, DKIM) and every subdomain in use. Anything missing here stops resolving the moment
   the switch takes effect.
3. **Disable DNSSEC at your registrar** if it is active. Changing nameservers while DNSSEC is
   still enabled can make the domain unreachable.
4. Replace the registrar's nameservers with the two Cloudflare assigned you, copied exactly.
5. Wait until the zone shows **Active** in Cloudflare — this can take up to 24 hours.
6. Re-enable DNSSEC afterwards, from Cloudflare this time.

> **This delegates the whole zone.** The receiver only needs one hostname such as
> `hooks.example.com`, but nameserver delegation happens at the apex (`example.com`) — every
> record in that domain then has to live in Cloudflare. If someone else in your organisation owns
> the company DNS, agree this with them before step 3.

Keeping your existing DNS provider and handing Cloudflare only a single hostname is possible
(Cloudflare calls it a *partial* or CNAME setup), but it requires a **Business or Enterprise**
plan and is not available for domains registered with Cloudflare Registrar. The
`cloudflared tunnel route dns` command below assumes a full setup; a partial setup is out of
scope here.

**No suitable domain at all?** Then the tunnel is not your blocker — nexcore has to reach
`PUBLIC_WEBHOOK_URL` over HTTPS, so *every* ingress option needs a public hostname you control.
The tunnel is only special in additionally wanting that hostname inside Cloudflare. See
[ingress-caddy.md](ingress-caddy.md) for the reverse-proxy alternative, which needs an inbound
port opened instead.

## Setup

Do this once the zone is **Active** in Cloudflare — `tunnel login` lets you authorise a zone and
`route dns` writes a record into it, so neither works before the delegation has taken effect.

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
