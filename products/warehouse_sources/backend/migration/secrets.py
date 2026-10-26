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
)
# Any key that ends in "key" is a secret (`sasl_plain_key`, `account_key`), except these.
_NON_SECRET_KEYS = frozenset({"publickey", "primarykey", "partitionkey", "sortkey"})
# A URL with a password in it: `scheme://user:password@host`.
_URL_WITH_PASSWORD = re.compile(r"://[^/@\s]+:[^/@\s]+@")


def is_secret_key(key: str) -> bool:
    normalized = re.sub(r"[_\-]", "", key.lower())
    if normalized.startswith("auth"):
        return True
    if normalized.endswith("key") and normalized not in _NON_SECRET_KEYS:
        return True
    return any(part in normalized for part in _SECRET_KEY_PARTS)


def _is_secret_value(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    return (len(value) > 0 and set(value) == {"*"}) or bool(_URL_WITH_PASSWORD.search(value))


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
