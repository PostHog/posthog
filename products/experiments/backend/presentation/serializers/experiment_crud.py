"""Serializers for reading and writing an experiment, and for its list, matching ids and activity endpoints."""

from typing import Any, TypeGuard

from django.utils import timezone

from drf_spectacular.utils import extend_schema_field, extend_schema_serializer
from opentelemetry import trace
from pydantic import RootModel as PydanticRootModel
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from posthog.schema import (
    ExperimentApiExposureCriteria,
    ExperimentApiMetric,
    ExperimentMetric,
    ExperimentParameters,
    ExperimentRunningTimeCalculation,
)

from posthog.api.scoped_related_fields import TeamScopedPrimaryKeyRelatedField
from posthog.api.shared import UserBasicSerializer
from posthog.api.tagged_item import BULK_UPDATE_TAGS_MAX_TAGS, TAG_NAME_MAX_LENGTH, TaggedItemSerializerMixin
from posthog.models.team.team import Team

from products.access_control.backend.presentation.access_control import UserAccessControlSerializerMixin
from products.experiments.backend.experiment_service import ExperimentService
from products.experiments.backend.facade.contracts import CreateExperimentInput, ExperimentValidationError
from products.experiments.backend.facade.timeseries import METRIC_BUILDERS, apply_saved_metric_overrides
from products.experiments.backend.hogql_queries.exposure_query_logic import (
    EXPERIMENT_EXPOSURE_EVENT,
    resolve_default_exposure_event,
)
from products.experiments.backend.metric_utils import refresh_action_names_in_metric
from products.experiments.backend.models.experiment import (
    Experiment,
    ExperimentHoldout,
    experiment_has_legacy_metrics,
    get_experiment_rule,
)
from products.feature_flags.backend.api.feature_flag import MinimalFeatureFlagSerializer
from products.feature_flags.backend.facade.config import ConfigFormatError
from products.feature_flags.backend.facade.rules import ExperimentRuleError
from products.feature_flags.backend.models.feature_flag import FeatureFlag, experiment_eligibility_error

from ee.clickhouse.views.experiment_holdouts import ExperimentHoldoutSerializer
from ee.clickhouse.views.experiment_saved_metrics import ExperimentToSavedMetricSerializer

from . import flag_input, health_checks

tracer = trace.get_tracer(__name__)


class _ExperimentApiMetricsList(PydanticRootModel):
    """List wrapper for OpenAPI schema generation — the field stores an array of metrics."""

    root: list[ExperimentApiMetric]


@extend_schema_field(_ExperimentApiMetricsList)  # type: ignore[arg-type]
class ExperimentMetricsField(serializers.JSONField):
    pass


def _with_split_percent(variants: list) -> list:
    # Add split_percent to outside representation for each variant to simplify frontend logic. The internal representation only uses rollout_percentage to avoid redundancy, but the frontend needs split_percent to display the variant splits in the UI and to support editing the splits in a user-friendly way (editing rollout_percentage directly would be more complex since it's not variant-specific and needs to be inferred from the variants' split_percent values).
    return [
        {**variant, "split_percent": variant["rollout_percentage"]}
        if isinstance(variant, dict) and "rollout_percentage" in variant
        else variant
        for variant in variants
    ]


@extend_schema_field(ExperimentParameters)  # type: ignore[arg-type]
class ExperimentParametersField(serializers.JSONField):
    def to_representation(self, value: Any) -> Any:
        data: Any = super().to_representation(value)
        if isinstance(data, dict) and isinstance(data.get("feature_flag_variants"), list):
            # New dicts throughout, to avoid mutating the model instance's in-memory parameters
            data = {**data, "feature_flag_variants": _with_split_percent(data["feature_flag_variants"])}
        return data


@extend_schema_field(ExperimentApiExposureCriteria)  # type: ignore[arg-type]
class ExperimentExposureCriteriaField(serializers.JSONField):
    pass


@extend_schema_field(ExperimentRunningTimeCalculation)  # type: ignore[arg-type]
class ExperimentRunningTimeCalculationField(serializers.JSONField):
    pass


