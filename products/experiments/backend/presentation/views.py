import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import asdict, fields
from typing import Any, Literal, cast

from django.db.models import Q
from django.utils.text import slugify

from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema, extend_schema_view
from loginas.utils import is_impersonated_session
from opentelemetry import trace
from rest_framework import serializers, viewsets
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.pagination import DefaultLimitOffsetPagination, FacadeLimitOffsetPagination, facade_page_response
from posthog.api.routing import PathParameter, TeamAndOrgViewSetMixin
from posthog.api.tagged_item import (
    BULK_UPDATE_TAGS_SKIPPED_REASON,
    BulkUpdateTagsRequestSerializer,
    BulkUpdateTagsResponseSerializer,
    TaggedItemViewSetMixin,
)
from posthog.api.utils import MAX_LISTED_IDS, action
from posthog.auth import ProjectSecretAPIKeyAuthentication
from posthog.exceptions_capture import capture_exception
from posthog.helpers.impersonation import get_original_user_from_session, is_impersonated
from posthog.models.activity_logging.activity_log import ActivityLog, get_activity_page
from posthog.models.activity_logging.activity_page import ActivityLogPaginatedResponseSerializer, activity_page_response
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.paging import Page, PageRequest
from posthog.permissions import (
    get_authenticator_scoped_team_ids,
    get_authenticator_scopes,
    is_scout_sandbox_request,
    is_service_auth,
    posthog_feature_flag_enabled,
    request_subject,
    resource_for_ref,
)
from posthog.rate_limit import (
    ClickHouseBurstRateThrottle,
    ClickHouseSustainedRateThrottle,
    PersonalOrProjectSecretApiKeyRateThrottle,
    ProjectSecretApiKeyTeamRateThrottle,
    SessionBucketsBurstRateThrottle,
    SessionBucketsSustainedRateThrottle,
    SessionContextsBurstRateThrottle,
    SessionContextsSustainedRateThrottle,
    SessionEventDeltasBurstRateThrottle,
    SessionEventDeltasSustainedRateThrottle,
)
from posthog.scopes.checks import scopes_not_covered
from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.user_permissions import UserPermissions
from posthog.utils import str_to_bool

from products.access_control.backend.facade.api import (
    get_restricted_properties_with_group_type_index_for_team,
    split_restricted_property_names,
)
from products.access_control.backend.facade.contracts import ObjectAccessRef
from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.access_control.backend.presentation.access_control import AccessControlViewSetMixin
from products.approvals.backend.presentation.mixins import ApprovalHandlingMixin
from products.authorization.backend.facade import api as authorization
from products.authorization.backend.facade.contracts import CheckRequest
from products.authorization.backend.facade.enums import Action
from products.experiments.backend.facade import (
    experiments as experiments_facade,
    lifecycle,
)
from products.experiments.backend.facade.api import (
    RECALCULATION_TRIGGER_AGENT_MCP,
    get_experiment_health,
    get_latest_recalculation,
    get_recalculation_run,
    get_running_time_target,
    start_metrics_recalculation,
    start_timeseries_recalculation_workflow,
)
from products.experiments.backend.facade.contracts import (
    EXPERIMENT_BEHAVIOR_COMPARISON_FLAG,
    EXPERIMENT_SETUP_CONTEXT_FLAG,
    BaselineStats,
    CreateExperimentInput,
    ExperimentBasic,
    ExperimentDetail,
    ExperimentHandle,
    ExperimentHealthReaderAccess,
    ExperimentListFilters,
    ExperimentNotFound,
    ExperimentRef,
    ExperimentSessionBucket,
    ExperimentUpdateTarget,
    ExperimentValidationError,
    ExperimentVersionConflict,
    LegacyMigrationError,
    ListAccess,
    RunningTimeMode,
    SessionBucketUnavailable,
    SessionEventDeltasUnavailable,
    SetupContextInputs,
    WarehouseNativeResultAccessDenied,
)
from products.experiments.backend.facade.enums import FEATURE_FLAG_CONFIG_KEYS
from products.experiments.backend.facade.legacy_migration import (
    experiment_uses_legacy_metrics,
    migrate_experiment as migrate_legacy_experiment,
)
from products.experiments.backend.facade.llm_metric_templates import build_template, list_templates
from products.experiments.backend.facade.replay import resolve_in_session_exposure_semantics
from products.experiments.backend.facade.running_time import (
    calculate_baseline_value,
    calculate_running_time_days,
    calculate_sample_size,
    calculate_variance,
    calculate_variance_from_stats,
)
from products.experiments.backend.facade.sessions import (
    all_card_session_ids,
    finalize_session_bucket,
    finalize_watch_cards,
    get_experiment_session_bucket,
    get_experiment_session_event_deltas,
    get_session_experiment_context,
    get_session_experiment_contexts,
)
from products.experiments.backend.facade.setup_context import build_setup_context
from products.experiments.backend.facade.warehouse_native_access import validate_warehouse_native_connection_access
from products.experiments.backend.presentation.saved_metrics import list_access
from products.experiments.backend.presentation.scout_writes import (
    is_true,
    refuse_scout_cleanup_pr,
    refuse_scout_experiment_copy_to_project,
    refuse_scout_experiment_delete,
    refuse_scout_experiment_migrate,
    refuse_scout_live_flag_config_change,
    refuse_scout_ship_variant_without_flag_write,
    update_carries_flag_config,
)
from products.experiments.backend.presentation.serializers import (
    ArchiveExperimentSerializer,
    CopyExperimentToProjectSerializer,
    CreateFromPromptInputSerializer,
    EndExperimentSerializer,
    ExperimentActivityQuerySerializer,
    ExperimentBasicSerializer,
    ExperimentFlagCleanupTargetSerializer,
    ExperimentFlagCleanupTaskSerializer,
    ExperimentHealthQuerySerializer,
    ExperimentHealthSerializer,
    ExperimentInSessionExposureSerializer,
    ExperimentMatchingIdsResponseSerializer,
    ExperimentMetricsRecalculationJobSerializer,
    ExperimentMetricsRecalculationLatestSerializer,
    ExperimentMetricsRecalculationRunSerializer,
    ExperimentSerializer,
    ExperimentSessionBucketRequestSerializer,
    ExperimentSessionBucketResponseSerializer,
    ExperimentSessionContextResponseSerializer,
    ExperimentSessionContextsRequestSerializer,
    ExperimentSessionContextsResponseSerializer,
    ExperimentSessionEventDeltaRequestSerializer,
    ExperimentSessionEventDeltaResponseSerializer,
    ExperimentSetupContextInputSerializer,
    ExperimentSetupContextResponseSerializer,
    ExperimentTimeseriesResultsSerializer,
    ExperimentWriteSerializer,
    RecalculateMetricsRequestSerializer,
    RunningTimeCalculationInputSerializer,
    RunningTimeCalculationResultSerializer,
    RunningTimeTargetQuerySerializer,
    RunningTimeTargetSerializer,
    ShipVariantSerializer,
)
from products.feature_flags.backend.facade.config import ConfigFormatError
from products.feature_flags.backend.facade.rules import ExperimentRuleError
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.tasks.backend.facade import api as tasks_facade

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

# The viewset's `list` method shadows the builtin `list` in the class namespace, so a
# `list[str]` annotation there resolves to that method (a runtime crash, and a mypy error).
# Reference this module-level alias instead.
RequiredScopes = list[str]


class ExperimentsPagination(FacadeLimitOffsetPagination, DefaultLimitOffsetPagination):
    """Pages the facade list, with the schema of the default paginator, which states no maximum for `limit`."""


