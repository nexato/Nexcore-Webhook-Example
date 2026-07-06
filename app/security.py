"""Webhook signature verification.

Nexcore signs each outgoing webhook with an HMAC and sends it in the
``x-auth-signature`` header. Reproducing that exactly is the single most
error-prone part of a receiver, so the recipe is spelled out here and verified
byte-for-byte against the Java implementation in the test suite.

The contract (verified against ``de.nexato.framework``):

- The server stores only ``secretHash = sha256hex(secret)`` (lowercase), never
  the plaintext secret. ``SubscriptionService``.
- When signing, it uses that **hash string** as the HMAC key — *not* the raw
  secret: ``HmacUtilities.hmacWithJava("HmacSHA256", body, subscription.getSecretHash())``.
  ``SendWebhookJob`` line 134.
- The key is the hex string's **UTF-8 bytes**; the data is the response body's
  **UTF-8 bytes** (``HmacUtilities`` line 13/16).
- The output is **UPPERCASE** hex (``HmacUtilities.HEX_ARRAY = "0123456789ABCDEF"``).
- The signed body is the exact JSON string Nexcore transmits. Jackson serializes
  a ``HashMap`` whose key order is **not deterministic**, so the receiver must
  verify over the **raw received bytes** and never re-serialize the parsed JSON.

Recipe::

    key       = sha256_hex(secret)                         # lowercase hex string
    expected  = hmac_sha256(key.encode(), raw_body).hexdigest().upper()
    valid     = constant_time_eq(expected.lower(), header_signature.lower())
"""

from __future__ import annotations

import hashlib
import hmac

#: HTTP header carrying the signature on incoming webhooks.
SIGNATURE_HEADER = "x-auth-signature"


def derive_key(secret: str) -> str:
    """Return the HMAC key Nexcore uses: ``sha256hex(secret)`` (lowercase hex)."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def compute_signature(raw_body: bytes, secret: str) -> str:
    """Compute the expected signature for ``raw_body`` as UPPERCASE hex.

    ``raw_body`` must be the exact bytes received on the wire — never a
    re-serialized version of the parsed payload.
    """
    key = derive_key(secret).encode("utf-8")
    return hmac.new(key, raw_body, hashlib.sha256).hexdigest().upper()


def verify_signature(raw_body: bytes, secret: str, provided_signature: str | None) -> bool:
    """Return ``True`` iff ``provided_signature`` matches ``raw_body``.

    Comparison is case-insensitive (the sender emits uppercase hex, ``hashlib``
    emits lowercase) and constant-time. A missing or empty signature is invalid.
    """
    if not provided_signature:
        return False
    expected = compute_signature(raw_body, secret).lower()
    # Compare as bytes: hmac.compare_digest rejects str with non-ASCII chars by
    # raising TypeError, and the header value is attacker-controlled. Encoding a
    # non-ASCII header to ASCII fails → treat as an invalid signature (fail closed).
    try:
        provided = provided_signature.strip().lower().encode("ascii")
    except UnicodeEncodeError:
        return False
    return hmac.compare_digest(expected.encode("ascii"), provided)
