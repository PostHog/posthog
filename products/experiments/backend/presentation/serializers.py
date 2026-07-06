"""
Serializers for experiments presentation layer.

Extracted from experiments.py as part of PR #2 (incremental migration).
All serializer classes and custom field classes live here.
ViewSet remains in experiments.py.
"""

from copy import deepcopy
from typing import Any

from drf_spectacular.utils import extend_schema_field
from opentelemetry import trace
from pydantic import RootModel as PydanticRootModel
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from posthog.schema import (
    ExperimentApiExposureCriteria,
    ExperimentApiMetric,
    ExperimentParameters,
    ExperimentRunningTimeCalculation,
)

from posthog.api.scoped_related_fields import TeamScopedPrimaryKeyRelatedField
from posthog.api.shared import UserBasicSerializer
from posthog.models.team.team import Team
from posthog.rbac.user_access_control import UserAccessControlSerializerMixin

from products.ai_observability.backend.models.llm_prompt import LLMPrompt
from products.experiments.backend.experiment_service import ExperimentService
from products.experiments.backend.facade.contracts import CreateExperimentInput
from products.experiments.backend.hogql_queries.experiment_metric_fingerprint import compute_metric_fingerprint
from products.experiments.backend.hogql_queries.utils import get_experiment_stats_method
from products.experiments.backend.llm_metric_templates import TEMPLATE_NAMES
from products.experiments.backend.metric_utils import refresh_action_names_in_metric
from products.experiments.backend.models.experiment import (
    Experiment,
    ExperimentHoldout,
    ExperimentMetricsRecalculation,
    experiment_has_legacy_metrics,
)
from products.experiments.backend.running_time_calculator import METRIC_TYPE_CHOICES
from products.feature_flags.backend.api.feature_flag import MinimalFeatureFlagSerializer
from products.feature_flags.backend.models.feature_flag import FeatureFlag

from ee.clickhouse.views.experiment_holdouts import ExperimentHoldoutSerializer
from ee.clickhouse.views.experiment_saved_metrics import ExperimentToSavedMetricSerializer

tracer = trace.get_tracer(__name__)


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
            variants = data["feature_flag_variants"]
            if isinstance(variants, list):
                # Normalize a case-insensitive 'control' key (e.g. 'Control', 'CONTROL') down
                # to lowercase 'control'. The downstream validator and runtime treat 'control'
                # as a special key, so a typo in casing was the leading cause of the
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
        return super().to_internal_value(data)


@extend_schema_field(ExperimentApiExposureCriteria)  # type: ignore[arg-type]
class ExperimentExposureCriteriaField(serializers.JSONField):
    pass


@extend_schema_field(ExperimentRunningTimeCalculation)  # type: ignore[arg-type]
class ExperimentRunningTimeCalculationField(serializers.JSONField):
    pass