@extend_schema_field(ExperimentMetric)  # type: ignore[arg-type]
class ExperimentMetricDefinitionField(serializers.JSONField):
    pass


class ExperimentBaseSerializer(
    TaggedItemSerializerMixin, UserAccessControlSerializerMixin, serializers.ModelSerializer
):
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
            "`custom_exposure_filter` and `variant_notes` "
            "(free-text notes per variant, keyed by variant key). "
            "Flag config (variants, rollout, aggregation, payloads, experience continuity) belongs "
            "on the `feature_flag` object; send it there. For backward compatibility, config still "
            "sent through these deprecated keys is copied onto the linked flag rather than rejected, "
            "and reads project the flag's current config back into this field. "
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
    # nosemgrep: choices-need-a-class -- moved unchanged from presentation/serializers.py
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
    # nosemgrep: choices-need-a-class -- moved unchanged from presentation/serializers.py
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
            "feature_flag.active, not stored), 'exposure_frozen' (running with enrollment frozen to the "
            "already-exposed cohort while metrics keep flowing — virtual state derived from the flag's "
            "release groups, not stored), 'stopped' (ended)."
        ),
    )
    is_legacy = serializers.SerializerMethodField(
        help_text=(
            "Whether the experiment uses any legacy-engine metrics (ExperimentTrendsQuery or "
            "ExperimentFunnelsQuery). Used to flag legacy experiments and gate actions that don't support "
            "them, such as duplicate and copy-to-project."
        ),
    )
    tags = serializers.ListField(
        child=serializers.CharField(max_length=TAG_NAME_MAX_LENGTH),
        max_length=BULK_UPDATE_TAGS_MAX_TAGS,
        required=False,
        help_text="Organizational tags for this experiment (up to 100, 255 characters each).",
    )

    @extend_schema_field({"type": "string", "enum": ["draft", "running", "paused", "exposure_frozen", "stopped"]})
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
        if instance.is_rule_linked:
            self._project_rule_config(data, instance)
        else:
            self._project_feature_flag_config(data, instance.feature_flag)
        return data

    @staticmethod
    def _project_rule_config(data: dict[str, Any], experiment: Experiment) -> None:
        """The `parameters` projection of a rule-linked experiment, in the same keys as
        `_project_feature_flag_config`, so a client reads the variants and the rollout of the rule the
        way it reads them from a flag.

        A rule that cannot be read, such as one a draft's flag no longer has, projects no variants:
        the read must still return the experiment.
        """
        stored = data.get("parameters")
        parameters = dict(stored) if isinstance(stored, dict) else {}
        for key in ("aggregation_group_type_index", "rollout_percentage", "feature_flag_payloads"):
            parameters.pop(key, None)
        try:
            rule = get_experiment_rule(experiment)
        except (ExperimentRuleError, ConfigFormatError):
            parameters["feature_flag_variants"] = []
        else:
            parameters["feature_flag_variants"] = _with_split_percent(rule.variants)
            if rule.assign_variant_by is not None:
                parameters["aggregation_group_type_index"] = rule.assign_variant_by
            if rule.rollout_percentage is not None:
                parameters["rollout_percentage"] = rule.rollout_percentage
        flag = experiment.feature_flag
        if flag.ensure_experience_continuity is not None:
            parameters["ensure_experience_continuity"] = flag.ensure_experience_continuity
        else:
            parameters.pop("ensure_experience_continuity", None)
        data["parameters"] = parameters

    @staticmethod
    def _project_feature_flag_config(data: dict[str, Any], flag: FeatureFlag | None) -> None:
        """Source feature-flag config in the deprecated `parameters` projection from the linked flag.

        The flag is the source of truth for every key in ``FEATURE_FLAG_CONFIG_KEYS`` — `parameters`
        is a deprecated compatibility surface (see the experiment model's `parameters` comment).
        Reading these keys from the flag instead of the stored column lets us stop persisting the
        `parameters` mirror without changing the API response. It also keeps read-modify-write
        echoes safe: legacy rows still carry stale copies in the column until the backfill strips
        them, and a client that spreads a GET response into a save must echo the flag's live
        config, not stale values the update path would then sync onto the flag. The linked flag is
        already serialized into `data["feature_flag"]`, so this adds no queries.
        """
        if flag is None:
            return
        stored = data.get("parameters")
        # The JSON column can legally hold a non-dict on legacy rows (see migration 0026); the flag
        # is the source of truth for the keys below, so a malformed blob is simply dropped.
        parameters = dict(stored) if isinstance(stored, dict) else {}

        parameters["feature_flag_variants"] = _with_split_percent(flag.variants)

        filters = flag.get_filters()
        if flag.aggregation_group_type_index is not None:
            parameters["aggregation_group_type_index"] = flag.aggregation_group_type_index
        else:
            parameters.pop("aggregation_group_type_index", None)

        groups = filters.get("groups") or []
        if groups and groups[0].get("rollout_percentage") is not None:
            parameters["rollout_percentage"] = groups[0]["rollout_percentage"]
        else:
            parameters.pop("rollout_percentage", None)

        payloads = filters.get("payloads")
        if payloads:
            parameters["feature_flag_payloads"] = payloads
        else:
            parameters.pop("feature_flag_payloads", None)

        if flag.ensure_experience_continuity is not None:
            parameters["ensure_experience_continuity"] = flag.ensure_experience_continuity
        else:
            parameters.pop("ensure_experience_continuity", None)

        data["parameters"] = parameters


