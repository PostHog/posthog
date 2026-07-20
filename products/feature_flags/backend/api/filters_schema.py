"""Structural validation for the `FeatureFlag.filters` JSON (issue #50084, structural tier).

This is the runtime Python mirror of the Rust flag structs — the shapes here must stay in
sync with `rust/feature-flags/src/flags/flag_models.rs` (`FlagFilters`, `FlagPropertyGroup`,
`MultivariateFlagVariant`, `Holdout`) and `rust/feature-flags/src/properties/property_models.rs`
(`PropertyFilter`, `OperatorType`, `PropertyType`). A stored filters value that fails serde in
Rust poisons the whole team's flag cache, so these serializers reject exactly what serde would
reject: no DRF type coercion (`"true"` is not a bool, `"42"` is not an int, `NaN` is not a
valid rollout percentage).

Modeled on the OpenAPI-only `FeatureFlagFiltersSchemaSerializer` in `posthog/api/documentation.py`
(which can't validate at runtime — it relies on `PolymorphicProxySerializer`). Not wired into
`FeatureFlagSerializer` yet: enforcement lands in a later phase, gated on the `audit_flag_filters`
management command reporting zero violations.

Phase 3 wiring notes:
- When `feature_flag.py` starts importing this module, move `FEATURE_FLAG_SUPPORTED_OPERATORS`
  and `FEATURE_FLAG_OPERATOR_ALIASES` here and re-export from `feature_flag.py` to avoid an
  import cycle.
- `type` and `operator` are collision-prone enum field names for drf-spectacular; before wiring
  this serializer into `@extend_schema`, run `python manage.py find_enum_collisions` and add
  `ENUM_NAME_OVERRIDES` entries as needed.
"""

import json
import math
from collections.abc import Mapping, Sequence
from typing import Any, ClassVar, Protocol, cast

import structlog
from rest_framework import serializers

from products.feature_flags.backend.api.feature_flag import (
    FEATURE_FLAG_OPERATOR_ALIASES,
    FEATURE_FLAG_SUPPORTED_OPERATORS,
)

logger = structlog.get_logger(__name__)

# The Rust PropertyType enum also accepts "person_metadata"; the locked inventory in #50084
# deliberately excludes it. If the audit shows stored flags using it, amend the inventory in
# the issue thread before adding it here.
FEATURE_FLAG_PROPERTY_TYPES: tuple[str, ...] = ("person", "cohort", "group", "flag")

FEATURE_FLAG_OPERATOR_CHOICES: list[str] = sorted(op for op in FEATURE_FLAG_SUPPORTED_OPERATORS if op is not None)

# Legacy keys that predate `holdout`; stored flags still carry them and read-modify-write
# clients echo them back, so dropping them is expected and not worth a log line.
LEGACY_UNKNOWN_FILTER_KEYS: frozenset[str] = frozenset({"holdout_groups", "super_groups"})


class UnknownKeySink(Protocol):
    def record(self, *, level: str, keys: Sequence[str], flag_id: int | None) -> None: ...


def _record_dropped_unknown_keys(level: str, keys: Sequence[str], context: Mapping[str, Any]) -> None:
    sink: UnknownKeySink | None = context.get("unknown_keys_sink")
    flag_id: int | None = context.get("flag_id")
    if sink is not None:
        sink.record(level=level, keys=keys, flag_id=flag_id)
        return
    non_legacy = [key for key in keys if level != "filters" or key not in LEGACY_UNKNOWN_FILTER_KEYS]
    if non_legacy:
        logger.warning(
            "feature_flag_filters_unknown_keys_dropped",
            level=level,
            keys=non_legacy,
            flag_id=flag_id,
        )


class DropsUnknownKeysMixin:
    """DRF drops keys without a declared field silently; this makes the drop observable.

    During an audit run an `unknown_keys_sink` in the serializer context collects them;
    otherwise non-legacy unknown keys are logged so we learn whether junk keys happen in
    the wild before enforcement flips on.
    """

    unknown_key_level: ClassVar[str]

    def to_internal_value(self, data: Any) -> Any:
        if isinstance(data, dict):
            serializer = cast(serializers.Serializer, self)
            unknown_keys = sorted(set(data) - set(serializer.fields))
            if unknown_keys:
                _record_dropped_unknown_keys(self.unknown_key_level, unknown_keys, serializer.context)
        return super().to_internal_value(data)  # type: ignore[misc]


