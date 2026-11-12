"""Shared helpers for bespoke scanner-finding emitters (record kind: scanner_finding)."""

import re
import hashlib
from typing import Any

# Scanner tables that store one row per occurrence (per application, repository, scan or component)
# group their rows by vulnerability. The window is on first-seen time, and the emission ledger keys on
# the vulnerability alone, so each vulnerability emits once. The window is wider than the grouped
# fetcher's default so a source that syncs once a few days still reaches every new vulnerability.
# A group is one vulnerability, not a burst of error occurrences, so these emitters keep the weight of
# 1.0 that the per-row scanner emitters use, and the key has no ISO week.
SCANNER_GROUP_WINDOW_DAYS = 7

_HTML_TAG = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"\s+")


def text_or_none(value: Any, limit: int | None = None) -> str | None:
    """A value as stripped text, or None when it is empty. JSON extraction gives '' or 'null' for a missing key."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text == "null":
        return None
    return text[:limit] if limit else text


def plain_text(value: Any, limit: int | None = None) -> str | None:
    """Like `text_or_none`, with HTML tags removed and whitespace collapsed."""
    text = text_or_none(value)
    if text is None:
        return None
    return text_or_none(_WHITESPACE.sub(" ", _HTML_TAG.sub(" ", text)), limit)


def extra_from(record: dict[str, Any], fields: tuple[str, ...]) -> dict[str, str | None]:
    """Every declared field as `str | None`, so the payload validates the same for any column type."""
    return {field: text_or_none(record.get(field)) for field in fields}


def hashed_source_id(prefix: str, *parts: Any) -> str:
    """A stable source id for a group key, hashed so long or odd key values stay short and safe."""
    fingerprint = "|".join("" if part is None else str(part).strip() for part in parts)
    return f"{prefix}:" + hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()


def datetime_expression(column: str) -> str:
    """A HogQL expression that reads a timestamp column stored either as a string or as a datetime."""
    return f"parseDateTimeBestEffort(toString({column}))"
