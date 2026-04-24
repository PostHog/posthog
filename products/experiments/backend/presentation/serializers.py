"""
Presentation serializers for experiments product.

These serializers handle HTTP request/response conversion and validation,
converting between JSON/HTTP and facade DTOs.
"""

from rest_framework import serializers

from posthog.models.feature_flag.feature_flag import FeatureFlag

from products.experiments.backend.facade.contracts import (
    CreateExperimentInput,
    CreateFeatureFlagInput,
    FeatureFlagVariant,
)


class FeatureFlagVariantSerializer(serializers.Serializer):
    """Serializer for feature flag variant."""

    key = serializers.CharField(required=True, help_text="Unique key for the variant")
    name = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, help_text="Display name for the variant"
    )
    rollout_percentage = serializers.IntegerField(
        required=True, min_value=0, max_value=100, help_text="Percentage of users to assign to this variant"
    )

    def to_dto(self) -> FeatureFlagVariant:
        """Convert validated data to DTO."""
        return FeatureFlagVariant(
            key=self.validated_data["key"],
            split_percent=self.validated_data["rollout_percentage"],
            name=self.validated_data.get("name") or None,
        )


class CreateFeatureFlagInputSerializer(serializers.Serializer):
    """Serializer for new feature flag creation data."""

    key = serializers.CharField(required=True, help_text="Unique key for the feature flag")
    name = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, help_text="Display name for the feature flag"
    )
    variants = FeatureFlagVariantSerializer(
        many=True, required=True, help_text="List of variants for the multivariate flag"
    )
    rollout_percentage = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=0,
        max_value=100,
        help_text="Percentage of users to include in the experiment",
    )
    aggregation_group_type_index = serializers.IntegerField(
        required=False, allow_null=True, help_text="Group type index for group-based experiments"
    )
    ensure_experience_continuity = serializers.BooleanField(
        required=False, allow_null=True, help_text="Whether to ensure users see consistent variants"
    )

    def validate_variants(self, value):
        """Validate variants list."""
        if not value or len(value) < 2:
            raise serializers.ValidationError(
                "Feature flag must have at least 2 variants (control and at least one test variant)"
            )

        if len(value) >= 21:
            raise serializers.ValidationError("Feature flag variants must be less than 21")

        # Check for control variant
        variant_keys = [variant["key"] for variant in value]
        if "control" not in variant_keys:
            raise serializers.ValidationError("Feature flag variants must contain a control variant")

        # Check for duplicate variant keys
        if len(variant_keys) != len(set(variant_keys)):
            raise serializers.ValidationError("Feature flag variant keys must be unique")

        # Validate rollout percentages sum to 100
        total_percentage = sum(variant.get("rollout_percentage", 0) for variant in value)
        if total_percentage != 100:
            raise serializers.ValidationError(f"Variant rollout percentages must sum to 100, got {total_percentage}")

        return value

    def to_dto(self) -> CreateFeatureFlagInput:
        """Convert validated data to DTO."""
        # Build DTOs directly from already-validated data
        variant_dtos = [
            FeatureFlagVariant(
                key=v["key"],
                split_percent=v["rollout_percentage"],
                name=v.get("name") or None,
            )
            for v in self.validated_data["variants"]
        ]

        return CreateFeatureFlagInput(
            key=self.validated_data["key"],
            name=self.validated_data.get("name") or None,
            variants=tuple(variant_dtos),
            rollout_percentage=self.validated_data.get("rollout_percentage"),
            aggregation_group_type_index=self.validated_data.get("aggregation_group_type_index"),
            ensure_experience_continuity=self.validated_data.get("ensure_experience_continuity"),
        )


class ExperimentCreateSerializer(serializers.Serializer):
    """
    Serializer for experiment creation.

    Supports both old format (parameters.feature_flag_variants)
    and new format (feature_flag_filters).
    """

    name = serializers.CharField(required=True, help_text="Name of the experiment")
    feature_flag_key = serializers.CharField(
        required=True, help_text="Key of the feature flag (existing or to be created)"
    )
    description = serializers.CharField(
        required=False, default="", allow_blank=True, help_text="Description of the experiment"
    )
    parameters = serializers.JSONField(
        required=False,
        allow_null=True,
        help_text="[Deprecated] Old format for experiment parameters including feature_flag_variants",
    )
    feature_flag_filters = CreateFeatureFlagInputSerializer(
        required=False, allow_null=True, help_text="New format for feature flag configuration"
    )

    def validate_feature_flag_key(self, value):
        """Validate feature flag key."""
        if not value:
            raise serializers.ValidationError("Feature flag key is required")

        # Check if feature flag already exists for this team
        get_team = self.context.get("get_team")
        if get_team is None:
            # If no team context, skip this validation (will fail elsewhere)
            return value

        team = get_team()
        if FeatureFlag.objects.filter(key=value, team=team).exists():
            raise serializers.ValidationError(
                f"Feature flag with key '{value}' already exists for this team. "
                "Please use a different key or update the existing flag."
            )

        return value

    def validate_parameters(self, value):
        """Validate old format parameters."""
        if not value:
            return value

        variants = value.get("feature_flag_variants", [])

        if len(variants) > 0:
            if len(variants) < 2:
                raise serializers.ValidationError(
                    "Feature flag must have at least 2 variants (control and at least one test variant)"
                )
            if len(variants) >= 21:
                raise serializers.ValidationError("Feature flag variants must be less than 21")

            variant_keys = [variant["key"] for variant in variants]
            if "control" not in variant_keys:
                raise serializers.ValidationError("Feature flag variants must contain a control variant")

            # Check for duplicate variant keys
            if len(variant_keys) != len(set(variant_keys)):
                raise serializers.ValidationError("Feature flag variant keys must be unique")

            # Validate rollout percentages sum to 100
            total_percentage = sum(variant.get("rollout_percentage", 0) for variant in variants)
            if total_percentage != 100:
                raise serializers.ValidationError(
                    f"Variant rollout percentages must sum to 100, got {total_percentage}"
                )

        return value

    def validate(self, attrs):
        """Cross-field validation."""
        has_parameters = attrs.get("parameters") is not None and "feature_flag_variants" in attrs.get("parameters", {})
        has_feature_flag_filters = attrs.get("feature_flag_filters") is not None

        # Cannot provide both formats
        if has_parameters and has_feature_flag_filters:
            raise serializers.ValidationError(
                "Cannot provide both 'parameters.feature_flag_variants' and 'feature_flag_filters'. "
                "Please use only one format."
            )

        # Must provide at least one format (for experiments that create new flags)
        # Note: If neither is provided, the facade will use default variants
        # This is intentionally permissive to allow minimal experiment creation

        return attrs

    def to_facade_dto(self) -> CreateExperimentInput:
        """Convert validated data to facade DTO."""
        feature_flag_filters_dto = None
        if self.validated_data.get("feature_flag_filters"):
            # validated_data already contains the deserialized nested dict
            flag_serializer = CreateFeatureFlagInputSerializer(data=self.validated_data["feature_flag_filters"])
            flag_serializer.is_valid(raise_exception=True)
            feature_flag_filters_dto = flag_serializer.to_dto()

        return CreateExperimentInput(
            name=self.validated_data["name"],
            feature_flag_key=self.validated_data["feature_flag_key"],
            description=self.validated_data.get("description", ""),
            parameters=self.validated_data.get("parameters"),
            feature_flag_filters=feature_flag_filters_dto,
        )
