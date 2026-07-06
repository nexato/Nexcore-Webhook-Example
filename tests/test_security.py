"""Signature verification tests.

The known vectors are anchored to the Java implementation so we prove
cross-implementation equivalence, not just internal self-consistency:

- ``LOREM`` / key ``"123456"`` → ``A68012CB...`` is copied verbatim from
  ``HmacUtilitiesTest.hmacWithJava_0`` in ``de.nexato.framework``.
"""

import hashlib
import hmac

from app.security import (
    SIGNATURE_HEADER,
    compute_signature,
    derive_key,
    verify_signature,
)

# --- Cross-implementation vector straight from the Java test suite -----------
LOREM = (
    "Lorem ipsum dolor sit amet, consectetuer adipiscing elit. Aenean commodo "
    "ligula eget dolor. Aenean massa. Cum sociis natoque penatibus et magnis dis "
    "parturient montes, nascetur ridiculus mus."
)
JAVA_HMAC_SHA256 = "A68012CBC93B1F5EB1F48445869429F4D7051C9E1CE87A4ADA23782C733D572B"

# --- Fixed recipe-level vector (key = sha256hex(secret)) ---------------------
RECIPE_SECRET = "s3cr3t-example"
RECIPE_BODY = b'{"id":"evt-1","eventType":"export.completed"}'
RECIPE_KEY = "dd693f21ec2535ef74b31ab3f1664f3ef0a78ddf296bd237a2857d18df51fd8a"
RECIPE_SIGNATURE = "9979507F5521A15982149CFC00F82A72C3EFD1A79B9AC421A6C6D508B063E8AE"


def test_header_name() -> None:
    assert SIGNATURE_HEADER == "x-auth-signature"


def test_hmac_primitive_matches_java() -> None:
    """Our raw HMAC-SHA256 (UTF-8, uppercase hex) matches Java's HmacUtilities."""
    result = hmac.new(b"123456", LOREM.encode("utf-8"), hashlib.sha256).hexdigest().upper()
    assert result == JAVA_HMAC_SHA256


def test_derive_key_is_lowercase_sha256_of_secret() -> None:
    assert derive_key(RECIPE_SECRET) == RECIPE_KEY
    assert derive_key(RECIPE_SECRET) == hashlib.sha256(RECIPE_SECRET.encode()).hexdigest()


def test_compute_signature_known_vector() -> None:
    """Full recipe: key = sha256hex(secret), HMAC over raw body, UPPERCASE hex."""
    assert compute_signature(RECIPE_BODY, RECIPE_SECRET) == RECIPE_SIGNATURE
    assert compute_signature(RECIPE_BODY, RECIPE_SECRET).isupper()


def test_verify_accepts_valid_uppercase_signature() -> None:
    assert verify_signature(RECIPE_BODY, RECIPE_SECRET, RECIPE_SIGNATURE) is True


def test_verify_is_case_insensitive() -> None:
    """Sender emits uppercase; a lowercase signature must still verify."""
    assert verify_signature(RECIPE_BODY, RECIPE_SECRET, RECIPE_SIGNATURE.lower()) is True


def test_verify_rejects_tampered_body() -> None:
    tampered = RECIPE_BODY + b" "
    assert verify_signature(tampered, RECIPE_SECRET, RECIPE_SIGNATURE) is False


def test_verify_rejects_wrong_secret() -> None:
    assert verify_signature(RECIPE_BODY, "wrong-secret", RECIPE_SIGNATURE) is False


def test_verify_rejects_missing_or_empty_signature() -> None:
    assert verify_signature(RECIPE_BODY, RECIPE_SECRET, None) is False
    assert verify_signature(RECIPE_BODY, RECIPE_SECRET, "") is False


def test_verify_rejects_non_ascii_signature() -> None:
    """A non-ASCII header must fail closed, not raise (hmac.compare_digest quirk)."""
    assert verify_signature(RECIPE_BODY, RECIPE_SECRET, "ünïcode") is False


def test_verify_uses_raw_bytes_not_reserialized_json() -> None:
    """Same logical JSON, different key order → different signature.

    This is the crux: the server signs Jackson's HashMap serialization whose key
    order is non-deterministic, so the receiver must verify the exact received
    bytes. Re-serializing the parsed payload would change byte order and break.
    """
    body_order_1 = b'{"a":1,"b":2}'
    body_order_2 = b'{"b":2,"a":1}'  # equivalent object, different bytes
    secret = "order-secret"
    sig = compute_signature(body_order_1, secret)
    assert verify_signature(body_order_1, secret, sig) is True
    assert verify_signature(body_order_2, secret, sig) is False
