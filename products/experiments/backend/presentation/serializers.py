"""
Serializers for experiments presentation layer.

Extracted from experiments.py as part of PR #2 (incremental migration).
All serializer classes and custom field classes live here.
ViewSet remains in experiments.py.
"""

from typing import Any

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from pydantic import RootModel as PydanticRootModel
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from posthog.schema import ExperimentApiExposureCriteria, ExperimentApiMetric, ExperimentParameters

from posthog.api.scoped_related_fields import TeamScopedPrimaryKeyRelatedField
from posthog.api.shared import UserBasicSerializer
from posthog.hogql_queries.experiments.experiment_metric_fingerprint import compute_metric_fingerprint
from posthog.hogql_queries.experiments.utils import get_experiment_stats_method
from posthog.models.team.team import Team
from posthog.rbac.user_access_control import UserAccessControlSerializerMixin

from products.experiments.backend.experiment_service import ExperimentService
from products.experiments.backend.metric_utils import refresh_action_names_in_metric
from products.experiments.backend.models.experiment import Experiment, ExperimentHoldout

from ee.clickhouse.views.experiment_holdouts import ExperimentHoldoutSerializer
from ee.clickhouse.views.experiment_saved_metrics import ExperimentToSavedMetricSerializer


class _ExperimentApiMetricsList(PydanticRootModel):
    """List wrapper for OpenAPI schema generation — the field stores an array of metrics."""

    root: list[ExperimentApiMetric]


@extend_schema_field(_ExperimentApiMetricsList)  # type: ignore[arg-type]
class ExperimentMetricsField(serializers.JSONField):
    pass


@extend_schema_field(ExperimentParameters)  # type: ignore[arg-type]
class ExperimentParametersField(serializers.JSONField):
    def to_representation(self, value: Any) -> Any:
        from copy import deepcopy

        # Add split_percent to outside representation for each variant to simplify frontend logic. The internal representation only uses rollout_percentage to avoid redundancy, but the frontend needs split_percent to display the variant splits in the UI and to support editing the splits in a user-friendly way (editing rollout_percentage directly would be more complex since it's not variant-specific and needs to be inferred from the variants' split_percent values).
        # Deep copy to avoid mutating the model instance's in-memory parameters dict
        data: Any = deepcopy(super().to_representation(value))
        if isinstance(data, dict) and "feature_flag_variants" in data:
            for variant in data["feature_flag_variants"]:
                if isinstance(variant, dict) and "rollout_percentage" in variant:
                    variant["split_percent"] = variant["rollout_percentage"]
        return data

    def to_internal_value(self, data: Any) -> Any:
        from copy import deepcopy

        # Deep copy to avoid mutating the caller's dict (e.g. serializer.initial_data / request.data)
        if isinstance(data, dict) and "feature_flag_variants" in data:
            data = deepcopy(data)
            for variant in data["feature_flag_variants"]:
                if isinstance(variant, dict) and "split_percent" in variant:
                    # split_percent wins in case both keys present, as rollout_percentage deprecated
                    variant["rollout_percentage"] = variant.pop("split_percent")
        return super().to_internal_value(data)


@extend_schema_field(ExperimentApiExposureCriteria)  # type: ignore[arg-type]
class ExperimentExposureCriteriaField(serializers.JSONField):
    pass


