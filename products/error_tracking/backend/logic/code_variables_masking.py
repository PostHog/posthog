"""Mask the code variables that Python stack frames carry.

The rules match cymbal's `rust/cymbal/src/core/code_variables.rs`, which masks code variables
on every incoming event. This copy masks the stack frames that cymbal stored before it masked.
Change both together.
"""

from __future__ import annotations

import re
import json
import math
import base64
import binascii
from collections import Counter
from typing import Union

JSONValue = Union[None, bool, int, float, str, list["JSONValue"], dict[str, "JSONValue"]]

REDACTED = "$$_posthog_redacted_based_on_masking_rules_$$"
TOO_LONG = "$$_posthog_value_too_long_$$"

_MAX_LENGTH_FOR_PATTERN_MATCH = 2_048
_MAX_DEPTH = 12
_SECRET_MIN_LENGTH = 16
_SECRET_MIN_ENTROPY_BITS = 3.8
_SECRET_MIN_CHAR_CLASSES = 3
# Shorter values are prose, such as "the bearer of", and so is a word of up to 15 letters
# that is lowercase or starts with a capital, such as "bearer transportation" or
# "basic: Configuration". A random token mixes case or is longer than that. A `Basic`
# credential of any length is still redacted when it decodes to `user:password`, e.g.
# `YTpi` for `a:b`.
_AUTH_CREDENTIAL_MIN_LENGTH = 8
_AUTH_PROSE_WORD_MAX_LENGTH = 15
_PEM_PRIVATE_KEY_MARKER = "PRIVATE KEY-----"
# Punctuation of reprs and structured strings. A bare token never holds it.
_SECRET_REJECT_CHARS = frozenset("()[]{}<>'\"`,;")
_HEX_LETTERS = frozenset("abcdefABCDEF")

# The posthog-python SDK's default mask patterns. They match names and string values alike, so a
# value that contains `token` is redacted whole. As in cymbal, `sk_` must start a word, so
# `task_id` and `disk_usage` keep their values.
_MASK_PATTERNS = re.compile(
    r"(?i)password|secret|passwd|pwd|api_key|apikey|auth|credentials|privatekey|"
    r"private_key|token|aws_access_key_id|_pass|(?:^|[^a-z0-9])sk_|jwt|connection_string|"
    r"connectionstring|conn_str|connstr|dsn|[?&]sig="
)

_KNOWN_SECRET = re.compile(
    "|".join(
        [
            r"sk-ant-[A-Za-z0-9_-]{16,}",
            r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}",
            r"hf_[A-Za-z0-9]{34}",
            r"AKIA[0-9A-Z]{16}",
            r"(?:ASIA|AGPA|AIDA|AROA|AIPA|ANPA|ANVA|ABIA|ACCA)[0-9A-Z]{16}",
            r"AIza[A-Za-z0-9_-]{35}",
            r"ya29\.[A-Za-z0-9_-]{20,}",
            r"do[opr]_v1_[a-f0-9]{64}",
            r"(?:sk|pk|rk)_(?:live|test)_[A-Za-z0-9]{16,}",
            r"sq0[a-z]{3}-[A-Za-z0-9_-]{22,43}",
            r"gh[pousr]_[A-Za-z0-9]{36}",
            r"github_pat_[A-Za-z0-9_]{20,}",
            r"gl(?:pat|ptt|rt|soat)-[A-Za-z0-9_-]{20}",
            r"glsa_[A-Za-z0-9]{32}_[A-Fa-f0-9]{8}",
            r"xox[abeoprs]-[A-Za-z0-9-]{10,}",
            r"xapp-[0-9]-[A-Za-z0-9-]{10,}",
            r"SK[0-9a-fA-F]{32}",
            r"SG\.[A-Za-z0-9_-]{22}\.[A-Za-z0-9_-]{43}",
            r"key-[0-9a-f]{32}",
            r"[0-9a-f]{32}-us[0-9]{1,2}",
            r"npm_[A-Za-z0-9]{36}",
            r"pypi-AgEI[A-Za-z0-9_-]{50,}",
            r"dapi[0-9a-f]{32}",
            r"dp\.pt\.[A-Za-z0-9]{40,}",
            r"PMAK-[a-f0-9]{24}-[a-f0-9]{34}",
            r"lin_api_[A-Za-z0-9]{40}",
            r"ntn_[A-Za-z0-9]{40,}",
            r"shp(?:at|ca|pa|ss)_[a-fA-F0-9]{32}",
            r"NR(?:AK|JS|II|MA|RA)-[A-Za-z0-9]{27}",
            r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{6,}",
        ]
    )
)

