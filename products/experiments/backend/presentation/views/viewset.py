"""The experiment viewset: its CRUD, list and activity endpoints, composed with one mixin per feature area."""

from collections.abc import Mapping
from typing import Any, Literal, cast

from django.db.models import BooleanField, Case, Exists, OuterRef, Prefetch, Q, QuerySet, Value, When

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
from posthog.api.tagged_item import TaggedItemViewSetMixin
from posthog.api.utils import MAX_LISTED_IDS, action
from posthog.auth import ProjectSecretAPIKeyAuthentication
from posthog.exceptions_capture import capture_exception
from posthog.models.activity_logging.activity_log import ActivityLog, get_activity_page
from posthog.models.activity_logging.activity_page import ActivityLogPaginatedResponseSerializer, activity_page_response
from posthog.permissions import is_scout_sandbox_request
from posthog.rate_limit import PersonalOrProjectSecretApiKeyRateThrottle, ProjectSecretApiKeyTeamRateThrottle

from products.access_control.backend.facade.user_access_control import access_level_satisfied_for_resource
from products.access_control.backend.presentation.access_control import AccessControlViewSetMixin
from products.approvals.backend.presentation.mixins import ApprovalHandlingMixin
from products.experiments.backend.experiment_service import ExperimentService, ExperimentVersionConflict

# TODO: Route through facade instead of direct import
from products.experiments.backend.models.experiment import LEGACY_METRIC_KINDS, Experiment, ExperimentToSavedMetric
from products.experiments.backend.presentation.scout_writes import (
    is_true,
    refuse_scout_experiment_delete,
    refuse_scout_live_flag_config_change,
    update_carries_flag_config,
)
from products.experiments.backend.presentation.serializers.experiment_crud import (
    ExperimentActivityQuerySerializer,
    ExperimentBasicSerializer,
    ExperimentMatchingIdsResponseSerializer,
    ExperimentSerializer,
    ExperimentWriteSerializer,
)
from products.feature_flags.backend.facade.config import ConfigFormatError
from products.feature_flags.backend.facade.rules import ExperimentRuleError
from products.feature_flags.backend.models.evaluation_context import FeatureFlagEvaluationContext

from . import copies, health_checks, lifecycle, prompts, recalculation, running_time, session_replay, setup_context

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


