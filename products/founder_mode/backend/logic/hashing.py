"""Stable hashing helpers shared between the validation task and the API serializer.

The hash is the staleness signal: the task stores `ideation_hash` in the validation envelope
at run time; the serializer exposes the *current* hash of `ideation` so the frontend can
compare the two and decide whether the saved report is still in sync.
"""

import json
import hashlib
from typing import Any


def ideation_hash(ideation: dict[str, Any] | None) -> str:
    """SHA-256 of `ideation` with sorted JSON keys.

    Sorted keys + tight separators makes the canonical form stable across equivalent dicts,
    so two semantically identical payloads always produce the same hash. Returns the empty
    string for falsy input — useful as a sentinel meaning "nothing to validate against".
    """
    if not ideation:
        return ""
    canonical = json.dumps(ideation, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