# The userinfo ends where the authority ends, at `/`, `?` or `#`.
_URL_CREDENTIALS = re.compile(r"(?i)([a-z][a-z0-9+.\-]{0,30}://)([^/?#\s]*)@")

# A header pair list or an ASGI scope holds an `Authorization` value apart from its header
# name, so the name patterns never see it. The separator also accepts a colon or an opening
# quote, as in `Bearer: <token>`, but it must not be empty, so that names such as
# `basicConfig` stay untouched.
_AUTH_HEADER_CREDENTIALS = re.compile(r"(?i)\b(bearer|basic)((?:\s*:\s*|\s+)['\"]?)([A-Za-z0-9._~+/-]+=*)")

_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_PATH_WORD = re.compile(r"[a-z][a-z.]*")
# A key that matches a mask pattern is kept only in this shape. Other text, such as
# `password=hunter2`, can hold the value itself.
_FIELD_NAME = re.compile(r"[\w.\-]+")


def _looks_like_path_or_url(value: str) -> bool:
    if "://" in value or "\\" in value:
        return True
    if "/" not in value:
        return False
    word_segments = [segment for segment in value.split("/") if segment and _PATH_WORD.fullmatch(segment)]
    return len(word_segments) >= 2


def _is_high_entropy_secret(value: str) -> bool:
    if " " in value or _looks_like_path_or_url(value) or _UUID.fullmatch(value):
        return False
    counts = Counter(value)
    lower = upper = digit = symbol = False
    hex_only = True
    for char in counts:
        if char.isspace() or char in _SECRET_REJECT_CHARS:
            return False
        if char.islower():
            lower = True
            hex_only = hex_only and char in _HEX_LETTERS
        elif char.isupper():
            upper = True
            hex_only = hex_only and char in _HEX_LETTERS
        elif char.isnumeric():
            digit = True
        else:
            symbol = True
            hex_only = False
    # A hex string is an id or a digest, such as a SHA or an ObjectId.
    if hex_only or sum((lower, upper, digit, symbol)) < _SECRET_MIN_CHAR_CLASSES:
        return False
    entropy = -sum((n / len(value)) * math.log2(n / len(value)) for n in counts.values())
    return entropy >= _SECRET_MIN_ENTROPY_BITS


def _looks_like_secret(value: str) -> bool:
    if _PEM_PRIVATE_KEY_MARKER in value:
        return True
    if len(value) < _SECRET_MIN_LENGTH:
        return False
    if _is_high_entropy_secret(value):
        return True
    # Known formats that the entropy check misses, e.g. AWS key ids with two char classes.
    return len(value) <= _MAX_LENGTH_FOR_PATTERN_MATCH and _KNOWN_SECRET.search(value) is not None


def _redact_url_credential(match: re.Match[str]) -> str:
    # Only userinfo with a password is a credential: `ssh://git@host` keeps its username.
    if ":" in match.group(2).split("@")[0]:
        return f"{match.group(1)}{REDACTED}@"
    return match.group(0)


def _is_basic_credential(credential: str) -> bool:
    try:
        return ":" in base64.b64decode(credential, validate=True).decode("utf-8")
    except (binascii.Error, ValueError):
        return False