class ExperimentSerializer(UserAccessControlSerializerMixin, serializers.ModelSerializer):
    feature_flag_key = serializers.CharField(
        source="get_feature_flag_key",
        help_text=(
            "Unique key for the experiment's feature flag. Letters, numbers, hyphens, and underscores only. "
            "Search existing flags with the feature-flags-get-all tool first — reuse an existing flag when possible."
        ),
    )
    created_by = UserBasicSerializer(read_only=True)
    feature_flag = serializers.SerializerMethodField(read_only=True)
    holdout = ExperimentHoldoutSerializer(read_only=True)
    holdout_id = TeamScopedPrimaryKeyRelatedField(
        queryset=ExperimentHoldout.objects.all(),
        source="holdout",
        required=False,
        allow_null=True,
        help_text="ID of a holdout group to exclude from the experiment.",
    )
    saved_metrics = ExperimentToSavedMetricSerializer(many=True, source="experimenttosavedmetric_set", read_only=True)
    saved_metrics_ids = serializers.ListField(
        child=serializers.JSONField(),
        required=False,
        allow_null=True,
        help_text="IDs of shared saved metrics to attach to this experiment. Each item has 'id' (saved metric ID) and 'metadata' with 'type' (primary or secondary).",
    )
    allow_unknown_events = serializers.BooleanField(required=False, default=False, write_only=True)
    name = serializers.CharField(
        max_length=400,
        help_text="Name of the experiment.",
    )
    description = serializers.CharField(
        max_length=3000,
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Description of the experiment hypothesis and expected outcomes.",
    )
    parameters = ExperimentParametersField(
        required=False,
        allow_null=True,
        help_text=(
            "Variant definitions and rollout configuration. "
            "Set feature_flag_variants to customize the split (default: 50/50 control/test). "
            "Each variant needs a key and split_percent (the variant's share of traffic); percentages must sum to 100. "
            "Set rollout_percentage (0-100, default 100) to limit what fraction of users enter the experiment. "
            "Set minimum_detectable_effect (percentage, suggest 20-30) to control statistical power."
        ),
    )
    metrics = ExperimentMetricsField(
        required=False,
        allow_null=True,
        help_text=(
            "Primary experiment metrics. Each metric must have kind='ExperimentMetric' and a metric_type: "
            "'mean' (set source to an EventsNode with an event name), "
            "'funnel' (set series to an array of EventsNode steps), "
            "'ratio' (set numerator and denominator EventsNode entries), or "
            "'retention' (set start_event and completion_event). "
            "Use the event-definitions-list tool to find available events in the project."
        ),
    )
    metrics_secondary = ExperimentMetricsField(
        required=False,
        allow_null=True,
        help_text="Secondary metrics for additional measurements. Same format as primary metrics.",
    )
    exposure_criteria = ExperimentExposureCriteriaField(
        required=False,
        allow_null=True,
        help_text="Exposure configuration including filter test accounts and custom exposure events.",
    )
    conclusion = serializers.ChoiceField(
        choices=["won", "lost", "inconclusive", "stopped_early", "invalid"],
        required=False,
        allow_null=True,
        help_text="Experiment conclusion: won, lost, inconclusive, stopped_early, or invalid.",
    )
    conclusion_comment = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Comment about the experiment conclusion.",
    )
    archived = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Whether the experiment is archived.",
    )
    type = serializers.ChoiceField(
        choices=["web", "product"],
        required=False,
        allow_null=True,
        help_text="Experiment type: web for frontend UI changes, product for backend/API changes.",
    )
    update_feature_flag_params = serializers.BooleanField(
        required=False,
        default=False,
        write_only=True,
        help_text=(
            "When true, sync feature flag configuration from parameters "
            "to the linked feature flag. Draft experiments always sync "
            "regardless of update_feature_flag_params, so only required "
            "for non-drafts."
        ),
    )
    status = serializers.SerializerMethodField(
        help_text=(
            "Experiment lifecycle state: 'draft' (not yet launched), 'running' (launched with active feature "
            "flag), 'paused' (running with feature flag deactivated — virtual state derived from "
            "feature_flag.active, not stored), 'stopped' (ended)."
        ),
    )
    _create_in_folder = serializers.CharField(required=False, allow_blank=True, write_only=True)

    @extend_schema_field({"type": "string", "enum": ["draft", "running", "paused", "stopped"]})
    def get_status(self, instance: Experiment) -> str:
        if instance.is_paused:
            return "paused"
        return instance.status or instance.computed_status.value

    class Meta:
        model = Experiment
        fields = [
            "id",
            "name",
            "description",
            "start_date",
            "end_date",
            "feature_flag_key",
            "feature_flag",
            "holdout",
            "holdout_id",
            "exposure_cohort",
            "parameters",
            "secondary_metrics",
            "saved_metrics",
            "saved_metrics_ids",
            "filters",
            "archived",
            "deleted",
            "created_by",
            "created_at",
            "updated_at",
            "type",
            "exposure_criteria",
            "metrics",
            "metrics_secondary",
            "stats_config",
            "scheduling_config",
            "allow_unknown_events",
            "_create_in_folder",
            "conclusion",
            "conclusion_comment",
            "primary_metrics_ordered_uuids",
            "secondary_metrics_ordered_uuids",
            "only_count_matured_users",
            "update_feature_flag_params",
            "status",
            "user_access_level",
        ]
        read_only_fields = [
            "id",
            "created_by",
            "created_at",
            "updated_at",
            "feature_flag",
            "exposure_cohort",
            "holdout",
            "saved_metrics",
            "status",
            "user_access_level",
        ]

    def get_fields(self):
        fields = super().get_fields()
        team_id = self.context.get("team_id")
        if team_id:
            fields["holdout_id"].queryset = ExperimentHoldout.objects.filter(team_id=team_id)  # type: ignore[attr-defined]
        else:
            fields["holdout_id"].queryset = ExperimentHoldout.objects.none()  # type: ignore[attr-defined]
        return fields

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_feature_flag(self, obj):
        from posthog.api.feature_flag import MinimalFeatureFlagSerializer

        return MinimalFeatureFlagSerializer(obj.feature_flag).data if obj.feature_flag else None

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # Normalize query date ranges to the experiment's current range
        # Cribbed from ExperimentTrendsQuery
        new_date_range = {
            "date_from": data["start_date"] if data["start_date"] else "",
            "date_to": data["end_date"] if data["end_date"] else "",
            "explicitDate": True,
        }

        # Refresh action names in inline metrics (metrics and metrics_secondary)
        for metrics_list in [data.get("metrics", []), data.get("metrics_secondary", [])]:
            for i, metric in enumerate(metrics_list):
                # Refresh action names to show current names instead of stale cached values
                refreshed_metric = refresh_action_names_in_metric(metric, instance.team)
                if refreshed_metric:
                    metrics_list[i] = refreshed_metric
                    metric = refreshed_metric

                if metric.get("count_query", {}).get("dateRange"):
                    metric["count_query"]["dateRange"] = new_date_range
                if metric.get("funnels_query", {}).get("dateRange"):
                    metric["funnels_query"]["dateRange"] = new_date_range

        # Update date ranges in saved metrics
        # Note: Action name refresh is handled by ExperimentToSavedMetricSerializer.to_representation
        for saved_metric in data.get("saved_metrics", []):
            if saved_metric.get("query"):
                if saved_metric["query"].get("count_query", {}).get("dateRange"):
                    saved_metric["query"]["count_query"]["dateRange"] = new_date_range
                if saved_metric["query"].get("funnels_query", {}).get("dateRange"):
                    saved_metric["query"]["funnels_query"]["dateRange"] = new_date_range

                # Add fingerprint to saved metric returned from API
                # so that frontend knows what timeseries records to query
                saved_metric["query"]["fingerprint"] = compute_metric_fingerprint(
                    saved_metric["query"],
                    instance.start_date,
                    get_experiment_stats_method(instance),
                    instance.exposure_criteria,
                    only_count_matured_users=instance.only_count_matured_users,
                )

        return data

    def validate_saved_metrics_ids(self, value):
        ExperimentService.validate_saved_metrics_ids(value, self.context["team_id"])
        return value

    def validate(self, data):
        ExperimentService.validate_experiment_date_range(data.get("start_date"), data.get("end_date"))
        return super().validate(data)

    def validate_parameters(self, value):
        ExperimentService.validate_experiment_parameters(value)
        return value

    def validate_exposure_criteria(self, exposure_criteria: dict | None):
        ExperimentService.validate_experiment_exposure_criteria(exposure_criteria)
        return exposure_criteria

    def _validate_metrics_list(self, metrics: list | None) -> list | None:
        ExperimentService.validate_experiment_metrics(metrics)
        return metrics

    def validate_metrics(self, value):
        return self._validate_metrics_list(value)

    def validate_metrics_secondary(self, value):
        return self._validate_metrics_list(value)

    def create(self, validated_data: dict, *args: Any, **kwargs: Any) -> Experiment:
        feature_flag_key = validated_data.pop("get_feature_flag_key")
        saved_metrics_ids = validated_data.pop("saved_metrics_ids", None)
        create_in_folder = validated_data.pop("_create_in_folder", None)
        name = validated_data.pop("name")
        description = validated_data.pop("description", "")
        experiment_type = validated_data.pop("type", "product")
        parameters = validated_data.pop("parameters", None)
        metrics = validated_data.pop("metrics", None)
        metrics_secondary = validated_data.pop("metrics_secondary", None)
        secondary_metrics = validated_data.pop("secondary_metrics", None)
        stats_config = validated_data.pop("stats_config", None)
        exposure_criteria = validated_data.pop("exposure_criteria", None)
        holdout = validated_data.pop("holdout", None)
        start_date = validated_data.pop("start_date", None)
        end_date = validated_data.pop("end_date", None)
        primary_metrics_ordered_uuids = validated_data.pop("primary_metrics_ordered_uuids", None)
        secondary_metrics_ordered_uuids = validated_data.pop("secondary_metrics_ordered_uuids", None)
        filters = validated_data.pop("filters", None)
        scheduling_config = validated_data.pop("scheduling_config", None)
        only_count_matured_users = validated_data.pop("only_count_matured_users", None)
        archived = validated_data.pop("archived", False)
        deleted = validated_data.pop("deleted", False)
        conclusion = validated_data.pop("conclusion", None)
        conclusion_comment = validated_data.pop("conclusion_comment", None)
        allow_unknown_events = validated_data.pop("allow_unknown_events", False)
        validated_data.pop("update_feature_flag_params", None)

        if validated_data:
            raise ValidationError(f"Can't create keys: {', '.join(sorted(validated_data))} on Experiment")

        team = Team.objects.get(id=self.context["team_id"])
        service = ExperimentService(team=team, user=self.context["request"].user)

        return service.create_experiment(
            name=name,
            feature_flag_key=feature_flag_key,
            description=description,
            type=experiment_type,
            parameters=parameters,
            metrics=metrics,
            metrics_secondary=metrics_secondary,
            secondary_metrics=secondary_metrics,
            stats_config=stats_config,
            exposure_criteria=exposure_criteria,
            holdout=holdout,
            saved_metrics_ids=saved_metrics_ids,
            start_date=start_date,
            end_date=end_date,
            primary_metrics_ordered_uuids=primary_metrics_ordered_uuids,
            secondary_metrics_ordered_uuids=secondary_metrics_ordered_uuids,
            create_in_folder=create_in_folder,
            filters=filters,
            scheduling_config=scheduling_config,
            only_count_matured_users=only_count_matured_users,
            archived=archived,
            deleted=deleted,
            conclusion=conclusion,
            conclusion_comment=conclusion_comment,
            serializer_context=self.context,
            allow_unknown_events=allow_unknown_events,
        )

    def update(self, instance: Experiment, validated_data: dict, *args: Any, **kwargs: Any) -> Experiment:
        allow_unknown_events = validated_data.pop("allow_unknown_events", False)
        team = Team.objects.get(id=self.context["team_id"])
        service = ExperimentService(team=team, user=self.context["request"].user)
        return service.update_experiment(
            instance, validated_data, serializer_context=self.context, allow_unknown_events=allow_unknown_events
        )


class EndExperimentSerializer(serializers.Serializer):
    conclusion = serializers.ChoiceField(
        choices=["won", "lost", "inconclusive", "stopped_early", "invalid"],
        required=False,
        allow_null=True,
        help_text="The conclusion of the experiment.",
    )
    conclusion_comment = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Optional comment about the experiment conclusion.",
    )


class ShipVariantSerializer(EndExperimentSerializer):
    variant_key = serializers.CharField(help_text="The key of the variant to ship to 100% of users.")


class CopyExperimentToProjectSerializer(serializers.Serializer):
    target_team_id = serializers.IntegerField(help_text="The team ID to copy the experiment to.")
    feature_flag_key = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Optional feature flag key to use in the destination team.",
    )
    name = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Optional name for the copied experiment.",
    )