def _dedupe_metric_ordering(value: list[str] | None) -> list[str] | None:
    """Keep the first occurrence of each uuid. The ordering is a display hint, so a repeat carries no meaning."""
    if value is None:
        return None
    return list(dict.fromkeys(value))


@extend_schema_serializer(component_name="ExperimentToSavedMetric")
class ExperimentSavedMetricLinkSerializer(ExperimentToSavedMetricSerializer):
    """A shared metric's link to one experiment, as the experiment API returns it."""

    # The link model has no such attribute, so this serializer renders it as null.
    # ExperimentSerializer.to_representation sets the value from the served query.
    effective_query = ExperimentMetricDefinitionField(
        read_only=True,
        allow_null=True,
        help_text=(
            "The metric this experiment calculates for this shared metric: `query` with the per-experiment "
            "overrides from `metadata` applied (breakdowns, breakdown_limit, and funnel breakdown attribution). "
            "Results, fingerprints and queries for this metric use this definition, not `query`. "
            "Null when `query` is not an ExperimentMetric, such as a legacy shared metric "
            "(kind ExperimentTrendsQuery or ExperimentFunnelsQuery), which takes no overrides."
        ),
    )

    class Meta(ExperimentToSavedMetricSerializer.Meta):
        fields = [*ExperimentToSavedMetricSerializer.Meta.fields, "effective_query"]


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
    saved_metrics = ExperimentSavedMetricLinkSerializer(many=True, source="experimenttosavedmetric_set", read_only=True)
    saved_metrics_ids = serializers.ListField(
        child=serializers.JSONField(),
        required=False,
        allow_null=True,
        help_text="IDs of shared saved metrics to attach to this experiment. Each item has 'id' (saved metric ID) and 'metadata' with 'type' (primary or secondary).",
    )
    primary_metrics_ordered_uuids = serializers.ListField(
        child=serializers.CharField(allow_blank=False),
        required=False,
        allow_null=True,
        help_text=(
            "Display order of the primary metrics, as metric uuids. This is a display hint only: a metric "
            "not in the list renders after the listed ones in stored order, and an entry that matches no "
            "metric is ignored. Send it only to reorder metrics. Adding or removing metrics does not need it."
        ),
    )
    secondary_metrics_ordered_uuids = serializers.ListField(
        child=serializers.CharField(allow_blank=False),
        required=False,
        allow_null=True,
        help_text=(
            "Display order of the secondary metrics, as metric uuids. This is a display hint only: a metric "
            "not in the list renders after the listed ones in stored order, and an entry that matches no "
            "metric is ignored. Send it only to reorder metrics. Adding or removing metrics does not need it."
        ),
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
            "'ratio' (set numerator and denominator EventsNode entries), "
            "'quantile' (set source to an EventsNode or ActionsNode with math_property, the numeric "
            "property to measure, and quantile, the level in [0.01, 0.99], for example 0.9 for p90), or "
            "'retention' (set start_event and completion_event; pass start_event "
            '{"kind": "ExperimentExposureNode"} to start retention from the experiment\'s exposure event). '
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
            "When true, sync the flag config sent in this request (via the "
            "`feature_flag` object) to the linked feature flag. Draft experiments "
            "always sync regardless. On a running experiment, `feature_flag` config "
            "without this flag is rejected."
        ),
    )
    can_freeze_exposure = serializers.SerializerMethodField(
        help_text=(
            "Whether enrollment can be frozen right now: the experiment must be running (not draft, "
            "paused, stopped, or already frozen) and its feature flag must have release conditions "
            "that a person cohort can narrow (no group aggregation, no holdout, no early access "
            "conditions)."
        ),
    )
    resolved_exposure_event = serializers.SerializerMethodField(
        help_text=(
            "The event exposures are actually counted on when the experiment doesn't configure a "
            "custom one — `$feature_flag_called`, or `$experiment_exposure` once the team is in the "
            "rollout and the experiment started at or after the cutoff. Resolved server-side so "
            "clients display the same event the results queries read. For a draft, this is what the "
            "experiment would resolve to if launched now."
        ),
    )
    health = serializers.SerializerMethodField(
        help_text=(
            "Always null. Read the health findings from `GET /api/projects/{project_id}/experiments/{id}/health/`: "
            "problems in this experiment's configuration and its feature flag that keep it from producing "
            "trustworthy results, each with a fix."
        ),
    )
    version = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text=(
            "Optimistic-concurrency token. Reads return the experiment's current version, bumped on "
            "every update. Send the version you last read with an update to detect concurrent edits: "
            "a stale update merges concurrent changes where safe — metric collections per metric "
            "uuid, other fields per field — using the base values sent in `original_experiment`, and "
            "fails with HTTP 409 only when the same metric or field changed on both sides (or no "
            "base value was sent for a changed field). Omit to skip the check."
        ),
    )
    original_experiment = serializers.DictField(
        required=False,
        allow_null=True,
        write_only=True,
        help_text=(
            "The experiment state as the client last read it, used together with `version` to "
            "resolve concurrent edits: metric collections merge per metric uuid, and any other "
            "field the update carries merges per field against its base value here (only a "
            "same-field double edit fails). Relevant keys are metrics, metrics_secondary, "
            "saved_metrics_ids, plus the last-read values of whichever scalar fields the update "
            "writes; unknown keys are ignored. Changed fields without a base value — and, without "
            "this object, any version mismatch — fail with HTTP 409."
        ),
    )
    _create_in_folder = serializers.CharField(required=False, allow_blank=True, write_only=True)
    feature_flag_rule_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text=(
            "The experiment rule that this experiment runs on, when its feature flag has rules. Null for "
            "every other experiment. Set it only on create, together with the feature_flag_key of an "
            "existing flag with rules. When that flag has one experiment rule, it can be left out. The "
            "experiment then counts exposures on the $experiment_exposure events of this rule, and "
            "never changes the flag."
        ),
    )
    flag_cleanup_task_id = serializers.UUIDField(
        read_only=True,
        allow_null=True,
        help_text=(
            "ID of the Desktop task opened to remove the experiment's feature-flag code, when one was "
            "requested via open_cleanup_pr on end/ship_variant. Read its status via the "
            "flag_cleanup_task action."
        ),
    )
    repository = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        max_length=255,
        help_text=(
            "GitHub repository holding this experiment's feature-flag code, in `organization/repository` "
            "format. Used as the target of the flag-cleanup pull request opened via open_cleanup_pr on "
            "end/ship_variant. When not set, cleanup targets the team's only connected repository and is "
            "skipped if the team has several."
        ),
    )

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
            "feature_flag_rule_id",
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
            "flag_cleanup_task_id",
            "repository",
            "primary_metrics_ordered_uuids",
            "secondary_metrics_ordered_uuids",
            "only_count_matured_users",
            "update_feature_flag_params",
            "version",
            "original_experiment",
            "status",
            "is_legacy",
            "can_freeze_exposure",
            "resolved_exposure_event",
            "health",
            "user_access_level",
            "tags",
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
            "can_freeze_exposure",
            "resolved_exposure_event",
            "health",
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

    @extend_schema_field(serializers.BooleanField())
    def get_can_freeze_exposure(self, obj: Experiment) -> bool:
        return obj.can_freeze_exposure

    @extend_schema_field(serializers.CharField())
    def get_resolved_exposure_event(self, obj: Experiment) -> str:
        # A rule-linked experiment counts the $experiment_exposure events of its rule, whatever the rollout says.
        if obj.is_rule_linked:
            return EXPERIMENT_EXPOSURE_EVENT
        # A draft has no start_date yet, so resolve against now: that's the event it would get if
        # launched today, which is what the setup UI needs to show.
        return resolve_default_exposure_event(obj.team, obj.start_date or timezone.now())

    @extend_schema_field(health_checks.ExperimentHealthSerializer(allow_null=True))
    def get_health(self, obj: Experiment) -> dict[str, Any] | None:
        # The `health` action serves the findings, so the experiment read stays fast as checks are added.
        return None

    @tracer.start_as_current_span("ExperimentSerializer.to_representation")
    def to_representation(self, instance):
        data = super().to_representation(instance)

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

        # Note: Action name refresh is handled by ExperimentToSavedMetricSerializer.to_representation
        saved_metrics = data.get("saved_metrics", [])
        with tracer.start_as_current_span("ExperimentSerializer.saved_metric_fingerprints") as span:
            span.set_attribute("saved_metric_count", len(saved_metrics))
            calculation_keys = ExperimentService.saved_metric_calculation_keys(instance) if saved_metrics else {}
            for saved_metric in saved_metrics:
                if saved_metric.get("query"):
                    # Add fingerprint to saved metric returned from API so that the frontend knows what
                    # timeseries records to query. Computed on the effective definition (with the link
                    # overrides), the same dict the daily discovery fingerprints, so the chart read finds
                    # the rows the daily workflow wrote. The action names are part of the hash, and the
                    # serialized query carries the refreshed names, so the hash reads the stored query.
                    calculation_key = calculation_keys.get(saved_metric["id"])
                    if calculation_key is not None:
                        saved_metric["query"]["fingerprint"] = calculation_key

                    # Derived from the served query after the fingerprint is stamped, so that the effective
                    # definition carries the same fingerprint and refreshed action names. Clients send it to
                    # /query as is. The schema types it as the ExperimentMetric union, so a query outside the
                    # union (a legacy kind, or a row without a known metric_type) keeps the null default.
                    served_query = saved_metric["query"]
                    if (
                        served_query.get("kind") == "ExperimentMetric"
                        and served_query.get("metric_type") in METRIC_BUILDERS
                    ):
                        saved_metric["effective_query"] = apply_saved_metric_overrides(
                            served_query, saved_metric.get("metadata")
                        )

        return data

    def validate_saved_metrics_ids(self, value):
        ExperimentService.validate_saved_metrics_ids(value, self.context["team_id"])
        return value

    def validate_repository(self, value: str | None) -> str | None:
        if not value:
            return None
        parts = value.split("/")
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise serializers.ValidationError("Repository must be in the format organization/repository")
        return value.lower()

    def validate(self, data):
        ExperimentService.validate_experiment_date_range(data.get("start_date"), data.get("end_date"))
        data = self._normalize_feature_flag_input(data)
        return super().validate(data)

    def _normalize_feature_flag_input(self, data: dict) -> dict:
        """Validate the ``feature_flag`` config object and stash it under ``data["feature_flag"]`` for
        the service to consume in the flag's own write shape (``{filters, ensure_experience_continuity}``).

        Read from ``initial_data`` because the serializer's ``feature_flag`` field is read-only output
        (the linked flag, as MinimalFeatureFlag); this is its write counterpart. Validation runs
        through ``ExperimentFeatureFlagInputSerializer`` — the same serializer the OpenAPI request
        schema advertises.

        An object carrying a non-null ``id`` is the serialized linked flag echoed back by a
        read-modify-write client (the GET response's ``feature_flag``); treating that echo as intent
        would reapply the flag's pre-edit state, so it is ignored. An object with no config keys at
        all (e.g. a ``{"key": ...}`` stub) is likewise ignored rather than rejected, so clients that
        have always included such stubs in write bodies keep working.

        When no such object is present, a legacy caller may still be sending flag config through the
        deprecated ``parameters`` keys. Rather than reject it, we copy it into the ``feature_flag``
        object shape here so it flows through this same validate/stash path (see
        ``_deprecated_parameters_as_feature_flag_config``).
        """
        feature_flag_input = (getattr(self, "initial_data", None) or {}).get("feature_flag")
        if not self._is_feature_flag_config_input(feature_flag_input):
            feature_flag_input = self._deprecated_parameters_as_feature_flag_config()
            if feature_flag_input is None:
                return data
        if self.instance is None:
            # The service links an existing flag as-is (it may already serve traffic), so explicit
            # config here would be applied nowhere — reject instead of silently dropping it.
            flag_key = data.get("get_feature_flag_key")
            if flag_key and FeatureFlag.objects.filter(key=flag_key, team_id=self.context["team_id"]).exists():
                raise serializers.ValidationError(
                    {
                        "feature_flag": f"A feature flag with key '{flag_key}' already exists; the experiment "
                        "links to it as-is, so its config cannot be set here. Omit feature_flag to reuse "
                        "the existing flag, or edit the flag directly."
                    }
                )
        # On a running experiment the service only syncs flag config when the caller opts in;
        # without the opt-in the config would be applied nowhere and silently dropped.
        if self.instance is not None and not self.instance.is_draft and not data.get("update_feature_flag_params"):
            raise serializers.ValidationError(
                {
                    "feature_flag": "This experiment is running. To change its flag config, "
                    "send update_feature_flag_params=true (or edit the feature flag directly)."
                }
            )
        # ``id`` is the echo marker (handled above); a null id still expresses write intent, so drop
        # it before validating the config-only shape.
        config_serializer = flag_input.ExperimentFeatureFlagInputSerializer(
            data={key: value for key, value in feature_flag_input.items() if key != "id"}
        )
        config_serializer.is_valid(raise_exception=True)
        config = dict(config_serializer.validated_data)
        self._assert_flag_variants_valid(config)
        data["feature_flag"] = config
        return data

    def validate_parameters(self, value):
        # Flag config is no longer a persisted `parameters` key; it is sourced from the linked flag
        # (see ExperimentBaseSerializer._project_feature_flag_config). Strip any flag-config keys sent
        # through `parameters` so they never reach the stored column; a legacy caller sending them is
        # copied into the `feature_flag` path in _normalize_feature_flag_input instead of rejected.
        return ExperimentService._strip_feature_flag_config(value)

    @staticmethod
    def _assert_flag_variants_valid(config: dict) -> None:
        """Variant rules on the validated (already normalized) config, raised as plain top-level
        errors so the messages surface directly to LLM/API callers. Absent or empty variants are
        allowed here — the service fills in the default control/test pair."""
        variants = ((config.get("filters") or {}).get("multivariate") or {}).get("variants")
        if not variants:
            return
        error = experiment_eligibility_error(variants)
        if error:
            raise serializers.ValidationError(error)

    @staticmethod
    def _is_feature_flag_config_input(feature_flag_input: Any) -> TypeGuard[dict]:
        """Whether the request carries a genuine ``feature_flag`` config object (write intent), as
        opposed to nothing, a read-only echo of the linked flag (non-null ``id``), or a bare stub
        with no config keys."""
        return (
            isinstance(feature_flag_input, dict)
            and feature_flag_input.get("id") is None
            and any(key in feature_flag_input for key in ("filters", "ensure_experience_continuity"))
        )

    def _deprecated_parameters_as_feature_flag_config(self) -> dict | None:
        """Copy flag config still sent through the deprecated ``parameters`` keys into a
        ``feature_flag`` config object, so legacy callers flow through the same build/sync path as
        the ``feature_flag`` object rather than being rejected. Read from ``initial_data`` because
        ``validate_parameters`` has already stripped these keys from the validated parameters.

        Returns ``None`` when ``parameters`` carries no flag config, or when every key merely echoes
        the linked flag's current projected config — a read-modify-write no-op that must stay a
        no-op (not resync the flag, not trip the running-experiment guard)."""
        raw_parameters = (getattr(self, "initial_data", None) or {}).get("parameters")
        if not isinstance(raw_parameters, dict):
            return None
        present = [key for key in ExperimentService.FEATURE_FLAG_CONFIG_KEYS if key in raw_parameters]
        if not present:
            return None

        instance = self.instance
        flag = instance.feature_flag if instance is not None else None
        projected: dict[str, Any] = {}
        if instance is not None and flag is not None:
            projection: dict[str, Any] = {}
            if instance.is_rule_linked:
                self._project_rule_config(projection, instance)
            else:
                self._project_feature_flag_config(projection, flag)
            projected = projection.get("parameters") or {}

        changed = {
            key: raw_parameters[key]
            for key in present
            if not self._flag_config_echo_matches(key, raw_parameters[key], projected.get(key))
        }
        if not changed:
            return None
        # Assemble the flag's native write shape from the changed deprecated keys. The service owns
        # this translation (it is the reverse of the read projection) so both the HTTP path and direct
        # service callers build the config identically.
        config = ExperimentService._feature_flag_config_from_parameters(changed)
        # Surface to update_experiment that a real flag-config write (not a faithful echo) came from
        # the deprecated `parameters` surface, for the "experiment updated" deprecation-bake telemetry.
        self._deprecated_flag_config_changed = config is not None
        return config

    @staticmethod
    def _flag_config_echo_matches(key: str, sent: Any, projected: Any) -> bool:
        if key == "feature_flag_variants":
            # The read projection adds split_percent; normalize both sides to the flag's native
            # shape (split_percent -> rollout_percentage) so a faithful echo compares equal.
            return flag_input._normalized_flag_variants(sent or []) == flag_input._normalized_flag_variants(
                projected or []
            )
        return sent == projected

    def validate_running_time_calculation(self, value):
        ExperimentService.validate_running_time_calculation(value)
        return value

    def validate_excluded_variants(self, value):
        ExperimentService.validate_excluded_variants(value)
        return value

    def validate_primary_metrics_ordered_uuids(self, value: list[str] | None) -> list[str] | None:
        return _dedupe_metric_ordering(value)

    def validate_secondary_metrics_ordered_uuids(self, value: list[str] | None) -> list[str] | None:
        return _dedupe_metric_ordering(value)

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
            feature_flag_config=self.validated_data.get("feature_flag"),
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
            repository=self.validated_data.get("repository"),
            holdout_id=holdout_id,
            filters=self.validated_data.get("filters"),
            scheduling_config=self.validated_data.get("scheduling_config"),
            create_in_folder=self.validated_data.get("_create_in_folder"),
            allow_unknown_events=self.validated_data.get("allow_unknown_events", False),
            serializer_context=self.context,
            feature_flag_rule_id=self.validated_data.get("feature_flag_rule_id"),
        )

    def create(self, validated_data: dict, *args: Any, **kwargs: Any) -> Experiment:
        """Create experiment via facade layer."""
        from products.experiments.backend.facade import create_experiment

        # Pop fields not needed for DTO but needed for validation
        validated_data.pop("update_feature_flag_params", None)
        # Tags live in the shared TaggedItem table, not on the experiment row; pop them so the
        # expected_fields check below doesn't reject them as an unknown key.
        tags = validated_data.pop("tags", None)
        # Concurrency keys are update-only; ignore them on create so clients can share payload builders
        validated_data.pop("version", None)
        validated_data.pop("original_experiment", None)

        # Check for unexpected fields
        expected_fields = {
            "name",
            "get_feature_flag_key",
            "description",
            "type",
            "parameters",
            "feature_flag",
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
            "repository",
            "holdout",
            "filters",
            "scheduling_config",
            "_create_in_folder",
            "allow_unknown_events",
            "feature_flag_rule_id",
        }
        unexpected = set(validated_data.keys()) - expected_fields
        if unexpected:
            raise ValidationError(f"Can't create keys: {', '.join(sorted(unexpected))} on Experiment")

        # Convert to facade DTO
        input_dto = self.to_facade_dto()

        # Route through facade
        team = Team.objects.get(id=self.context["team_id"])
        try:
            experiment_dto = create_experiment(
                team=team,
                user=self.context["request"].user,
                input_dto=input_dto,
            )
        except ExperimentValidationError as error:
            raise ValidationError(str(error)) from error

        # Load instance for return (DRF expects model instance)
        instance = Experiment.objects.get(id=experiment_dto.id)
        self._attempt_set_tags(tags, instance)
        return instance

    def update(self, instance: Experiment, validated_data: dict, *args: Any, **kwargs: Any) -> Experiment:
        allow_unknown_events = validated_data.pop("allow_unknown_events", False)
        feature_flag_config = validated_data.pop("feature_flag", None)
        tags = validated_data.pop("tags", None)
        # The rule is chosen on create. A client that sends back what it read changes nothing.
        if "feature_flag_rule_id" in validated_data:
            if validated_data.pop("feature_flag_rule_id") != instance.feature_flag_rule_id:
                raise ValidationError("feature_flag_rule_id cannot change after the experiment is created.")
        team = Team.objects.get(id=self.context["team_id"])
        service = ExperimentService(team=team, user=self.context["request"].user)
        updated_instance = service.update_experiment(
            instance,
            validated_data,
            feature_flag_config=feature_flag_config,
            serializer_context=self.context,
            allow_unknown_events=allow_unknown_events,
            deprecated_flag_config_changed=getattr(self, "_deprecated_flag_config_changed", False),
        )
        self._attempt_set_tags(tags, updated_instance)
        return updated_instance


