"""Shared rule for the variant keys a flag write may not store, on the v1 and v2 write paths.

The ingest cleaner stores a variant named "false" or "true" under a sentinel in the `$feature_flags` map, so every
write refuses the sentinels. flag_evaluations stores `$feature_flag_response` with the JSON quotes trimmed, so a variant
named "null" stores the same 'null' as a flag that returned null, and reads turn both into NULL. A variant with an
empty key stores ''. That is the value flag_evaluations stores for a missing response. HogQL reads '' as NULL on a
materialized events column. A flag that already serves a key in `RESERVED_NEW_VARIANT_KEYS` keeps it, because renaming
a variant breaks experiment and chart continuity.
"""

from collections.abc import Collection
from typing import Any

from posthog.hogql.constants import FEATURE_FLAG_VARIANT_SENTINELS

# Mirrored by RESERVED_NEW_VARIANT_KEYS in featureFlagLogic.ts. That list leaves out "", because the editor rejects
# every empty variant key before it checks the list.
RESERVED_NEW_VARIANT_KEYS: frozenset[str] = frozenset({"null", ""})


def is_reserved_variant_key(value: Any, *, held: Collection[Any]) -> bool:
    """Whether a write may not store ``value`` as a variant, given the variants the stored flag ``held``."""
    return value in FEATURE_FLAG_VARIANT_SENTINELS or (value in RESERVED_NEW_VARIANT_KEYS and value not in held)
