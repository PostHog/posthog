"""
TEMPORARY: This file is in transition.

Current state: Moved from ee/clickhouse/views/experiments.py to products/experiments/backend/presentation/
to break down the monolith incrementally. Serializers split into serializers.py (PR #2) but this file
still directly imports from service/models layers (violating product architecture temporarily).

This will be refactored incrementally in subsequent PRs to match the product architecture pattern.
"""

import json
import asyncio
from typing import Any, Literal, cast

from django.conf import settings
from django.db.models import BooleanField, Case, Exists, OuterRef, Prefetch, Q, QuerySet, Value, When
from django.utils.text import slugify

from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema, extend_schema_view
from opentelemetry import trace
from rest_framework import serializers, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.cohort import CohortSerializer
from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.auth import IDJagAccessTokenAuthentication, OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication
from posthog.models.filters.filter import Filter
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin
from posthog.temporal.common.client import sync_connect
from posthog.temporal.experiments.models import ExperimentTimeseriesRecalculationWorkflowInputs
from posthog.user_permissions import UserPermissions

from products.approvals.backend.mixins import ApprovalHandlingMixin
from products.experiments.backend.experiment_service import ExperimentService
from products.experiments.backend.llm_metric_templates import build_template, list_templates

# TODO: Route through facade instead of direct import
from products.experiments.backend.models.experiment import (
    LEGACY_METRIC_KINDS,
    Experiment,
    ExperimentMetricsRecalculation,
    ExperimentTimeseriesRecalculation,
    ExperimentToSavedMetric,
    experiment_has_legacy_metrics,
)
from products.experiments.backend.presentation.serializers import (
    ArchiveExperimentSerializer,
    CopyExperimentToProjectSerializer,
    CreateFromPromptInputSerializer,
    EndExperimentSerializer,
    ExperimentBasicSerializer,
    ExperimentMetricsRecalculationSerializer,
    ExperimentSerializer,
    RecalculateMetricsRequestSerializer,
    RunningTimeCalculationInputSerializer,
    RunningTimeCalculationResultSerializer,
    ShipVariantSerializer,
)
from products.experiments.backend.recalculation import (
    build_job_payload,
    build_timeseries_cold_start_payload,
    get_latest_recalculation,
    get_recalculation_by_id,
    get_run_results,
    request_recalculation,
)
from products.experiments.backend.running_time_calculator import (
    BaselineStats,
    calculate_baseline_value,
    calculate_running_time_days,
    calculate_sample_size,
    calculate_variance,
    calculate_variance_from_stats,
)
from products.experiments.backend.temporal.models import (
    ExperimentMetricsRecalculationWorkflowInputs as MetricsRecalcInputs,
)
from products.feature_flags.backend.api.feature_flag import FeatureFlagSerializer
from products.feature_flags.backend.models.evaluation_context import FeatureFlagEvaluationContext
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.product_tours.backend.models import ProductTour
from products.surveys.backend.models import Survey

from ee.clickhouse.queries.experiments.utils import requires_flag_warning

tracer = trace.get_tracer(__name__)

# Heavy JSON columns the list view never renders. Deferred for the list action so large
# pages don't pay to read/decode detail-only data; the full serializer still loads them
# for retrieve/update. None of these are touched by the list filters or status derivation.
LIST_DEFERRED_FIELDS = (
    "metrics",
    "metrics_secondary",
    "secondary_metrics",
    "exposure_criteria",
    "stats_config",
    "scheduling_config",
    "filters",
    "primary_metrics_ordered_uuids",
    "secondary_metrics_ordered_uuids",
)

# The viewset's `list` method shadows the builtin `list` in the class namespace, so a
# `list[str]` annotation there resolves to that method (a runtime crash, and a mypy error).
# Reference this module-level alias instead.
RequiredScopes = list[str]


def flag_evaluation_contexts_prefetch() -> Prefetch:
    return Prefetch(
        "feature_flag__flag_evaluation_contexts",
        queryset=FeatureFlagEvaluationContext.objects.select_related("evaluation_context"),
    )


def list_is_legacy_annotation() -> Case:
    """DB-side `is_legacy` for the list endpoint, mirroring ``experiment_has_legacy_metrics`` in SQL.

    The list serializer omits metrics, so it can't compute legacy-ness in Python without
    re-reading the deferred JSON columns (one query per row). Instead we annotate the flag in the
    single list query: a JSONB containment check on the inline metrics plus an ``EXISTS`` over the
    saved metrics. The metric columns are referenced only in the predicate, so they stay out of the
    SELECT output and the response — the deferral still holds.
    """
    inline_legacy = Q()
    for kind in LEGACY_METRIC_KINDS:
        inline_legacy |= Q(metrics__contains=[{"kind": kind}]) | Q(metrics_secondary__contains=[{"kind": kind}])
    saved_legacy = Exists(
        ExperimentToSavedMetric.objects.filter(
            experiment=OuterRef("pk"),
            saved_metric__query__kind__in=LEGACY_METRIC_KINDS,
        )
    )
    return Case(
        When(inline_legacy | saved_legacy, then=Value(True)),
        default=Value(False),
        output_field=BooleanField(),
    )


