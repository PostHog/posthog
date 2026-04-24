"""Serializers for saved metrics presentation layer."""

from typing import TYPE_CHECKING, cast

from rest_framework import serializers

from posthog.api.shared import UserBasicSerializer
from posthog.api.tagged_item import TaggedItemSerializerMixin
from posthog.models import User
from posthog.rbac.user_access_control import UserAccessControlSerializerMixin

from products.experiments.backend.metric_utils import refresh_action_names_in_metric
from products.experiments.backend.models.experiment import ExperimentSavedMetric, ExperimentToSavedMetric

if TYPE_CHECKING:
    from products.experiments.backend.facade.saved_metric_contracts import (
        CreateSavedMetricInput,
        UpdateSavedMetricInput,
    )


class ExperimentToSavedMetricSerializer(serializers.ModelSerializer):
    """Serializer for the join table between experiments and saved metrics."""

    query = serializers.JSONField(source="saved_metric.query", read_only=True)
    name = serializers.CharField(source="saved_metric.name", read_only=True)

    class Meta:
        model = ExperimentToSavedMetric
        fields = [
            "id",
            "experiment",
            "saved_metric",
            "metadata",
            "created_at",
            "query",
            "name",
        ]
        read_only_fields = [
            "id",
            "created_at",
        ]

    def to_representation(self, instance: ExperimentToSavedMetric):
        data = super().to_representation(instance)
        # Refresh action names to show current names instead of stale cached values
        team = instance.experiment.team
        data["query"] = refresh_action_names_in_metric(data.get("query"), team)
        return data


class ExperimentSavedMetricSerializer(
    UserAccessControlSerializerMixin, TaggedItemSerializerMixin, serializers.ModelSerializer
):
    """
    Serializer for saved metrics.

    Handles DRF request/response format and routes to facade layer for business logic.
    """

    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = ExperimentSavedMetric
        fields = [
            "id",
            "name",
            "description",
            "query",
            "created_by",
            "created_at",
            "updated_at",
            "tags",
            "user_access_level",
        ]
        read_only_fields = [
            "id",
            "created_by",
            "created_at",
            "updated_at",
            "user_access_level",
        ]

    def validate_name(self, value: str) -> str:
        """Validate name is unique for the team."""
        team = self.context["get_team"]()
        qs = ExperimentSavedMetric.objects.filter(team=team, name__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A shared metric with this name already exists.")
        return value

    def to_representation(self, instance: ExperimentSavedMetric):
        """Refresh action names when serializing."""
        data = super().to_representation(instance)
        team = self.context["get_team"]()
        data["query"] = refresh_action_names_in_metric(data.get("query"), team)
        return data

    def to_facade_dto(self) -> "CreateSavedMetricInput":
        """
        Convert validated serializer data to CreateSavedMetricInput DTO.

        This is called after validation passes.
        """
        from products.experiments.backend.facade.saved_metric_contracts import CreateSavedMetricInput

        return CreateSavedMetricInput(
            name=self.validated_data["name"],
            query=self.validated_data["query"],
            description=self.validated_data.get("description"),
            tags=self.validated_data.get("tags"),
        )

    def to_update_facade_dto(self) -> "UpdateSavedMetricInput":
        """
        Convert validated serializer data to UpdateSavedMetricInput DTO.

        This is called for PATCH/PUT requests after validation passes.
        """
        from products.experiments.backend.facade.saved_metric_contracts import UpdateSavedMetricInput

        return UpdateSavedMetricInput(
            name=self.validated_data.get("name"),
            description=self.validated_data.get("description"),
            query=self.validated_data.get("query"),
            tags=self.validated_data.get("tags"),
        )

    def create(self, validated_data):
        """Create saved metric via facade."""
        from products.experiments.backend.facade import create_saved_metric

        tags = validated_data.pop("tags", None)

        # Validate no extra keys
        expected_keys = {"name", "query", "description"}
        extra_keys = set(validated_data.keys()) - expected_keys
        if extra_keys:
            raise serializers.ValidationError(
                f"Can't create keys: {', '.join(sorted(extra_keys))} on ExperimentSavedMetric"
            )

        # Call facade (returns model instance)
        request = self.context["request"]
        instance = create_saved_metric(
            team=self.context["get_team"](),
            user=cast(User, request.user),
            input_dto=self.to_facade_dto(),
        )

        # Handle tags (not part of facade yet)
        self._attempt_set_tags(tags, instance)

        return instance

    def update(self, instance: ExperimentSavedMetric, validated_data):
        """Update saved metric via facade."""
        from products.experiments.backend.facade import update_saved_metric

        tags = validated_data.pop("tags", None)

        # Call facade (returns updated model instance)
        request = self.context["request"]
        instance = update_saved_metric(
            team=self.context["get_team"](),
            user=cast(User, request.user),
            saved_metric_id=instance.id,
            input_dto=self.to_update_facade_dto(),
        )

        # Handle tags
        self._attempt_set_tags(tags, instance)

        return instance
