"""Redact credentials from span attribute values before they reach an agent.

OTel HTTP instrumentation can record request headers as span attributes
(`http.request.header.authorization`) or as one JSON-encoded header map. Agent
responses end up in model context and stored transcripts, so MCP callers get these
values replaced. Attribute keys and ordinary values stay as they are.
"""

import re
import json
from typing import Any

FILTERED = "[Filtered]"

# A key matches when a word of its last dot segment (split on `-`, `_` and spaces) is in this set.
_SENSITIVE_WORDS = frozenset(
    {
        "accesstoken",
        "apikey",
        "assertion",
        "authorization",
        "cookie",
        "cookies",
        "credential",
        "credentials",
        "jwt",
        "oidc",
        "passwd",
        "password",
        "secret",
        "signature",
        "token",
    }
)
_SENSITIVE_WORD_PAIRS = frozenset({("api", "key"), ("access", "key"), ("private", "key")})
_WORD_SPLIT = re.compile(r"[\-_\s]+")
# Credentials can also sit inside free text, for example a raw header dump.
_AUTH_SCHEMES = (
    re.compile(r"\b(Bearer)\s+[A-Za-z0-9._~+/\-]{8,}=*", re.IGNORECASE),
    re.compile(r"\b(Basic)\s+[A-Za-z0-9+/]{8,}=*"),
)


def is_sensitive_key(key: str) -> bool:
    """Check a header name, an attribute key, or a key inside an encoded header map.

    Only the last dot segment counts, so `http.request.header.authorization` matches
    and `llm.token_count.prompt` keeps its value.
    """
    words = [word for word in _WORD_SPLIT.split(key.lower().rsplit(".", 1)[-1]) if word]
    if any(word in _SENSITIVE_WORDS for word in words):
        return True
    return any(pair in _SENSITIVE_WORD_PAIRS for pair in zip(words, words[1:]))


def _redact_auth_schemes(value: str) -> str:
    for pattern in _AUTH_SCHEMES:
        value = pattern.sub(lambda match: f"{match.group(1)} {FILTERED}", value)
    return value


def _redact_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: FILTERED if is_sensitive_key(str(key)) else _redact_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_json(item) for item in value]
    if isinstance(value, str):
        return _redact_auth_schemes(value)
    return value


def redact_attribute_value(key: str, value: Any) -> Any:
    if not isinstance(value, str):
        return value
    if is_sensitive_key(key):
        return FILTERED
    if value.lstrip()[:1] in ("{", "["):
        try:
            decoded = json.loads(value)
        except ValueError:
            decoded = None
        if isinstance(decoded, dict | list):
            redacted = _redact_json(decoded)
            return value if redacted == decoded else json.dumps(redacted)
    return _redact_auth_schemes(value)


def redact_attributes(attributes: Any) -> Any:
    if not isinstance(attributes, dict):
        return attributes
    return {key: redact_attribute_value(str(key), value) for key, value in attributes.items()}


def redact_span_rows(rows: list[dict]) -> list[dict]:
    """Return copies of span rows with credentials in both attribute maps replaced."""
    return [
        {
            **row,
            "attributes": redact_attributes(row.get("attributes")),
            "resource_attributes": redact_attributes(row.get("resource_attributes")),
        }
        for row in rows
    ]
