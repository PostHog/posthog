"""Writer admission and server-owned identity for config version 2 updates.

Three things a v2 update needs that the pure validator deliberately does not do:

- **Admission.** ``v2_update_limits`` is the closed seam the writer asks before it looks at
  a request. It answers ``None`` in every deployed configuration, so no v2 write is
  reachable in production through any entrypoint. The production admission requirements
  are documented in ``docs/internal/feature-flags/api-writes.md``.
- **Identity.** Rule ids and assignment seeds are server-owned and identify rules, not
  list positions. ``resolve_identity`` echoes back existing identity, allocates it for
  genuinely new rules, and rejects a client that tries to choose it.
- **Comparison.** ``review_update`` validates both documents' shape and semantics, so
  warnings describe the real before/proposed pair and unsupported stored families are
  rejected. Byte limits apply only to the candidate so oversized rows can be reduced.

Deliberately free of Django ORM and DRF imports: the endpoint owns HTTP error shapes and
the row lock, this module owns the document.
"""

import sys
import json
from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from django.conf import settings

from products.feature_flags.backend.facade.config_validation import (
    ConfigError,
    ConfigValidationError,
    ValidationLimits,
    validate_config,
)
from products.feature_flags.backend.facade.rule_warnings import review_config
from products.feature_flags.backend.facade.warnings import ManagementWarning

# The trusted writer policy for admitted v2 updates. ``None`` denies every one of them and
# is the only value any deployed configuration has: per-team admission is not implemented,
# and the per-rule metadata byte bound has no agreed production value (see api-writes.md).
# Tests patch this attribute to exercise the dormant path; nothing reads a request field,
# a serializer context flag, staff status or a missing user as permission to write v2.
V2_UPDATE_LIMITS: ValidationLimits | None = None

_SEEDED_RULE_TYPE = "percentage_rollout"


def v2_update_limits() -> ValidationLimits | None:
    """Trusted limits for an admitted v2 update, or ``None`` when the write is denied.

    A lower deployment filter-size limit always wins over the policy's, matching the cap
    the v1 write path and the Rust reader both enforce.
    """
    limits = V2_UPDATE_LIMITS
    if limits is None:
        return None
    return ValidationLimits(
        max_config_bytes=min(limits.max_config_bytes, settings.MAX_FEATURE_FLAG_FILTER_SIZE_BYTES),
        max_metadata_bytes=limits.max_metadata_bytes,
    )


def reject_duplicate_json_keys(body: bytes) -> None:
    """Reject request bytes that carry the same key twice at any depth.

    ``json.loads`` keeps the last of two duplicate keys, so a body the Rust parser rejects
    would otherwise reach the validator as a clean document and be persisted. Only the v2
    path calls this; v1 parsing, coercion and error behavior are untouched.
    """

    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ConfigValidationError(
                    [ConfigError(code="invalid", detail=f"Must not repeat the key {json.dumps(key)}.", attr="filters")]
                )
            result[key] = value
        return result

    try:
        json.loads(body, object_pairs_hook=object_pairs)
    except ConfigValidationError:
        raise
    except ValueError as exc:
        raise ConfigValidationError(
            [ConfigError(code="invalid", detail="Must not repeat a key.", attr="filters")]
        ) from exc


def resolve_identity(submitted: object, *, stored: Mapping[str, Any]) -> dict[str, Any]:
    """Return ``submitted`` with server-owned rule ids and seeds resolved against ``stored``.

    An echoed id keeps its rule's stored seed through reordering and unrelated edits; a
    rule that omits its id is new and gets fresh identity. Clients may round-trip identity
    but never choose it, so an unknown id, an id claimed twice, or a changed seed is
    rejected here rather than silently honoured — the last of those is an assignment reset,
    which is a separate operation nobody owns yet.

    The input is not modified, and nothing else is filled in: the result is the exact
    document that both the validator and the row will see.
    """
    if not isinstance(submitted, Mapping):
        raise ConfigValidationError([ConfigError(code="invalid", detail="Must be an object.", attr="filters")])
    rules = submitted.get("rules")
    if not isinstance(rules, list):
        return dict(submitted)  # not a document shape this module can resolve; the validator reports it

    stored_rules = {
        rule["id"]: rule
        for rule in (stored.get("rules") or [])
        if isinstance(rule, Mapping) and isinstance(rule.get("id"), str)
    }
    errors: list[ConfigError] = []
    claimed: set[str] = set()
    resolved = [
        _resolve_rule(rule, f"filters.rules[{index}]", stored_rules, claimed, errors)
        if isinstance(rule, Mapping)
        else rule
        for index, rule in enumerate(rules)
    ]
    if errors:
        raise ConfigValidationError(errors)
    return {**submitted, "rules": resolved}


def _resolve_rule(
    rule: Mapping[str, Any],
    path: str,
    stored_rules: Mapping[str, Mapping[str, Any]],
    claimed: set[str],
    errors: list[ConfigError],
) -> dict[str, Any]:
    resolved = dict(rule)
    current: Mapping[str, Any] | None = None
    if "id" not in rule:
        resolved["id"] = str(uuid4())
    elif not isinstance(rule["id"], str) or rule["id"] not in stored_rules:
        errors.append(
            ConfigError(
                code="invalid",
                detail="Rule ids are server-assigned; echo one this flag already has or omit the field.",
                attr=f"{path}.id",
            )
        )
    elif rule["id"] in claimed:
        errors.append(ConfigError(code="not_unique", detail="Used by another rule.", attr=f"{path}.id"))
    else:
        claimed.add(rule["id"])
        current = stored_rules[rule["id"]]

    if rule.get("rule_type") != _SEEDED_RULE_TYPE:
        # A rule that is not randomized carries no seed; changing type away from a rollout
        # drops it, and changing type towards one allocates a fresh one below.
        return resolved
    stored_seed = current.get("seed") if current is not None and current.get("rule_type") == _SEEDED_RULE_TYPE else None
    if not isinstance(stored_seed, str):
        if "seed" in rule:
            errors.append(
                ConfigError(code="invalid", detail="Assignment seeds are server-assigned.", attr=f"{path}.seed")
            )
        resolved["seed"] = str(uuid4())
    elif "seed" not in rule or rule["seed"] == stored_seed:
        resolved["seed"] = stored_seed
    else:
        errors.append(
            ConfigError(
                code="invalid",
                detail="Cannot be changed; resetting assignment is a separate operation.",
                attr=f"{path}.seed",
            )
        )
    return resolved


def review_update(
    document: object, *, stored: Mapping[str, Any], limits: ValidationLimits
) -> tuple[ManagementWarning, ...]:
    """Validate the candidate against the stored document it replaces; raise on either.

    A stored document this milestone cannot validate is rejected rather than overwritten:
    replacing it with a generic admitted document would erase semantics no detector here
    can judge.
    """
    try:
        # Stored rows may predate lower byte caps; validate their semantics without
        # preventing a replacement that brings them back within the write limits.
        current = validate_config(
            stored, limits=ValidationLimits(max_config_bytes=sys.maxsize, max_metadata_bytes=sys.maxsize)
        )
    except ConfigValidationError as exc:
        raise ConfigValidationError(
            [
                ConfigError(
                    code="unsupported",
                    detail="This flag's stored configuration cannot be updated through this API.",
                    attr="filters",
                )
            ]
        ) from exc
    return review_config(document, limits=limits, current=current).warnings
