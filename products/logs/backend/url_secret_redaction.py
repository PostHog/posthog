"""Redaction of credential-shaped URL query parameters in log payloads.

Logs record request URLs verbatim, so an OAuth callback line carries a live token in its
query string. Agent-facing responses pass through here first: the host, the path and
benign parameter names survive, the credential values do not.
"""

import re
from typing import Any

REDACTED = "[redacted]"

# Names that carry a credential wherever the part appears. Separators are stripped before the
# match, so `access-token`, `access_token` and `accessToken` all hit the `token` part.
_SENSITIVE_NAME_PARTS = (
    "token",
    "secret",
    "password",
    "passwd",
    "passcode",
    "apikey",
    "accesskey",
    "secretkey",
    "privatekey",
    "signingkey",
    "authorization",
    "credential",
    "signature",
    "assertion",
    "jwt",
    "bearer",
    "otp",
)

# Names that are a credential on their own but read as a false positive inside a longer word,
# so `auth=` matches while `author=` does not.
_SENSITIVE_NAMES = frozenset({"auth", "oauth", "code", "key", "keys", "sig", "pass", "pwd", "pin", "ticket"})

_NAME_SEPARATORS = re.compile(r"[^a-z0-9]+")

# A query or a fragment runs from its `?` or `#` up to the first character that cannot be
# part of a URL inside log text.
_QUERY_REGION = re.compile(r"(?<=[?#])[^\s\"'<>`)\]}]+")

_NAME = r"[A-Za-z0-9_.%\[\]-]{1,128}"
_PAIR = re.compile(rf"({_NAME})=([^&;]*)")

# An attribute such as `url.query` holds the query string alone, with no `?` to anchor on.
_BARE_QUERY = re.compile(rf"{_NAME}=[^&\s]*(?:&{_NAME}=[^&\s]*)*")


def _is_sensitive_name(name: str) -> bool:
    normalized = _NAME_SEPARATORS.sub("", name.lower())
    if normalized in _SENSITIVE_NAMES:
        return True
    return any(part in normalized for part in _SENSITIVE_NAME_PARTS)


def _redact_pairs(region: str) -> str:
    def replace(pair: re.Match) -> str:
        name, value = pair.group(1), pair.group(2)
        if value and _is_sensitive_name(name):
            return f"{name}={REDACTED}"
        return pair.group(0)

    return _PAIR.sub(replace, region)


def redact_url_secrets(text: str) -> str:
    """Replace credential-shaped query parameter values in one string."""
    if "=" not in text:
        return text
    if _BARE_QUERY.fullmatch(text):
        return _redact_pairs(text)
    return _QUERY_REGION.sub(lambda region: _redact_pairs(region.group(0)), text)


def redact_secrets(value: Any) -> Any:
    """Replace credential-shaped query parameter values in every string a payload holds."""
    if isinstance(value, str):
        return redact_url_secrets(value)
    if isinstance(value, dict):
        return {key: redact_secrets(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    return value
