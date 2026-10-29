import re
from collections.abc import Mapping
from typing import Any

# Vendors mask secrets on read, but we do not rely on it: a field that is not masked
# (a vendor bug or a new field) must still never reach storage.
# Keys are compared lowercased with `_` and `-` removed, so `apiKey` and `api_key` match alike.
_SECRET_KEY_PARTS = (
    "password",
    "secret",
    "token",
    "passphrase",
    "connectionstring",
    "dsn",
    "credential",
    "privatekey",
    "keystore",
    "truststore",
)
# Secret fields whose names fit no rule above (GitHub personal access tokens, Alchemer's API key).
_SECRET_KEYS = frozenset({"pat", "pats", "queryparamvalue"})
# Any key that ends in "key" or "keys", maybe with a number (`sasl_plain_key`, `api_keys`, `api_key_2`), is a
# secret, except these.
_NON_SECRET_KEYS = frozenset(
    {f"{name}{suffix}" for name in ("public", "primary", "partition", "sort") for suffix in ("key", "keys")}
)
_KEY_SUFFIX = re.compile(r"keys?\d*$")
# A URL with a password in it (`scheme://user:password@host`), or a token in its query (an Azure SAS `sig`).
_URL_WITH_PASSWORD = re.compile(r"://[^/@\s]+:[^/@\s]+@")
_URL_WITH_TOKEN = re.compile(r"://\S*[?&](sig|signature|token|access_token|api_key|apikey|key)=", re.IGNORECASE)


def is_secret_key(key: str) -> bool:
    normalized = re.sub(r"[_\-]", "", key.lower())
    if normalized.startswith("auth") or normalized in _SECRET_KEYS:
        return True
    if _KEY_SUFFIX.search(normalized) and normalized not in _NON_SECRET_KEYS:
        return True
    return any(part in normalized for part in _SECRET_KEY_PARTS)


def _is_secret_value(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    return (
        (len(value) > 0 and set(value) == {"*"})
        or bool(_URL_WITH_PASSWORD.search(value))
        or bool(_URL_WITH_TOKEN.search(value))
    )


def strip_secrets(config: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy of `config` without secret keys or secret values, at any depth."""
    return {
        key: _strip_value(value)
        for key, value in config.items()
        if not is_secret_key(key) and not _is_secret_value(value)
    }


def _strip_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return strip_secrets(value)
    if isinstance(value, list):
        return [_strip_value(item) for item in value if not _is_secret_value(item)]
    return value