def _build_prompt_variants(versions: list[int]) -> list[dict[str, Any]]:
    """Build N feature flag variants from an ordered list of prompt versions.

    First variant is keyed "control" (required by ExperimentService._validate_existing_flag
    when the experiment is later launched). For the standard 2-variant case the second is
    keyed "test", matching the rest of the codebase's defaults. For N >= 3 the trailing
    variants are keyed "test-1", "test-2", … so each key stays unique.
    The human-readable prompt version goes in the variant name so chart legends stay readable.
    Splits are integers summing to 100; the last variant absorbs any remainder.
    """
    n = len(versions)
    base = 100 // n
    splits = [base] * n
    splits[-1] += 100 - base * n
    variants: list[dict[str, Any]] = []
    for i, (version, split) in enumerate(zip(versions, splits)):
        if i == 0:
            key = "control"
        elif n == 2:
            key = "test"
        else:
            key = f"test-{i}"
        variants.append({"key": key, "name": f"v{version}", "rollout_percentage": split})
    return variants


def _slugify_feature_flag_key(name: str, *, team_id: int) -> str:
    """Slugify a feature flag name, adding a numeric suffix if the slug already exists for this team."""
    base = slugify(name)[:200] or "experiment"
    candidate = base
    suffix = 2
    while FeatureFlag.objects.filter(team_id=team_id, key=candidate).exists():
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