def _redact_auth_credential(match: re.Match[str]) -> str:
    credential = match.group(3)
    is_basic_pair = match.group(1).lower() == "basic" and _is_basic_credential(credential)
    is_prose_word = (
        len(credential) <= _AUTH_PROSE_WORD_MAX_LENGTH
        and credential[:1].isascii()
        and credential[:1].isalpha()
        and all("a" <= c <= "z" for c in credential[1:])
    )
    if not is_basic_pair and (len(credential) < _AUTH_CREDENTIAL_MIN_LENGTH or is_prose_word):
        return match.group(0)
    return f"{match.group(1)}{match.group(2)}{REDACTED}"


def _redact_embedded_credentials(value: str) -> str:
    # URLs go first, because the `Authorization` pass can consume a URL scheme, as in
    # `Bearer postgresql://user:pass@host`.
    if "://" in value:
        value = _URL_CREDENTIALS.sub(_redact_url_credential, value)
    return _AUTH_HEADER_CREDENTIALS.sub(_redact_auth_credential, value)


def _reject_json_constant(constant: str) -> float:
    raise ValueError(f"not valid JSON: {constant}")


def _parse_json_container(value: str) -> JSONValue | None:
    if not value.lstrip().startswith(("{", "[")):
        return None
    try:
        return json.loads(value, parse_constant=_reject_json_constant)
    except ValueError:
        return None


class _PlaceholderKeys:
    """Hands out unused placeholder keys for one mapping. Placeholders are only added, so the
    search resumes from the last one instead of zero."""

    def __init__(self) -> None:
        self._next = 0

    def take(self, result: dict[str, JSONValue]) -> str:
        while True:
            candidate = f"$$_posthog_redacted_key_{self._next}_$$"
            self._next += 1
            if candidate not in result:
                return candidate


def _mask_string(value: str, depth: int) -> str:
    if len(value) > _MAX_LENGTH_FOR_PATTERN_MATCH:
        return TOO_LONG
    # The SDK serializes a dict or an object to a JSON string after it masks it. The string
    # rules would redact all of it for any sensitive key name, so mask the structure instead.
    parsed = _parse_json_container(value)
    if parsed is not None:
        masked = _mask_value(parsed, depth + 1)
        return value if masked == parsed else json.dumps(masked, separators=(",", ":"), ensure_ascii=False)
    if _MASK_PATTERNS.search(value) or _looks_like_secret(value):
        return REDACTED
    return _redact_embedded_credentials(value)


def _mask_mapping(entries: dict[str, JSONValue], depth: int) -> dict[str, JSONValue]:
    result: dict[str, JSONValue] = {}
    placeholders = _PlaceholderKeys()
    for key, value in entries.items():
        if len(key) > _MAX_LENGTH_FOR_PATTERN_MATCH:
            result[placeholders.take(result)] = TOO_LONG
            continue
        key_matches_mask = _MASK_PATTERNS.search(key) is not None
        if (key_matches_mask and not _FIELD_NAME.fullmatch(key)) or _looks_like_secret(key):
            out_key = placeholders.take(result)
        else:
            out_key = _redact_embedded_credentials(key)
        # Two keys can mask to the same text, e.g. URLs that differ only in their credentials.
        if out_key in result:
            out_key = placeholders.take(result)
        result[out_key] = REDACTED if key_matches_mask else _mask_value(value, depth + 1)
    return result


def _mask_value(value: JSONValue, depth: int) -> JSONValue:
    if depth >= _MAX_DEPTH and isinstance(value, dict | list):
        return TOO_LONG
    if isinstance(value, str):
        return _mask_string(value, depth)
    if isinstance(value, list):
        return [_mask_value(item, depth + 1) for item in value]
    if isinstance(value, dict):
        return _mask_mapping(value, depth)
    return value


def mask_code_variables(code_variables: JSONValue) -> JSONValue:
    """Return a masked copy of a frame's `code_variables`. Masking the result again changes nothing."""
    return _mask_value(code_variables, 0)
