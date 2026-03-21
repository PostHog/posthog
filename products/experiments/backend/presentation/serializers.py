"""
Presentation serializers for experiments product.

These serializers handle HTTP request/response conversion and validation,
converting between JSON/HTTP and facade DTOs.
"""

from rest_framework import serializers

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
            name=self.validated_data.get("name") or None,
            rollout_percentage=self.validated_data["rollout_percentage"],
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
        return value

    def to_dto(self) -> CreateFeatureFlagInput:
        """Convert validated data to DTO."""
        # Manually validate nested serializers to get DTOs
        variants_data = self.validated_data["variants"]
        variant_dtos = []
        for variant_data in variants_data:
            variant_serializer = FeatureFlagVariantSerializer(data=variant_data)
            variant_serializer.is_valid(raise_exception=True)
            variant_dtos.append(variant_serializer.to_dto())

        return CreateFeatureFlagInput(
            key=self.validated_data["key"],
            name=self.validated_data.get("name") or None,
            variants=variant_dtos,
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

    def validate(self, attrs):
        """Cross-field validation."""
        has_parameters = attrs.get("parameters") is not None and "feature_flag_variants" in attrs.get("parameters", {})
        has_feature_flag_filters = attrs.get("feature_flag_filters") is not None

        if has_parameters and has_feature_flag_filters:
            raise serializers.ValidationError(
                "Cannot provide both 'parameters.feature_flag_variants' and 'feature_flag_filters'. "
                "Please use only one format."
            )

        return attrs

    def to_facade_dto(self) -> CreateExperimentInput:
        """Convert validated data to facade DTO."""
        feature_flag_filters_dto = None
        if self.validated_data.get("feature_flag_filters"):
            flag_serializer = CreateFeatureFlagInputSerializer(data=self.initial_data.get("feature_flag_filters"))
            flag_serializer.is_valid(raise_exception=True)
            feature_flag_filters_dto = flag_serializer.to_dto()

        return CreateExperimentInput(
            name=self.validated_data["name"],
            feature_flag_key=self.validated_data["feature_flag_key"],
            description=self.validated_data.get("description", ""),
            parameters=self.validated_data.get("parameters"),
            feature_flag_filters=feature_flag_filters_dto,
        )