@extend_schema_view(
    # PATCH /experiments/{id}/
    # DRF mixin calls implementation at ExperimentSerializer.update
    partial_update=extend_schema(
        description="Update an experiment. Use this to modify experiment properties such as name, description, metrics, variants, and configuration. Metrics can be added, changed and removed at any time.",
    ),
    # POST /experiments/ — DRF mixin calls ExperimentSerializer.create
    create=extend_schema(
        description="Create a new experiment in draft status with optional metrics.",
    ),
    # GET /experiments/{id}/ — DRF mixin, read-only serialization via ExperimentSerializer
    retrieve=extend_schema(
        description="Retrieve a single experiment by ID, including its current status, metrics, feature flag, and results metadata.",
    ),
    # GET /experiments/ — DRF mixin, filtering via ExperimentService.filter_experiments_queryset
    list=extend_schema(
        description="List experiments for the current project. Supports filtering by status and archival state.",
        parameters=[
            OpenApiParameter(
                name="status",
                location=OpenApiParameter.QUERY,
                type=str,
                enum=["draft", "running", "paused", "stopped", "complete", "all"],
                description=(
                    'Filter by experiment status. "running" and "paused" are mutually exclusive: "running" returns '
                    'launched experiments with an active feature flag, "paused" returns launched experiments whose '
                    'feature flag is deactivated. "complete" is an alias for "stopped". "all" disables status '
                    "filtering."
                ),
                required=False,
            ),
            OpenApiParameter(
                name="archived",
                location=OpenApiParameter.QUERY,
                type=bool,
                description="Filter by archived state. Defaults to non-archived experiments only.",
                required=False,
            ),
            OpenApiParameter(
                name="feature_flag_id",
                location=OpenApiParameter.QUERY,
                type=int,
                description="Filter to experiments linked to the given feature flag ID.",
                required=False,
            ),
            OpenApiParameter(
                name="created_by_id",
                location=OpenApiParameter.QUERY,
                type=str,
                description=(
                    "Filter to experiments created by the given user(s). Accepts a single user ID, "
                    "or a JSON-encoded / comma-separated list of user IDs to match any of them."
                ),
                required=False,
            ),
            OpenApiParameter(
                name="search",
                location=OpenApiParameter.QUERY,
                type=str,
                description="Free-text search applied to the experiment name (case-insensitive).",
                required=False,
            ),
            OpenApiParameter(
                name="prompt_name",
                location=OpenApiParameter.QUERY,
                type=str,
                description=(
                    "Filter to experiments created from an LLM prompt with this name. "
                    "Matches experiments whose parameters.prompt_metadata.name equals the given value."
                ),
                required=False,
            ),
            OpenApiParameter(
                name="event",
                location=OpenApiParameter.QUERY,
                type=str,
                description=(
                    "Filter to experiments whose metrics reference this event name. Matches events used "
                    "directly in metric queries as well as events behind any actions those metrics reference."
                ),
                required=False,
            ),
            OpenApiParameter(
                name="order",
                location=OpenApiParameter.QUERY,
                type=str,
                description=(
                    "Field to order by. Prefix with '-' for descending. Allowlisted fields include name, "
                    "created_at, updated_at, start_date, end_date, duration, and status."
                ),
                required=False,
            ),
        ],
    ),
    # DELETE /experiments/{id}/
    # Logic and API docs defined in posthog/api/forbid_destroy_model.py (hard delete not allowed)
)
class EnterpriseExperimentsViewSet(
    # ApprovalHandlingMixin converts ApprovalRequired exceptions (raised by
    # FeatureFlagSerializer in ship_variant) into 409 HTTP responses. The
    # approval check itself lives in the service layer — this mixin is only
    # responsible for exception-to-response formatting.
    ApprovalHandlingMixin,
    ForbidDestroyModel,
    TeamAndOrgViewSetMixin,
    AccessControlViewSetMixin,
    viewsets.ModelViewSet,
):
    scope_object: Literal["experiment"] = "experiment"
    serializer_class = ExperimentSerializer
    queryset = (
        Experiment.objects.select_related(
            "team",
            "feature_flag",
            "created_by",
            "exposure_cohort",
            "holdout__created_by",
        )
        .prefetch_related(
            flag_evaluation_contexts_prefetch(),
            Prefetch(
                # order_by("id") keeps saved metrics in insertion order — select_related below adds
                # joins that would otherwise leave the row order unspecified.
                "experimenttosavedmetric_set",
                queryset=ExperimentToSavedMetric.objects.select_related("saved_metric", "experiment__team").order_by(
                    "id"
                ),
            ),
        )
        .all()
    )
    ordering = "-created_at"

    def get_serializer_class(self):
        # The list view renders only scalar/flag fields; use the lightweight serializer so the
        # heavy metric fields (and their prefetch/fingerprinting) are skipped — see safely_get_queryset.
        if self.action == "list":
            return ExperimentBasicSerializer
        return ExperimentSerializer

    @tracer.start_as_current_span("ExperimentViewSet.list")
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    @tracer.start_as_current_span("ExperimentViewSet.safely_get_queryset")
    def safely_get_queryset(self, queryset) -> QuerySet:
        request = getattr(self, "request", None)
        if self.action == "list":
            # ExperimentBasicSerializer omits metrics/saved_metrics, so drop the saved-metric
            # prefetch and defer the heavy JSON columns. The ?event= filter reads metrics via its
            # own values_list/queries, so it is unaffected by the defer. is_legacy is computed in
            # SQL (see list_is_legacy_annotation) so the badge/guards survive without loading metrics.
            queryset = (
                queryset.prefetch_related(None)
                .prefetch_related(flag_evaluation_contexts_prefetch())
                .defer(*LIST_DEFERRED_FIELDS)
                .annotate(is_legacy_annotation=list_is_legacy_annotation())
            )
        service = ExperimentService(team=self.team, user=getattr(request, "user", None))
        return service.filter_experiments_queryset(
            queryset,
            action=self.action,
            query_params=getattr(request, "query_params", None),
            request_data=getattr(request, "data", None),
        )

    def dangerously_get_required_scopes(self, request: Request, view: Any) -> RequiredScopes | None:
        # Archiving with disable_feature_flag=true also disables and archives the linked flag,
        # which is a feature_flag write — require feature_flag:write on the token, not just
        # experiment:write. Other actions fall back to their own scopes.
        if self.action == "archive":
            scopes = ["experiment:write"]
            # Use DRF's own truthy set so this matches how ArchiveExperimentSerializer parses the field.
            if request.data.get("disable_feature_flag", False) in serializers.BooleanField.TRUE_VALUES:
                scopes.append("feature_flag:write")
            return scopes
        # Ending or shipping with open_cleanup_pr=true starts a Code task that opens a pull
        # request. Starting a task is a task write, so require task:write on the token, not
        # just experiment:write.
        if self.action in ("end", "ship_variant"):
            scopes = ["experiment:write"]
            if request.data.get("open_cleanup_pr", False) in serializers.BooleanField.TRUE_VALUES:
                scopes.append("task:write")
            return scopes
        return None

    def _token_can_write_feature_flag(self, request: Request) -> bool:
        """Whether the request's token carries feature_flag:write.

        Archiving/unarchiving an experiment can touch the linked flag's archived/active
        state as a side effect; that is a feature_flag write and must not be reachable with
        only experiment:write. Session and other non-token auth aren't scope-limited (gated by
        access control instead), mirroring APIScopePermission.
        """
        authenticator = request.successful_authenticator
        if isinstance(authenticator, PersonalAPIKeyAuthentication):
            scopes = authenticator.personal_api_key.scopes or []
        elif isinstance(authenticator, OAuthAccessTokenAuthentication):
            scopes = (authenticator.access_token.scope or "").split()
        elif isinstance(authenticator, IDJagAccessTokenAuthentication):
            scopes = list(authenticator.scopes or [])
        else:
            return True
        return "*" in scopes or "feature_flag:write" in scopes

    # ******************************************
    # /projects/:id/experiments/requires_flag_implementation
    #
    # Returns current results of an experiment, and graphs
    # 1. Probability of success
    # 2. Funnel breakdown graph to display
    # ******************************************
    @action(methods=["GET"], detail=False, required_scopes=["experiment:read"])
    def requires_flag_implementation(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        filter = Filter(request=request, team=self.team).shallow_clone({"date_from": "-7d", "date_to": ""})

        warning = requires_flag_warning(filter, self.team)

        return Response({"result": warning})

    @extend_schema(
        request=None,
        responses=ExperimentSerializer,
    )
    @action(methods=["POST"], detail=True, required_scopes=["experiment:write"])
    def launch(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Launch a draft experiment.

        Validates the experiment is in draft state, activates its linked feature flag,
        sets start_date to the current server time, and transitions the experiment to running.
        Returns 400 if the experiment has already been launched or if the feature flag
        configuration is invalid (e.g. missing "control" variant or fewer than 2 variants).
        """
        experiment: Experiment = self.get_object()
        service = ExperimentService(team=self.team, user=request.user)
        launched_experiment = service.launch_experiment(experiment, request=request)
        return Response(ExperimentSerializer(launched_experiment, context=self.get_serializer_context()).data)

    @extend_schema(
        request=ArchiveExperimentSerializer,
        responses=ExperimentSerializer,
    )
    # required_scopes is computed by dangerously_get_required_scopes — disabling the linked
    # flag additionally requires feature_flag:write.
    @action(methods=["POST"], detail=True)
    def archive(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Archive an ended experiment.

        Hides the experiment from the default list view. The experiment can be
        restored at any time by updating archived=false. When the linked feature
        flag is still enabled, pass disable_feature_flag=true to also disable and
        archive it. Returns 400 if the experiment is already archived or has not
        ended yet.
        """
        experiment: Experiment = self.get_object()
        request_serializer = ArchiveExperimentSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        service = ExperimentService(team=self.team, user=request.user)
        archived_experiment = service.archive_experiment(
            experiment,
            disable_feature_flag=request_serializer.validated_data["disable_feature_flag"],
            can_write_feature_flag=self._token_can_write_feature_flag(request),
            request=request,
        )
        return Response(ExperimentSerializer(archived_experiment, context=self.get_serializer_context()).data)

    @extend_schema(
        request=None,
        responses=ExperimentSerializer,
    )
    @action(methods=["POST"], detail=True, required_scopes=["experiment:write"])
    def unarchive(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Unarchive an archived experiment.

        Restores the experiment to the default list view. Returns 400 if the
        experiment is not currently archived.
        """
        experiment: Experiment = self.get_object()
        service = ExperimentService(team=self.team, user=request.user)
        unarchived_experiment = service.unarchive_experiment(
            experiment,
            can_write_feature_flag=self._token_can_write_feature_flag(request),
            request=request,
        )
        return Response(ExperimentSerializer(unarchived_experiment, context=self.get_serializer_context()).data)

    @extend_schema(
        request=EndExperimentSerializer,
        responses=ExperimentSerializer,
    )
    # required_scopes is computed by dangerously_get_required_scopes; opening a cleanup PR
    # additionally requires task:write.
    @action(methods=["POST"], detail=True)
    def end(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        End a running experiment without shipping a variant.

        Sets end_date to now and marks the experiment as stopped. The feature
        flag is NOT modified — users continue to see their assigned variants
        and exposure events ($feature_flag_called) continue to be recorded.
        However, only data up to end_date is included in experiment results.

        Use this when:

        - You want to freeze the results window without changing which variant
          users see.
        - A variant was already shipped manually via the feature flag UI and
          the experiment just needs to be marked complete.

        The end_date can be adjusted after ending via PATCH if it needs to be
        backdated (e.g. to match when the flag was actually paused).

        Other options:
        - Use ship_variant to end the experiment AND roll out a single variant to 100%% of users.
        - Use pause to deactivate the flag without ending the experiment (stops variant assignment but does not freeze results).

        Returns 400 if the experiment is not running.
        """
        experiment: Experiment = self.get_object()
        request_serializer = EndExperimentSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        service = ExperimentService(team=self.team, user=request.user)
        ended_experiment = service.end_experiment(
            experiment,
            conclusion=request_serializer.validated_data.get("conclusion"),
            conclusion_comment=request_serializer.validated_data.get("conclusion_comment"),
            open_cleanup_pr=request_serializer.validated_data["open_cleanup_pr"],
            request=request,
        )
        return Response(ExperimentSerializer(ended_experiment, context=self.get_serializer_context()).data)

    @extend_schema(
        request=ShipVariantSerializer,
        responses=ExperimentSerializer,
    )
    # required_scopes is computed by dangerously_get_required_scopes; opening a cleanup PR
    # additionally requires task:write.
    @action(methods=["POST"], detail=True, url_path="ship_variant")
    def ship_variant(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Ship a variant and (optionally) end the experiment.

        Updates the feature flag so the selected variant gets 100% of the variant
        distribution. By default, existing release conditions on the flag are preserved
        untouched — the variant is served only to users who already match them. Pass
        ``release_to_everyone: true`` to also prepend a catch-all release condition
        that rolls the variant out to 100% of users (overrides any existing release
        conditions on the flag).

        Can be called on both running and stopped experiments. If the experiment is
        still running, it will also be ended (end_date set and status marked as stopped).
        If the experiment has already ended, only the flag is rewritten - this supports
        the "end first, ship later" workflow.

        If an approval policy requires review before changes on the flag take effect,
        the API returns 409 with a change_request_id. The experiment is NOT ended until
        the change request is approved and the user retries.

        Returns 400 if the experiment is in draft state, the variant_key is not found
        on the flag, or the experiment has no linked feature flag.
        """
        experiment: Experiment = self.get_object()
        request_serializer = ShipVariantSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        service = ExperimentService(team=self.team, user=request.user)
        shipped_experiment = service.ship_variant(
            experiment,
            variant_key=request_serializer.validated_data["variant_key"],
            release_to_everyone=request_serializer.validated_data["release_to_everyone"],
            conclusion=request_serializer.validated_data.get("conclusion"),
            conclusion_comment=request_serializer.validated_data.get("conclusion_comment"),
            open_cleanup_pr=request_serializer.validated_data["open_cleanup_pr"],
            request=request,
        )
        return Response(ExperimentSerializer(shipped_experiment, context=self.get_serializer_context()).data)

    @extend_schema(
        request=None,
        responses=ExperimentSerializer,
    )
    @action(methods=["POST"], detail=True, required_scopes=["experiment:write"])
    def pause(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Pause a running experiment.

        Deactivates the linked feature flag so it is no longer returned by the
        /decide endpoint. Users fall back to the application default (typically
        the control experience), and no new exposure events are recorded (i.e.
        $feature_flag_called is not fired).
        Returns 400 if the experiment is not running or is already paused.
        """
        experiment: Experiment = self.get_object()
        service = ExperimentService(team=self.team, user=request.user)
        paused_experiment = service.pause_experiment(experiment, request=request)
        return Response(ExperimentSerializer(paused_experiment, context=self.get_serializer_context()).data)

    @extend_schema(
        request=None,
        responses=ExperimentSerializer,
    )
    @action(methods=["POST"], detail=True, required_scopes=["experiment:write"])
    def resume(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Resume a paused experiment.

        Reactivates the linked feature flag so it is returned by /decide again.
        Users are re-bucketed deterministically into the same variants they had
        before the pause, and exposure tracking resumes.
        Returns 400 if the experiment is not running or is not paused.
        """
        experiment: Experiment = self.get_object()
        service = ExperimentService(team=self.team, user=request.user)
        resumed_experiment = service.resume_experiment(experiment, request=request)
        return Response(ExperimentSerializer(resumed_experiment, context=self.get_serializer_context()).data)

    @extend_schema(
        request=None,
        responses=ExperimentSerializer,
    )
    @action(methods=["POST"], detail=True, required_scopes=["experiment:write"])
    def reset(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Reset an experiment back to draft state.

        Clears start/end dates, conclusion, and archived flag. The feature
        flag is left unchanged — users continue to see their assigned variants.

        Previously collected events still exist but won't be included in
        results unless the start date is manually adjusted after re-launch.

        Returns 400 if the experiment is already in draft state.
        """
        experiment: Experiment = self.get_object()
        service = ExperimentService(team=self.team, user=request.user)
        reset_experiment = service.reset_experiment(experiment, request=request)
        return Response(ExperimentSerializer(reset_experiment, context=self.get_serializer_context()).data)

    @action(methods=["POST"], detail=True, required_scopes=["experiment:write"])
    def duplicate(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        source_experiment: Experiment = self.get_object()

        if experiment_has_legacy_metrics(source_experiment):
            return Response(
                {"detail": "Duplication is not supported for experiments using legacy metrics."},
                status=400,
            )

        feature_flag_key = request.data.get("feature_flag_key")
        name = request.data.get("name")

        service = ExperimentService(team=self.team, user=request.user)
        duplicate_experiment = service.duplicate_experiment(
            source_experiment,
            feature_flag_key=feature_flag_key,
            name=name,
            serializer_context=self.get_serializer_context(),
        )

        return Response(
            ExperimentSerializer(duplicate_experiment, context=self.get_serializer_context()).data, status=201
        )

    @extend_schema(
        request=CreateFromPromptInputSerializer,
        responses=ExperimentSerializer,
    )
    @action(
        methods=["POST"],
        detail=False,
        url_path="create_from_prompt",
        # Endpoint reads an LLMPrompt's name + versions to validate input, so the caller
        # needs prompt-read scope in addition to experiment-write. Without llm_prompt:read,
        # a token with experiment:write alone could enumerate existing prompts by guessing
        # names.
        required_scopes=["experiment:write", "llm_prompt:read"],
    )
    def create_from_prompt(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Create an experiment that compares N versions of an LLM prompt using a metric template.

        The user picks 2+ versions of an existing LLMPrompt and 1+ metric templates
        (cost / latency / eval_pass_rate). The endpoint builds the matching variants
        (control + test-N, each named after its prompt version) and attaches one
        metric per selected template, each scoped to the prompt's $ai_prompt_name.
        Resulting experiment is in draft state.
        """
        serializer = CreateFromPromptInputSerializer(data=request.data, context={"team": self.team})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        prompt_name: str = data["prompt_name"]
        versions: list[int] = data["versions"]
        templates: list[str] = data["templates"]
        versions_label = ", ".join(f"v{v}" for v in versions)
        templates_label = ", ".join(templates)
        name = data.get("name") or f"{prompt_name}: {versions_label} ({templates_label})"
        feature_flag_key = data.get("feature_flag_key") or _slugify_feature_flag_key(name, team_id=self.team.id)

        metrics: list[dict[str, Any]] = []
        for template in templates:
            metric_dict = build_template(template, prompt_name).model_dump(exclude_none=True)
            metric_dict.setdefault("kind", "ExperimentMetric")
            metrics.append(metric_dict)

        variants = _build_prompt_variants(versions)
        # Encode (prompt_name, prompt_version) as a JSON payload per variant so the SDK can
        # read it via flags.get_flag_payload(...) instead of hard-coding a variant→version map.
        feature_flag_payloads = {
            variant["key"]: json.dumps({"prompt_name": prompt_name, "prompt_version": version})
            for variant, version in zip(variants, versions)
        }

        service = ExperimentService(team=self.team, user=request.user)
        experiment = service.create_experiment(
            name=name,
            feature_flag_key=feature_flag_key,
            description=data.get("description", ""),
            parameters={
                "feature_flag_variants": variants,
                "feature_flag_payloads": feature_flag_payloads,
                "rollout_percentage": 100,
                "prompt_metadata": {
                    "name": prompt_name,
                    "templates": templates,
                    "versions": versions,
                },
            },
            metrics=metrics,
            serializer_context=self.get_serializer_context(),
            allow_unknown_events=True,
        )

        return Response(
            ExperimentSerializer(experiment, context=self.get_serializer_context()).data,
            status=201,
        )

    @extend_schema(
        request=None,
        responses={
            200: {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                        "label": {"type": "string"},
                        "description": {"type": "string"},
                    },
                    "required": ["key", "label", "description"],
                },
            }
        },
    )
    @action(
        methods=["GET"],
        detail=False,
        url_path="prompt_templates",
        required_scopes=["experiment:read"],
    )
    def prompt_templates(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """List the LLM metric templates that can be passed to `create_from_prompt`."""
        return Response(list_templates())

    @extend_schema(
        request=CopyExperimentToProjectSerializer,
        responses=ExperimentSerializer,
    )
    @action(methods=["POST"], detail=True, url_path="copy_to_project", required_scopes=["experiment:write"])
    def copy_to_project(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Copy an experiment into another project in the same organization as a new draft."""
        source_experiment: Experiment = self.get_object()

        if experiment_has_legacy_metrics(source_experiment):
            return Response(
                {"detail": "Copying is not supported for experiments using legacy metrics."},
                status=400,
            )

        request_serializer = CopyExperimentToProjectSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)

        target_team_id = request_serializer.validated_data["target_team_id"]
        target_team = Team.objects.filter(id=target_team_id, organization_id=self.team.organization_id).first()
        if target_team is None:
            return Response({"detail": "Target team not found."}, status=404)

        user_permissions = UserPermissions(user=cast(User, request.user))
        target_team_permissions = user_permissions.team(target_team)
        effective_level = target_team_permissions.effective_membership_level
        if effective_level is None or effective_level < OrganizationMembership.Level.MEMBER:
            return Response({"detail": "You do not have write access to the target project."}, status=403)

        feature_flag_key = request_serializer.validated_data.get("feature_flag_key")
        name = request_serializer.validated_data.get("name")

        service = ExperimentService(team=self.team, user=request.user)
        new_experiment = service.copy_experiment_to_project(
            source_experiment,
            target_team,
            feature_flag_key=feature_flag_key,
            name=name,
            serializer_context={
                "request": request,
                "team_id": target_team.id,
                "project_id": target_team.project_id,
                "get_team": lambda: target_team,
            },
        )

        target_context = {
            **self.get_serializer_context(),
            "team_id": target_team.id,
            "project_id": target_team.project_id,
            "get_team": lambda: target_team,
        }
        return Response(ExperimentSerializer(new_experiment, context=target_context).data, status=201)

    @action(methods=["POST"], detail=True, required_scopes=["experiment:write"])
    def create_exposure_cohort_for_experiment(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        experiment = self.get_object()
        service = ExperimentService(team=self.team, user=request.user)
        cohort = service.create_exposure_cohort(
            experiment,
            serializer_context={
                "request": request,
                "team": self.team,
                "team_id": self.team_id,
            },
        )
        cohort_data = CohortSerializer(cohort, context={"request": request, "team": self.team}).data
        return Response({"cohort": cohort_data}, status=201)

    @action(methods=["GET"], detail=False, required_scopes=["feature_flag:read"])
    def eligible_feature_flags(self, request: Request, **kwargs: Any) -> Response:
        """
        Returns a paginated list of feature flags eligible for use in experiments.

        Eligible flags must:
        - Be multivariate with at least 2 variants
        - Have "control" as the first variant key

        Query parameters:
        - search: Filter by flag key or name (case insensitive)
        - limit: Number of results per page (default: 20)
        - offset: Pagination offset (default: 0)
        - active: Filter by active status ("true" or "false")
        - created_by_id: Filter by creator user ID
        - order: Sort order field
        - evaluation_runtime: Filter by evaluation runtime
        - has_evaluation_contexts: Filter by presence of evaluation contexts ("true" or "false")
        """
        # validate limit and offset
        try:
            limit = min(int(request.query_params.get("limit", 20)), 100)
            offset = max(int(request.query_params.get("offset", 0)), 0)
        except ValueError:
            return Response({"error": "Invalid limit or offset"}, status=400)

        survey_flag_ids = Survey.get_internal_flag_ids(project_id=self.project_id)
        product_tour_internal_targeting_flags = ProductTour.all_objects.filter(
            team__project_id=self.project_id, internal_targeting_flag__isnull=False
        ).values_list("internal_targeting_flag_id", flat=True)
        excluded_flag_ids = survey_flag_ids | set(product_tour_internal_targeting_flags)

        service = ExperimentService(team=self.team, user=request.user)
        eligible_feature_flags = service.get_eligible_feature_flags(
            limit=limit,
            offset=offset,
            excluded_flag_ids=excluded_flag_ids,
            search=request.query_params.get("search"),
            active=request.query_params.get("active"),
            created_by_id=request.query_params.get("created_by_id"),
            order=request.query_params.get("order"),
            evaluation_runtime=request.query_params.get("evaluation_runtime"),
            has_evaluation_contexts=request.query_params.get("has_evaluation_contexts"),
        )

        # Serialize using the standard FeatureFlagSerializer
        serializer = FeatureFlagSerializer(
            eligible_feature_flags["results"],
            many=True,
            context=self.get_serializer_context(),
        )

        return Response(
            {
                "results": serializer.data,
                "count": eligible_feature_flags["count"],
            }
        )

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="metric_uuid",
                type=str,
                location=OpenApiParameter.QUERY,
                description=(
                    "UUID of the metric to fetch timeseries for. Available on each metric in the "
                    "experiment's metrics array."
                ),
                required=True,
            ),
            OpenApiParameter(
                name="fingerprint",
                type=str,
                location=OpenApiParameter.QUERY,
                description=(
                    "Fingerprint of the metric configuration. Available alongside metric_uuid on "
                    "each metric in the experiment's metrics array."
                ),
                required=True,
            ),
        ],
    )
    @action(methods=["GET"], detail=True, required_scopes=["experiment:read"])
    def timeseries_results(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        experiment = self.get_object()
        metric_uuid = request.query_params.get("metric_uuid")
        fingerprint = request.query_params.get("fingerprint")

        if not metric_uuid:
            raise ValidationError("metric_uuid query parameter is required")
        if not fingerprint:
            raise ValidationError("fingerprint query parameter is required")

        service = ExperimentService(team=self.team, user=request.user)
        return Response(service.get_timeseries_results(experiment, metric_uuid=metric_uuid, fingerprint=fingerprint))

    @action(methods=["POST"], detail=True, required_scopes=["experiment:write"])
    def recalculate_timeseries(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        experiment = self.get_object()

        metric = request.data.get("metric")
        fingerprint = request.data.get("fingerprint")

        if not metric:
            raise ValidationError("metric is required")
        if not fingerprint:
            raise ValidationError("fingerprint is required")

        service = ExperimentService(team=self.team, user=request.user)
        result = service.request_timeseries_recalculation(experiment, metric=metric, fingerprint=fingerprint)
        is_existing = result.pop("is_existing", False)

        if not is_existing:
            recalculation_id = str(result["id"])
            try:
                temporal = sync_connect()
                asyncio.run(
                    temporal.start_workflow(
                        "experiment-timeseries-recalculation-workflow",
                        ExperimentTimeseriesRecalculationWorkflowInputs(recalculation_id=recalculation_id),
                        id=f"experiment-recalculation-{recalculation_id}",
                        task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
                    )
                )
            except Exception:
                # team-scoped filter: defense in depth so the rollback can never reach across teams even if
                # recalculation_id were ever sourced from somewhere less trusted than the row we just created.
                ExperimentTimeseriesRecalculation.objects.filter(team=self.team, id=recalculation_id).update(
                    status=ExperimentTimeseriesRecalculation.Status.FAILED
                )
                raise

        status_code = 200 if is_existing else 201
        return Response(result, status=status_code)

    @extend_schema(
        request=RecalculateMetricsRequestSerializer,
        responses={
            200: ExperimentMetricsRecalculationSerializer,
            201: ExperimentMetricsRecalculationSerializer,
        },
    )
    @action(
        methods=["POST"],
        detail=True,
        url_path="metrics_recalculation",
        required_scopes=["experiment:write"],
    )
    def metrics_recalculation(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Trigger a batch recalculation of all metrics for this experiment.

        Returns 201 with the new pending recalculation, or 200 with the active one if a recalculation is
        already pending or in progress for this experiment. The response payload intentionally does not
        include the `results` array — at POST time the workflow has just been queued and no per-metric
        results exist yet. Clients should poll `GET metrics_recalculation/{id}/` for results as the workflow
        progresses.
        """
        experiment: Experiment = self.get_object()
        request_serializer = RecalculateMetricsRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        trigger = request_serializer.validated_data["trigger"]

        # request.user is User | AnonymousUser at the DRF level; the viewset enforces auth so it's a User here.
        result = request_recalculation(experiment, cast(User, request.user), trigger)
        # Read without mutating — the serializer surfaces is_existing on the response so clients can detect
        # the idempotent-reuse path without inspecting the HTTP status code.
        is_existing = result.get("is_existing", False)

        if not is_existing:
            recalculation_id = str(result["id"])
            try:
                temporal = sync_connect()
                asyncio.run(
                    temporal.start_workflow(
                        "experiment-metrics-recalculation-workflow",
                        MetricsRecalcInputs(recalculation_id=recalculation_id),
                        id=f"experiment-metrics-recalculation-{recalculation_id}",
                        task_queue=settings.EXPERIMENTS_RECALCULATION_TASK_QUEUE,
                    )
                )
            except Exception:
                # team-scoped filter: defense in depth so the rollback can never reach across teams even if
                # recalculation_id were ever sourced from somewhere less trusted than the row we just created.
                ExperimentMetricsRecalculation.objects.filter(team=self.team, id=recalculation_id).update(
                    status=ExperimentMetricsRecalculation.Status.FAILED
                )
                raise

        return Response(
            ExperimentMetricsRecalculationSerializer(result).data,
            status=200 if is_existing else 201,
        )

    @extend_schema(responses={200: ExperimentMetricsRecalculationSerializer, 404: None})
    @action(
        methods=["GET"],
        detail=True,
        # NOTE: this action is declared BEFORE the by-id action so its URL pattern wins on /latest/.
        url_path="metrics_recalculation/latest",
        required_scopes=["experiment:read"],
    )
    def metrics_recalculation_latest(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        experiment: Experiment = self.get_object()
        recalc = get_latest_recalculation(experiment)
        if recalc is not None:
            return Response(_serialize_recalculation(recalc))
        # Cold start: no completed run yet. Fall back to the latest timeseries data as a read-only
        # placeholder so the user sees results immediately. Pure read, no workflow start.
        fallback = build_timeseries_cold_start_payload(experiment)
        if fallback is not None:
            return Response(ExperimentMetricsRecalculationSerializer(fallback).data)
        return Response({"detail": "No completed recalculation found"}, status=404)

    @extend_schema(responses={200: ExperimentMetricsRecalculationSerializer, 404: None})
    @action(
        methods=["GET"],
        detail=True,
        # Strict UUID regex so 'latest' (the sibling action above) never matches this route.
        url_path=r"metrics_recalculation/(?P<recalculation_id>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})",
        required_scopes=["experiment:read"],
    )
    def metrics_recalculation_detail(
        self, request: Request, recalculation_id: str, *args: Any, **kwargs: Any
    ) -> Response:
        experiment: Experiment = self.get_object()
        recalc = get_recalculation_by_id(experiment, recalculation_id)
        if recalc is None:
            return Response({"detail": "Recalculation not found"}, status=404)
        return Response(_serialize_recalculation(recalc))

    @action(methods=["GET"], detail=False, url_path="stats", required_scopes=["experiment:read"])
    def stats(self, request: Request, **kwargs: Any) -> Response:
        service = ExperimentService(team=self.team, user=request.user)
        return Response(service.get_velocity_stats())

    @validated_request(
        request_serializer=RunningTimeCalculationInputSerializer,
        responses={200: OpenApiResponse(response=RunningTimeCalculationResultSerializer)},
    )
    @action(
        methods=["POST"],
        detail=False,
        url_path="calculate_running_time",
        required_scopes=["experiment:read"],
    )
    def calculate_running_time(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        """Estimate the recommended sample size and running time for an experiment.

        Pure statistical calculation — does not read or write any experiment. Pass the metric type, a
        minimum detectable effect, and either a baseline value or raw baseline statistics. When
        `exposure_rate_per_day` is provided, the response also includes the estimated running time in days.
        """
        data = request.validated_data
        metric_type = data["metric_type"]
        mde = data["minimum_detectable_effect"]
        number_of_variants = data["number_of_variants"]
        exposure_rate = data.get("exposure_rate_per_day")

        baseline: BaselineStats | None = None
        stats = data.get("baseline_stats")
        if stats is not None:
            baseline = BaselineStats(
                number_of_samples=stats["number_of_samples"],
                sum=stats["sum"],
                sum_squares=stats.get("sum_squares", 0.0),
                denominator_sum=stats.get("denominator_sum"),
                denominator_sum_squares=stats.get("denominator_sum_squares"),
                numerator_denominator_sum_product=stats.get("numerator_denominator_sum_product"),
                step_counts=stats.get("step_counts") or [],
            )

        baseline_value = data.get("baseline_value")
        if baseline_value is None and baseline is not None:
            baseline_value = calculate_baseline_value(baseline, metric_type)

        variance = data.get("variance")
        if variance is None and baseline_value is not None:
            if baseline is not None:
                variance = calculate_variance_from_stats(baseline_value, metric_type, baseline)
            else:
                variance = calculate_variance(metric_type, baseline_value)

        recommended_sample_size: int | None = None
        if baseline_value is not None:
            recommended_sample_size = calculate_sample_size(
                metric_type, baseline_value, mde, number_of_variants, variance
            )

        return Response(
            {
                "baseline_value": baseline_value,
                "variance": variance,
                "recommended_sample_size": recommended_sample_size,
                "recommended_running_time_days": calculate_running_time_days(recommended_sample_size, exposure_rate),
            }
        )


def _serialize_recalculation(recalc: ExperimentMetricsRecalculation) -> dict:
    """Shape an ExperimentMetricsRecalculation row + its per-run results for the GET responses.

    Computes the per-run results once and threads them into both the derived counters and the response
    `results` field — recomputing per-metric fingerprints once per request is enough.
    """
    results = get_run_results(recalc)
    payload = build_job_payload(recalc, results=results, include_live_progress=True)
    payload["results"] = results
    return ExperimentMetricsRecalculationSerializer(payload).data