class ExperimentBaseSerializer(UserAccessControlSerializerMixin, serializers.ModelSerializer):
    """Shared read-side fields for the full and list experiment serializers.

    ``ExperimentSerializer`` (detail + write) and ``ExperimentBasicSerializer`` (list) both
    declare the scalar, feature-flag, and method fields here, so they render identical types
    for the fields they share. That keeps ``ExperimentApi`` a structural superset of
    ``ExperimentBasicApi`` — which consumers rely on — by construction, not by hand-mirroring
    field definitions across two classes. This base is abstract: subclasses supply their own
    ``Meta`` (model + fields) and it is never instantiated on its own.
    """

    feature_flag_key = serializers.CharField(
        source="get_feature_flag_key",
        help_text=(
            "Unique key for the experiment's feature flag. Letters, numbers, hyphens, and underscores only. "
            "Search existing flags with the feature-flag-get-all tool first — reuse an existing flag when possible."
        ),
    )
    created_by = UserBasicSerializer(read_only=True)
    feature_flag = serializers.SerializerMethodField(read_only=True)
    holdout = ExperimentHoldoutSerializer(read_only=True)
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
            "Experiment parameters JSON. Supported keys include "
            "`feature_flag_variants`, `rollout_percentage`, "
            "`custom_exposure_filter`, and `variant_notes` "
            "(free-text notes per variant, keyed by variant key). "
            "Excluded variants live on the top-level `excluded_variants` field, not here."
        ),
    )
    running_time_calculation = ExperimentRunningTimeCalculationField(
        required=False,
        allow_null=True,
        help_text=(
            "Running-time calculator state: `minimum_detectable_effect`, `recommended_running_time`, "
            "`recommended_sample_size`, and `exposure_estimate_config`. Canonical home for these keys, "
            "which historically lived in `parameters`."
        ),
    )
    excluded_variants = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_null=True,
        help_text=(
            "Variant keys to exclude from metric result calculations. Excluded variants are still "
            "served to users but omitted from statistical analysis. The baseline variant and holdout "
            "pseudo-variants cannot be excluded. Canonical home for what historically lived in "
            "`parameters.excluded_variants`."
        ),
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
        max_length=4000,
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
    status = serializers.SerializerMethodField(
        help_text=(
            "Experiment lifecycle state: 'draft' (not yet launched), 'running' (launched with active feature "
            "flag), 'paused' (running with feature flag deactivated — virtual state derived from "
            "feature_flag.active, not stored), 'stopped' (ended)."
        ),
    )
    is_legacy = serializers.SerializerMethodField(
        help_text=(
            "Whether the experiment uses any legacy-engine metrics (ExperimentTrendsQuery or "
            "ExperimentFunnelsQuery). Used to flag legacy experiments and gate actions that don't support "
            "them, such as duplicate and copy-to-project."
        ),
    )

    @extend_schema_field({"type": "string", "enum": ["draft", "running", "paused", "stopped"]})
    def get_status(self, instance: Experiment) -> str:
        return instance.status_label

    @extend_schema_field(MinimalFeatureFlagSerializer)
    def get_feature_flag(self, obj):
        return MinimalFeatureFlagSerializer(obj.feature_flag).data if obj.feature_flag else None

    @extend_schema_field(serializers.BooleanField())
    def get_is_legacy(self, obj: Experiment) -> bool:
        # The list queryset annotates is_legacy_annotation in SQL so the heavy metric columns stay
        # deferred (see EnterpriseExperimentsViewSet.safely_get_queryset / list_is_legacy_annotation).
        # On other paths (detail) the metrics are loaded, so fall back to computing it directly.
        annotated = getattr(obj, "is_legacy_annotation", None)
        if annotated is not None:
            return annotated
        return experiment_has_legacy_metrics(obj)

    def to_representation(self, instance: Experiment) -> dict[str, Any]:
        data = super().to_representation(instance)
        self._project_feature_flag_config(data, instance.feature_flag)
        return data

    @staticmethod
    def _project_feature_flag_config(data: dict[str, Any], flag: FeatureFlag | None) -> None:
        """Source feature-flag config in the deprecated `parameters` projection from the linked flag.

        The flag is the source of truth for variants/rollout/aggregation group type — `parameters`
        is a deprecated compatibility surface (see the experiment model's `parameters` comment).
        Reading these keys from the flag instead of the stored column lets us stop persisting the
        `parameters` mirror without changing the API response. The linked flag is already serialized
        into `data["feature_flag"]`, so this adds no queries.
        """
        if flag is None:
            return
        parameters = dict(data.get("parameters") or {})

        variants = deepcopy(flag.variants)
        for variant in variants:
            # Mirror ExperimentParametersField.to_representation: the UI edits splits via split_percent.
            if isinstance(variant, dict) and "rollout_percentage" in variant:
                variant["split_percent"] = variant["rollout_percentage"]
        parameters["feature_flag_variants"] = variants

        filters = flag.get_filters()
        aggregation_group_type_index = filters.get("aggregation_group_type_index")
        if aggregation_group_type_index is not None:
            parameters["aggregation_group_type_index"] = aggregation_group_type_index
        else:
            parameters.pop("aggregation_group_type_index", None)

        groups = filters.get("groups") or []
        if groups and groups[0].get("rollout_percentage") is not None:
            parameters["rollout_percentage"] = groups[0]["rollout_percentage"]
        else:
            parameters.pop("rollout_percentage", None)

        data["parameters"] = parameters


