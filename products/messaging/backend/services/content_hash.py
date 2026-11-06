import hashlib
from typing import Any

HASH_PREFIX = "v1:"
HASHED_FIELDS = ("subject", "preheader", "html", "text")

_ENCODING_HEADER = b"posthog-email-template-v1\n"


def email_content_hash(email: dict[str, Any]) -> str:
    encoded = bytearray(_ENCODING_HEADER)
    for field in HASHED_FIELDS:
        value = _normalized_line_endings(email.get(field) or "").encode()
        encoded += f"{len(value)}:".encode() + value + b"\n"
    return HASH_PREFIX + hashlib.sha256(encoded).hexdigest()


def _normalized_line_endings(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")
