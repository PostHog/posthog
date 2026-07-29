"""Run-metadata self-report: the scout stamps structured context onto its own run row.

`SignalScoutRun.metadata` has two regions. The top-level keys (`model`,
`runtime_adapter`, `reasoning_effort`, ...) are runner-stamped at run creation and
stay write-once. This tool owns the second region: the `self_reported` sub-object,
a small flat map of scalars the scout merges into mid-run via `record_run_metadata`
("what kind of run was this?" — flags like `has_agent_feedback: true` or
`validation_run: true`, small counts, short labels). Keeping the two regions
separate means a scout write can never clobber the routing triple, and a future
runner-stamped key can never collide with a scout-chosen one.

Merge semantics, not append: re-recording a key overwrites its value in place, so
a scout can safely refine a flag late in the run. Facts the harness can already
derive server-side (`emitted_report_ids`, `edited_report_ids`, the emit tally)
should NOT be self-reported — this surface exists for the things only the scout
can see, e.g. actions taken over the public MCP (agent feedback) or a judgment
about the run itself (a validation pass).
"""

from __future__ import annotations

import re
import math
from collections.abc import Mapping
from typing import Any

from django.db import transaction

from products.signals.backend.models import SignalScoutRun

# The sub-object inside `SignalScoutRun.metadata` that scout self-reports live under.
SELF_REPORTED_METADATA_KEY = "self_reported"

# Caps keep the map a set of dimensions, not a document: values this size belong in the
# scratchpad or the run summary, and a bounded key count keeps the run row cheap to read
# on the list surface (the whole `metadata` column ships with every run summary).
MAX_SELF_REPORTED_KEYS = 25
MAX_SELF_REPORTED_KEY_LENGTH = 64
MAX_SELF_REPORTED_VALUE_LENGTH = 200

# Keys are snake_case identifiers so they read as queryable dimensions
# (`metadata->'self_reported'->>'has_agent_feedback'`), never free prose.
_SELF_REPORTED_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class InvalidRunMetadataError(ValueError):
    """The scout tried to self-report metadata with invalid shape (bad key, non-scalar value, over cap)."""


def validate_self_reported_updates(updates: Mapping[str, Any]) -> None:
    """Validate a self-report payload's shape without touching the database.

    Values must be JSON scalars (str/bool/int/float) — nested objects and lists are
    rejected so the map stays flat and each key stays a breakdown-friendly dimension.
    """
    if not updates:
        raise InvalidRunMetadataError("metadata must contain at least one key")
    if len(updates) > MAX_SELF_REPORTED_KEYS:
        raise InvalidRunMetadataError(f"metadata carries {len(updates)} keys, exceeding max {MAX_SELF_REPORTED_KEYS}")
    for key, value in updates.items():
        # `fullmatch`, not `match`: `$` would accept a trailing newline ("validation_run\n"),
        # minting a visually identical but distinct JSON key that exact-match queries then miss.
        if (
            not isinstance(key, str)
            or len(key) > MAX_SELF_REPORTED_KEY_LENGTH
            or not _SELF_REPORTED_KEY_RE.fullmatch(key)
        ):
            raise InvalidRunMetadataError(
                f"invalid metadata key {key!r}: keys must be snake_case identifiers "
                f"(lowercase letters, digits, underscores; start with a letter; "
                f"max {MAX_SELF_REPORTED_KEY_LENGTH} chars)"
            )
        # bool is checked before int/float since bool subclasses int — accepted either way,
        # but keeping the check explicit documents the allowed scalar set.
        if not isinstance(value, str | bool | int | float):
            raise InvalidRunMetadataError(
                f"invalid value for metadata key {key!r}: values must be scalars (string, boolean, or number)"
            )
        if isinstance(value, str):
            if len(value) > MAX_SELF_REPORTED_VALUE_LENGTH:
                raise InvalidRunMetadataError(
                    f"value for metadata key {key!r} is {len(value)} chars, exceeding max "
                    f"{MAX_SELF_REPORTED_VALUE_LENGTH} — long-form context belongs in the scratchpad or run summary"
                )
            _validate_storable_string(key, value)
        # Postgres jsonb rejects non-finite numbers at write time — catch them here so the
        # caller gets the documented validation error, not a 500 from `run.save()`.
        if isinstance(value, float) and not math.isfinite(value):
            raise InvalidRunMetadataError(
                f"invalid value for metadata key {key!r}: numbers must be finite (no NaN or Infinity)"
            )


def _validate_storable_string(key: str, value: str) -> None:
    """Reject strings Postgres jsonb cannot store — a NUL character or a lone surrogate would
    otherwise pass the shape checks and turn into a 500 at `run.save()`."""
    if "\x00" in value:
        raise InvalidRunMetadataError(f"invalid value for metadata key {key!r}: strings must not contain NUL (\\x00)")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise InvalidRunMetadataError(
            f"invalid value for metadata key {key!r}: strings must be valid UTF-8 (no lone surrogates)"
        )


def record_run_metadata(*, run_id: Any, updates: Mapping[str, Any]) -> dict[str, Any]:
    """Merge `updates` into the run's `metadata["self_reported"]` and return the merged map.

    The caller (the viewset) has already resolved the run team-scoped and asserted it is
    in progress, so this only guards the row still existing at write time. Runs under
    `select_for_update` so the read-modify-write on the JSON column can't lose a
    concurrent write (mirrors `emit._record_emit`); the merged result is capped the same
    way as a single payload so repeated calls can't grow the map past
    `MAX_SELF_REPORTED_KEYS`. Uses the unscoped `all_teams` manager because ownership was
    validated by the caller, matching the other run-row writers in this package.
    """
    validate_self_reported_updates(updates)
    with transaction.atomic():
        run = SignalScoutRun.all_teams.select_for_update(of=("self",)).filter(pk=run_id).first()
        if run is None:
            raise InvalidRunMetadataError(f"run {run_id} no longer exists")
        metadata = dict(run.metadata or {})
        merged = {**(metadata.get(SELF_REPORTED_METADATA_KEY) or {}), **updates}
        if len(merged) > MAX_SELF_REPORTED_KEYS:
            raise InvalidRunMetadataError(
                f"merging would leave {len(merged)} self-reported keys, exceeding max {MAX_SELF_REPORTED_KEYS} — "
                "re-use existing keys instead of minting new ones"
            )
        metadata[SELF_REPORTED_METADATA_KEY] = merged
        run.metadata = metadata
        run.save(update_fields=["metadata"])
    return merged