class ExperimentSerializer(ExperimentBaseSerializer):
    """Full experiment representation for the detail, create, and update endpoints.

    Extends the shared read-side fields in ``ExperimentBaseSerializer`` with the metric
    definitions (``metrics``/``metrics_secondary``/``saved_metrics``) and the write-side
    fields, and refreshes stale action names while serializing. The list endpoint uses the
    leaner ``ExperimentBasicSerializer`` instead.
    """

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
    allow_unknown_events = serializers.BooleanField(
        required=False,
        default=False,
        write_only=True,
        help_text=(
            "Suppresses the validation that rejects metrics referencing events not yet "
            "ingested by this project. REQUIRES explicit user confirmation before being "
            "set to true — never flip this silently to retry a failed call. The default "
            "validation catches typo'd event names and missing instrumentation. Set this "
            "to true only when the user has confirmed the event is intentional (e.g. they "
            "are about to instrument it)."
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
            "Use the read-data-schema tool with query kind 'events' to find available events in the project."
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
    _create_in_folder = serializers.CharField(required=False, allow_blank=True, write_only=True)

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
            "running_time_calculation",
            "excluded_variants",
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
            "is_legacy",
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

    @tracer.start_as_current_span("ExperimentSerializer.to_representation")
    def to_representation(self, instance):
        data = super().to_representation(instance)
        # Normalize query date ranges to the experiment's current range
        # Cribbed from ExperimentTrendsQuery
        new_date_range = {
            "date_from": data["start_date"] if data["start_date"] else "",
            "date_to": data["end_date"] if data["end_date"] else "",
            "explicitDate": True,
        }

        # Refresh action names in inline metrics (metrics and metrics_secondary).
        # The columns are nullable, so the keys can be present with a None value. Each call
        # resolves the experiment's actions in a single query — fine here because this serializer
        # only ever renders one experiment at a time (detail/launch/archive/…), never a list page.
        for metrics_list in [data.get("metrics") or [], data.get("metrics_secondary") or []]:
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
        saved_metrics = data.get("saved_metrics", [])
        with tracer.start_as_current_span("ExperimentSerializer.saved_metric_fingerprints") as span:
            span.set_attribute("saved_metric_count", len(saved_metrics))
            for saved_metric in saved_metrics:
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
                        excluded_variants=instance.excluded_variants or [],
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

    def validate_running_time_calculation(self, value):
        ExperimentService.validate_running_time_calculation(value)
        return value

    def validate_excluded_variants(self, value):
        ExperimentService.validate_excluded_variants(value)
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

    def to_facade_dto(self) -> CreateExperimentInput:
        """Convert validated request data to facade DTO."""
        # Extract holdout ID if provided
        holdout_id = None
        if holdout := self.validated_data.get("holdout"):
            holdout_id = holdout.id if hasattr(holdout, "id") else None

        # Convert ordering lists to tuples (DTO uses tuples for immutability)
        primary_ordering = self.validated_data.get("primary_metrics_ordered_uuids")
        secondary_ordering = self.validated_data.get("secondary_metrics_ordered_uuids")

        return CreateExperimentInput(
            name=self.validated_data["name"],
            feature_flag_key=self.validated_data["get_feature_flag_key"],
            description=self.validated_data.get("description", ""),
            type=self.validated_data.get("type", "product"),
            parameters=self.validated_data.get("parameters"),
            running_time_calculation=self.validated_data.get("running_time_calculation"),
            excluded_variants=self.validated_data.get("excluded_variants"),
            metrics=self.validated_data.get("metrics"),
            metrics_secondary=self.validated_data.get("metrics_secondary"),
            secondary_metrics=self.validated_data.get("secondary_metrics"),
            metrics_ordering=tuple(primary_ordering) if primary_ordering else None,
            secondary_metrics_ordering=tuple(secondary_ordering) if secondary_ordering else None,
            saved_metrics_ids=self.validated_data.get("saved_metrics_ids"),
            stats_config=self.validated_data.get("stats_config"),
            exposure_criteria=self.validated_data.get("exposure_criteria"),
            only_count_matured_users=self.validated_data.get("only_count_matured_users"),
            start_date=self.validated_data.get("start_date"),
            end_date=self.validated_data.get("end_date"),
            archived=self.validated_data.get("archived", False),
            deleted=self.validated_data.get("deleted", False),
            conclusion=self.validated_data.get("conclusion"),
            conclusion_comment=self.validated_data.get("conclusion_comment"),
            holdout_id=holdout_id,
            filters=self.validated_data.get("filters"),
            scheduling_config=self.validated_data.get("scheduling_config"),
            create_in_folder=self.validated_data.get("_create_in_folder"),
            allow_unknown_events=self.validated_data.get("allow_unknown_events", False),
            serializer_context=self.context,
        )

    def create(self, validated_data: dict, *args: Any, **kwargs: Any) -> Experiment:
        """Create experiment via facade layer."""
        from products.experiments.backend.facade import create_experiment

        # Pop fields not needed for DTO but needed for validation
        validated_data.pop("update_feature_flag_params", None)

        # Check for unexpected fields
        expected_fields = {
            "name",
            "get_feature_flag_key",
            "description",
            "type",
            "parameters",
            "running_time_calculation",
            "excluded_variants",
            "metrics",
            "metrics_secondary",
            "secondary_metrics",
            "primary_metrics_ordered_uuids",
            "secondary_metrics_ordered_uuids",
            "saved_metrics_ids",
            "stats_config",
            "exposure_criteria",
            "only_count_matured_users",
            "start_date",
            "end_date",
            "archived",
            "deleted",
            "conclusion",
            "conclusion_comment",
            "holdout",
            "filters",
            "scheduling_config",
            "_create_in_folder",
            "allow_unknown_events",
        }
        unexpected = set(validated_data.keys()) - expected_fields
        if unexpected:
            raise ValidationError(f"Can't create keys: {', '.join(sorted(unexpected))} on Experiment")

        # Convert to facade DTO
        input_dto = self.to_facade_dto()

        # Route through facade
        team = Team.objects.get(id=self.context["team_id"])
        experiment_dto = create_experiment(
            team=team,
            user=self.context["request"].user,
            input_dto=input_dto,
        )

        # Load instance for return (DRF expects model instance)
        return Experiment.objects.get(id=experiment_dto.id)

    def update(self, instance: Experiment, validated_data: dict, *args: Any, **kwargs: Any) -> Experiment:
        allow_unknown_events = validated_data.pop("allow_unknown_events", False)
        team = Team.objects.get(id=self.context["team_id"])
        service = ExperimentService(team=team, user=self.context["request"].user)
        return service.update_experiment(
            instance, validated_data, serializer_context=self.context, allow_unknown_events=allow_unknown_events
        )


class ExperimentBasicSerializer(ExperimentBaseSerializer):
    """Lightweight, read-only serializer for the experiment list endpoint.

    The list view (and the MCP list tool) render only the scalar and feature-flag fields
    shared via ``ExperimentBaseSerializer`` — never the metric definitions. Omitting
    ``metrics``/``metrics_secondary``/``saved_metrics`` lets the list query defer the large
    JSON columns and skip the saved-metric prefetch plus per-row fingerprinting; that work
    belongs to the detail response served by ``ExperimentSerializer``.

    Because the metric fields, the write-side machinery, and the action-name-refreshing
    ``to_representation`` all live on ``ExperimentSerializer`` rather than the shared base,
    this serializer needs no overrides: it gets DRF's default ``get_fields`` (no write-only
    ``holdout_id`` to configure), default ``to_representation`` (no metrics to normalize), and
    a plain ``ListSerializer`` that never touches the deferred columns. See
    ``EnterpriseExperimentsViewSet.safely_get_queryset``.
    """

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
            "exposure_cohort",
            "parameters",
            "running_time_calculation",
            "excluded_variants",
            "archived",
            "deleted",
            "created_by",
            "created_at",
            "updated_at",
            "type",
            "conclusion",
            "conclusion_comment",
            "status",
            "is_legacy",
            "user_access_level",
        ]
        # Shared fields take their definitions from ExperimentBaseSerializer, so their types
        # already match ExperimentSerializer. read_only_fields still has to mirror the full
        # serializer for the model-derived fields (id/created_at/exposure_cohort/...) so each
        # field's optionality matches and ExperimentApi stays a structural superset of
        # ExperimentBasicApi, which consumers rely on.
        read_only_fields = [
            "id",
            "created_by",
            "created_at",
            "updated_at",
            "feature_flag",
            "exposure_cohort",
            "holdout",
            "status",
            "user_access_level",
        ]


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
        max_length=4000,
        help_text="Optional comment about the experiment conclusion.",
    )