class StrictCharField(serializers.CharField):
    """CharField without cross-type coercion: Rust `String` fields reject JSON numbers."""

    def __init__(self, **kwargs: Any) -> None:
        # Validate, don't mutate: stored values must round-trip unchanged.
        kwargs.setdefault("trim_whitespace", False)
        super().__init__(**kwargs)

    def to_internal_value(self, data: Any) -> str:
        if not isinstance(data, str):
            self.fail("invalid")
        return super().to_internal_value(data)


class StrictBooleanField(serializers.BooleanField):
    """BooleanField without coercion: Rust `Option<bool>` rejects "true", 1, etc."""

    def to_internal_value(self, data: Any) -> bool:
        if not isinstance(data, bool):
            self.fail("invalid", input=data)
        return data


class StrictIntegerField(serializers.IntegerField):
    """IntegerField without coercion: Rust `i32`/`i64` reject "42", 42.0, and bools."""

    def to_internal_value(self, data: Any) -> int:
        if isinstance(data, bool) or not isinstance(data, int):
            self.fail("invalid")
        return data


class FiniteFloatField(serializers.FloatField):
    """FloatField that rejects bools, numeric strings, and non-finite values.

    JSON parsed with stdlib `json.loads` can contain NaN/Infinity tokens, which compare
    False against min_value/max_value and then crash percentage math downstream.
    """

    def to_internal_value(self, data: Any) -> float:
        if isinstance(data, bool) or not isinstance(data, (int, float)):
            self.fail("invalid")
        value = float(data)
        if not math.isfinite(value):
            self.fail("invalid")
        return value


class FlagPayloadsField(serializers.DictField):
    """Payloads stay lenient at the edge: any JSON value is accepted and normalized to a
    JSON-encoded string, so everything past this boundary (cross-field validators, storage,
    the Rust service) only ever sees JSON-encoded strings. Mirrors the normalization in
    `FeatureFlagSerializer.validate_filters`; tightening the public contract to
    strings-only would be a breaking change and is out of scope for #50084.
    """

    def to_internal_value(self, data: Any) -> dict[str, str]:
        if not isinstance(data, dict):
            self.fail("not_a_dict", input_type=type(data).__name__)
        normalized: dict[str, str] = {}
        errors: list[str] = []
        for key, value in data.items():
            try:
                if isinstance(value, str):
                    # An incoming string is already the canonical stored form; just check it parses.
                    json.loads(value)
                    normalized[key] = value
                else:
                    normalized[key] = json.dumps(value)
            except json.JSONDecodeError:
                errors.append(f"Payload for key '{key}' is not valid JSON.")
            except (TypeError, ValueError):
                errors.append(f"Payload for key '{key}' could not be serialized to JSON.")
        if errors:
            # Flat (not keyed by payload key) so the audit's rule id stays stable instead of
            # exploding per variant key.
            raise serializers.ValidationError(errors, code="invalid_payload_json")
        return normalized


class FlagPropertySerializer(DropsUnknownKeysMixin, serializers.Serializer):
    unknown_key_level = "property"

    key = StrictCharField(help_text="Property key used in this feature flag condition.")
    value = serializers.JSONField(
        required=False,
        allow_null=True,
        # Deliberately any JSON value: which shapes are valid depends on `operator`, and that
        # dependency is enforced in the cross-field tier (filters_validation.py), not here.
        help_text="Comparison value for the property filter. Valid shapes depend on the operator.",
    )
    type = serializers.ChoiceField(
        choices=FEATURE_FLAG_PROPERTY_TYPES,
        help_text="Property filter type. One of 'person', 'cohort', 'group', or 'flag'.",
    )
    operator = serializers.ChoiceField(
        choices=FEATURE_FLAG_OPERATOR_CHOICES,
        required=False,
        allow_null=True,
        help_text="Operator used to compare the property value. Null means exact match.",
    )
    group_type_index = StrictIntegerField(
        required=False,
        allow_null=True,
        help_text="Group type index when using group-based filters.",
    )
    negation = StrictBooleanField(
        required=False,
        allow_null=True,
        help_text="Whether the property condition is negated.",
    )

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        # Canonicalize operator aliases before field validation so everything downstream
        # (the operator ChoiceField, cross-field validators, storage) only ever sees
        # canonical operators.
        if isinstance(data, dict) and data.get("operator") in FEATURE_FLAG_OPERATOR_ALIASES:
            data = {**data, "operator": FEATURE_FLAG_OPERATOR_ALIASES[data["operator"]]}
        return super().to_internal_value(data)


