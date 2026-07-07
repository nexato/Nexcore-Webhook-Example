# nexcore prerequisites

For nexcore to actually export a file and deliver it to this receiver, **four** conditions
must all be true. If any is missing, the export is **silently skipped** — no error, no file.
The first one this app handles itself; the other three are **Nexato/admin settings** set per
tenant.

## Checklist

- [ ] **1. An active `export.completed` subscription** — *handled by this app.* Register it
  with `python -m app.cli subscription register` (see
  [registering-a-subscription.md](registering-a-subscription.md)). Without it the export never
  starts.
- [ ] **2. Exports are enabled for the tenant** — setting, **default off**. Must be turned on
  by a Nexato admin.
- [ ] **3. The triggering event is allow-listed for export** — setting (list), **default
  empty**. A Nexato admin must add the source event(s) you want to export (see the 8 supported
  events below).
- [ ] **4. The webhook is configured to include file data** — setting, **default off**. Only
  then does the webhook include the `data` block with the file URLs (which this app needs to
  download them). This is a separate, general switch — not export-specific.

> Settings **2–4** must be set up by a Nexato admin in the nexcore settings (per tenant) —
> reach out to Nexato support or your account manager to have them enabled.

## Supported source events (8)

Only these event types can trigger an export.

| Event type | Export output |
|---|---|
| `rental.order.archived` | 1 PDF |
| `rental.order.completed` | 1 PDF |
| `rental.resourceAssignment.refueled` | ZIP (+ PDF if a related order exists) |
| `rental.resourceAssignment.in.completed` | ZIP (+ PDF if a related order exists) |
| `rental.resourceAssignment.out.completed` | ZIP (+ PDF if a related order exists) |
| `operatedRental.order.archived` | 1 PDF |
| `operatedRental.order.completed` | 1 PDF |
| `operatedRental.order.taskCompleted` | 1 PDF |

So the receiver must handle **PDF and/or ZIP** per event — it processes every entry in
`data.files[]` by its `mimeType`.

## How delivery works once enabled

1. A source event above fires for a tenant where conditions 2–4 hold.
2. nexcore generates the file(s), uploads them, and emits an `export.completed` event.
3. Because an active subscription exists (condition 1), nexcore POSTs a signed
   `export.completed` webhook to your `PUBLIC_WEBHOOK_URL`, including `data.files[]` with
   pre-signed, ~24h, read-only download URLs.
4. This app verifies the signature, responds `200`, and downloads the file(s) into
   `OUTPUT_DIR`.

See also: [webhook-payload-reference.md](webhook-payload-reference.md),
[signature-verification.md](signature-verification.md).
