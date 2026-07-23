"""Structural validation for the `FeatureFlag.filters` JSON (issue #50084, structural tier).

This is the runtime Python mirror of the Rust flag structs — the shapes here must stay in
sync with `rust/feature-flags/src/flags/flag_models.rs` (`FlagFilters`, `FlagPropertyGroup`,
`MultivariateFlagVariant`, `Holdout`) and `rust/feature-flags/src/properties/property_models.rs`
(`PropertyFilter`, `OperatorType`, `PropertyType`). A stored filters value that fails serde in
Rust poisons the whole team's flag cache, so these serializers reject exactly what serde would
reject: no DRF type coercion (`"true"` is not a bool, `"42"` is not an int, `NaN` is not a
valid rollout percentage).

Modeled on the OpenAPI-only `FeatureFlagFiltersSchemaSerializer` in `posthog/api/documentation.py`
(which can't validate at runtime — it relies on `PolymorphicProxySerializer`). The two are meant
to converge: once this serializer is wired into `FeatureFlagSerializer` (phase 3 of #50084), it
becomes the OpenAPI source of truth and the documentation.py one is retired. Not wired in yet:
enforcement is gated on the `audit_flag_filters` management command reporting zero violations.

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

# Rust i32 / i64 bounds. Integers outside these ranges pass Python validation but fail serde
# deserialization — exactly the cache-poisoning class this module exists to stop.
I32_MIN, I32_MAX = -(2**31), 2**31 - 1
I64_MIN, I64_MAX = -(2**63), 2**63 - 1


# Serializer-context keys shared with the audit command; constants so a typo on either side
# fails loudly at import instead of silently under-reporting unknown keys.
UNKNOWN_KEYS_SINK_CONTEXT_KEY = "unknown_keys_sink"
FLAG_ID_CONTEXT_KEY = "flag_id"


class UnknownKeySink(Protocol):
    def record(self, *, level: str, keys: Sequence[str], flag_id: int | None) -> None: ...


def is_legacy_unknown_key(level: str, key: str) -> bool:
    return level == "filters" and key in LEGACY_UNKNOWN_FILTER_KEYS


def _record_dropped_unknown_keys(level: str, keys: Sequence[str], context: Mapping[str, Any]) -> None:
    sink: UnknownKeySink | None = context.get(UNKNOWN_KEYS_SINK_CONTEXT_KEY)
    flag_id: int | None = context.get(FLAG_ID_CONTEXT_KEY)
    if sink is not None:
        sink.record(level=level, keys=keys, flag_id=flag_id)
        return
    non_legacy = [key for key in keys if not is_legacy_unknown_key(level, key)]
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
    """IntegerField without coercion: Rust `i32`/`i64` reject "42", 42.0, and bools.

    min_value/max_value are enforced by DRF's validators, which run after this method.
    """

    def to_internal_value(self, data: Any) -> int:
        if isinstance(data, bool) or not isinstance(data, int):
            self.fail("invalid")
        return data


class PropertyKeyField(serializers.CharField):
    """Property keys are strings, but JSON numbers are accepted and normalized to strings.

    Mirrors Rust's `deserialize_key` on `PropertyFilter.key`: flag-dependency keys are flag
    IDs and the API has persisted them as raw JSON numbers, so serde accepts both forms and
    normalizes to a string. Rejecting numbers here would flag stored data that evaluates fine
    and would 400 read-modify-write PATCHes that echo it back.
    """

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("trim_whitespace", False)
        super().__init__(**kwargs)

    def to_internal_value(self, data: Any) -> str:
        if isinstance(data, bool):
            self.fail("invalid")
        if isinstance(data, int) or (isinstance(data, float) and math.isfinite(data)):
            data = str(data)
        if not isinstance(data, str):
            self.fail("invalid")
        return super().to_internal_value(data)


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


def _reject_json_constant(name: str) -> None:
    raise ValueError(f"non-RFC JSON constant {name}")


class FlagPayloadsField(serializers.DictField):
    """Payloads stay lenient at the edge: any JSON value is accepted and normalized to a
    JSON-encoded string, so everything past this boundary (cross-field validators, storage,
    the Rust service) only ever sees JSON-encoded strings. Mirrors the normalization in
    `FeatureFlagSerializer.validate_filters`; tightening the public contract to
    strings-only would be a breaking change and is out of scope for #50084.

    One deliberate divergence from the live normalization: NaN/Infinity are rejected. stdlib
    json accepts them, but they produce non-RFC payload strings that strict parsers
    (serde_json, SDK JSON.parse) fail on.
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
                    json.loads(value, parse_constant=_reject_json_constant)
                    normalized[key] = value
                else:
                    normalized[key] = json.dumps(value, allow_nan=False)
            except json.JSONDecodeError:
                errors.append(f"Payload for key '{key}' is not valid JSON.")
            except (TypeError, ValueError):
                errors.append(f"Payload for key '{key}' is not valid strict JSON (NaN/Infinity not allowed).")
        if errors:
            # Flat (not keyed by payload key) so the audit's rule id stays stable instead of
            # exploding per variant key.
            raise serializers.ValidationError(errors, code="invalid_payload_json")
        return normalized