# Advertises the writable feature_flag input in the OpenAPI request schema. PostHog's drf-spectacular
# config doesn't split request/response components, so feature_flag stays read-only (MinimalFeatureFlag)
# on ExperimentSerializer for the response, and this subclass carries the writable input for the
# request. Referenced via extend_schema(request=...) on the create/update/partial_update methods.
class ExperimentWriteSerializer(ExperimentSerializer):
    """Experiment write payload. Identical to Experiment, plus the writable `feature_flag` config input."""

    feature_flag = flag_input.ExperimentFeatureFlagInputSerializer(  # type: ignore[assignment]
        required=False,
        help_text=(
            "Feature-flag config for the experiment, in the flag's own filters shape. The linked flag "
            "is the source of truth for variants, rollout, aggregation, payloads, and experience "
            "continuity: send config here instead of the deprecated `parameters` keys. On a running "
            "experiment, also send `update_feature_flag_params=true`. Cannot be combined with the key "
            "of a pre-existing feature flag on create (the experiment links to it as-is)."
        ),
    )

    class Meta(ExperimentSerializer.Meta):
        # feature_flag is writable in this schema-only variant, so it must leave read_only_fields.
        read_only_fields = [field for field in ExperimentSerializer.Meta.read_only_fields if field != "feature_flag"]


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
            "tags",
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


class ExperimentMatchingIdsResponseSerializer(serializers.Serializer):
    ids = serializers.ListField(
        child=serializers.IntegerField(),
        help_text="IDs of all experiments matching the current list filters that the user can edit.",
    )
    total = serializers.IntegerField(help_text="Number of matching editable experiments.")


class ExperimentActivityQuerySerializer(serializers.Serializer):
    limit = serializers.IntegerField(required=False, default=10, min_value=1, help_text="Number of items per page")
    page = serializers.IntegerField(required=False, default=1, min_value=1, help_text="Page number")
