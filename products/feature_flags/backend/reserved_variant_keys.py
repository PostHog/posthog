"""Shared rules for the variant keys a flag write may not store, on the v1 and v2 write paths.

The ingest cleaner stores a variant named "false" or "true" under a sentinel in the `$feature_flags` map, so every
write refuses the sentinels.

`RESERVED_NEW_VARIANT_KEYS` holds the keys that read the same as a response that is not a variant:

- `/flags` returns a variant named "true" or "false" as a JSON string, and a boolean flag returns a JSON boolean.
  HogQL, the materialized columns and flag_evaluations trim the JSON quotes, so both read as the same 'true' or 'false'.
  A "false" variant then reads as a multivariate flag's not-enrolled `false`.
- flag_evaluations stores a variant named "null" as 'null', the same as a flag that returned null, and reads turn both
  into NULL.
- A variant with an empty key stores ''. That is the value flag_evaluations stores for a missing response. HogQL reads
  '' as NULL on a materialized events column.

A flag that already serves a key in `RESERVED_NEW_VARIANT_KEYS` keeps it, because renaming a variant breaks experiment
and chart continuity. The match is exact, so "True" and "NULL" stay allowed.
"""

import json
from collections import Counter
from collections.abc import Collection, Iterator, Mapping, Sequence
from typing import Any

from posthog.hogql.constants import FEATURE_FLAG_VARIANT_SENTINELS

from products.feature_flags.backend.facade.config import detect_config_format

# Mirrored by RESERVED_NEW_VARIANT_KEYS in featureFlagLogic.ts. That list leaves out "", because the editor rejects
# every empty variant key before it checks the list.
RESERVED_NEW_VARIANT_KEYS: frozenset[str] = frozenset({"null", "", "true", "false"})


def is_reserved_variant_key(value: Any, *, held: Collection[Any]) -> bool:
    """Whether a write may not store ``value`` as a variant, given the variants the stored flag ``held``."""
    return value in FEATURE_FLAG_VARIANT_SENTINELS or (value in RESERVED_NEW_VARIANT_KEYS and value not in held)


def reserved_variant_key(filters: object, *, held: Collection[str] = ()) -> str | None:
    """The first variant key in ``filters`` that a write over a flag holding the keys ``held`` may not store."""
    return next((key for key in variant_keys(filters) if is_reserved_variant_key(key, held=held)), None)


def variant_keys(filters: object) -> Iterator[str]:
    """Each string variant key in ``filters``, skipping keys of any other type."""
    for _, variants in _variant_lists(filters):
        for variant in variants:
            if isinstance(variant, Mapping) and isinstance(variant.get("key"), str):
                yield variant["key"]


def reserved_variant_key_message(key: str) -> str:
    if key == "":
        return "Variant keys can't be empty. Enter a key for each variant."
    return f'The variant key "{key}" is reserved. Choose another key.'


def non_string_variants(filters: object) -> list[tuple[str, Any]]:
    """Each variant in ``filters`` without a string key, with the path of that key.

    Reads ``multivariate.variants`` in a v1 document and each ``rules[].variants`` list in a v2 document. Rust declares a
    variant key as a required string, so one variant without one fails the team's whole cached flag payload, not only
    its own flag.
    """
    return [
        (f"{path}[{index}].key", variant)
        for path, variants in _variant_lists(filters)
        for index, variant in enumerate(variants)
        if not isinstance(variant, Mapping) or not isinstance(variant.get("key"), str)
    ]


def unheld_non_string_variant(filters: object, *, held: object) -> str | None:
    """The key path of the first variant in ``filters`` without a string key that the ``held`` filters do not hold.

    Each variant in ``held`` excuses one variant in ``filters``, so a second copy of a held variant is refused.
    """
    held_texts = Counter(_json_text(variant) for _, variant in non_string_variants(held))
    for path, variant in non_string_variants(filters):
        text = _json_text(variant)
        if held_texts[text]:
            held_texts[text] -= 1
        else:
            return path
    return None


def _json_text(value: Any) -> str:
    # Unlike canonical_value in facade/config_validation.py, this keeps 1.0 apart from 1. It also keeps true apart from 1,
    # which == does not.
    return json.dumps(value, sort_keys=True, default=str)


def _variant_lists(filters: object) -> Iterator[tuple[str, Sequence[Any]]]:
    # JSONField stores a tuple as a JSON array, so an ORM write can pass either.
    if not isinstance(filters, Mapping):
        return
    kind = detect_config_format(filters).kind
    if kind == "v1":
        multivariate = filters.get("multivariate")
        if isinstance(multivariate, Mapping) and isinstance(multivariate.get("variants"), list | tuple):
            yield "multivariate.variants", multivariate["variants"]
    elif kind == "v2" and isinstance(filters.get("rules"), list | tuple):
        for index, rule in enumerate(filters["rules"]):
            if isinstance(rule, Mapping) and isinstance(rule.get("variants"), list | tuple):
                yield f"rules[{index}].variants", rule["variants"]
