"""Snake case naming convention used for normalizing identifiers coming from
external data sources.

This is a port of ``dlt.common.normalizers.naming.snake_case.NamingConvention``
so we can drop the DLT runtime dependency from the data import code paths. The
behavior must stay byte-for-byte compatible with the DLT implementation because
existing schemas, column names and table names stored in ClickHouse/S3 were
produced by it.
"""

import re
import math
import base64
import hashlib
from functools import lru_cache

RE_UNDERSCORES = re.compile("__+")
RE_LEADING_DIGITS = re.compile(r"^\d+")
RE_NON_ALPHANUMERIC = re.compile(r"[^a-zA-Z\d_]+")

_SNAKE_CASE_BREAK_1 = re.compile("([^_])([A-Z][a-z]+)")
_SNAKE_CASE_BREAK_2 = re.compile("([a-z0-9])([A-Z])")

_REDUCE_ALPHABET = ("+-*@|", "x_xal")
_TR_REDUCE_ALPHABET = str.maketrans(_REDUCE_ALPHABET[0], _REDUCE_ALPHABET[1])

# base64 produces `+` and `/`; translate them to alphanumeric so the resulting
# tag survives the alphanumeric-only identifier rules.
_TR_TAG_TABLE = bytes.maketrans(b"/+", b"ab")

_DEFAULT_COLLISION_PROB = 0.001


class NamingConvention:
    """Case insensitive snake_case naming convention with a reduced alphabet.

    - Spaces around the identifier are trimmed.
    - All ascii characters except alphanumerics and underscores are removed.
    - Prepends ``_`` if the name starts with a number.
    - Multiples of ``_`` are collapsed to a single ``_``.
    - Trailing ``_`` characters are replaced with ``x``.
    - ``+`` and ``*`` become ``x``, ``-`` becomes ``_``, ``@`` becomes ``a``,
      ``|`` becomes ``l``.

    When ``max_length`` is set, identifiers longer than that are truncated and
    a short deterministic tag derived from the original identifier is inserted
    in the middle so that collisions remain unlikely.
    """

    @staticmethod
    def normalize_identifier(identifier: str, max_length: int | None = None) -> str:
        if identifier is None:
            raise ValueError("`name` is None")
        identifier = identifier.strip()
        if not identifier:
            raise ValueError(identifier)
        return _normalize_identifier(identifier, max_length)


@lru_cache
def _normalize_identifier(identifier: str, max_length: int | None) -> str:
    normalized = identifier.translate(_TR_REDUCE_ALPHABET)
    normalized = RE_NON_ALPHANUMERIC.sub("_", normalized)
    normalized = _to_snake_case(normalized)
    return _shorten_identifier(normalized, identifier, max_length)


def _to_snake_case(identifier: str) -> str:
    identifier = _SNAKE_CASE_BREAK_1.sub(r"\1_\2", identifier)
    identifier = _SNAKE_CASE_BREAK_2.sub(r"\1_\2", identifier).lower()

    if RE_LEADING_DIGITS.match(identifier):
        identifier = "_" + identifier

    stripped = identifier.rstrip("_")
    strip_count = len(identifier) - len(stripped)
    stripped += "x" * strip_count

    return RE_UNDERSCORES.sub("_", stripped)


@lru_cache
def _shorten_identifier(
    normalized_ident: str,
    identifier: str,
    max_length: int | None,
    collision_prob: float = _DEFAULT_COLLISION_PROB,
) -> str:
    if max_length and len(normalized_ident) > max_length:
        tag = _compute_tag(identifier, collision_prob)
        normalized_ident = _trim_and_tag(normalized_ident, tag, max_length)
    return normalized_ident


def _compute_tag(identifier: str, collision_prob: float) -> str:
    # Assume shake_128 has ~perfect collision resistance 2^(N/2); account for
    # the ~1.5x bit overhead introduced by lower-casing base64 output.
    tl_bytes = int(((2 + 1) * math.log2(1 / collision_prob) // 8) + 1)
    return (
        base64.b64encode(hashlib.shake_128(identifier.encode("utf-8")).digest(tl_bytes))
        .rstrip(b"=")
        .translate(_TR_TAG_TABLE)
        .lower()
        .decode("ascii")
    )


def _trim_and_tag(identifier: str, tag: str, max_length: int) -> str:
    assert len(tag) <= max_length
    remaining_length = max_length - len(tag)
    remaining_overflow = remaining_length % 2
    trimmed = (
        identifier[: remaining_length // 2 + remaining_overflow]
        + tag
        + identifier[len(identifier) - remaining_length // 2 :]
    )
    assert len(trimmed) == max_length
    return trimmed