class ArchiveExperimentSerializer(serializers.Serializer):
    disable_feature_flag = serializers.BooleanField(
        default=False,
        help_text=(
            "When the linked feature flag is still enabled, also disable and archive it along with "
            "the experiment. Has no effect if the flag is already disabled (it is archived either way)."
        ),
    )


class ShipVariantSerializer(EndExperimentSerializer):
    variant_key = serializers.CharField(help_text="The key of the variant to ship.")
    release_to_everyone = serializers.BooleanField(
        default=False,
        help_text=(
            "If true, prepend a release condition to the feature flag that rolls the variant out to 100% of users, "
            "overriding any existing release conditions on the flag. If false (default), only update the variant "
            "distribution — existing release conditions are preserved and the variant is served only to users who "
            "already match them."
        ),
    )


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


CREATE_FROM_PROMPT_MIN_VERSIONS = 2
CREATE_FROM_PROMPT_MAX_VERSIONS = 10


class CreateFromPromptInputSerializer(serializers.Serializer):
    prompt_name = serializers.CharField(
        help_text="The name of the LLM prompt to experiment on. Must already exist for this team.",
    )
    versions = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        min_length=CREATE_FROM_PROMPT_MIN_VERSIONS,
        max_length=CREATE_FROM_PROMPT_MAX_VERSIONS,
        help_text=(
            "Ordered list of prompt version numbers to assign to experiment variants. "
            "The first entry is the control variant. Must contain between "
            f"{CREATE_FROM_PROMPT_MIN_VERSIONS} and {CREATE_FROM_PROMPT_MAX_VERSIONS} distinct versions."
        ),
    )
    templates = serializers.ListField(
        child=serializers.ChoiceField(choices=TEMPLATE_NAMES),
        min_length=1,
        max_length=len(TEMPLATE_NAMES),
        help_text=(
            "One or more metric templates to attach as primary metrics. "
            "Each template becomes one metric on the experiment. "
            f"Allowed values: {', '.join(TEMPLATE_NAMES)}."
        ),
    )
    name = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Optional experiment name. If omitted, a name is generated from the prompt and versions.",
    )
    feature_flag_key = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Optional feature flag key. If omitted, a slug is derived from the experiment name.",
    )
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Optional experiment description.",
    )

    def validate_versions(self, value: list[int]) -> list[int]:
        if len(set(value)) != len(value):
            raise ValidationError("versions must not contain duplicates.")
        return value

    def validate_templates(self, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValidationError("templates must not contain duplicates.")
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        team = self.context.get("team")
        if team is None:
            raise ValidationError("Team is required in serializer context.")

        prompt_name = attrs["prompt_name"]
        versions = attrs["versions"]

        found = set(
            LLMPrompt.objects.filter(
                team_id=team.id,
                name=prompt_name,
                version__in=versions,
                deleted=False,
            ).values_list("version", flat=True)
        )
        missing = [v for v in versions if v not in found]
        if missing:
            raise ValidationError({"versions": f"Versions not found for prompt {prompt_name!r}: {missing}"})

        # Reusing an existing flag would link the experiment to a flag whose payloads do not
        # encode {prompt_name, prompt_version}, leaving the experiment created but unusable
        # by the SDK (flags.get_flag_payload returns None). Reject explicit collisions so the
        # caller can pick a different key; an omitted key falls through to slug auto-resolution.
        feature_flag_key = attrs.get("feature_flag_key")
        if feature_flag_key and FeatureFlag.objects.filter(team_id=team.id, key=feature_flag_key).exists():
            raise ValidationError(
                {
                    "feature_flag_key": (
                        f"Feature flag {feature_flag_key!r} already exists for this team. "
                        "Pick a different key, or omit this field to auto-generate one."
                    )
                }
            )

        return attrs


class MetricRecalculationResultSerializer(serializers.Serializer):
    """One metric's recalculated result row, read back from ExperimentMetricResult."""

    metric_uuid = serializers.CharField(read_only=True, help_text="UUID of the metric this result belongs to")
    status = serializers.ChoiceField(
        choices=["pending", "completed", "failed"],
        read_only=True,
        help_text="Status of this metric's calculation in the run",
    )
    # JSONField mirrors the ExperimentMetricResult.result column; concrete shape comes from
    # posthog.schema.ExperimentQueryResponse (variants/baseline/credible intervals/etc., depending on metric type).
    result = serializers.JSONField(
        read_only=True,
        allow_null=True,
        help_text="The computed metric result (ExperimentQueryResponse shape); null when status is pending or failed",
    )
    error_message = serializers.CharField(
        read_only=True, allow_null=True, help_text="Error message when status is failed; otherwise null"
    )


class RecalculateMetricsRequestSerializer(serializers.Serializer):
    """Request body for triggering a metrics recalculation."""

    trigger = serializers.ChoiceField(
        choices=ExperimentMetricsRecalculation.Trigger.choices,
        required=False,
        default="manual",
        help_text="What triggered this recalculation (manual is the default for user-initiated runs)",
    )


class ExperimentMetricsRecalculationSerializer(serializers.Serializer):
    """Serializer for metrics recalculation status responses."""

    id = serializers.UUIDField(read_only=True, help_text="Unique identifier for this recalculation job")
    experiment_id = serializers.IntegerField(read_only=True, help_text="ID of the experiment being recalculated")
    status = serializers.ChoiceField(
        choices=ExperimentMetricsRecalculation.Status.choices,
        read_only=True,
        help_text="Current status of the recalculation job",
    )
    total_metrics = serializers.IntegerField(read_only=True, help_text="Total number of metrics to recalculate")
    completed_metrics = serializers.IntegerField(
        read_only=True,
        help_text="Number of metrics with a COMPLETED result row in this run (derived, not stored)",
    )
    failed_metrics = serializers.IntegerField(
        read_only=True,
        help_text=(
            "Number of failed metrics in this run (derived): FAILED result rows plus discovery-step failures "
            "that never made it to a result row"
        ),
    )
    # Named metric_errors (not errors) to avoid shadowing DRF's reserved Serializer.errors property.
    metric_errors = serializers.JSONField(read_only=True, help_text="Map of metric_uuid to error details")
    trigger = serializers.ChoiceField(
        choices=ExperimentMetricsRecalculation.Trigger.choices,
        read_only=True,
        help_text="What triggered this recalculation",
    )
    created_at = serializers.DateTimeField(read_only=True, help_text="When the job was created")
    started_at = serializers.DateTimeField(read_only=True, allow_null=True, help_text="When processing started")
    completed_at = serializers.DateTimeField(read_only=True, allow_null=True, help_text="When processing completed")
    query_to = serializers.DateTimeField(
        read_only=True,
        allow_null=True,
        help_text=(
            "Upper time bound the metrics in this run were calculated against (the data freshness cutoff). "
            "Shared by every metric in the run; null until processing starts"
        ),
    )
    is_existing = serializers.BooleanField(
        read_only=True, required=False, help_text="True if returning an existing job rather than a newly created one"
    )
    # Named result_source (not source) to avoid shadowing DRF's reserved Field.source attribute, mirroring
    # the metric_errors-vs-errors rename above.
    result_source = serializers.ChoiceField(
        choices=["recalculation", "timeseries_fallback"],
        required=False,
        default="recalculation",
        read_only=True,
        help_text=(
            "Where these results came from: 'recalculation' for a real metrics-recalculation run, "
            "'timeseries_fallback' for a cold-start placeholder built from the latest daily timeseries data."
        ),
    )
    # Populated by the GET endpoints (latest / by-id). Omitted from the POST response payload (which doesn't carry
    # per-metric results yet — the workflow has just started).
    results = MetricRecalculationResultSerializer(
        many=True,
        read_only=True,
        required=False,
        help_text="Per-metric results computed by this run, scoped by the run's recalc fingerprint",
    )


class RunningTimeBaselineStatsSerializer(serializers.Serializer):
    """Raw control-group statistics the calculator uses to derive a baseline value and variance.

    Supply this when you want the server to compute the baseline value and (for ratio/retention)
    the delta-method variance, instead of passing `baseline_value`/`variance` directly.
    """

    number_of_samples = serializers.IntegerField(
        min_value=0, help_text="Number of control-group samples (users/units) observed."
    )
    sum = serializers.FloatField(
        help_text="Sum of the metric values across the control group (for funnels, the numerator/conversions)."
    )
    sum_squares = serializers.FloatField(
        required=False, default=0.0, help_text="Sum of squared metric values. Required for ratio/retention variance."
    )
    denominator_sum = serializers.FloatField(
        required=False,
        allow_null=True,
        help_text="Sum of the denominator values. Required for ratio/retention metrics.",
    )
    denominator_sum_squares = serializers.FloatField(
        required=False, allow_null=True, help_text="Sum of squared denominator values (ratio/retention variance)."
    )
    numerator_denominator_sum_product = serializers.FloatField(
        required=False,
        allow_null=True,
        help_text="Sum of numerator×denominator products, used for the delta-method covariance term.",
    )
    step_counts = serializers.ListField(
        child=serializers.FloatField(),
        required=False,
        help_text="Per-step counts for funnel metrics; the last entry is the final-step count.",
    )


class RunningTimeCalculationInputSerializer(serializers.Serializer):
    """Inputs for estimating the recommended sample size and running time of an experiment."""

    metric_type = serializers.ChoiceField(
        choices=METRIC_TYPE_CHOICES,
        help_text=(
            "Metric type to size for. 'funnel' for conversion rates, 'mean_count' for event counts per user, "
            "'mean_sum_or_avg' for summed property values per user, 'ratio' and 'retention' for ratio-style metrics "
            "(both require baseline_stats or an explicit variance)."
        ),
    )
    minimum_detectable_effect = serializers.FloatField(
        min_value=0,
        help_text="Smallest relative change to detect, as a percentage (e.g. 5 means a 5% lift). Must be > 0.",
    )
    number_of_variants = serializers.IntegerField(
        required=False,
        default=2,
        min_value=2,
        help_text="Total number of variants including control (default 2).",
    )
    exposure_rate_per_day = serializers.FloatField(
        required=False,
        allow_null=True,
        min_value=0,
        help_text="Expected exposures per day. When provided, the response includes the recommended running time.",
    )
    baseline_value = serializers.FloatField(
        required=False,
        allow_null=True,
        help_text=(
            "Baseline metric value: conversion rate as a fraction 0-1 (funnel), average per user (mean), or the ratio "
            "(ratio/retention). Provide this or baseline_stats."
        ),
    )
    variance = serializers.FloatField(
        required=False,
        allow_null=True,
        help_text=(
            "Pre-computed variance for ratio/retention metrics. Provide this or baseline_stats when metric_type is "
            "ratio/retention and baseline_value is given directly."
        ),
    )
    baseline_stats = RunningTimeBaselineStatsSerializer(
        required=False,
        allow_null=True,
        help_text="Raw control-group statistics. When provided, the server derives baseline_value and variance.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs.get("minimum_detectable_effect", 0) <= 0:
            raise ValidationError({"minimum_detectable_effect": "Must be greater than 0."})

        has_baseline_value = attrs.get("baseline_value") is not None
        has_baseline_stats = attrs.get("baseline_stats") is not None
        if not has_baseline_value and not has_baseline_stats:
            raise ValidationError("Provide either baseline_value or baseline_stats.")

        if attrs["metric_type"] in ("ratio", "retention"):
            # A baseline value and variance must both be available. Pass them directly, or supply
            # baseline_stats with denominator_sum so the server can derive them — without it both
            # derivations return None and the endpoint silently responds with all-null results.
            has_variance = attrs.get("variance") is not None
            if not (has_baseline_value and has_variance):
                stats = attrs.get("baseline_stats")
                if not stats:
                    raise ValidationError(
                        "Ratio and retention metrics require baseline_stats, or both baseline_value and variance."
                    )
                if not stats.get("denominator_sum"):
                    raise ValidationError(
                        {"baseline_stats": {"denominator_sum": "Required to size ratio and retention metrics."}}
                    )

        return attrs


class RunningTimeCalculationResultSerializer(serializers.Serializer):
    """Estimated sample size and running time for the given inputs."""

    baseline_value = serializers.FloatField(
        allow_null=True, help_text="Baseline metric value used in the calculation (echoed or derived from stats)."
    )
    variance = serializers.FloatField(
        allow_null=True, help_text="Variance used in the calculation; null for funnel metrics (implicit in p(1-p))."
    )
    recommended_sample_size = serializers.IntegerField(
        allow_null=True, help_text="Total recommended sample size across all variants. Null if inputs are insufficient."
    )
    recommended_running_time_days = serializers.IntegerField(
        allow_null=True,
        help_text="Estimated days to reach the recommended sample size. Null when exposure_rate_per_day is omitted.",
    )
