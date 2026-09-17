# Generating an API key

This app authenticates to the nexcore REST API with an **API key** (not Keycloak/OAuth). It is
used in two places: the `subscription` CLI (registering and managing the webhook subscription),
and the running service itself, which looks orders up to name exported files after the order
number — see the README section on naming order exports. An API key is two values:

- **`apiKeyId`** — the key's id (a UUID)
- **`apiKeyData`** — the secret key material

Both are needed; they map to the request headers `x-auth-apiKeyId` and `x-auth-apiKey`. The
tenant is derived from the key server-side, so no tenant header is required.

> ⚠️ **`apiKeyData` is shown only once**, at creation time. Copy it immediately and store it
> securely — it cannot be retrieved again. If you lose it, create a new key.

## Create the key in the nexcore GUI

1. Sign in to nexcore as a user allowed to manage API keys for the tenant.
2. Open the API-keys / integrations administration area.
3. Create a new API key (optionally add a comment like `nexcore-webhook-example` so you can
   identify it later).
4. Copy **both** values shown on creation: the **API key id** (`apiKeyId`) and the **API key**
   (`apiKeyData`).

## Equivalent GraphQL mutation

The GUI wraps the `createApiKey` mutation. If you use a GraphQL client (authenticated as an
admin), it looks like:

```graphql
mutation {
  createApiKey(input: { comment: "nexcore-webhook-example" }) {
    apiKeyId
    apiKeyData
  }
}
```

The response is the only place `apiKeyData` appears:

```json
{ "data": { "createApiKey": { "apiKeyId": "…uuid…", "apiKeyData": "…secret…" } } }
```

Listing keys afterwards returns only `id`, `hash`, `comment`, `lastUsedDateTime` — never the
secret again.

## Put the values into the app config

In your `.env`:

```dotenv
NEXCORE_BASE_URL=https://<your-nexcore-host>
NEXCORE_API_KEY=<apiKeyData>
NEXCORE_API_KEY_ID=<apiKeyId>
```

Both the CLI and the running service read these, so they belong in the `.env` the service
starts with — not only on the machine you register from.

Next: [registering-a-subscription.md](registering-a-subscription.md).
