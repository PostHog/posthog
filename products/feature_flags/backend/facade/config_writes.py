"""Writer admission and server-owned identity for config version 2 writes.

Three things a v2 write needs that the pure validator deliberately does not do:

- **Admission.** ``v2_write_limits`` and ``v2_creation_enabled`` are the writer policy: two
  internal feature flags evaluated for the project, both off by default. Nothing else grants
  admission. Disabling and soft-deleting an existing v2 row need neither, which the serializer
  decides; the operation matrix is in ``docs/internal/feature-flags/api-writes.md``.
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

from posthog.ph_client import feature_enabled_or_false

from products.feature_flags.backend.facade.config_validation import (
    ConfigError,
    ConfigValidationError,
    ValidatedConfig,
    ValidationLimits,
    validate_config,
)
from products.feature_flags.backend.facade.rule_warnings import review_config
from products.feature_flags.backend.facade.warnings import ManagementWarning

_SEEDED_RULE_TYPE = "percentage_rollout"

# Internal feature flags, targeted at the ``project`` group by id. Both off means closed.
V2_WRITES_FLAG = "feature-flag-rules-v2-writes"
V2_CREATION_FLAG = "feature-flag-rules-v2-creation"


def _flag_enabled(key: str, team_id: int) -> bool:
    # Local evaluation only: a write path must not wait on a remote flag call, and an
    # unresolved flag (client not loaded yet, unsupported condition) reads as closed.
    try:
        return feature_enabled_or_false(
            key,
            f"team-{team_id}",
            groups={"project": str(team_id)},
            group_properties={"project": {"id": str(team_id)}},
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
    except Exception:
        return False


def v2_write_limits(team_id: int) -> ValidationLimits | None:
    """Trusted limits for a v2 write on ``team_id``'s flags, or ``None`` when the project is not admitted.

    Admission is the ``feature-flag-rules-v2-writes`` flag for the project alone: no request
    field, serializer context flag, staff status or missing user opens it.

    ``max_config_bytes`` is the deployment filter-size limit the v1 write path and the Rust
    reader both enforce. ``max_metadata_bytes`` is pilot scope: its default is sized for the
    known pilot documents and is revisited at the shared-project gate, before users author
    documents through the editor or broader API use.
    """
    if not _flag_enabled(V2_WRITES_FLAG, team_id):
        return None
    return ValidationLimits(
        max_config_bytes=settings.MAX_FEATURE_FLAG_FILTER_SIZE_BYTES,
        max_metadata_bytes=settings.FEATURE_FLAG_RULES_V2_MAX_METADATA_BYTES,
    )


def v2_creation_enabled(team_id: int) -> bool:
    """Whether ``team_id`` may create a new v2 flag: both the writes and the creation flag are on.

    Turning the creation flag off leaves existing rows updatable and enableable in admitted projects.
    """
    return _flag_enabled(V2_CREATION_FLAG, team_id) and _flag_enabled(V2_WRITES_FLAG, team_id)


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
    can judge. An empty ``stored`` is a create, which has no current document to compare.
    """
    # Stored rows may predate lower byte caps; validate their semantics without
    # preventing a replacement that brings them back within the write limits.
    unbounded = ValidationLimits(max_config_bytes=sys.maxsize, max_metadata_bytes=sys.maxsize)
    current = _validated_stored(stored, limits=unbounded, operation="updated") if stored else None
    return review_config(document, limits=limits, current=current).warnings


def validate_stored(stored: Mapping[str, Any], *, limits: ValidationLimits) -> None:
    """Reject enabling a stored document that no longer validates under the current limits.

    Enabling is what makes the document reachable by evaluation, so a row written under an
    older contract or a larger byte limit must be edited back into validity first.
    """
    _validated_stored(stored, limits=limits, operation="enabled")


def _validated_stored(stored: Mapping[str, Any], *, limits: ValidationLimits, operation: str) -> ValidatedConfig:
    try:
        return validate_config(stored, limits=limits)
    except ConfigValidationError as exc:
        detail = f"This flag's stored configuration cannot be {operation} through this API."
        raise ConfigValidationError([ConfigError(code="unsupported", detail=detail, attr="filters")]) from exc
