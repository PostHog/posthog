from collections.abc import Mapping
from typing import Any

# Vendors mask secrets on read, but we do not rely on it: a field that is not masked
# (a vendor bug or a new field) must still never reach storage.
_SECRET_KEY_PARTS = (
    "password",
    "secret",
    "token",
    "private_key",
    "api_key",
    "passphrase",
    "pass_phrase",
    "connection_string",
    "dsn",
    "credential",
)
_SECRET_KEYS = frozenset({"auth"})


def is_secret_key(key: str) -> bool:
    lowered = key.lower()
    return lowered in _SECRET_KEYS or any(part in lowered for part in _SECRET_KEY_PARTS)


def _is_masked(value: Any) -> bool:
    return isinstance(value, str) and len(value) > 0 and set(value) == {"*"}


def strip_secrets(config: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy of `config` without secret keys or masked values, at any depth."""
    return {
        key: _strip_value(value) for key, value in config.items() if not is_secret_key(key) and not _is_masked(value)
    }


def _strip_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return strip_secrets(value)
    if isinstance(value, list):
        return [_strip_value(item) for item in value if not _is_masked(item)]
    return value