def _build_prompt_variants(versions: list[int]) -> list[dict[str, Any]]:
    """Build N feature flag variants from an ordered list of prompt versions.

    First variant is keyed "control", matching the codebase's baseline convention (the
    baseline defaults to 'control' when present). For the standard 2-variant case the
    second is keyed "test", matching the rest of the codebase's defaults. For N >= 3 the
    trailing variants are keyed "test-1", "test-2", … so each key stays unique.
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


def _accessible_session_ids(
    request: Request, user_access_control: UserAccessControl, team: Team, session_ids: list[str]
) -> list[str]:
    """Drop session ids whose recording the viewer is denied at the object level.

    The resource-level `session_recording` check the session-context actions run first grants
    access to the replay product, not to every recording in it: a recording can carry its own
    access controls, which the replay retrieve endpoint enforces via `check_object_permissions`.
    Without this filter a viewer denied one recording could still read which experiments it saw.

    Object-level controls can only target a recording that has a Postgres row, so an id without
    one is returned as accessible. That matches replay, which serves those ids from an unsaved
    `SessionRecording` no access control row can point at.
    """
    if is_service_auth(request):
        # Mirrors AccessControlPermission.has_object_permission: service credentials authenticate
        # as synthetic users that UserAccessControl cannot evaluate, so they are gated by API
        # scope and project membership instead of object-level RBAC.
        return session_ids

    recordings = SessionRecording.objects.filter(team=team, session_id__in=session_ids)
    denied_ids = {
        recording.session_id
        for recording in recordings
        if not user_access_control.check_access_level_for_object(recording, required_level="viewer")
    }
    return [session_id for session_id in session_ids if session_id not in denied_ids]


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
    # request=ExperimentWriteSerializer is schema-only: it adds the writable feature_flag input
    # to the OpenAPI request body; runtime validation stays on ExperimentSerializer.
    partial_update=extend_schema(
        description="Update an experiment. Use this to modify experiment properties such as name, description, metrics, variants, and configuration. Metrics can be added, changed and removed at any time. Feature-flag config (variants, rollout, payloads) is sent via the feature_flag object.",
        request=ExperimentWriteSerializer,
    ),
    # PUT /experiments/{id}/, same request shape as PATCH
    update=extend_schema(request=ExperimentWriteSerializer),
    create=extend_schema(
        description="Create a new experiment in draft status with optional metrics.",
        request=ExperimentWriteSerializer,
    ),
    # GET /experiments/{id}/ — DRF mixin, read-only serialization via ExperimentSerializer
    retrieve=extend_schema(
        description="Retrieve a single experiment by ID, including its current status, metrics, feature flag, and results metadata.",
    ),
    list=extend_schema(
        description="List experiments for the current project. Supports filtering by status and archival state.",
        parameters=EXPERIMENT_LIST_FILTER_PARAMETERS,
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
    # bulk_update_tags declares no required_scopes, so it must be opted into PAT access explicitly.
    scope_object_write_actions = ["create", "update", "partial_update", "patch", "destroy", "bulk_update_tags"]
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
    pagination_class = ExperimentsPagination
    path_parameters = {
        "pk": PathParameter(type=int, description="A unique integer value identifying this experiment."),
    }

    def get_serializer_class(self):
        if self.action == "list":
            return ExperimentBasicSerializer
        return ExperimentSerializer

    def read_object(self) -> ExperimentDetail | ExperimentHandle | ExperimentUpdateTarget | None:
        if self.action == "retrieve":
            return experiments_facade.get_experiment(team=self.team, experiment_id=self.kwargs["pk"])
        if self.action in ("update", "partial_update"):
            return experiments_facade.get_experiment_update_target(
                team=self.team, experiment_id=self.kwargs["pk"], include_deleted=self._update_includes_deleted()
            )
        return experiments_facade.get_experiment_handle(team=self.team, experiment_id=self.kwargs["pk"])

    def _update_includes_deleted(self) -> bool:
        # An update that sends a `deleted` that is not true restores a deleted experiment, so it must find one.
        data = self.request.data
        deleted = data.get("deleted") if isinstance(data, Mapping) else None
        return deleted is not None and not str_to_bool(deleted)

    def object_access_ref(
        self, record: ExperimentDetail | ExperimentHandle | ExperimentRef | ExperimentUpdateTarget
    ) -> ObjectAccessRef:
        return ObjectAccessRef(
            resource="experiment", id=str(record.id), team_id=self.team.id, created_by_id=record.created_by_id
        )

    def _can_edit_by_id(self, experiments: Sequence[ExperimentRef]) -> dict[int, bool]:
        subject = request_subject(self.request)
        checks = [
            CheckRequest(
                resource=resource_for_ref(self.object_access_ref(experiment)), action=Action.EDIT, subject=subject
            )
            for experiment in experiments
        ]
        return {
            experiment.id: can_edit
            for experiment, can_edit in zip(experiments, authorization.check(checks), strict=True)
        }

    def _experiment_response(self, experiment_id: int, *, team: Team | None = None, status_code: int = 200) -> Response:
        """The experiment with the id as the detail endpoint shows it, read again after a write."""
        experiment = experiments_facade.get_experiment(
            team=team or self.team, experiment_id=experiment_id, include_deleted=True
        )
        if experiment is None:
            raise NotFound()
        return Response(
            ExperimentSerializer(experiment, context=self.get_serializer_context()).data, status=status_code
        )

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = cast(ExperimentSerializer, self.get_serializer(data=request.data))
        serializer.is_valid(raise_exception=True)
        try:
            experiment_id = experiments_facade.add_experiment(
                team=self.team,
                user=cast(User, request.user),
                experiment=serializer.to_create(),
                tags=serializer.validated_data.get("tags"),
            )
        except ExperimentValidationError as error:
            raise ValidationError(str(error)) from error
        return self._experiment_response(experiment_id, status_code=201)

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        if is_scout_sandbox_request(request) and isinstance(request.data, Mapping):
            self._check_scout_update(request)
        experiment: ExperimentUpdateTarget = self.get_object()
        serializer = cast(
            ExperimentSerializer,
            self.get_serializer(experiment, data=request.data, partial=kwargs.pop("partial", False)),
        )
        serializer.is_valid(raise_exception=True)
        experiments_facade.edit_experiment(
            team=self.team,
            user=cast(User, request.user),
            experiment_id=experiment.id,
            update=serializer.to_update(),
            include_deleted=self._update_includes_deleted(),
            serializer_context=serializer.context,
        )
        return self._experiment_response(experiment.id)

    def handle_exception(self, exc: Exception) -> Response:
        # Structured 409 body ({detail, current_version, conflicting_*}) so clients can refetch
        # and retry precisely.
        if isinstance(exc, ExperimentVersionConflict):
            body: dict[str, Any] = {"detail": exc.detail, "current_version": exc.current_version}
            if exc.conflicting_fields:
                body["conflicting_fields"] = exc.conflicting_fields
            if exc.conflicting_metric_uuids:
                body["conflicting_metric_uuids"] = exc.conflicting_metric_uuids
            return Response(body, status=409)
        if isinstance(exc, ExperimentNotFound):
            exc = NotFound()
        if isinstance(exc, WarehouseNativeResultAccessDenied):
            exc = PermissionDenied(exc.detail)
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
            request.data, legacy_flag_config_keys=FEATURE_FLAG_CONFIG_KEYS
        ) and not self._token_can_write_feature_flag(request):
            experiment: ExperimentUpdateTarget = self.get_object()
            refuse_scout_live_flag_config_change(
                True,
                can_write_feature_flag=False,
                flag_is_live=not experiment.is_draft or experiment.feature_flag_active,
            )

    @tracer.start_as_current_span("ExperimentViewSet.list")
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        list_filters = _list_filters(request)
        # The access control narrowing a queryset list gets from TeamAndOrgViewSetMixin, with the same gates.
        access = (
            None
            if is_service_auth(request)
            else self._list_access("experiment", include_all_if_admin=request.GET.get("admin_include_all") == "true")
        )

        def fetch(page: PageRequest) -> Page[ExperimentBasic]:
            return experiments_facade.list_experiments(team=self.team, filters=list_filters, access=access, page=page)

        return facade_page_response(self, fetch)

    def _list_access(
        self, resource: Literal["experiment", "experiment_saved_metric"], *, include_all_if_admin: bool = False
    ) -> ListAccess | None:
        return list_access(
            self.user_access_control,
            resource,
            viewer_id=cast(User, self.request.user).id,
            include_all_if_admin=include_all_if_admin,
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
        can_edit = self._can_edit_by_id(
            experiments_facade.list_experiment_refs(team=self.team, filters=_list_filters(request))
        )
        editable_ids = [experiment_id for experiment_id, editable in can_edit.items() if editable]
        return Response(ExperimentMatchingIdsResponseSerializer({"ids": editable_ids, "total": len(editable_ids)}).data)

    @extend_schema(
        request=BulkUpdateTagsRequestSerializer,
        responses={200: BulkUpdateTagsResponseSerializer},
    )
    @action(methods=["POST"], detail=False)
    def bulk_update_tags(self, request: Request, **kwargs: Any) -> Response:
        serializer = BulkUpdateTagsRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        experiment_ids: list[int] = serializer.validated_data["ids"]

        can_edit = self._can_edit_by_id(
            experiments_facade.experiment_refs_among(team=self.team, experiment_ids=experiment_ids)
        )
        skipped_ids = [experiment_id for experiment_id, editable in can_edit.items() if not editable]
        skipped_ids += [experiment_id for experiment_id in experiment_ids if experiment_id not in can_edit]

        changes = experiments_facade.change_experiment_tags(
            team=self.team,
            user=cast(User, request.user),
            was_impersonated=is_impersonated(request),
            experiment_ids=[experiment_id for experiment_id, editable in can_edit.items() if editable],
            tag_action=serializer.validated_data["action"],
            tags=serializer.validated_data["tags"],
        )
        skipped = [{"id": experiment_id, "reason": BULK_UPDATE_TAGS_SKIPPED_REASON} for experiment_id in skipped_ids]
        return Response(BulkUpdateTagsResponseSerializer({"updated": changes, "skipped": skipped}).data)

    # Shared so this endpoint is documented like every TaggedItemViewSetMixin bulk tag endpoint.
    bulk_update_tags.__doc__ = TaggedItemViewSetMixin.bulk_update_tags.__doc__

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

    def _check_team_default_repository_access(self, request: Request) -> None:
        """The team default cleanup repository is environment-wide configuration; writing it via
        experiments_config requires project admin (TeamMemberStrictManagementPermission), so the
        write through end/ship_variant must hold the same bar."""
        user_permissions = UserPermissions(user=cast(User, request.user))
        effective_level = user_permissions.team(self.team).effective_membership_level
        if effective_level is None or effective_level < OrganizationMembership.Level.ADMIN:
            raise PermissionDenied("Setting the default cleanup repository requires project admin access.")

    def _check_copy_target_access(self, request: Request, target_team: Team) -> None:
        """Authorize the target project of a cross-project copy.

        Every class in the permission stack resolves against `view.team`, which is the source
        project in the URL, so the target project is not checked at all by the time the action
        body runs. This applies the same gates the target project's own `POST /experiments/`
        would apply: the credential's project scope, project membership, and experiment editor
        access in the target.
        """
        scoped_teams = get_authenticator_scoped_team_ids(getattr(request, "successful_authenticator", None))
        if scoped_teams is not None and target_team.id not in scoped_teams:
            raise PermissionDenied(f"API key does not have access to the requested project: ID {target_team.id}.")

        user = cast(User, request.user)
        effective_level = UserPermissions(user=user).team(target_team).effective_membership_level
        if effective_level is None or effective_level < OrganizationMembership.Level.MEMBER:
            raise PermissionDenied("You do not have write access to the target project.")

        target_access_control = UserAccessControl(user=user, team=target_team)
        if not target_access_control.check_access_level_for_object(
            target_team, required_level="member"
        ) or not target_access_control.check_access_level_for_resource("experiment", required_level="editor"):
            raise PermissionDenied("You do not have permission to create experiments in the target project.")

    def _token_can_write_feature_flag(self, request: Request) -> bool:
        """Whether the request's token carries feature_flag:write.

        Archiving/unarchiving an experiment can touch the linked flag's archived/active
        state as a side effect; that is a feature_flag write and must not be reachable with
        only experiment:write. Session and other non-token auth aren't scope-limited (gated by
        access control instead), mirroring APIScopePermission.
        """
        scopes = get_authenticator_scopes(request.successful_authenticator)
        if scopes is None:
            return True
        return "*" in scopes or "feature_flag:write" in scopes

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
        configuration is invalid (e.g. fewer than 2 variants).
        """
        experiment: ExperimentHandle = self.get_object()
        launched_experiment = lifecycle.launch_experiment(
            team=self.team,
            user=cast(User, request.user),
            experiment_id=experiment.id,
            request_context={"request": request},
        )
        return self._experiment_response(launched_experiment.id)

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
        experiment: ExperimentHandle = self.get_object()
        request_serializer = ArchiveExperimentSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        archived_experiment = lifecycle.archive_experiment(
            team=self.team,
            user=cast(User, request.user),
            experiment_id=experiment.id,
            disable_feature_flag=request_serializer.validated_data["disable_feature_flag"],
            can_write_feature_flag=self._token_can_write_feature_flag(request),
            request_context={"request": request},
        )
        return self._experiment_response(archived_experiment.id)

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
        experiment: ExperimentHandle = self.get_object()
        unarchived_experiment = lifecycle.unarchive_experiment(
            team=self.team,
            user=cast(User, request.user),
            experiment_id=experiment.id,
            can_write_feature_flag=self._token_can_write_feature_flag(request),
            request_context={"request": request},
        )
        return self._experiment_response(unarchived_experiment.id)

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
        experiment: ExperimentHandle = self.get_object()
        request_serializer = EndExperimentSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        refuse_scout_cleanup_pr(
            is_scout_sandbox_request(request), open_cleanup_pr=request_serializer.validated_data["open_cleanup_pr"]
        )
        if request_serializer.validated_data["set_repository_as_team_default"]:
            self._check_team_default_repository_access(request)
        ended_experiment = lifecycle.end_experiment(
            team=self.team,
            user=cast(User, request.user),
            experiment_id=experiment.id,
            conclusion=request_serializer.validated_data.get("conclusion"),
            conclusion_comment=request_serializer.validated_data.get("conclusion_comment"),
            open_cleanup_pr=request_serializer.validated_data["open_cleanup_pr"],
            repository=request_serializer.validated_data.get("repository"),
            set_repository_as_team_default=request_serializer.validated_data["set_repository_as_team_default"],
            request_context={"request": request},
        )
        return self._experiment_response(ended_experiment.id)

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
        refuse_scout_ship_variant_without_flag_write(
            is_scout_sandbox_request(request), can_write_feature_flag=self._token_can_write_feature_flag(request)
        )
        experiment: ExperimentHandle = self.get_object()
        request_serializer = ShipVariantSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        refuse_scout_cleanup_pr(
            is_scout_sandbox_request(request), open_cleanup_pr=request_serializer.validated_data["open_cleanup_pr"]
        )
        if request_serializer.validated_data["set_repository_as_team_default"]:
            self._check_team_default_repository_access(request)
        shipped_experiment = lifecycle.ship_variant(
            team=self.team,
            user=cast(User, request.user),
            experiment_id=experiment.id,
            variant_key=request_serializer.validated_data["variant_key"],
            release_to_everyone=request_serializer.validated_data["release_to_everyone"],
            conclusion=request_serializer.validated_data.get("conclusion"),
            conclusion_comment=request_serializer.validated_data.get("conclusion_comment"),
            open_cleanup_pr=request_serializer.validated_data["open_cleanup_pr"],
            repository=request_serializer.validated_data.get("repository"),
            set_repository_as_team_default=request_serializer.validated_data["set_repository_as_team_default"],
            request_context={"request": request},
        )
        return self._experiment_response(shipped_experiment.id)

    @extend_schema(
        request=None,
        responses=ExperimentFlagCleanupTaskSerializer,
    )
    @action(methods=["GET"], detail=True, required_scopes=["experiment:read"])
    def flag_cleanup_task(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Status of the flag-cleanup Desktop task opened for this experiment.

        When an experiment was ended or shipped with open_cleanup_pr=true, a Desktop task
        removes the experiment's feature-flag code and opens a draft pull request. This
        returns that task's latest run status and the PR URL once one is opened. Poll
        until is_terminal is true. Returns 404 when no cleanup task was opened.
        """
        experiment: ExperimentHandle = self.get_object()
        if not experiment.flag_cleanup_task_id:
            raise NotFound("No flag cleanup task was opened for this experiment.")
        # Read through the facade rather than the tasks API: cleanup tasks are creator-visible
        # there, but their status should be visible to everyone who can see the experiment.
        run = tasks_facade.get_latest_run_by_task([experiment.flag_cleanup_task_id]).get(
            str(experiment.flag_cleanup_task_id)
        )
        # get_latest_run_by_task filters by task id only. After a project transfer the
        # experiment can point at a task in the old team — treat that run as absent rather
        # than leaking its status across teams.
        if run is not None and run.team_id != experiment.team_id:
            run = None
        # The PR URL comes from the task run's output blob — only pass it through when it
        # actually points at GitHub, since the frontend renders it as a GitHub link.
        pr_url = run.pr_url if run else None
        if pr_url and not pr_url.startswith("https://github.com/"):
            pr_url = None
        response_serializer = ExperimentFlagCleanupTaskSerializer(
            {
                "task_id": experiment.flag_cleanup_task_id,
                "run_status": run.status if run else "queued",
                "is_terminal": run.is_terminal if run else False,
                "pr_url": pr_url,
                # Whether the tasks API would let this user open the task page — cleanup
                # tasks are creator-visible there today, so hide the link from everyone else.
                "can_view_task": tasks_facade.task_visible(
                    experiment.flag_cleanup_task_id, self.team.pk, cast(User, request.user).id
                ),
            }
        )
        return Response(response_serializer.data)

    @extend_schema(
        request=None,
        responses=ExperimentFlagCleanupTargetSerializer,
    )
    @action(methods=["GET"], detail=True, url_path="flag_cleanup_target", required_scopes=["experiment:read"])
    def flag_cleanup_target(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Repository a flag-cleanup pull request for this experiment would be opened in.

        Resolution order: the experiment's saved repository, else the environment's default
        cleanup repository, else the team's only connected GitHub repository. When the team
        has several repositories and none is saved (source=ambiguous), pass one via
        `repository` on end/ship_variant.
        """
        experiment: ExperimentHandle = self.get_object()
        target = experiments_facade.get_flag_cleanup_target(
            team=self.team, user=cast(User, request.user), experiment_id=experiment.id
        )
        return Response(ExperimentFlagCleanupTargetSerializer(target).data)

    @validated_request(
        query_serializer=ExperimentHealthQuerySerializer,
        responses={200: OpenApiResponse(response=ExperimentHealthSerializer)},
    )
    @action(methods=["GET"], detail=True, required_scopes=["experiment:read"])
    def health(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        """
        Health check findings for this experiment: problems in its configuration and its feature flag
        that keep it from producing trustworthy results, each with a fix. `checks` gives the result of
        each check, so a check that found no problem can be told from one that did not apply or could
        not read an input.

        The checks here read the experiment, its flag, its linked metrics, the project's event and
        property definitions, the cohorts of the exposure criteria, and the changes of the flag's
        variant split since launch. The checks that read exposure counts come with the
        exposure query. The split-change check compares the split changes with the exposures only
        for exposure criteria that name an event without property filters. When the split changed
        after launch and the criteria have filters or an action, or an API key lacks `query:read`,
        it returns an info finding with the subcode `not_checked` and the cause in
        `reason`. A caller who can't view the linked flag's history (viewer access to the
        flag and, with an API key, `activity_log:read`) gets that finding for every running
        experiment, because the changes are not read. A finding that tells the reader to
        move the start date offers `move_start_date`, and `evidence.suggested_start_date` holds that
        date in UTC: set the experiment's `start_date` to it. When one variant was set to 100% of the
        split, the finding offers `end_experiment` instead.

        Two checks read whether the project received an event from its event definitions: a
        definition without `last_seen_at`, such as one Wizard wrote for a planned event, counts as
        not received. A name whose definition was deleted since launch, or in the last day for a
        draft, is not checked, because ingestion writes the definition again only when the event
        arrives. No missing definition is checked when ingestion saw none of the experiment's events
        in the last day, because ingestion can be set to skip a team. `metric_event_not_ingested`
        names each metric that
        reads an event the project never received, in the `evidence` keys `metric_N`,
        `metric_N_role` and `metric_N_events`. `exposure_criteria_cannot_match` reports a custom
        exposure event the project never received (`exposure_event_not_ingested`), a
        `$feature_flag` filter on the flag call events that requires another flag
        (`filter_on_another_flag`), and a filter on an event or person property that the project has
        no definition of, with an operator that a missing property fails
        (`filter_on_property_not_ingested`, the keys in `evidence.properties`). A property whose
        definition was ever deleted is not checked, and neither is an event property filter on an
        action or on `$groupidentify`, whose properties ingestion keeps no definitions of. An event
        or property not received is info before launch, in the first 24 hours after launch, and when
        only secondary metrics read it, and a warning otherwise. `filter_on_another_flag` is a
        warning in every state, `filter_on_property_not_ingested` also reports after the end, and
        the other findings stop at the end.

        `exposure_filters` reads the cohort filters of the exposure criteria and of the activation,
        not the test account filters. `exposure_filter_on_dynamic_cohort` is a warning in every
        state: the results use the members of a dynamic cohort at the calculation, not at exposure.
        Its subcode is `cohort_forces_variant` when a release condition of the flag that matches the
        cohort's members gives one variant, `cohort_in_release_conditions` when the release
        conditions match its members otherwise, and `evidence.cohort_ids` names the cohorts. Both
        subcodes need the exposure criteria to keep the members too, not to leave them out.

        `metric_cannot_compile` builds and compiles the query of each metric without running it, as
        the caller, so a metric that every calculation fails on shows before launch. A metric that
        reads a warehouse table or view the caller may not query is not checked for them. The finding
        names each failing metric in the `evidence` keys `metric_N`, `metric_N_role`, `metric_N_error`
        (the error class, which is also the subcode of the first metric) and `metric_N_message` (the
        compiler's message). It is a warning when a primary metric fails, also after the end, because
        the calculation after the fix reads the events up to the end. It is info otherwise. A failure
        inside ClickHouse, such as a type that the data holds, isn't found. A failing metric compiles
        again on every request. A metric that compiles is cached per caller for a day, so a cohort or
        table that is deleted after a compile can take up to a day to show.

        `metric_calculation_failed` reports each metric whose latest calculation failed, from the
        latest finished calculation that the results page shows. It leaves out a metric that
        `metric_cannot_compile` reports. The subcode is the kind of the first failure: `busy`,
        `query_limit` (the query reached the read, memory, time or length limit), `settings` (a setting of
        the metric or the experiment), `not_enough_data`, `experiment_too_old` (the experiment
        started too long ago to calculate again) or `unexpected_error`. Each metric is in the
        `evidence` keys `metric_N`, `metric_N_role`, `metric_N_failure` (the kind), `metric_N_error`
        (the limit, or the family of a setting) and `metric_N_message` (only a message that PostHog
        wrote for users), and `calculated_at` is when the calculation finished. It is a
        warning when a primary metric fails for a kind that a change fixes (`query_limit`,
        `settings`, `experiment_too_old`), also after the end, because the calculation after the fix
        reads the events up to the end. It is info otherwise. When the first failure reached the
        read, memory or time limit, `reason` names the cause that the calculation shows: `metric`
        when another metric of the same calculation completed the same read of the exposures, or
        `exposure_criteria` when every metric reached a limit and an exposure or test account filter
        makes each query read all the properties of an event, person or group. `evidence.properties`
        then names the filters. A query that read precomputed exposures doesn't apply those filters,
        so it can't get `exposure_criteria`. It is null otherwise.

        `metric_all_zero` reports a metric that reads zero in every variant, from the same latest
        finished calculation, so the results page shows "Not enough data yet" at any sample size.
        Each side of a ratio that is zero in every variant counts on its own. It reads the stored
        result and the project's event definitions, and no events. A primary metric needs 1,000
        exposures in the result and 72 hours of data, because most zeros before that are outcomes
        that take time. A retention metric counts those hours from the start of its retention
        window. The subcode is the cause of the first metric: `blank_event` (an event with an empty
        name), `event_stopped` (the project last received the event before launch, while ingestion
        still records the project), `outlier_bound` (an upper outlier bound that is 0 while some
        exposures have a value) or null when none shows a cause. `blank_event` and `outlier_bound`
        also report a secondary metric, and need only 100 exposures and 12 hours of data, because
        they read 0 at any traffic. A bound on the largest value of the exposures can't be 0 while
        one has a value, so it is no cause. Neither is a bound on a metric with breakdowns, which
        gets one bound per breakdown group. Until the end, the check leaves out a metric that uses an
        event `metric_event_not_ingested` reports. Each metric, or side of a ratio, is in the
        `evidence` keys `metric_N`, `metric_N_role`, `metric_N_side`, `metric_N_exposures` and
        `metric_N_cause`. It is a warning for a primary metric. After the end it stays a warning only
        for a cause that a setting fixes, because the calculation after the fix reads the events up
        to the end. It is info otherwise.

        `metric_uses_feature_flag_called` names each metric that reads `$feature_flag_called`
        events, in the `evidence` keys `metric_N` and `metric_N_role`. PostHog is reducing how long
        it keeps these events, so the fix is to read `$experiment_exposure` instead. It is a warning
        when a primary metric reads them and info otherwise. It runs only on PostHog Cloud, and not
        after the end or on an archived experiment. A metric that matches the event through an
        action step isn't found.

        A launched experiment that has not ended gets the info `stale_experiment` more than 60 days
        after its start date, when the daily calculation leaves it out, with `days_running` from the
        start date in `evidence`.
        It offers `freeze_exposure` next to `end_experiment` when the experiment can freeze exposure.

        The severity of the `some_conditions_pinned` finding follows the largest share that the
        users of the pinned release conditions make up among the users who got one variant from
        the flag, in the last 7 days, or since launch or the flag's last save if later. It reads
        the flag's calls that name the matched condition, not the experiment's exposure criteria.
        When the experiment applies the filter for internal and test users, the counts leave out the
        calls that the filter excludes, so pinned users that the filter excludes add nothing. The
        severity is info up to 5%, warning above, and no finding under 1% when at least half of the calls
        that returned a variant name a condition. The finding is info when the share is unknown,
        and `reason` says why: `not_measured` (for example an API key without
        `query:read`, or a caller denied a flag call property), `too_few_people` (under 100), or
        `evaluated_outside_flag_service` (most calls come from local evaluation, a bootstrap or
        the caller's own assignment). A pin to a variant with 0% in the split adds an info,
        because that variant's results show only the pinned users, unless the experiment
        excludes the variant from the analysis.

        Two findings say that the variants are assigned outside PostHog, as info. A running
        experiment whose flag has a 0% rollout gets `assigned_outside_flag_service` instead of
        `running_but_no_rollout` when 10 or more people got a variant from flag calls without a
        flag version that are no local evaluation, from an hour after the window starts. The
        count leaves out the calls that the filter for internal and test users excludes, when the
        experiment applies it. When
        every condition that includes users pins the variant whose key one property holds,
        `assigned_by_property` replaces `all_conditions_pinned`. When none of them includes
        everyone, so that every other user gets no variant, `closed_to_matched_users` replaces it,
        as a warning. A condition without filters, or with only filters that leave users out,
        includes everyone.

        A draft whose flag has no recorded call gets the info `new_flag_no_traffic`. The record
        is the flag's `last_called_at`, which a periodic task updates, so it trails a call. The
        check reports `not_checked` when the organization's flag calls skip the events table,
        and when the project has no active flag, because the web SDK then requests no flags.

        A running experiment whose flag is disabled gets `paused_from_experiment`, as info, when
        its latest pause or resume since launch is a pause of the experiment. Otherwise it gets
        `running_but_flag_disabled`, as a warning. A caller who can't view the linked flag's
        history gets the warning, because the pause is not read. A draft whose flag is already
        active with multiple variants gets `not_started_but_multiple_variants_rolled_out` as info.
        An ended experiment whose flag is still active with multiple variants gets no finding when
        another experiment on the flag is running or launched after the end. Otherwise it gets
        `ended_flag_shared_with_draft` as info when a draft experiment uses the flag,
        `ended_but_multiple_variants_rolled_out` as a warning when the flag's `last_called_at` is
        after the end and within the last 3 days, and `ended_flag_not_called` as info when it is
        not, from 3 days and an hour after the end, because `last_called_at` trails a call. Until
        then without such a call, or when the organization's flag calls can't be read, it gets
        `ended_flag_calls_unknown` as info.

        A running experiment whose first primary metric is a funnel gets the info
        `early_significance` (subcode `below_detectable_effect`) when a significant variant's
        difference is smaller than the smallest difference its sample can detect, while that
        sample is below the one the running time estimate plans for the minimum detectable
        effect. It reads the metric's current stored result, the one the results page shows
        after its last calculation, and the running time calculator's formula.

        A running experiment gets the info `result_ready` when its first primary metric has an
        answer, with `end_experiment`. Subcode `stayed_significant`: every stored result for 3 days
        or more shows a variant as significant, named in `evidence` with `significant_since` and
        `days_significant`. The results count from the earliest result in that unbroken run up to
        the current one, both daily points and recalculations, so an edit of the metric starts
        over. Subcode `target_reached_not_significant`: the current result counts at least the
        sample that the running time estimate plans for, and shows every variant as not
        significant. Neither fires while `early_significance` reports the experiment.

        A running experiment with `only_count_matured_users` on gets the info
        `metrics_not_matured` while it is younger than the conversion or retention window of
        every primary metric, because no user can count for those metrics until a window passes.

        With `at_launch=true`, a draft is checked as it will be when its launch succeeds: a check
        that runs only after launch, such as `no_metric`, also runs as if the experiment launched
        now. A check that needs exposures, a calculation or a flag change keeps the reason
        "Runs after launch".
        """
        experiment: ExperimentHandle = self.get_object()
        # The checks read the stored results and the exposure counts, which came from the warehouse.
        _check_warehouse_native_result_access(experiment, self.team, request.user)
        health = get_experiment_health(
            team_id=self.team_id,
            experiment_id=experiment.id,
            reader_access=self._health_reader_access(request, experiment),
            user=request.user if isinstance(request.user, User) else None,
            at_launch=request.validated_query_data["at_launch"],
        )
        return Response(ExperimentHealthSerializer(health).data)

    def _health_reader_access(self, request: Request, experiment: ExperimentHandle) -> ExperimentHealthReaderAccess:
        # The split history is flag history, which `activity` keeps behind the flag's own access controls and
        # `activity_log:read`. It also queries events, which a scoped token reaches only with `query:read`.
        scopes = get_authenticator_scopes(request.successful_authenticator)
        missing_scopes = (
            set()
            if scopes is None or "*" in scopes
            else set(scopes_not_covered(scopes, ["activity_log:read", "query:read"]))
        )
        can_view_flag = self._can_view_flag(experiment)
        restrictions = get_restricted_properties_with_group_type_index_for_team(
            user=cast(User, request.user), team_id=self.team_id
        )
        return ExperimentHealthReaderAccess(
            can_read_flag_history=can_view_flag and "activity_log:read" not in missing_scopes,
            can_query_events="query:read" not in missing_scopes,
            denied_event_properties=split_restricted_property_names(restrictions).event,
            restricted_properties=frozenset(restrictions),
        )

    def _can_view_flag(self, experiment: ExperimentHandle) -> bool:
        flag = ObjectAccessRef(
            resource="feature_flag",
            id=str(experiment.feature_flag_id),
            team_id=self.team.id,
            created_by_id=experiment.feature_flag_created_by_id,
        )
        return authorization.check(
            resource=resource_for_ref(flag), action=Action.VIEW, subject=request_subject(self.request)
        )

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

        experiment: ExperimentHandle = self.get_object()

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
        saved_metric_ids = [str(pk) for pk in experiments_facade.linked_saved_metric_ids(experiment_id=experiment.id)]
        if saved_metric_ids:
            activity_filter |= Q(scope="Experiment", item_id__in=saved_metric_ids, detail__type="shared_metric")
        # The flag's history stays behind the flag's own access controls: a viewer of the
        # experiment may have "none" access to the linked flag.
        if self._can_view_flag(experiment):
            activity_filter |= Q(scope="FeatureFlag", item_id=str(experiment.feature_flag_id))

        activity_query = (
            ActivityLog.objects.select_related("user")
            .filter(activity_filter, team_id=self.team_id)
            .order_by("-created_at")
        )
        activity_page = get_activity_page(activity_query, limit, page)
        return activity_page_response(activity_page, limit, page, request)

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
        experiment: ExperimentHandle = self.get_object()
        paused_experiment = lifecycle.pause_experiment(
            team=self.team,
            user=cast(User, request.user),
            experiment_id=experiment.id,
            request_context={"request": request},
        )
        return self._experiment_response(paused_experiment.id)

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
        experiment: ExperimentHandle = self.get_object()
        resumed_experiment = lifecycle.resume_experiment(
            team=self.team,
            user=cast(User, request.user),
            experiment_id=experiment.id,
            request_context={"request": request},
        )
        return self._experiment_response(resumed_experiment.id)

    @extend_schema(
        request=None,
        responses=ExperimentSerializer,
    )
    @action(methods=["POST"], detail=True, required_scopes=["experiment:write"])
    def freeze_exposure(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Freeze exposure on a running experiment while metrics keep flowing.

        Snapshots the already-exposed users into a static cohort and narrows the
        linked feature flag so only those users keep matching — new users can no
        longer enter the experiment. ``end_date`` is left null so long-term metrics
        (revenue/LTV/renewals/retention) keep accumulating. Enrolled users keep
        their assigned variant. The serialized status becomes 'exposure_frozen'.

        Returns 400 if the experiment is not running, exposure is already frozen,
        the experiment is group-aggregated (group flags cannot be frozen with a
        person cohort), or the exposed set is too large to snapshot synchronously.
        """
        experiment: ExperimentHandle = self.get_object()
        frozen_experiment = lifecycle.freeze_exposure(
            team=self.team,
            user=cast(User, request.user),
            experiment_id=experiment.id,
            request_context={"request": request},
        )
        return self._experiment_response(frozen_experiment.id)

    @extend_schema(
        request=None,
        responses=ExperimentSerializer,
    )
    @action(methods=["POST"], detail=True, required_scopes=["experiment:write"])
    def unfreeze_exposure(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Reopen enrollment on an exposure-frozen experiment.

        Removes the snapshot-cohort condition and freeze markers from every release
        group, restoring the flag's original targeting: new users can enroll again
        and already-enrolled users keep their assigned variant. The snapshot cohort
        is soft-deleted. The serialized status returns to 'running'.

        Returns 400 if the experiment is not running or its exposure is not frozen.
        """
        experiment: ExperimentHandle = self.get_object()
        unfrozen_experiment = lifecycle.unfreeze_exposure(
            team=self.team,
            user=cast(User, request.user),
            experiment_id=experiment.id,
            request_context={"request": request},
        )
        return self._experiment_response(unfrozen_experiment.id)

    @extend_schema(
        request=None,
        responses=ExperimentSerializer,
    )
    @action(methods=["POST"], detail=True, required_scopes=["experiment:write"])
    def reset(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Reset an experiment back to draft state.

        Clears start/end dates, conclusion, archived flag, and any flag-cleanup
        task pointer. The feature flag is left unchanged — users continue to see
        their assigned variants.

        Previously collected events still exist but won't be included in
        results unless the start date is manually adjusted after re-launch.

        Returns 400 if the experiment is already in draft state.
        """
        experiment: ExperimentHandle = self.get_object()
        reset_experiment = lifecycle.reset_experiment(
            team=self.team,
            user=cast(User, request.user),
            experiment_id=experiment.id,
            request_context={"request": request},
        )
        return self._experiment_response(reset_experiment.id)

    @action(methods=["POST"], detail=True, required_scopes=["experiment:write"])
    def duplicate(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        source_experiment: ExperimentHandle = self.get_object()

        if experiment_uses_legacy_metrics(team=self.team, experiment_id=source_experiment.id):
            return Response(
                {"detail": "Duplication is not supported for experiments using legacy metrics."},
                status=400,
            )

        feature_flag_key = request.data.get("feature_flag_key")
        name = request.data.get("name")

        duplicate_experiment = lifecycle.duplicate_experiment(
            team=self.team,
            user=cast(User, request.user),
            experiment_id=source_experiment.id,
            feature_flag_key=feature_flag_key,
            name=name,
            serializer_context=self.get_serializer_context(),
        )

        return self._experiment_response(duplicate_experiment.id, status_code=201)

    @extend_schema(
        request=None,
        responses=ExperimentSerializer,
    )
    @action(methods=["POST"], detail=True, required_scopes=["experiment:write"])
    def migrate(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Move a legacy experiment onto the new experiments engine.

        Creates a new experiment with the same configuration and its metrics converted
        to the new format, and returns it. Legacy experiments no longer show results,
        so this is how to get results for one. The legacy experiment is left untouched,
        so the project ends up with two experiments. Both point at the same feature
        flag, so no new rollout is needed and users keep the variant they already have.

        Legacy shared metrics used by the experiment are converted as part of the same
        call. Each one gets a new shared metric, and the new experiment links to that.

        Calling this again returns the experiment created the first time instead of
        making another copy.

        Returns 400 if the experiment already uses the new engine.
        """
        refuse_scout_experiment_migrate(is_scout_sandbox_request(request))
        experiment: ExperimentHandle = self.get_object()

        if not experiment_uses_legacy_metrics(team=self.team, experiment_id=experiment.id):
            raise ValidationError(
                "This experiment already uses the new experiments engine, so there is nothing to migrate."
            )

        try:
            migrated_experiment = migrate_legacy_experiment(experiment.id, self.team.id, migrate_shared_metrics=True)
        except (LegacyMigrationError, ValueError) as e:
            raise ValidationError(f"Couldn't migrate this experiment: {e}. Contact support if it keeps happening.")

        return self._experiment_response(migrated_experiment.id)

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
        # Scope checks alone don't cover resource-level access controls: this action runs on the
        # experiment viewset, so AccessControlPermission only verifies experiment access. Check
        # prompt access explicitly before validation queries LLMPrompt and leaks which names exist.
        if not self.user_access_control.check_access_level_for_resource("llm_prompt", required_level="viewer"):
            raise PermissionDenied("Creating an experiment from a prompt requires LLM analytics access.")

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

        experiment_id = experiments_facade.add_experiment(
            team=self.team,
            user=cast(User, request.user),
            experiment=CreateExperimentInput(
                name=name,
                feature_flag_key=feature_flag_key,
                description=data.get("description", ""),
                parameters={
                    "prompt_metadata": {
                        "name": prompt_name,
                        "templates": templates,
                        "versions": versions,
                    },
                },
                feature_flag_config={
                    "filters": {
                        "multivariate": {"variants": variants},
                        "groups": [{"properties": [], "rollout_percentage": 100}],
                        "payloads": feature_flag_payloads,
                    },
                },
                metrics=metrics,
                serializer_context=self.get_serializer_context(),
                allow_unknown_events=True,
            ),
            tags=None,
        )

        return self._experiment_response(experiment_id, status_code=201)

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
        refuse_scout_experiment_copy_to_project(is_scout_sandbox_request(request))
        source_experiment: ExperimentHandle = self.get_object()

        if experiment_uses_legacy_metrics(team=self.team, experiment_id=source_experiment.id):
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

        self._check_copy_target_access(request, target_team)

        feature_flag_key = request_serializer.validated_data.get("feature_flag_key")
        name = request_serializer.validated_data.get("name")

        new_experiment = lifecycle.copy_experiment_to_project(
            team=self.team,
            user=cast(User, request.user),
            experiment_id=source_experiment.id,
            target_team=target_team,
            feature_flag_key=feature_flag_key,
            name=name,
            serializer_context={
                "request": request,
                "team_id": target_team.id,
                "project_id": target_team.project_id,
                "get_team": lambda: target_team,
            },
        )

        # The response's access level comes from the access control of this view, which reads the rules of the
        # source project.
        return self._experiment_response(new_experiment.id, team=target_team, status_code=201)

    @action(methods=["POST"], detail=True, required_scopes=["experiment:write"])
    def create_exposure_cohort_for_experiment(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        experiment: ExperimentHandle = self.get_object()
        cohort_data = lifecycle.create_exposure_cohort(
            team=self.team,
            user=cast(User, request.user),
            experiment_id=experiment.id,
            serializer_context={
                "request": request,
                "team": self.team,
                "team_id": self.team_id,
            },
        ).cohort
        return Response({"cohort": cohort_data}, status=201)

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
                    "Ignored. The server derives the metric's calculation key from the experiment's current "
                    "settings. Accepted so that existing clients keep working."
                ),
                required=False,
                deprecated=True,
            ),
        ],
        responses={200: ExperimentTimeseriesResultsSerializer},
    )
    @action(methods=["GET"], detail=True, required_scopes=["experiment:read"])
    def timeseries_results(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        experiment: ExperimentHandle = self.get_object()
        _check_warehouse_native_result_access(experiment, self.team, request.user)
        metric_uuid = request.query_params.get("metric_uuid")

        if not metric_uuid:
            raise ValidationError("metric_uuid query parameter is required")

        results = experiments_facade.get_timeseries_results(
            team=self.team, user=cast(User, request.user), experiment_id=experiment.id, metric_uuid=metric_uuid
        )
        return Response(ExperimentTimeseriesResultsSerializer(results).data)

    @action(methods=["POST"], detail=True, required_scopes=["experiment:write"])
    def recalculate_timeseries(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        experiment: ExperimentHandle = self.get_object()

        # Only the metric's uuid is read, and a `fingerprint` in the body is ignored: the service derives the
        # definition and the key from the experiment.
        metric = request.data.get("metric")

        if not isinstance(metric, dict) or not metric:
            raise ValidationError("metric is required")

        recalculation = lifecycle.request_timeseries_recalculation(
            team=self.team,
            user=cast(User, request.user),
            experiment_id=experiment.id,
            metric_uuid=metric.get("uuid") or "",
        )

        if not recalculation.is_existing:
            start_timeseries_recalculation_workflow(str(recalculation.id), team_id=self.team.id)

        result = {field.name: getattr(recalculation, field.name) for field in fields(recalculation)}
        del result["is_existing"]
        return Response(result, status=200 if recalculation.is_existing else 201)

    @extend_schema(
        request=RecalculateMetricsRequestSerializer,
        responses={
            200: ExperimentMetricsRecalculationJobSerializer,
            201: ExperimentMetricsRecalculationJobSerializer,
            429: OpenApiResponse(
                description=(
                    "A manual trigger arrived less than five minutes after the latest completed run finished. "
                    "Retry-After carries the seconds until the next run is allowed."
                )
            ),
            503: OpenApiResponse(
                description=(
                    "Experiment recalculations are paused for this instance and no run was created. "
                    "Retry-After carries the seconds until the next attempt."
                )
            ),
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
        already pending or in progress for this experiment. An experiment that started too long ago gets 201 with
        a run that is already failed: every metric carries the `recalculation_window_too_long` error in
        `metric_errors`, no workflow starts, and a retry gets the same answer. A manual trigger within five
        minutes after the latest completed run finished returns 429 with a Retry-After header. While recalculations are
        paused for the instance, a request with no active run returns 503 with a Retry-After header. The response payload intentionally does not
        include the `results` array — at POST time the workflow has just been queued and no per-metric
        results exist yet. Clients should poll `GET metrics_recalculation/{id}/` for results as the workflow
        progresses.
        """
        experiment: ExperimentHandle = self.get_object()
        request_serializer = RecalculateMetricsRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)

        is_mcp_client = request.headers.get("x-posthog-client") == "mcp"
        trigger = RECALCULATION_TRIGGER_AGENT_MCP if is_mcp_client else request_serializer.validated_data["trigger"]

        # request.user is User | AnonymousUser at the DRF level; the viewset enforces auth so it's a User here.
        experiments_facade.assert_user_may_run_warehouse_native_sources(
            team=self.team, user=cast(User, request.user), experiment_id=experiment.id
        )
        result = start_metrics_recalculation(
            team_id=experiment.team_id,
            experiment_id=experiment.id,
            user_id=cast(User, request.user).id,
            trigger=trigger,
        )
        return Response(
            ExperimentMetricsRecalculationJobSerializer(result).data,
            status=200 if result.is_existing else 201,
        )

    @extend_schema(responses={200: ExperimentMetricsRecalculationLatestSerializer, 404: None})
    @action(
        methods=["GET"],
        detail=True,
        # NOTE: this action is declared BEFORE the by-id action so its URL pattern wins on /latest/.
        url_path="metrics_recalculation/latest",
        required_scopes=["experiment:read"],
    )
    def metrics_recalculation_latest(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        experiment: ExperimentHandle = self.get_object()
        latest = get_latest_recalculation(
            team_id=experiment.team_id, experiment_id=experiment.id, user_id=_request_user_id(request)
        )
        if latest is None:
            return Response({"detail": "No completed recalculation found"}, status=404)
        return Response(ExperimentMetricsRecalculationLatestSerializer(latest).data)

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="recalculation_id",
                location=OpenApiParameter.PATH,
                # Keep the URL's UUID pattern in the schema; declaring a bare UUID type drops it.
                type={
                    "type": "string",
                    "pattern": r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$",
                },
                description=(
                    "UUID of the recalculation run to fetch. This is the run's own id, not the experiment id."
                ),
            )
        ],
        responses={200: ExperimentMetricsRecalculationRunSerializer, 404: None},
    )
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
        experiment: ExperimentHandle = self.get_object()
        run = get_recalculation_run(
            team_id=experiment.team_id,
            experiment_id=experiment.id,
            recalculation_id=recalculation_id,
            user_id=_request_user_id(request),
        )
        if run is None:
            return Response({"detail": "Recalculation not found"}, status=404)
        return Response(ExperimentMetricsRecalculationRunSerializer(run).data)

    @action(methods=["GET"], detail=False, url_path="stats", required_scopes=["experiment:read"])
    def stats(self, request: Request, **kwargs: Any) -> Response:
        return Response(asdict(experiments_facade.get_velocity_stats(team=self.team)))

    @validated_request(
        query_serializer=RunningTimeTargetQuerySerializer,
        responses={200: OpenApiResponse(response=RunningTimeTargetSerializer)},
    )
    @action(methods=["GET"], detail=True, url_path="running_time_target", required_scopes=["experiment:read"])
    def running_time_target(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        """The target sample of the experiment's running time estimate, which the experiment page's header compares
        with the exposures so far, and what the experiment can detect over time.

        In manual running time mode it is the saved target. Otherwise it is sized from the first primary metric's
        current result: the variance the analysis uses (with CUPED when the analysis applied it) and the flag's
        traffic split, so that the comparison of each variant with the control reaches the minimum detectable effect.
        """
        experiment: ExperimentHandle = self.get_object()
        # The target is sized from the stored result of the primary metric, which came from the warehouse.
        _check_warehouse_native_result_access(experiment, self.team, request.user)
        target = get_running_time_target(
            team_id=self.team.id,
            experiment_id=experiment.id,
            mode=RunningTimeMode(mode) if (mode := request.validated_query_data.get("mode")) else None,
        )
        return Response(RunningTimeTargetSerializer(target).data)

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
                step_counts=tuple(stats.get("step_counts") or ()),
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

    @validated_request(
        request_serializer=ExperimentSetupContextInputSerializer,
        responses={200: OpenApiResponse(response=ExperimentSetupContextResponseSerializer)},
    )
    @action(
        methods=["POST"],
        detail=False,
        url_path="setup_context",
        # The response carries saved-metric definitions and reuse counts, which the saved-metric
        # API gates behind its own scope. Object-level filtering does not check token scopes.
        # It also counts arbitrary events across the project, which /query/ gates behind query:read.
        required_scopes=["experiment:read", "experiment_saved_metric:read", "query:read"],
        throttle_classes=[ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle],
    )
    def setup_context(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        """Facts about this project that decide how to configure a new experiment.

        Returns the team's experiment defaults, which SDKs call feature flags, traffic on a target
        surface, the baseline of a candidate metric, how recent experiments were set up, and the
        most reused shared metrics. Each section has its own status, so a slow or failed read
        leaves the others valid. POST because the inputs describe a plan rather than a resource;
        the endpoint only reads.
        """
        if not self._setup_context_enabled():
            raise NotFound()

        data = request.validated_data
        # detail=False actions skip the automatic list-action ACL filtering, so filter here: the
        # response names experiments and shared metrics, which must respect object-level access.
        experiment_access = self._list_access("experiment")
        saved_metric_access = self._list_access("experiment_saved_metric")
        context = build_setup_context(
            team=self.team,
            inputs=SetupContextInputs(
                target_event=data.get("target_event") or None,
                target_url_contains=data.get("target_url_contains") or None,
                target_properties=tuple(data.get("target_properties") or ()),
                metric_event=data.get("metric_event") or None,
                metric_properties=tuple(data.get("metric_properties") or ()),
                previous_experiments_limit=data["previous_experiments_limit"],
                shared_metrics_limit=data["shared_metrics_limit"],
            ),
            experiment_access=experiment_access,
            saved_metric_access=saved_metric_access,
        )
        return Response(ExperimentSetupContextResponseSerializer(context).data)

    def _setup_context_enabled(self) -> bool:
        # In a loginas impersonation session request.user is the customer. The flag is evaluated for the staff
        # user, so support can read a customer's setup context without the flag being on for that customer.
        # OAuth impersonation (MCP) has no session, so it keeps the customer's flag, which also gates the tool.
        flag_user = get_original_user_from_session(self.request) if is_impersonated_session(self.request) else None
        try:
            return posthog_feature_flag_enabled(
                EXPERIMENT_SETUP_CONTEXT_FLAG,
                str((flag_user or cast(User, self.request.user)).distinct_id),
                organization_id=self.organization_id,
                team_id=self.team.id,
            )
        except Exception:
            logger.warning("Failed to evaluate the experiment setup context flag", exc_info=True)
            return False

    @extend_schema(
        description=(
            "Resolve which experiments (and variants) a session recording saw. Variants come from the session's "
            "$feature_flag_called events and stamped $feature/<key> event properties — flag evaluation, which may "
            "differ from an experiment's exposure criteria."
        ),
        parameters=[
            OpenApiParameter(
                name="session_id",
                location=OpenApiParameter.QUERY,
                type=str,
                required=True,
                description="ID of the session recording to resolve experiment context for.",
            ),
        ],
        responses={200: OpenApiResponse(response=ExperimentSessionContextResponseSerializer)},
    )
    @action(
        methods=["GET"],
        detail=False,
        url_path="session_context",
        required_scopes=["experiment:read", "session_recording:read"],
        throttle_classes=[ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle],
    )
    def session_context(self, request: Request, **kwargs: Any) -> Response:
        session_id = (request.query_params.get("session_id") or "").strip()
        if not session_id:
            raise ValidationError({"session_id": ["This field is required."]})

        if not self.user_access_control.check_access_level_for_resource("session_recording", required_level="viewer"):
            raise PermissionDenied("Reading session experiment context requires session replay access.")

        if not _accessible_session_ids(request, self.user_access_control, self.team, [session_id]):
            raise PermissionDenied("You don't have access to this recording.")

        # detail=False actions skip the automatic list-action ACL filtering, so filter here —
        # private experiments must not leak into another user's session context.
        experiment_access = self._list_access("experiment")
        # user threads through to the HogQL queries: exposure criteria can filter on arbitrary
        # properties, which must respect the viewer's property-level access control.
        items = get_session_experiment_context(
            team=self.team, user=cast(User, request.user), session_id=session_id, experiment_access=experiment_access
        )
        if items is None:
            raise NotFound("Recording not found")

        serializer = ExperimentSessionContextResponseSerializer({"session_id": session_id, "results": items})
        return Response(serializer.data)

    @validated_request(
        request_serializer=ExperimentSessionContextsRequestSerializer,
        responses={200: OpenApiResponse(response=ExperimentSessionContextsResponseSerializer)},
    )
    @action(
        methods=["POST"],
        detail=False,
        url_path="session_contexts",
        required_scopes=["experiment:read", "session_recording:read"],
        # Not the ClickHouse* pair the single-session action uses: that pair only limits
        # personal-API-key traffic, and this endpoint's primary caller is the
        # session-authenticated web app.
        throttle_classes=[SessionContextsBurstRateThrottle, SessionContextsSustainedRateThrottle],
    )
    def session_contexts(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        """Resolve experiment context for a batch of session recordings.

        Batch variant of `session_context`, used to prefetch the replay player's experiments
        box for a whole recordings list in one request. POST because the id list doesn't fit a
        query string; the endpoint only reads. Already-computed sessions are served from (and
        cold ones written to) the same short-lived per-viewer cache the single-session endpoint
        uses, so opening any prefetched recording renders its context instantly. Sessions whose
        recording metadata doesn't exist yet are omitted from the response, as are recordings
        the caller can't access and sessions beyond the batch's recording-day budget (each
        distinct recording day costs its own set of ClickHouse scans, so only the most recent
        days are computed per request).
        """
        session_ids: list[str] = request.validated_data["session_ids"]

        if not self.user_access_control.check_access_level_for_resource("session_recording", required_level="viewer"):
            raise PermissionDenied("Reading session experiment context requires session replay access.")

        # Denied recordings are omitted rather than rejecting the batch, matching how the response
        # already treats a session whose recording metadata doesn't exist.
        session_ids = _accessible_session_ids(request, self.user_access_control, self.team, session_ids)

        # detail=False actions skip the automatic list-action ACL filtering, so filter here —
        # private experiments must not leak into another user's session context.
        experiment_access = self._list_access("experiment")
        contexts = get_session_experiment_contexts(
            team=self.team, user=cast(User, request.user), session_ids=session_ids, experiment_access=experiment_access
        )
        serializer = ExperimentSessionContextsResponseSerializer(
            {"results": [{"session_id": session_id, "results": items} for session_id, items in contexts.items()]}
        )
        return Response(serializer.data)

    @extend_schema(
        request=None,
        responses={200: OpenApiResponse(response=ExperimentInSessionExposureSerializer)},
    )
    @action(methods=["GET"], detail=True, url_path="in_session_exposure", required_scopes=["experiment:read"])
    def in_session_exposure(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """How the recordings tab's in-session exposure scope reads on this experiment.

        Resolved through the same seam as the recordings query's `in_session` refusal, so the
        scope control disables exactly what a query would be refused for, and the copy can say
        when sessions are matched on the stamped flag property rather than on the exposure event.
        Postgres reads only, so it can serve the tab's mount path.
        """
        experiment: ExperimentHandle = self.get_object()
        semantics = resolve_in_session_exposure_semantics(team_id=self.team_id, experiment_id=experiment.id)
        if semantics is None:
            raise NotFound()
        return Response(ExperimentInSessionExposureSerializer(semantics).data)

    @validated_request(
        request_serializer=ExperimentSessionBucketRequestSerializer,
        responses={200: OpenApiResponse(response=ExperimentSessionBucketResponseSerializer)},
    )
    @action(
        methods=["POST"],
        detail=True,
        url_path="session_buckets",
        required_scopes=["experiment:read", "session_recording:read"],
        # Heavier than the session-context batch (it scans the run window rather than a known id
        # list) and called by the session-authenticated web app, which the ClickHouse* pair
        # doesn't cover.
        throttle_classes=[SessionBucketsBurstRateThrottle, SessionBucketsSustainedRateThrottle],
    )
    def session_buckets(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        """Session recordings of this experiment matching a bucket.

        Answers the questions a recordings query can't express on its own — "fired any of these
        metrics", "fired none of them", "was exposed but never completed the funnel in this
        session" — by returning a bounded, most-recent-first list of session IDs to pass back as
        a recordings query's session_ids. POST because the metric list doesn't fit a query
        string; the endpoint only reads.

        Session-scoped and goal-free: the set describes what happened in each session, while the
        experiment analysis counts per person over the whole run window. A session can be in the
        drop-off bucket while the same person converts in a later one.
        """
        experiment: ExperimentHandle = self.get_object()

        if not self.user_access_control.check_access_level_for_resource("session_recording", required_level="viewer"):
            raise PermissionDenied("Reading experiment session buckets requires session replay access.")

        try:
            scan = get_experiment_session_bucket(
                team=self.team,
                # user threads through to the HogQL query: metric sources and exposure criteria
                # can filter on arbitrary properties, which must respect the viewer's
                # property-level access control.
                user=cast(User, request.user),
                experiment_id=experiment.id,
                bucket=ExperimentSessionBucket(request.validated_data["bucket"]),
                metric_uuids=request.validated_data["metric_uuids"],
                variant=request.validated_data["variant"],
                limit=request.validated_data["limit"],
            )
        except SessionBucketUnavailable as error:
            raise ValidationError(str(error))
        if scan is None:
            raise NotFound()

        # Applied to the computed set rather than inside the scan: the bucket is cached per
        # viewer, so filtering on read honors a revocation that lands while an entry is warm. The
        # cut to `limit` follows it, so a denied recording never spends a returned slot and
        # `truncated` describes what this viewer may see.
        result = finalize_session_bucket(
            scan,
            _accessible_session_ids(request, self.user_access_control, self.team, scan.candidate_session_ids),
        )
        return Response(ExperimentSessionBucketResponseSerializer(result).data)

    @validated_request(
        request_serializer=ExperimentSessionEventDeltaRequestSerializer,
        responses={200: OpenApiResponse(response=ExperimentSessionEventDeltaResponseSerializer)},
    )
    @action(
        methods=["POST"],
        detail=True,
        url_path="session_event_deltas",
        required_scopes=["experiment:read", "session_recording:read"],
        # The heaviest read in this family: it compares every event name in the window, so unlike
        # the bucket scan there is no event-name predicate for ClickHouse to prune on.
        throttle_classes=[SessionEventDeltasBurstRateThrottle, SessionEventDeltasSustainedRateThrottle],
    )
    def session_event_deltas(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        """The recordings worth watching for this experiment, grouped into cards.

        Each card is one sentence and the recordings that back it: an event one variant did clearly
        more than the others, an error signal concentrated in one variant, or a shortcut to a
        metric event happening on screen. Every card's count is a count of recordings that actually
        exist, so handing its session ids to the recordings list can't come back empty. POST to
        take the same throttle and cache posture as the other reads in this family rather than
        because it carries a body: it takes no parameters, and it only reads.

        It reports no effect size. Cards carry a direction and a band rather than a rate, a ratio
        or a person count: the experiment's results already state magnitudes, computed per person
        over the whole run window, and this reads one session per person over a clamped one. Two
        numbers for the same event would read as a contradiction, so this surface states none. That
        is what lets a card sit on one of the experiment's own metric events, which it names, so a
        reader is sent to the results rather than given a second answer.
        """
        experiment: ExperimentHandle = self.get_object()

        if not self._session_event_deltas_enabled():
            raise NotFound()

        if not self.user_access_control.check_access_level_for_resource("session_recording", required_level="viewer"):
            raise PermissionDenied("Comparing an experiment's session behavior requires session replay access.")

        try:
            result = get_experiment_session_event_deltas(
                team=self.team,
                # user threads through to the HogQL queries: exposure criteria can filter on
                # arbitrary properties, which must respect the viewer's property-level access
                # control.
                user=cast(User, request.user),
                experiment_id=experiment.id,
            )
        except SessionEventDeltasUnavailable as error:
            raise ValidationError(str(error))
        if result is None:
            raise NotFound()

        # Applied to the computed shelf rather than inside the scan, as the session buckets do it:
        # the shelf is cached across viewers sharing a restriction profile, so filtering on read is
        # what keeps one viewer's entry from leaking another's denied recordings, and a revocation
        # lands even while an entry is warm. The resource-level check above grants the replay
        # product, not every recording in it — without this a viewer denied one recording could
        # still read its id, the variant it was in, and an event it contains.
        result = finalize_watch_cards(
            result,
            _accessible_session_ids(request, self.user_access_control, self.team, all_card_session_ids(result)),
        )
        return Response(ExperimentSessionEventDeltaResponseSerializer(result).data)

    def _session_event_deltas_enabled(self) -> bool:
        # Scoped to the experiment's organization rather than the caller's current one: a user in
        # several orgs could otherwise switch their current org to a flagged-in one and read an
        # experiment in an org that is not.
        try:
            return posthog_feature_flag_enabled(
                EXPERIMENT_BEHAVIOR_COMPARISON_FLAG,
                str(cast(User, self.request.user).distinct_id),
                organization_id=self.organization_id,
                team_id=self.team.id,
            )
        except Exception:
            logger.warning("Failed to evaluate the experiment behavior comparison flag", exc_info=True)
            return False


def _list_filters(request: Request) -> ExperimentListFilters:
    return ExperimentListFilters(
        **{field.name: request.query_params.get(field.name) for field in fields(ExperimentListFilters)}
    )


def _request_user_id(request: Request) -> int | None:
    return request.user.id if isinstance(request.user, User) else None


def _check_warehouse_native_result_access(experiment: ExperimentHandle, team: Team, user: Any) -> None:
    """A stored run holds totals read from the customer's warehouse. The reader needs the connection access
    that the query endpoint asks for, or the run hands out what that endpoint refuses."""
    if experiment.warehouse_native_connection_id is None:
        return
    validate_warehouse_native_connection_access(
        team, user if isinstance(user, User) else None, experiment.warehouse_native_connection_id
    )