class FlagPropertySerializer(DropsUnknownKeysMixin, serializers.Serializer):
    unknown_key_level = "property"

    key = PropertyKeyField(
        help_text="Property key used in this feature flag condition. Numbers are normalized to strings."
    )
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
        min_value=I32_MIN,
        max_value=I32_MAX,
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
        # canonical operators. The isinstance guard matters: an unhashable operator (list/dict
        # in stored junk) would raise TypeError on the dict lookup instead of failing cleanly
        # in the ChoiceField.
        operator = data.get("operator") if isinstance(data, dict) else None
        if isinstance(operator, str) and operator in FEATURE_FLAG_OPERATOR_ALIASES:
            data = {**data, "operator": FEATURE_FLAG_OPERATOR_ALIASES[operator]}
        return super().to_internal_value(data)


class FlagConditionGroupSerializer(DropsUnknownKeysMixin, serializers.Serializer):
    unknown_key_level = "group"

    # allow_null: Rust reads properties as Option<Vec<PropertyFilter>> with #[serde(default)],
    # so an explicit JSON null deserializes fine (treated like absent) and must not audit as
    # a violation.
    properties = FlagPropertySerializer(
        many=True,
        required=False,
        allow_null=True,
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
        min_value=I32_MIN,
        max_value=I32_MAX,
        required=False,
        allow_null=True,
        help_text="Group type index for this condition set. Null means person-level aggregation; "
        "absent falls back to the flag-level value.",
    )

    def validate_properties(self, value: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        # Null means "no properties" (Rust treats it like absent); normalize so cross-field
        # checks can iterate without a None guard.
        return value if value is not None else []


class FlagMultivariateVariantSerializer(DropsUnknownKeysMixin, serializers.Serializer):
    unknown_key_level = "variant"

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


class FlagMultivariateSerializer(DropsUnknownKeysMixin, serializers.Serializer):
    unknown_key_level = "multivariate"

    variants = FlagMultivariateVariantSerializer(
        many=True,
        allow_empty=False,
        help_text="Variant definitions for multivariate feature flags.",
    )


class FlagHoldoutSerializer(DropsUnknownKeysMixin, serializers.Serializer):
    unknown_key_level = "holdout"

    id = StrictIntegerField(
        min_value=I64_MIN,
        max_value=I64_MAX,
        help_text="ID of the experiment holdout this flag belongs to.",
    )
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
        min_value=I32_MIN,
        max_value=I32_MAX,
        required=False,
        allow_null=True,
        help_text="Group type index for group-based feature flags. Null means person-level aggregation.",
    )
    # allow_null: Rust reads payloads as Option<serde_json::Value>, so stored `payloads: null`
    # evaluates fine and must not audit as a violation (the live write path rejects null, but
    # that is contextual strictness, not serde fidelity).
    payloads = FlagPayloadsField(
        required=False,
        allow_null=True,
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
