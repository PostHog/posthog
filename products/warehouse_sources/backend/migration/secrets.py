import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import unquote, unquote_plus

# Vendors mask secrets on read, but we do not rely on it: a field that is not masked
# (a vendor bug or a new field) must still never reach storage.
# Keys are compared lowercased with `_` and `-` removed, so `apiKey` and `api_key` match alike.
_SECRET_KEY_PARTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "passphrase",
    "connectionstring",
    "dsn",
    "credential",
    "privatekey",
    "keystore",
    "truststore",
    # `auth`, `dsv_service_auth`, `shard_authorization_id`, `serviceauthentication`.
    "auth",
)
# Secret fields whose names fit no rule above (GitHub personal access tokens, Alchemer's API key,
# Open Exchange Rates' app id).
_SECRET_KEYS = frozenset({"appid", "pat", "pats", "pwd", "queryparamvalue"})
# Any key that ends in "key" or "keys", maybe with a number (`sasl_plain_key`, `api_keys`, `api_key_2`), is a
# secret, except these. A singular `primary_key` is a credential in some connectors (Care Quality Commission).
_NON_SECRET_KEYS = frozenset(
    {"publickey", "publickeys", "primarykeys", "partitionkey", "partitionkeys", "sortkey", "sortkeys"}
)
_KEY_SUFFIX = re.compile(r"keys?\d*$")
# Client certificates authenticate the caller. CA certificates (`ca_cert`, `ssl_root_cert`) are public.
_CA_TOKENS = frozenset({"ca", "root"})
_KEY_TOKEN_SPLIT = re.compile(r"[_\-]|(?<=[a-z])(?=[A-Z])")
# Signed-URL parameters: Azure SAS `sig`, AWS `X-Amz-Signature`, `SharedAccessSignature`.
_SIGNATURE_PARAM = re.compile(r"(^|[_\-])sig$|signature", re.IGNORECASE)
_URL_AUTHORITY = re.compile(r"[^/\s]*")
_QUERY_SEPARATOR = re.compile(r"[?&]")
_NOT_IN_PARAM_NAME = re.compile(r"[#\s]")


def is_secret_key(key: str) -> bool:
    normalized = re.sub(r"[_\-]", "", key.lower())
    if normalized in _SECRET_KEYS:
        return True
    if _KEY_SUFFIX.search(normalized) and normalized not in _NON_SECRET_KEYS:
        return True
    if "cert" in normalized and not _CA_TOKENS & {token.lower() for token in _KEY_TOKEN_SPLIT.split(key)}:
        return True
    return any(part in normalized for part in _SECRET_KEY_PARTS)


def _is_secret_value(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    if len(value) > 0 and set(value) == {"*"}:
        return True
    if "://" not in value:
        return False
    # Names are decoded first, so `%73ig` is checked as `sig`.
    names = [unquote_plus(name) for name in _query_param_names(value)]
    return _has_url_password(value) or any(is_secret_key(name) or _SIGNATURE_PARAM.search(name) for name in names)


# These scans are linear in the value's length, because an agent upload can carry any string, and a backtracking
# pattern stalls on one like `https://::::…`.
def _has_url_password(value: str) -> bool:
    """`scheme://user:password@host`, also with an empty user."""
    start = value.find("://")
    while start >= 0:
        authority = _URL_AUTHORITY.match(value, start + 3)
        # The host follows the last `@`, as `urllib` reads it, so a user such as `reader@corp` keeps its password.
        userinfo, at, _host = (authority.group() if authority else "").rpartition("@")
        # A colon with a non-empty password after it, also percent-encoded as `%3A`.
        if at and (":" in userinfo[:-1] or ":" in unquote(userinfo)[:-1]):
            return True
        start = value.find("://", start + 3)
    return False


def _query_param_names(value: str) -> list[str]:
    names = []
    for piece in _QUERY_SEPARATOR.split(value)[1:]:
        name, equals, _value = piece.partition("=")
        if equals and name and not _NOT_IN_PARAM_NAME.search(name):
            names.append(name)
    return names


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
