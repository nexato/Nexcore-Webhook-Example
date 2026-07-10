# Signature verification (the HMAC trap)

nexcore signs every webhook and sends the signature in the **`x-auth-signature`** header.
Reproducing it correctly is the single most error-prone part of writing a receiver, so here is
exactly how it works — and the three things that trip people up.

## The recipe

```
key       = sha256_hex(secret)                          # lowercase hex STRING
expected  = hmac_sha256(key.encode(), raw_body_bytes).hexdigest().upper()   # UPPERCASE hex
valid     = constant_time_equals(expected.lower(), header_signature.lower())
```

## The three traps

1. **The HMAC key is `sha256hex(secret)`, NOT the secret.** nexcore stores only
   `secretHash = sha256hex(secret)` (lowercase hex) and uses that **hex string's bytes** as the
   HMAC key. If you key the HMAC with the raw secret, every signature will mismatch.
2. **Sign the RAW received bytes — never re-serialize.** The signature is computed over the
   exact JSON bytes on the wire. nexcore serializes a hash map whose key order is **not
   deterministic**, so parsing the JSON and re-serializing it will reorder keys and break the
   signature. Read the raw body *before* JSON parsing and verify against those bytes.
3. **Output is UPPERCASE hex; compare case-insensitively.** nexcore emits uppercase hex; most
   libraries produce lowercase. Normalize both sides (and use a constant-time compare).

## Reference implementation (Python)

This is what the app does (see [`app/security.py`](../app/security.py)):

```python
import hashlib, hmac

def verify(raw_body: bytes, secret: str, header_signature: str | None) -> bool:
    if not header_signature:
        return False
    key = hashlib.sha256(secret.encode("utf-8")).hexdigest()        # lowercase hex string
    expected = hmac.new(key.encode("utf-8"), raw_body, hashlib.sha256).hexdigest().upper()
    return hmac.compare_digest(expected.lower(), header_signature.strip().lower())
```

## Known test vector

This vector is taken from the framework's own test suite and lets you check your HMAC core
independently of the `sha256hex(secret)` step:

```
key  = "123456"
data = "Lorem ipsum dolor sit amet, consectetuer adipiscing elit. Aenean commodo ligula eget dolor. Aenean massa. Cum sociis natoque penatibus et magnis dis parturient montes, nascetur ridiculus mus."
HMAC-SHA256(data, key) = A68012CBC93B1F5EB1F48445869429F4D7051C9E1CE87A4ADA23782C733D572B   (uppercase)
```

## Where the secret comes from

The secret is the one this app generated and registered (see
[registering-a-subscription.md](registering-a-subscription.md)); it's stored locally and read
per request. If verification suddenly fails after an update, check gotcha #1 in that doc
(a POST without `secret` clears the server-side hash).

## Operational note

A missing/invalid signature returns **401**. Behind a proxy or tunnel, make sure nothing
rewrites the request body — see the ingress docs ([Caddy](ingress-caddy.md),
[Cloudflare Tunnel](ingress-cloudflare-tunnel.md)).
