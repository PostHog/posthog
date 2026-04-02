"""
HMAC-SHA256 signing for snapshot baseline hashes.

Format: ``v1.<kid>.<contenthex>.<mac_b64url>``

- ``v1``: format version (literal)
- ``kid``: key ID, matches ``[A-Za-z0-9_-]{1,32}``
- ``contenthex``: BLAKE3 hex digest of image RGBA pixel bytes (64 chars)
- ``mac_b64url``: base64url-encoded HMAC-SHA256 tag, no padding (43 chars)

MAC input: ``"v1|{repo_id}|{identifier}|{contenthex}"``

Key rotation: ``kid`` identifies which key was used. Backend stores multiple
keys per repo and accepts any valid ``kid`` during verification, issuing
new signatures with the latest key.
"""

import re
import hmac
import base64
import hashlib
import secrets
from dataclasses import dataclass

# v1.<kid 1-32 alphanum/dash/underscore>.<64 hex chars>.<43 base64url chars>
SIGNED_HASH_RE = re.compile(r"^v1\.([A-Za-z0-9_-]{1,32})\.([0-9a-f]{64})\.([A-Za-z0-9_-]{43})$")


@dataclass(frozen=True)
class ParsedSignedHash:
    kid: str
    content_hash: str
    tag_b64url: str


def generate_signing_key() -> tuple[str, str]:
    """Generate a new signing key pair.

    Returns ``(kid, secret_hex)`` where *kid* is a short key identifier
    and *secret_hex* is a 32-byte hex-encoded secret.
    """
    kid = f"k{secrets.token_hex(4)}"
    secret_hex = secrets.token_hex(32)
    return kid, secret_hex


def sign_snapshot_hash(
    repo_id: str,
    identifier: str,
    content_hash: str,
    secret_hex: str,
    kid: str,
) -> str:
    """Sign a content hash, returning ``v1.<kid>.<hash>.<tag>``."""
    message = f"v1|{repo_id}|{identifier}|{content_hash}"
    tag = hmac.new(
        bytes.fromhex(secret_hex),
        message.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    tag_b64 = base64.urlsafe_b64encode(tag).rstrip(b"=").decode("ascii")
    return f"v1.{kid}.{content_hash}.{tag_b64}"


def parse_signed_hash(value: str) -> ParsedSignedHash | None:
    """Parse a signed hash string. Returns ``None`` on invalid format."""
    m = SIGNED_HASH_RE.match(value)
    if m is None:
        return None
    return ParsedSignedHash(kid=m.group(1), content_hash=m.group(2), tag_b64url=m.group(3))


def verify_signed_hash(
    repo_id: str,
    identifier: str,
    signed_hash: str,
    keys: dict[str, str],
) -> str | None:
    """Verify a signed hash and return the plain content hash if valid.

    *keys* maps ``kid → secret_hex``, supporting rotation. Returns
    ``None`` if the format is invalid, the ``kid`` is unknown, or the
    MAC does not match.
    """
    parsed = parse_signed_hash(signed_hash)
    if parsed is None:
        return None

    secret_hex = keys.get(parsed.kid)
    if secret_hex is None:
        return None

    # Recompute expected tag
    message = f"v1|{repo_id}|{identifier}|{parsed.content_hash}"
    expected_tag = hmac.new(
        bytes.fromhex(secret_hex),
        message.encode("utf-8"),
        hashlib.sha256,
    ).digest()

    # Decode provided tag (re-add padding for base64)
    padded = parsed.tag_b64url + "=" * (-len(parsed.tag_b64url) % 4)
    try:
        provided_tag = base64.urlsafe_b64decode(padded)
    except Exception:
        return None

    if hmac.compare_digest(expected_tag, provided_tag):
        return parsed.content_hash
    return None
