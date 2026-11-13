"""The feature flag config input that an experiment write accepts."""

from copy import deepcopy
from typing import Any

from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from posthog.api.documentation import FeatureFlagFiltersSchemaSerializer


def _normalized_flag_variants(variants: list) -> list:
    """Returns a new list, leaving the caller's input (e.g. request.data) untouched."""
    variants = deepcopy(variants)
    # Normalize a case-insensitive 'control' key (e.g. 'Control', 'CONTROL') down
    # to lowercase 'control'. 'control' is the conventional baseline key (the default
    # baseline when present), and a typo in casing was the leading cause of the
    # "Feature flag variants must contain a control variant" error in MCP traces —
    # most often from LLM-generated payloads. Only rewrite when no exact 'control'
    # match already exists, so we never collapse two distinct keys into a duplicate.
    existing_keys = {v.get("key") for v in variants if isinstance(v, dict)}
    if "control" not in existing_keys:
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            key = variant.get("key")
            if isinstance(key, str) and key != "control" and key.lower() == "control":
                variant["key"] = "control"
                break
    for variant in variants:
        if isinstance(variant, dict) and "split_percent" in variant:
            # split_percent wins in case both keys present, as rollout_percentage deprecated
            variant["rollout_percentage"] = variant.pop("split_percent")
    return variants


class _StrictFieldsMixin:
    """Reject unknown keys instead of silently dropping them (DRF's default).

    Applying half a validated object (taking the keys we know, ignoring the rest) would leave the
    flag in a state the caller never asked for, so the experiment feature_flag input rejects any
    key it doesn't recognize.
    """

    fields: Any

    def to_internal_value(self, data: Any) -> Any:
        if isinstance(data, dict):
            unknown = sorted(set(data) - set(self.fields))
            if unknown:
                raise ValidationError(dict.fromkeys(unknown, "Unsupported key for the experiment feature_flag input."))
        return super().to_internal_value(data)  # type: ignore[misc]


class ExperimentFlagVariantSerializer(serializers.Serializer):
    """A single multivariate variant. Extra per-variant keys are dropped."""

    key = serializers.CharField(
        help_text="Unique variant key. The baseline defaults to the variant keyed 'control' when present, else the first variant."
    )
    name = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Human-readable variant name.",
    )
    rollout_percentage = serializers.IntegerField(
        min_value=0,
        max_value=100,
        help_text="Variant rollout percentage (0-100). Across variants these must sum to 100.",
    )


class ExperimentFlagMultivariateSerializer(_StrictFieldsMixin, serializers.Serializer):
    """Multivariate config for the experiment's feature flag."""

    variants = ExperimentFlagVariantSerializer(
        many=True,
        help_text="Variant definitions (2 to 20). The baseline defaults to the variant keyed 'control' when present, else the first variant.",
    )

    def to_internal_value(self, data: Any) -> Any:
        # Normalize before per-variant validation so the case-insensitive 'control' rewrite and the
        # deprecated split_percent -> rollout_percentage translation happen before the strict child
        # serializer sees the variants (the child accepts only rollout_percentage).
        if isinstance(data, dict) and isinstance(data.get("variants"), list):
            data = {**data, "variants": _normalized_flag_variants(data["variants"])}
        return super().to_internal_value(data)


class ExperimentFlagRolloutGroupSerializer(_StrictFieldsMixin, serializers.Serializer):
    """A single release-condition group carrying only the overall rollout percentage, the one
    groups entry the experiment input applies."""

    rollout_percentage = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=0,
        max_value=100,
        help_text="Percentage of users who enter the experiment (0-100).",
    )
    properties = serializers.ListField(
        child=serializers.JSONField(),
        required=False,
        max_length=0,
        help_text=(
            "Must be empty or omitted: release-condition properties are not supported via the "
            "experiment input. Edit the feature flag directly for targeting."
        ),
    )


# Subclassing the flag's canonical filters schema (rather than redeclaring the shape) keeps the
# experiment write surface from drifting when the flag filters schema changes. Strict field
# handling rejects filters keys experiments don't apply.
class ExperimentFeatureFlagFiltersSerializer(_StrictFieldsMixin, FeatureFlagFiltersSchemaSerializer):
    """Feature-flag filters accepted by the experiment endpoints: the flag's own filters shape,
    minus the keys experiments don't apply."""

    # DRF's declarative field removal: assigning None drops the inherited field.
    feature_enrollment = None  # type: ignore[assignment]
    early_exit = None  # type: ignore[assignment]
    # The runtime applies only groups[0].rollout_percentage and rejects release conditions, so
    # advertise exactly that instead of the flag's full condition-group schema. The full schema
    # would invite payloads (property filters, variant overrides, multiple groups) that always
    # fail validation, and it adds ~10KB to each generated MCP tool schema.
    groups = ExperimentFlagRolloutGroupSerializer(  # type: ignore[assignment,call-arg]
        many=True,
        required=False,
        max_length=1,
        help_text='Overall rollout as a single group: [{"properties": [], "rollout_percentage": N}].',
    )
    multivariate = ExperimentFlagMultivariateSerializer(  # type: ignore[assignment]
        required=False,
        allow_null=True,
        help_text="Multivariate variant configuration.",
    )


class ExperimentFeatureFlagInputSerializer(_StrictFieldsMixin, serializers.Serializer):
    """Flag config for experiment create/update, sent through the linked feature flag's own shape.

    Validated both as the OpenAPI request field (via ``ExperimentWriteSerializer``) and at runtime
    (``ExperimentSerializer._normalize_feature_flag_input`` runs it against the raw feature_flag
    object). Echoed read-only flag objects (carrying a non-null id) are handled upstream and never
    reach this validation.
    """

    filters = ExperimentFeatureFlagFiltersSerializer(
        required=False,
        help_text=(
            "Flag config to apply: `multivariate.variants` (2 to 20 variants; the baseline defaults to "
            "the variant keyed 'control' when present, else the first variant), "
            "`groups` (a single group with `rollout_percentage` only; release "
            "conditions are not supported here, edit the feature flag directly), "
            "`aggregation_group_type_index`, and `payloads` (JSON-encoded strings keyed by variant key). "
            "On update, config this object omits is preserved from the linked flag's current state."
        ),
    )
    ensure_experience_continuity = serializers.BooleanField(
        required=False,
        allow_null=True,
        help_text="Whether the flag persists variant assignment across authentication steps.",
    )