class FlagConditionGroupSerializer(DropsUnknownKeysMixin, serializers.Serializer):
    unknown_key_level = "group"

    properties = FlagPropertySerializer(
        many=True,
        required=False,
        default=list,
        help_text="Property conditions for this release condition group.",
    )
    rollout_percentage = FiniteFloatField(
        min_value=0,
        max_value=100,
        required=False,
        allow_null=True,
        help_text="Rollout percentage for this release condition group, between 0 and 100.",
    )
    variant = StrictCharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Variant key override for multivariate flags.",
    )
    # No default here: an absent key falls back to the flag-level aggregation while an explicit
    # null means person aggregation (Rust models this as Option<Option<i32>>). Injecting a
    # default would erase that distinction.
    aggregation_group_type_index = StrictIntegerField(
        required=False,
        allow_null=True,
        help_text="Group type index for this condition set. Null means person-level aggregation; "
        "absent falls back to the flag-level value.",
    )


class FlagMultivariateVariantSerializer(serializers.Serializer):
    key = StrictCharField(help_text="Unique key for this variant.")
    name = StrictCharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Human-readable name for this variant.",
    )
    rollout_percentage = FiniteFloatField(
        min_value=0,
        max_value=100,
        help_text="Variant rollout percentage, between 0 and 100.",
    )


class FlagMultivariateSerializer(serializers.Serializer):
    variants = FlagMultivariateVariantSerializer(
        many=True,
        allow_empty=False,
        help_text="Variant definitions for multivariate feature flags.",
    )


class FlagHoldoutSerializer(serializers.Serializer):
    id = StrictIntegerField(help_text="ID of the experiment holdout this flag belongs to.")
    exclusion_percentage = FiniteFloatField(
        min_value=0,
        max_value=100,
        help_text="Percentage of users held out from the flag, between 0 and 100.",
    )


class FeatureFlagFiltersSerializer(DropsUnknownKeysMixin, serializers.Serializer):
    unknown_key_level = "filters"

    groups = FlagConditionGroupSerializer(
        many=True,
        required=False,
        default=list,
        help_text="Release condition groups for the feature flag.",
    )
    multivariate = FlagMultivariateSerializer(
        required=False,
        allow_null=True,
        help_text="Multivariate configuration for variant-based rollouts.",
    )
    aggregation_group_type_index = StrictIntegerField(
        required=False,
        allow_null=True,
        help_text="Group type index for group-based feature flags. Null means person-level aggregation.",
    )
    payloads = FlagPayloadsField(
        required=False,
        help_text="Payloads keyed by variant key (multivariate flags) or 'true' (boolean flags). "
        "Values are stored as JSON-encoded strings; non-string JSON values are normalized on write.",
    )
    feature_enrollment = StrictBooleanField(
        required=False,
        allow_null=True,
        help_text="Whether this flag has early access feature enrollment enabled. When true, the flag "
        "is evaluated against the person property $feature_enrollment/{flag_key}.",
    )
    holdout = FlagHoldoutSerializer(
        required=False,
        allow_null=True,
        help_text="Experiment holdout configuration for this flag.",
    )
    # Addendum to the locked #50084 inventory: `early_exit` exists in the Rust FlagFilters struct
    # and is already type-checked in validate_filters, so it must be a declared field here or
    # enforcement would silently drop it. Shape only — the org-level gating on enabling it is
    # contextual tier and stays in FeatureFlagSerializer.
    early_exit = StrictBooleanField(
        required=False,
        allow_null=True,
        help_text="When true, condition evaluation stops at the first matching condition set rather "
        "than continuing to evaluate subsequent groups.",
    )
