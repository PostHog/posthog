"""What a scanner's recording filter may hold, defined once for every path that accepts one.

A scanner keeps less of a recording filter than the replay list does, and each difference fails
silently: a dropped condition saves a scanner that watches more than the person chose, and a broken
one saves a scanner whose runs keep failing. Create, update and the estimate all accept a filter, so
they share these rules rather than each keeping a copy that can drift.
"""

import json
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from posthog.schema import RecordingsQuery

# A scanner's schedule owns time, so a saved filter never carries a date range.
DATE_FIELDS = ("date_from", "date_to")
# Copied into every observation's snapshot, so the write boundary caps it.
MAX_QUERY_BYTES = 50_000


class ScannerQueryError(ValueError):
    """A recording filter a scanner cannot keep. The message is safe to show to the caller."""


def _as_object(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ScannerQueryError("Recording filter must be a JSON object.")
    return value


def _parsed(value: dict[str, Any]) -> RecordingsQuery:
    try:
        return RecordingsQuery.model_validate(value)
    except PydanticValidationError:
        raise ScannerQueryError("Recording filter is invalid.")


def clean_scanner_query(value: object) -> dict[str, Any]:
    """The filter as a scanner stores it: a valid `RecordingsQuery` without the date range.

    Raises `ScannerQueryError` for anything a saved scanner must not hold.
    """
    value = _as_object(value)
    _parsed(value)
    # Exposure is derived from experiment_targeting at scan time, never persisted in the query blob:
    # writable exposure there would bypass experiment_targeting's access check and let an editor run
    # the exposure filter under the creator's access.
    if value.get("experiment_exposure") is not None:
        raise ScannerQueryError(
            "Recording filter can't set experiment exposure directly. Set experiment_targeting instead."
        )
    cleaned = {key: item for key, item in value.items() if key not in DATE_FIELDS}
    if len(json.dumps(cleaned, separators=(",", ":")).encode()) > MAX_QUERY_BYTES:
        raise ScannerQueryError(f"Recording filter is too large. Keep it under {MAX_QUERY_BYTES // 1000} KB.")
    return cleaned