# Query parameters shared by the list endpoint and matching_ids, which accepts the same filters.
EXPERIMENT_LIST_FILTER_PARAMETERS = [
    OpenApiParameter(
        name="status",
        location=OpenApiParameter.QUERY,
        type=str,
        enum=["draft", "running", "paused", "exposure_frozen", "stopped", "complete", "all"],
        description=(
            'Filter by experiment status. "running", "paused", and "exposure_frozen" are mutually exclusive: '
            '"running" returns launched experiments with an active feature flag, "paused" returns launched '
            'experiments whose feature flag is deactivated, and "exposure_frozen" returns launched '
            "experiments whose exposure was frozen to the already-enrolled cohort while metrics keep "
            'flowing. "complete" is an alias for "stopped". "all" disables status filtering.'
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
        name="feature_flag_ids",
        location=OpenApiParameter.QUERY,
        type=str,
        description=f"Comma-separated feature flag IDs, at most {MAX_LISTED_IDS}. Returns experiments linked to any of them.",
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
        description="Free-text search applied to the experiment name and its feature flag key (case-insensitive).",
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
    OpenApiParameter(
        name="tags",
        location=OpenApiParameter.QUERY,
        type=str,
        description=(
            "JSON-encoded list of tag names. Returns experiments carrying at least one of the "
            'given tags, e.g. `["growth", "checkout"]`.'
        ),
        required=False,
    ),
    OpenApiParameter(
        name="excluded_tags",
        location=OpenApiParameter.QUERY,
        type=str,
        description=(
            "JSON-encoded list of tag names. Excludes experiments carrying any of the given tags, "
            "even when they also carry non-excluded tags."
        ),
        required=False,
    ),
]


class ExperimentBurstRateThrottle(PersonalOrProjectSecretApiKeyRateThrottle):
    # Same scope and rate as the default BurstRateThrottle so personal-key and session
    # behavior is unchanged; the subclass only adds per-key throttling for PSAK requests,
    # which the default throttles silently bypass (no personal key, no throttling).
    scope = "burst"
    rate = "480/minute"


class ExperimentSustainedRateThrottle(PersonalOrProjectSecretApiKeyRateThrottle):
    scope = "sustained"
    rate = "4800/hour"


class ExperimentProjectSecretApiKeyTeamBurstThrottle(ProjectSecretApiKeyTeamRateThrottle):
    """Per-team aggregate burst budget across all of a project's PSAKs — same size as the
    per-key budget, so minting extra keys never multiplies a project's total burst capacity."""

    scope = "experiment_psak_team_burst"
    rate = "480/minute"


class ExperimentProjectSecretApiKeyTeamSustainedThrottle(ProjectSecretApiKeyTeamRateThrottle):
    """Per-team aggregate sustained budget across all of a project's PSAKs."""

    scope = "experiment_psak_team_sustained"
    rate = "4800/hour"


@extend_schema_view(
    # PATCH /experiments/{id}/
    # DRF mixin calls implementation at ExperimentSerializer.update
    # request=ExperimentWriteSerializer is schema-only: it adds the writable feature_flag input
    # to the OpenAPI request body; runtime validation stays on ExperimentSerializer.
    partial_update=extend_schema(
        description="Update an experiment. Use this to modify experiment properties such as name, description, metrics, variants, and configuration. Metrics can be added, changed and removed at any time. Feature-flag config (variants, rollout, payloads) is sent via the feature_flag object.",
        request=ExperimentWriteSerializer,
    ),
    # PUT /experiments/{id}/, same request shape as PATCH
    update=extend_schema(request=ExperimentWriteSerializer),
    # POST /experiments/ — DRF mixin calls ExperimentSerializer.create
    create=extend_schema(
        description="Create a new experiment in draft status with optional metrics.",
        request=ExperimentWriteSerializer,
    ),
    # GET /experiments/{id}/ — DRF mixin, read-only serialization via ExperimentSerializer
    retrieve=extend_schema(
        description="Retrieve a single experiment by ID, including its current status, metrics, feature flag, and results metadata.",
    ),
    # GET /experiments/ — DRF mixin, filtering via ExperimentService.filter_experiments_queryset
    list=extend_schema(
        description="List experiments for the current project. Supports filtering by status and archival state.",
        parameters=EXPERIMENT_LIST_FILTER_PARAMETERS,
    ),
    # DELETE /experiments/{id}/
    # Logic and API docs defined in posthog/api/forbid_destroy_model.py (hard delete not allowed)
)
class EnterpriseExperimentsViewSet(
    lifecycle.ExperimentLifecycleMixin,
    health_checks.ExperimentHealthChecksMixin,
    copies.ExperimentCopiesMixin,
    prompts.ExperimentPromptsMixin,
    recalculation.ExperimentRecalculationMixin,
    running_time.ExperimentRunningTimeMixin,
    setup_context.ExperimentSetupContextMixin,
    session_replay.ExperimentSessionReplayMixin,
    # ApprovalHandlingMixin converts ApprovalRequired exceptions (raised by
    # FeatureFlagSerializer in ship_variant) into 409 HTTP responses. The
    # approval check itself lives in the service layer — this mixin is only
    # responsible for exception-to-response formatting.
    ApprovalHandlingMixin,
    ForbidDestroyModel,
    TeamAndOrgViewSetMixin,
    AccessControlViewSetMixin,
    TaggedItemViewSetMixin,
    viewsets.ModelViewSet,
):
    scope_object: Literal["experiment"] = "experiment"
    # bulk_update_tags comes from TaggedItemViewSetMixin and must be opted into PAT access explicitly.
    scope_object_write_actions = ["create", "update", "partial_update", "patch", "destroy", "bulk_update_tags"]
    bulk_tag_activity_scope = "Experiment"
    # Extends the default authenticators (TeamAndOrgViewSetMixin appends session/PAT/OAuth).
    authentication_classes = [ProjectSecretAPIKeyAuthentication]
    # A project secret API key with experiment:read can export experiment definitions
    # (list/retrieve) — a service credential not tied to one person's account. Everything
    # else (writes, lifecycle actions, results) stays session/PAT/OAuth-only.
    psak_allowed_actions = ["list", "retrieve"]
    throttle_classes = [
        ExperimentBurstRateThrottle,
        ExperimentSustainedRateThrottle,
        ExperimentProjectSecretApiKeyTeamBurstThrottle,
        ExperimentProjectSecretApiKeyTeamSustainedThrottle,
    ]
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

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        if is_scout_sandbox_request(request) and isinstance(request.data, Mapping):
            self._check_scout_update(request)
        # Structured 409 body ({detail, current_version, conflicting_*}) so clients can refetch
        # and retry precisely; the default exception handler would flatten it to a plain string.
        try:
            return super().update(request, *args, **kwargs)
        except ExperimentVersionConflict as err:
            return Response(err.response_data(), status=err.status_code)

    def handle_exception(self, exc: Exception) -> Response:
        # An action that still reads the flag as a config version 1 document cannot serve an experiment on a
        # feature flag rule yet. That is a refused request, and the capture keeps an action that should work visible.
        if isinstance(exc, ConfigFormatError | ExperimentRuleError):
            capture_exception(exc)
            exc = ValidationError(
                "This is not supported yet for an experiment on a feature flag that has rules.",
                code="feature_flag_rules_not_supported",
            )
        return super().handle_exception(exc)

    def _check_scout_update(self, request: Request) -> None:
        # The API has no hard delete, so `deleted: true` on an update is the delete a scout must not make.
        if is_true(request.data.get("deleted", False)):
            refuse_scout_experiment_delete(True)
        if update_carries_flag_config(
            request.data, legacy_flag_config_keys=ExperimentService.FEATURE_FLAG_CONFIG_KEYS
        ) and not self._token_can_write_feature_flag(request):
            experiment: Experiment = self.get_object()
            refuse_scout_live_flag_config_change(
                True,
                can_write_feature_flag=False,
                flag_is_live=not experiment.is_draft
                or (experiment.feature_flag is not None and experiment.feature_flag.active),
            )

    @tracer.start_as_current_span("ExperimentViewSet.list")
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    @tracer.start_as_current_span("ExperimentViewSet.safely_get_queryset")
    def safely_get_queryset(self, queryset) -> QuerySet:
        request = getattr(self, "request", None)
        if self.action == "bulk_update_tags":
            # The bulk tag mutation reads only id/team_id/name and the tags themselves (which the
            # mixin prefetches). Drop the detail joins and heavy JSON columns so selecting up to
            # 500 experiments doesn't drag every metrics/filters payload along.
            queryset = (
                queryset.select_related(None)
                .prefetch_related(None)
                .select_related("created_by")
                .defer(*LIST_DEFERRED_FIELDS)
            )
        if self.action in ("health", "health_inputs", "in_session_exposure"):
            # The facade reads the experiment again with the joins its checks need, so the object lookup
            # here only checks access.
            queryset = queryset.select_related(None).prefetch_related(None).select_related("team")
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

    @extend_schema(
        responses={200: ExperimentMatchingIdsResponseSerializer},
        parameters=EXPERIMENT_LIST_FILTER_PARAMETERS,
    )
    @action(methods=["GET"], detail=False, pagination_class=None, required_scopes=["experiment:read"])
    def matching_ids(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Get IDs of all experiments matching the current list filters.
        Accepts the same query params as the list endpoint and returns only
        IDs of experiments the user has permission to edit.
        """
        service = ExperimentService(team=self.team, user=request.user)
        queryset = service.filter_experiments_queryset(
            self.get_queryset(),
            action="list",
            query_params=request.query_params,
        )

        # Drop the class queryset's joins/prefetches; the access check below reads only the
        # experiment ID and its creator, so load exactly those (a bare only("id") would leave
        # created_by deferred and cost two refresh queries per row).
        queryset = (
            queryset.select_related(None).prefetch_related(None).select_related("created_by").only("id", "created_by")
        )

        if not self.user_access_control:
            editable_ids = list(queryset.values_list("id", flat=True))
        else:
            experiments = list(queryset)
            self.user_access_control.preload_object_access_controls(cast(list, experiments))
            editable_ids = [
                experiment.id
                for experiment in experiments
                if (user_access_level := self.user_access_control.get_user_access_level(experiment))
                and access_level_satisfied_for_resource("experiment", user_access_level, "editor")
            ]

        return Response(ExperimentMatchingIdsResponseSerializer({"ids": editable_ids, "total": len(editable_ids)}).data)

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
        # Ending or shipping with open_cleanup_pr=true starts a Desktop task that opens a pull
        # request. Starting a task is a task write, so require task:write on the token, not
        # just experiment:write.
        if self.action in ("end", "ship_variant"):
            scopes = ["experiment:write"]
            if request.data.get("open_cleanup_pr", False) in serializers.BooleanField.TRUE_VALUES:
                scopes.append("task:write")
            # Saving the team default cleanup repository writes environment-wide configuration,
            # so the token also needs project:write, matching the experiments_config surface.
            if request.data.get("set_repository_as_team_default", False) in serializers.BooleanField.TRUE_VALUES:
                scopes.append("project:write")
            return scopes
        return None

    @validated_request(
        query_serializer=ExperimentActivityQuerySerializer,
        responses={
            200: OpenApiResponse(response=ActivityLogPaginatedResponseSerializer),
            404: OpenApiResponse(response=None),
        },
    )
    @action(methods=["GET"], detail=True, required_scopes=["activity_log:read"])
    def activity(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        """
        Change history for this experiment.

        Returns a paginated audit trail of changes to the experiment, its holdouts and
        shared metrics, and its linked feature flag: who made each change, what changed
        (field-level before/after values), and when. Ordered newest first.
        """
        limit = request.validated_query_data["limit"]
        page = request.validated_query_data["page"]

        experiment: Experiment = self.get_object()

        # Holdout and shared-metric changes log under the Experiment scope with the child
        # object's own id, so they need their own type-matched clauses. The experiment's own
        # clause must exclude those detail types in turn: an unrelated holdout or shared
        # metric whose pk collides with this experiment's id would otherwise leak in.
        # The linked flag's changes log under the FeatureFlag scope, so each clause carries
        # its own scope instead of a single outer scope filter.
        activity_filter = Q(scope="Experiment", item_id=str(experiment.id)) & ~Q(
            detail__type__in=["holdout", "shared_metric"]
        )
        if experiment.holdout_id is not None:
            activity_filter |= Q(scope="Experiment", item_id=str(experiment.holdout_id), detail__type="holdout")
        saved_metric_ids = [str(pk) for pk in experiment.saved_metrics.values_list("id", flat=True)]
        if saved_metric_ids:
            activity_filter |= Q(scope="Experiment", item_id__in=saved_metric_ids, detail__type="shared_metric")
        # The flag's history stays behind the flag's own access controls: a viewer of the
        # experiment may have "none" access to the linked flag.
        if experiment.feature_flag_id is not None and self.user_access_control.check_access_level_for_object(
            experiment.feature_flag, required_level="viewer"
        ):
            activity_filter |= Q(scope="FeatureFlag", item_id=str(experiment.feature_flag_id))

        activity_query = (
            ActivityLog.objects.select_related("user")
            .filter(activity_filter, team_id=self.team_id)
            .order_by("-created_at")
        )
        activity_page = get_activity_page(activity_query, limit, page)
        return activity_page_response(activity_page, limit, page, request)

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
        # nosemgrep: api-response-must-match-schema -- moved unchanged from presentation/views.py
        return Response({"cohort": cohort_data}, status=201)

    @action(methods=["GET"], detail=False, url_path="stats", required_scopes=["experiment:read"])
    def stats(self, request: Request, **kwargs: Any) -> Response:
        service = ExperimentService(team=self.team, user=request.user)
        return Response(service.get_velocity_stats())
