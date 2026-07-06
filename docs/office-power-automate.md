# Low-code receiver with Power Automate + OneDrive

This is a **low-code alternative** to running the Python receiver. You "click together" a
**Microsoft Power Automate** cloud flow that downloads the exported files from a Nexcore
`export.completed` webhook and saves them into **OneDrive for Business**.

The flow itself needs no custom code. Power Automate, however, does not let an anonymous external
caller trigger a flow — so a small **relay** has to sit between Nexcore and the flow. That relay
is the only piece of code in this recipe; everything else (filtering, downloads, OneDrive) stays
inside the flow described below.

> ### Why a relay is required
> A Power Automate "When an HTTP request is received" trigger only accepts callers who present a
> valid Azure AD (Entra ID) OAuth token for your tenant — there is no anonymous/public option.
> Nexcore's webhook delivery is a plain signed `POST` with no OAuth token, so it cannot call the
> flow's trigger directly.
>
> The fix:
> 1. Register an **Azure AD App Registration** and grant it **delegated Power Automate
>    permissions**, with **admin consent**.
> 2. Put a small **relay** in front of the flow. It receives the Nexcore webhook (this relay's URL
>    is what you register as `PUBLIC_WEBHOOK_URL` in Nexcore — see
>    [prerequisites](nexcore-prerequisites.md)), requests an OAuth token from Azure AD using the
>    registered app, and then forwards the original webhook body together with that token to the
>    flow's trigger.
>
> Since you're writing that little bit of code anyway, it's cheap to also verify the
> `x-auth-signature` there, using the same recipe as
> [signature-verification.md](signature-verification.md) — the flow itself never talks to Nexcore
> directly, so it has no way to check the signature on its own.

## Licensing note

The **Request** trigger ("When an HTTP request is received"), the **HTTP** action (to download
the files), and the **Response** action are **premium** Power Automate connectors — you need a
Power Automate Premium (per-user or per-flow) plan. The **OneDrive for Business** connector is
standard.

## Build the flow

Create an **automated cloud flow** with no trigger selected, then add the steps below.

### 1. Trigger — "When an HTTP request is received"

- **Who can trigger:** *Any user in my tenant* — this is what forces the relay described above;
  it cannot be set to an anonymous option.
- **Request Body JSON Schema:** click *Use sample payload to generate schema* and paste a real
  `export.completed` body (see [webhook-payload-reference.md](webhook-payload-reference.md)).
- **Save** the flow once. The trigger's URL/documentation panel shows the flow's **Direct API
  invoke URL** — that is what the relay calls (with the OAuth token in the `Authorization: Bearer`
  header and the same JSON body Nexcore sent it), not a plain HTTP POST URL.

> By default a Request-triggered flow returns **`202 Accepted` immediately** and runs the rest
> asynchronously.

### 2. Filter — only `export.completed`

Add a **Condition**: `triggerBody()?['eventType']` **is equal to** `export.completed`.
Put the rest of the flow in the **If yes** branch; leave **If no** empty (the flow still ends
`2xx`, so Nexcore won't retry).

### 3. (Optional) Idempotency — skip duplicates

Nexcore may redeliver an event. To dedupe on the event `id`:

- Keep a small **Excel table** (in OneDrive) or a **SharePoint list** with one `eventId` column.
- *List rows* / *Get items* filtered on `triggerBody()?['id']`. If a row exists → **Terminate**
  (Succeeded). Otherwise add a row and continue.

If you skip this, a redelivery simply overwrites the same files — usually harmless.

### 4. Download + store each file

Add **Foreach** over `triggerBody()?['data']?['files']`. Inside it:

1. **HTTP** action — Method `GET`, URI `@item()?['url']`. The URL is a pre-signed
   Azure SAS link (read-only, ~24 h), so no auth header is needed. The response **Body** is the
   file content.
2. **OneDrive for Business → Create file**:
   - **Folder path:**
     `/Nexcore Exports/@{formatDateTime(utcNow(),'yyyy-MM-dd')}/@{triggerBody()?['entityId']}`
     (OneDrive creates missing folders automatically).
   - **File name:**
     `@{guid()}.@{if(equals(item()['mimeType'],'application/pdf'),'pdf','zip')}`
   - **File content:** the **Body** from the HTTP step.

This mirrors the Python receiver's layout
(`OUTPUT_DIR/<tenantId>/<YYYY-MM-DD>/<uniqueId>.<ext>`), just under
*OneDrive → Nexcore Exports*.

## Register the subscription

The **relay's** public URL is your `PUBLIC_WEBHOOK_URL` — the flow itself never talks to Nexcore
directly. Register it with Nexcore exactly as for the Python receiver — see
[registering-a-subscription.md](registering-a-subscription.md). You can use this project's CLI
just for the one-time registration, or `curl`/Postman.

Nexcore still requires a **secret** on the subscription (it signs every delivery with it) — the
relay uses it to verify `x-auth-signature` if you chose to add that check. The four Nexcore-side
[prerequisites](nexcore-prerequisites.md) still apply — without them no file is ever produced.

Once you are writing a relay, weigh whether the low-code flow still earns its keep over just
running the Python receiver — see the [README](../README.md) — since you now need an Azure AD App
Registration and somewhere to host the relay either way.

## Limitations

- **Not a pure no-code path** — requires an Azure AD App Registration (with admin consent) and
  somewhere to host the small relay.
- **Premium connectors** required (Request trigger, HTTP, Response).
- **Large files / ZIPs:** Power Automate has per-action message-size limits (~100 MB depending on
  plan). Big exports may need chunking or the Python receiver, which streams to disk with a 1 GiB cap.
- No automatic retry/backoff on a failed download beyond Power Automate's defaults.
