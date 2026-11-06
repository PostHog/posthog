import hashlib
from typing import Any

from products.messaging.backend.facade.contracts import ContentHashState

HASH_PREFIX = "v1:"
HASHED_FIELDS = ("subject", "preheader", "html", "text")
SUPERSEDED_HASHES_KEPT = 100

_ENCODING_HEADER = b"posthog-email-template-v1\n"


def email_content_hash(email: dict[str, Any]) -> str:
    encoded = bytearray(_ENCODING_HEADER)
    for field in HASHED_FIELDS:
        value = _normalized_line_endings(email.get(field) or "").encode()
        encoded += f"{len(value)}:".encode() + value + b"\n"
    return HASH_PREFIX + hashlib.sha256(encoded).hexdigest()


def _normalized_line_endings(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")


def superseded_after_publish(previous_hash: str | None, published_hash: str, superseded: list[str]) -> list[str]:
    replaced = [previous_hash] if previous_hash and previous_hash != published_hash else []
    kept = [h for h in superseded if h not in (previous_hash, published_hash)]
    return (replaced + kept)[:SUPERSEDED_HASHES_KEPT]


def sent_hash_state(sent_hash: str | None, content_hash: str | None, superseded: list[str]) -> ContentHashState:
    if sent_hash is None:
        return ContentHashState.NONE
    if sent_hash == content_hash:
        return ContentHashState.CURRENT
    if sent_hash in superseded:
        return ContentHashState.SUPERSEDED
    return ContentHashState.OUTDATED
