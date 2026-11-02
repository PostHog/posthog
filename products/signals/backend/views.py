import re
import json
import math
import time
import uuid
from collections.abc import Callable, Iterable, Sequence
from contextlib import ExitStack
from datetime import UTC, timedelta
from functools import cached_property, partial
from typing import Any, Literal, cast

from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError, models, transaction
from django.db.models import (
    BooleanField,
    Case,
    Count,
    Exists,
    F,
    IntegerField,
    OuterRef,
    Prefetch,
    Q,
    Subquery,
    Sum,
    Value,
    When,
    Window,
)
from django.db.models.expressions import OrderBy
from django.db.models.functions import Coalesce
from django.db.models.lookups import GreaterThanOrEqual
from django.utils import timezone

import structlog
import posthoganalytics
from asgiref.sync import async_to_sync
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema, extend_schema_view
from opentelemetry import trace
from pydantic import ValidationError as PydanticValidationError
from rest_framework import exceptions, mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from temporalio.common import RetryPolicy, WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.api.integration import github_rate_limited_response
from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import (
    InternalAPIAuthentication,
    OAuthAccessTokenAuthentication,
    PersonalAPIKeyAuthentication,
    SessionAuthentication,
    is_mcp_request,
)
from posthog.dataclasses import frozen
from posthog.egress.github.transport import GitHubEgressBudgetExhausted, GitHubRateLimitError
from posthog.egress.limiter.policies import Priority
from posthog.event_usage import report_user_action
from posthog.integrations import IntegrationManager, IntegrationNotFound
from posthog.models import Team, User
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.activity_logging.model_activity import is_impersonated_session
from posthog.models.github_integration_base import GitHubIntegrationBase, PullRequestRef
from posthog.models.integration import GitHubIntegration
from posthog.models.team.extensions import get_or_create_team_extension
from posthog.models.user_integration import ReauthorizationRequired, UserGitHubIntegration, UserIntegration
from posthog.oauth_provenance import is_sandbox_oauth_request, is_sandbox_origin_request
from posthog.permissions import (
    APIScopePermission,
    get_authenticator_scoped_team_ids,
    get_authenticator_scopes,
    is_service_auth,
)
from posthog.rate_limit import ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle
from posthog.temporal.common.client import sync_connect
from posthog.user_permissions import UserPermissions

from products.data_warehouse.backend.facade.api import trigger_external_data_workflow
from products.signals.backend.agent_instructions import STEERING_FIELDS
from products.signals.backend.artefact_schemas import (
    DISMISSAL_NOTE_MAX_LENGTH,
    DISMISSAL_REASON_WRONG_ASSIGNEE,
    DISMISSAL_REASON_WRONG_REPO,
    FIXED_DISMISSAL_REASONS,
    NON_WRITABLE_ARTEFACT_TYPES,
    ArtefactContentValidationError,
    ChannelAssignment,
    Dismissal,
    NoteArtefact,
    RelevantCommit,
    ReviewerEdit,
    ReviewerProposal,
    ReviewerState,
    SuggestedReviewerEntry,
    SuggestedReviewers,
    SummaryChange,
    TitleChange,
    parse_artefact_content,
)
from products.signals.backend.assignment_flags import assignment_side_effects_allowed
from products.signals.backend.background_pilot import (
    BACKGROUND_REPORT_DISMISSED_EVENT,
    BACKGROUND_REPORT_RATED_EVENT,
    BACKGROUND_REPORT_VIEWED_EVENT,
    capture_background_report_events,
)
from products.signals.backend.billing import (
    REFUND_INELIGIBLE_BILLING_EXEMPT,
    REFUND_INELIGIBLE_NO_BILLABLE_PR,
    REFUND_INELIGIBLE_OUT_OF_PERIOD,
    SIGNALS_CREDITS_PER_REPORT_WITH_PR,
    annotate_first_billable_pr_run_at,
    current_billing_period_bounds,
    first_billable_pr_run,
    first_billable_pr_run_at_by_report,
    period_billable_credits_for_org,
    refund_ineligibility_reason,
    report_pr_is_merged,
)
from products.signals.backend.briefing_reports import reports_for_person
from products.signals.backend.dismissal_notes import forward_dismissal_note, principal_may_steer_scouts
from products.signals.backend.enums import ReportPriority, ReportTaskActionKind, ReviewerRemovalReason
from products.signals.backend.facade.api import emit_signal
from products.signals.backend.feedback_notes import forward_feedback_note
from products.signals.backend.implementation_pr import (
    ImplementationPr,
    fetch_implementation_prs_for_reports,
    implementation_pr_report_filter,
    primary_pull_request,
    pull_request_matches_id,
)
from products.signals.backend.models import (
    ArtefactAttribution,
    AutonomyPriority,
    InvalidStatusTransition,
    SignalActorKind,
    SignalReport,
    SignalReportAction,
    SignalReportArtefact,
    SignalReportCheck,
    SignalReportMonitoringAttempt,
    SignalReportRefund,
    SignalScoutConfig,
    SignalSourceConfig,
    SignalTeamConfig,
    SignalUserAutonomyConfig,
)
from products.signals.backend.personal_ranking.config import PERSONAL_INBOX_RANKING_FLAG
from products.signals.backend.personal_ranking.serve import serve_personal_ranking
from products.signals.backend.pr_ci_status import pr_ci_statuses_for_references, rollup_ci_status
from products.signals.backend.presentation.scout_permissions import ScoutCanonicalTeamAccessPermission
from products.signals.backend.pull_requests import import_report_pull_requests
from products.signals.backend.quota import self_driving_quota_enforcement_enabled, self_driving_quota_gate
from products.signals.backend.ranking.access import can_view_inbox_ranking, user_flag_enabled
from products.signals.backend.ranking.inbox_sort import (
    PRIORITY_ORDERING,
    RANKER_ORDERINGS,
    InboxRanker,
    latest_ranking_value,
    resolve_recommended_ranker,
    score_decile,
)
from products.signals.backend.ranking.public_outcomes import MODEL_HEAD_BY_OUTCOME, PUBLIC_OUTCOME_NAMES
from products.signals.backend.ranking.served_outcomes import served_outcomes
from products.signals.backend.ranking.staleness import EDIT_ARTEFACT_TYPES
from products.signals.backend.receivers import capture_verdict_reason_added_analytics
from products.signals.backend.repo_corrections import sanitized_repository
from products.signals.backend.report_assignments import InvalidPullRequestUrl, ReportClaimConflict, claim_report
from products.signals.backend.report_check_authoring import (
    CheckCreationError,
    CheckQueryAccessError,
    cancel_check,
    replace_metric_check,
)
from products.signals.backend.report_claims import (
    ReportClaim,
    actor_works_under_claim,
    get_active_claim,
    get_active_claims,
    reports_claimed_for_user,
    reports_with_active_claim,
    responsible_users,
)
from products.signals.backend.report_content_gates import (
    organization_inbox_cached_filters_enabled,
    organization_report_monitoring_enabled,
)
from products.signals.backend.report_generation.research import ActionabilityChoice
from products.signals.backend.report_generation.resolve_reviewers import (
    ReviewerPayloadIndex,
    _normalized_reviewer_user_uuid,
    bounded_reviewer_reason,
    get_org_member_github_logins_by_user_uuid,
    normalized_github_logins_from_suggested_reviewer_artefacts,
    normalized_user_uuids_from_suggested_reviewer_artefacts,
    resolve_org_github_login_to_users,
    resolve_org_users_by_uuid,
    search_org_member_users_by_uuid,
    source_skills_from_suggested_reviewer_artefacts,
)
from products.signals.backend.report_generation.reviewer_telemetry import capture_suggested_reviewers_resolved
from products.signals.backend.report_merge import (
    MAX_MERGE_REASON_LENGTH,
    MAX_MERGE_SOURCE_REPORTS,
    ReportMergeError,
    merge_reports,
    was_merged_away,
)
from products.signals.backend.report_metric_access import ReportMetricAccessPolicy
from products.signals.backend.report_metric_refresh import CURRENT_REPORT_STATUSES, refresh_report_metric_snapshots
from products.signals.backend.report_monitoring_attempts import complete_implementation
from products.signals.backend.report_plan import report_plan
from products.signals.backend.report_priority import latest_priority_rank, update_report_priority
from products.signals.backend.report_read_state import (
    ReportReadStateRequestSerializer,
    ReportReadStateResponseSerializer,
    report_read_states,
)
from products.signals.backend.report_task_actions import (
    AI_CONSENT_DISABLED_REASON,
    INBOX_REPORT_ACTION_EVENT,
    PULL_REQUEST_RUN_ACTIVE_DETAIL,
    ReportActionState,
    ReportTaskActionContext,
    ReportTaskActionStartError,
    active_pull_request_run,
    inbox_report_action_properties,
    list_report_task_actions,
    resolve_report_task_action,
    start_report_task_action,
)
from products.signals.backend.reviewer_correction_notes import ReviewerCorrection, forward_reviewer_correction_note
from products.signals.backend.reviewer_pr_assignment import schedule_reviewer_pr_assignment
from products.signals.backend.reviewer_rules import ReviewerRules, ReviewerWriteError, StaleReviewerProposal
from products.signals.backend.scout_authorship import inbox_hidden_report_filter
from products.signals.backend.scout_harness.trial_access import trial_state_errors, trial_store_for_request
from products.signals.backend.scout_report.trial_inbox import TrialInboxReads, private_report_artefacts
from products.signals.backend.serializers import (
    CommitDiffResponseSerializer,
    PersonalRankingQuerySerializer,
    PersonalRankingSerializer,
    PullRequestChecksPermissionErrorSerializer,
    PullRequestChecksResponseSerializer,
    PullRequestCiStatusesResponseSerializer,
    PullRequestCommentsResponseSerializer,
    PullRequestReviewCommentCreateResponseSerializer,
    PullRequestReviewCommentCreateSerializer,
    PullRequestReviewCommentReactionCreateResponseSerializer,
    PullRequestReviewCommentReactionCreateSerializer,
    PullRequestReviewCommentUpdateSerializer,
    RankingOutcomesResponseSerializer,
    RankingOutcomesStatus,
    ReportSignalsResponseSerializer,
    SignalReportArtefactLogCreateSerializer,
    SignalReportArtefactLogUpdateSerializer,
    SignalReportArtefactSerializer,
    SignalReportArtefactWriteResponseSerializer,
    SignalReportArtefactWriteSerializer,
    SignalReportCheckReplacementSerializer,
    SignalReportCheckSerializer,
    SignalReportClaimSerializer,
    SignalReportFilterQuerySerializer,
    SignalReportLeaveReviewersSerializer,
    SignalReportListQuerySerializer,
    SignalReportListSerializer,
    SignalReportMetricRefreshRequestSerializer,
    SignalReportMetricRefreshResponseSerializer,
    SignalReportPriorityUpdateSerializer,
    SignalReportRefundSerializer,
    SignalReportSectionCountsSerializer,
    SignalReportSerializer,
    SignalReportSourceMetadataRequestSerializer,
    SignalReportSourceMetadataResponseSerializer,
    SignalReportSuggestedReviewersArtefactSerializer,
    SignalReportTaskActionErrorSerializer,
    SignalReportTaskActionListResponseSerializer,
    SignalReportTaskActionRunRequestSerializer,
    SignalReportTaskActionRunResponseSerializer,
    SignalSourceConfigSerializer,
    SignalTeamConfigSerializer,
    SignalUserAutonomyConfigCreateSerializer,
    SignalUserAutonomyConfigSerializer,
    personal_ranking_payload,
)
from products.signals.backend.signal_metadata import (
    ReportSignalMeta,
    fetch_signals_for_report_sync,
    fetch_source_products_for_reports,
)
from products.signals.backend.slack_notification_targets import (
    is_slack_member_target,
    resolve_own_direct_message_target,
    saved_notification_integration,
    validate_slack_notification_target,
)
from products.signals.backend.source_suggestions import current_source_suggestion
from products.signals.backend.suggested_reviewer_index import report_ids_naming_reviewers
from products.signals.backend.task_attribution import TASK_ID_HEADER, resolve_request_attribution
from products.signals.backend.task_run_artefacts import ReportTaskCapExceeded
from products.signals.backend.tasks import send_reviewer_added_slack_notifications, sync_signals_refund_credit
from products.signals.backend.temporal.backfill_error_tracking import (
    BackfillErrorTrackingInput,
    BackfillErrorTrackingWorkflow,
)
from products.signals.backend.temporal.deletion import SignalReportDeletionWorkflow
from products.signals.backend.temporal.grouping_v2 import TeamSignalGroupingV2Workflow
from products.signals.backend.temporal.reingestion import SignalReportReingestionWorkflow
from products.signals.backend.temporal.signal_queries import (
    fetch_live_report_ids_for_source_ids,
    fetch_report_ids_for_scout_names,
    fetch_report_ids_for_scout_prefix,
    fetch_report_ids_for_source_products,
)
from products.signals.backend.temporal.types import (
    SignalReportDeletionWorkflowInputs,
    SignalReportReingestionWorkflowInputs,
)
from products.signals.backend.throttles import (
    ReportMetricRefreshThrottle,
    ReportTaskActionRunBurstThrottle,
    ReportTaskActionRunSustainedThrottle,
)
from products.signals.backend.tracker_issues import tracker_issue_completion_lock
from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.access import code_access_required_response, usage_limit_response
from products.tasks.backend.facade.repo_selection_types import RepoSelectionResult
from products.warehouse_sources.backend.facade.models import ExternalDataSchema

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)

AVAILABLE_REVIEWERS_LIMIT = 100
PR_GITHUB_CACHE_SECONDS = 15
_PULL_REQUEST_ID_PARAMETER = OpenApiParameter(
    "pull_request_id",
    OpenApiTypes.UUID,
    OpenApiParameter.QUERY,
    required=False,
    description="Select a PR from the report's pull_requests collection. Omit for the compatibility primary PR (unfinished first).",
)

# Reports one batch CI-status request may ask about. A report list page is 50 rows, so a full page
# of pull requests fits, with room for a flat list that merges several sections.
PR_CI_STATUS_MAX_REPORTS = 100
# Report statuses whose pull request is no longer open, so its CI is not worth a GitHub call.
_PR_CI_STATUS_TERMINAL_REPORT_STATUSES = frozenset(
    {
        SignalReport.Status.FAILED,
        SignalReport.Status.SUPPRESSED,
        SignalReport.Status.RESOLVED,
        SignalReport.Status.CLOSED,
    }
)


def _pull_request_ref_for_commit(
    artefact: SignalReportArtefact,
    repository: str,
    branch: str,
    github: GitHubIntegration,
) -> PullRequestRef | None:
    """Find the report PR that contains the commit artefact's branch."""
    candidates: dict[int, tuple[PullRequestRef, str | None]] = {}
    prs = fetch_implementation_prs_for_reports([str(artefact.report_id)], team_id=artefact.team_id).get(
        str(artefact.report_id), []
    )
    for pr in prs:
        parsed = GitHubIntegration.parse_pull_request_url(pr.url)
        if parsed is not None and parsed.repository.lower() == repository.lower():
            candidates.setdefault(parsed.number, (parsed, pr.task_id))
    if len(candidates) == 1:
        return next(iter(candidates.values()))[0]

    task_id = str(artefact.task_id) if artefact.task_id else None
    task_matches = [candidate for candidate, candidate_task_id in candidates.values() if candidate_task_id == task_id]
    if task_id is not None and len(task_matches) == 1:
        return task_matches[0]

    for candidate, _ in candidates.values():
        details = github.get_pull_request(repository, candidate.number)
        if details.get("success") and details.get("head_branch") == branch:
            return candidate
    return None


def parse_pr_ci_status_report_ids(raw: str | None) -> list[uuid.UUID]:
    """Parse the batch CI-status endpoint's comma-separated `report_ids`.

    A malformed or oversized list is the caller's bug, not a report that has no CI state, so it
    fails loudly instead of answering for the ids that happened to parse.
    """
    ids = [part.strip() for part in (raw or "").split(",") if part.strip()]
    if not ids:
        raise exceptions.ValidationError({"report_ids": "Pass at least one report id."})
    if len(ids) > PR_CI_STATUS_MAX_REPORTS:
        raise exceptions.ValidationError(
            {"report_ids": f"Pass at most {PR_CI_STATUS_MAX_REPORTS} report ids per request."}
        )
    try:
        return [uuid.UUID(report_id) for report_id in ids]
    except ValueError:
        raise exceptions.ValidationError({"report_ids": "Every report id must be a UUID."})


# Ordering field to the outcome head it reads from the served model of the latest ranking score. The API
# documents only the public outcomes. Staff tools and saved URLs still use the internal heads and `ranking_fixed`,
# the old name of `ranking_fix`, so the API accepts them but does not document them.
PUBLIC_RANKING_ORDERING_HEADS: dict[str, str] = {
    f"ranking_{outcome}": head for outcome, head in MODEL_HEAD_BY_OUTCOME.items()
}
UNDOCUMENTED_RANKING_ORDERING_HEADS: dict[str, str] = {
    "ranking_fixed": "fixed",
    "ranking_pr_merged": "pr_merged",
    "ranking_pr_created": "pr_created",
    "ranking_discuss": "discuss",
    "ranking_thumbs_up": "thumbs_up",
    "ranking_reviewer_fix": "reviewer_fix",
    "ranking_refund": "refund",
    "ranking_dismiss_wrong": "dismiss_wrong",
    "ranking_dismiss_lowvalue": "dismiss_lowvalue",
}
RANKING_ORDERING_HEADS: dict[str, str] = PUBLIC_RANKING_ORDERING_HEADS | UNDOCUMENTED_RANKING_ORDERING_HEADS
_OUTCOME_BY_MODEL_HEAD: dict[str, str] = {head: outcome for outcome, head in MODEL_HEAD_BY_OUTCOME.items()}


def classify_report_list_client(user_agent: str | None) -> str:
    if user_agent and user_agent.startswith("posthog/desktop.hog.dev;"):
        return "desktop"
    if user_agent and user_agent.startswith("Mozilla/"):
        return "web"
    return "other"


class EmitSignalSerializer(serializers.Serializer):
    source_product = serializers.CharField(max_length=100)
    source_type = serializers.CharField(max_length=100)
    description = serializers.CharField()
    weight = serializers.FloatField(default=0.5, min_value=0.0, max_value=1.0)
    extra = serializers.DictField(required=False, default=dict)


# Simple debug view, to make testing out the flow easier. Disabled in production.
class SignalViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "INTERNAL"

    @extend_schema(exclude=True)
    @action(methods=["POST"], detail=False)
    def emit(self, request: Request, *args, **kwargs):
        if not settings.DEBUG:
            raise NotFound()

        serializer = EmitSignalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data

        async_to_sync(emit_signal)(
            team=self.team,
            source_product=data["source_product"],
            source_type=data["source_type"],
            source_id=str(uuid.uuid4()),
            description=data["description"],
            weight=data["weight"],
            extra=data["extra"],
        )

        return Response({"status": "ok"}, status=status.HTTP_202_ACCEPTED)


class InternalEmitSignalSerializer(serializers.Serializer):
    source_product = serializers.CharField(max_length=100)
    source_type = serializers.CharField(max_length=100)
    source_id = serializers.CharField(max_length=512)
    description = serializers.CharField()
    weight = serializers.FloatField(default=0.5, min_value=0.0, max_value=1.0)
    extra = serializers.DictField(required=False, default=dict)


class InternalSignalViewSet(viewsets.ViewSet):
    """
    Internal-only endpoint for service-to-service signal emission (e.g. from cymbal).
    Authenticated via X-Internal-Api-Secret header, not exposed to external ingress.
    """

    authentication_classes = [InternalAPIAuthentication]

    @extend_schema(exclude=True)
    def emit(self, request: Request, team_id: str, *args, **kwargs):
        try:
            team = Team.objects.get(id=int(team_id))
        except (Team.DoesNotExist, ValueError):
            return Response({"error": "Team not found"}, status=status.HTTP_404_NOT_FOUND)

        serializer = InternalEmitSignalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data

        async_to_sync(emit_signal)(
            team=team,
            source_product=data["source_product"],
            source_type=data["source_type"],
            source_id=data["source_id"],
            description=data["description"],
            weight=data["weight"],
            extra=data["extra"],
        )

        return Response({"status": "ok"}, status=status.HTTP_202_ACCEPTED)


class SignalSourceConfigViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    serializer_class = SignalSourceConfigSerializer
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "task"
    queryset = SignalSourceConfig.objects.all().order_by("-updated_at")

    @tracer.start_as_current_span("signals.source_configs.list")
    def list(self, request, *args, **kwargs):
        # This list is fetched on inbox load, so the span shows how much of that load the
        # endpoint accounts for. The serializer resolves every row's `status` from one warehouse
        # query per team, and reports no status rather than failing the list if that query fails.
        return super().list(request, *args, **kwargs)

    def _is_scout_source(self, source_product: str | None, source_type: str | None) -> bool:
        return (
            source_product == SignalSourceConfig.SourceProduct.SIGNALS_SCOUT
            and source_type == SignalSourceConfig.SourceType.CROSS_SOURCE_ISSUE
        )

    def _config_team_id(self, source_product: str | None, source_type: str | None) -> int:
        # The scout source config is a project-level singleton: the scout fleet canonicalizes
        # child environments to the parent team, and the emit preflight gates on the parent
        # team's row (see scout_harness/views.py `_canonical_team_id` and tools/emit.py). Writing
        # it to the canonical team keeps the inbox toggle and the emit gate on the same row from
        # any environment. All other sources stay environment-scoped.
        if self._is_scout_source(source_product, source_type):
            if not self._can_reach_canonical_team():
                raise exceptions.PermissionDenied(ScoutCanonicalTeamAccessPermission.message)
            return self.team.parent_team_id or self.team_id
        return self.team_id

    def _can_reach_canonical_team(self) -> bool:
        # The default team check authorizes only the URL environment. A caller must also reach the
        # parent project before it reads or writes that project's scout row.
        return ScoutCanonicalTeamAccessPermission().has_permission(self.request, self)

    def _filter_queryset_by_parents_lookups(self, queryset):
        # Mirror of `_config_team_id` on the read side: surface the scout row from the canonical
        # (parent) team while every other source stays scoped to the URL environment, so the
        # toggle reads and updates the same project-level row the emit gate checks.
        canonical_team_id = self.team.parent_team_id or self.team_id
        scout_source = Q(
            source_product=SignalSourceConfig.SourceProduct.SIGNALS_SCOUT,
            source_type=SignalSourceConfig.SourceType.CROSS_SOURCE_ISSUE,
        )
        if not self._can_reach_canonical_team():
            return queryset.filter(Q(team_id=self.team_id) & ~scout_source)
        return queryset.filter(
            (Q(team_id=self.team_id) & ~scout_source) | (Q(team_id=canonical_team_id) & scout_source)
        )

    def perform_create(self, serializer):
        team_id = self._config_team_id(
            serializer.validated_data.get("source_product"), serializer.validated_data.get("source_type")
        )
        try:
            instance = serializer.save(team_id=team_id, created_by=self.request.user)
        except IntegrityError:
            raise serializers.ValidationError(
                {"source_product": "A configuration for this source product and type already exists for this team."}
            )

        if (
            instance.source_product == SignalSourceConfig.SourceProduct.ERROR_TRACKING
            and instance.source_type == SignalSourceConfig.SourceType.ISSUE_CREATED
            and instance.enabled
        ):
            self._trigger_error_tracking_backfill()

    def _trigger_error_tracking_backfill(self) -> None:
        """Fire-and-forget backfill of recent error tracking issues as signals."""
        try:
            client = sync_connect()
            async_to_sync(client.start_workflow)(  # type: ignore
                "backfill-error-tracking",  # type: ignore
                BackfillErrorTrackingInput(team_id=self.team_id),  # type: ignore
                id=BackfillErrorTrackingWorkflow.workflow_id_for(self.team_id),
                id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
            logger.info(f"Started error tracking backfill workflow for team {self.team_id}")
        except Exception:
            logger.exception(f"Failed to start error tracking backfill workflow for team {self.team_id}")

    def update(self, request: Request, *args: object, **kwargs: object) -> Response:
        partial = kwargs.pop("partial", False)
        with transaction.atomic():
            # Read after locking so validation and merging use the last committed configuration.
            self.queryset = self.queryset.select_for_update()
            instance = self.get_object()
            serializer = self.get_serializer(instance, data=request.data, partial=partial)
            serializer.is_valid(raise_exception=True)
            self.perform_update(serializer)

        # A best-effort status query must not roll back the configuration write if it fails.
        return Response(serializer.data)

    def perform_update(self, serializer):
        instance = cast(SignalSourceConfig, serializer.instance)
        was_enabled = instance.enabled

        # The source keys are the row's identity and decide its canonical team_id on create
        # (`_config_team_id`); retagging them in place would strand the row on the wrong team —
        # e.g. a child-environment row retagged to the scout source would stay on the child team,
        # hidden by the read filter while the emit gate checks the parent. There is no legitimate
        # reason to change a config's source identity, so reject it rather than re-deriving team_id.
        for field in ("source_product", "source_type"):
            new_value = serializer.validated_data.get(field)
            if new_value is not None and new_value != getattr(instance, field):
                raise serializers.ValidationError({field: f"{field} cannot be changed after creation."})

        try:
            instance = serializer.save()
        except IntegrityError:
            raise serializers.ValidationError(
                {"source_product": "A configuration for this source product and type already exists for this team."}
            )

        if instance.enabled and not was_enabled:
            transaction.on_commit(partial(self._trigger_data_import_sync, instance))

    # Maps source_product to ExternalDataSourceType value for data import sources
    _DATA_IMPORT_SOURCE_TYPE_MAP: dict[str, str] = {
        SignalSourceConfig.SourceProduct.GITHUB: "Github",
        SignalSourceConfig.SourceProduct.LINEAR: "Linear",
        SignalSourceConfig.SourceProduct.ZENDESK: "Zendesk",
    }

    def _trigger_data_import_sync(self, config: SignalSourceConfig) -> None:
        """Fire-and-forget sync trigger for data import signal sources."""
        ext_source_type = self._DATA_IMPORT_SOURCE_TYPE_MAP.get(config.source_product)
        if ext_source_type is None:
            return

        schemas = (
            ExternalDataSchema.objects.filter(
                team_id=self.team_id,
                source__source_type=ext_source_type,
                should_sync=True,
            )
            .exclude(source__deleted=True)
            .select_related("source")
        )
        for schema in schemas:
            try:
                trigger_external_data_workflow(schema)
                logger.info("Triggered data import sync for %s schema %s", config.source_product, schema.id)
            except Exception:
                logger.exception(
                    "Failed to trigger data import sync for %s schema %s", config.source_product, schema.id
                )


# A task agent that could edit this list would widen the GitHub token of every later implementation run.
_SANDBOX_PROTECTED_CONFIG_FIELDS = (*STEERING_FIELDS.values(), "implementation_repositories")


class SignalSteeringPermission(BasePermission):
    def has_permission(self, request: Request, view: APIView) -> bool:
        if (
            request.method in ("GET", "HEAD", "OPTIONS")
            or not isinstance(request.data, dict)
            or not any(field in request.data for field in _SANDBOX_PROTECTED_CONFIG_FIELDS)
        ):
            return True
        if is_sandbox_oauth_request(request):
            self.message = "Task agents cannot modify steering instructions or implementation repositories."
            return False
        return True


class SignalTeamConfigViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Team-level signal autonomy config (singleton per team).

    GET  /signals/config/  → retrieve
    POST /signals/config/  → update
    """

    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission, SignalSteeringPermission]
    serializer_class = SignalTeamConfigSerializer
    queryset = SignalTeamConfig.objects.all()
    scope_object = "task"
    # The read returns the singleton, so the inherited limit and offset params are noise.
    pagination_class = None

    def dangerously_get_required_scopes(self, request: Request, view) -> list[str] | None:
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return ["task:read"]
        return ["task:write"]

    def _get_config(self) -> SignalTeamConfig:
        # Singleton per team with safe defaults. A post_save signal creates it on team
        # creation, but teams predating that signal (or where it failed) have no row, so
        # lazily create it here — otherwise the first read/write (e.g. connecting a default
        # notification channel) would 404.
        return get_or_create_team_extension(self.team, SignalTeamConfig)

    @extend_schema(summary="Read the project's signals config")
    def list(self, request: Request, *args, **kwargs) -> Response:
        return Response(SignalTeamConfigSerializer(self._get_config()).data)

    @extend_schema(
        summary="Update the project's signals config",
        description="Partial update of the per-project singleton. Omitted fields keep their value.",
        responses={200: SignalTeamConfigSerializer},
    )
    def create(self, request: Request, *args, **kwargs) -> Response:
        config = self._get_config()
        with transaction.atomic():
            # Independent settings editors share this row; refetch under lock to keep concurrent edits.
            config = SignalTeamConfig.objects.select_for_update().get(pk=config.pk, team_id=self.team.pk)
            serializer = self.get_serializer(config, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
        return Response(serializer.data)


SIGNAL_REPORT_DISMISSAL_NOTE_MAX_LENGTH = DISMISSAL_NOTE_MAX_LENGTH
# Upper bound on how far a snooze can push out re-promotion. Generous enough for any
# realistic snooze, but bounded so a caller can't effectively block a report forever.
SIGNAL_REPORT_MAX_SNOOZE_FOR = 100_000
# Upper bound on how many reports a single bulk transition may touch. Keeps one call
# from fanning out into an unbounded write; callers page through larger sets.
SIGNAL_REPORT_BULK_STATE_MAX_IDS = 100
# Bounds on the editable human-facing report fields. `title`/`summary` are TextFields on the
# model (so unbounded in the DB), but the write API caps them to keep an edit from storing an
# absurdly long title or summary.
SIGNAL_REPORT_TITLE_MAX_LENGTH = 300
SIGNAL_REPORT_SUMMARY_MAX_LENGTH = 10_000

# Canonical dismissal reason codes, mirrored from the inbox UI source of truth at
# products/signals/frontend/inbox/utils/dismissalReasons.ts (itself a port of
# packages/agent/packages/agent-contracts/src/dismissal-reasons.ts). Constraining the API to these values keeps
# agent-supplied reasons rendering as labelled chips in the inbox instead of raw,
# unrecognised codes. Keep the values (and order) in sync with that file.
SIGNAL_REPORT_DISMISSAL_REASON_CHOICES = [
    ("already_fixed", "Already fixed"),
    ("report_unclear", "Report is unclear to me"),
    ("analysis_wrong", "Agent's analysis is wrong"),
    ("wrong_assignee", "Wrong assignee"),
    ("wrong_repo", "Agent picked the wrong repository"),
    ("wontfix_intentional", "Won't fix - intentional behavior"),
    ("wontfix_irrelevant", "Not relevant to this project"),
    ("fixed_outside_posthog", "Fixed outside PostHog"),
    ("verified_manually", "Verified manually"),
    ("no_action_needed", "No action needed"),
    ("pr_merged", "PR was merged"),
    ("other", "Something else…"),
]

_DISMISSAL_REASON_HELP_TEXT = (
    "Optional canonical reason code recorded with the transition. Must be one of: already_fixed, "
    "report_unclear, analysis_wrong, wrong_assignee, wrong_repo, wontfix_intentional, wontfix_irrelevant, "
    "fixed_outside_posthog, verified_manually, no_action_needed, pr_merged, other — these match the inbox UI so the rationale renders as a "
    "labelled chip rather than a raw code. When the work this report asked for is done, the honest "
    "transition is state='resolved' with 'fixed_outside_posthog' (the fix landed without a pull request), "
    "'pr_merged' (a pull request with the fix was merged but did not resolve the report on its own), "
    "or 'already_fixed' (it was fixed before the report was filed). Use 'no_action_needed' with "
    "state='resolved' when the report was useful but needs no implementation. A report that failed in processing "
    "resolves too, so a fix that landed is recorded as a fix rather than as a dismissal. These three "
    "codes claim the issue is gone, so a later signal about the same issue starts a fresh report linked "
    "to this one. Fixed reason codes require state='suppressed' or state='resolved', not 'potential'. "
    "The dismissal codes (report_unclear, analysis_wrong, wrong_assignee, "
    "wontfix_*) go with state='suppressed' and absorb later signals silently. "
    "'wrong_assignee' is accepted from older clients, but a report sent to the wrong person still holds "
    "work: remove the person from the report's reviewers with a removal_reason instead of suppressing it. "
    "'wrong_repo' when the agent picked the wrong repository for this report, ideally with "
    "corrected_repository naming the right one. The report stays suppressed, but a later matching "
    "signal starts a fresh linked report with a new repository selection informed by the project's "
    "correction feedback, even when no corrected_repository was supplied. "
    "Use 'verified_manually' with state='resolved' to stop Monitoring after manual verification. "
    "It requires Monitoring to be enabled and a report with a Monitoring period, and records no automatic "
    "verification result or evidence amendment. "
    "Use 'other' together with a dismissal_note for anything that doesn't fit a code."
)

# GitHub caps owners at 39 characters and repository names at 100; 'owner/repo' fits in 140.
_CORRECTED_REPOSITORY_MAX_LENGTH = 140
_CORRECTED_REPOSITORY_RE = re.compile(r"^[^/\s]+/[^/\s]+$")


class SignalReportBulkClaimOutcome(models.TextChoices):
    """Per-id result of a bulk claim. Mirrors the single-report claim responses:
    `claimed` ~ 200, `conflict` ~ 409, `not_found` ~ 404."""

    CLAIMED = "claimed", "claimed"
    CONFLICT = "conflict", "conflict"
    NOT_FOUND = "not_found", "not_found"


class SignalReportBulkStateOutcome(models.TextChoices):
    """Per-id result of a bulk state transition. Mirrors the single-report responses:
    `transitioned` ~ 200, `skipped` ~ 409 (transition not allowed), `failed` ~ 400."""

    TRANSITIONED = "transitioned", "transitioned"
    SKIPPED = "skipped", "skipped"
    FAILED = "failed", "failed"
    NOT_FOUND = "not_found", "not_found"


# Statuses a report may have held before being archived and still resolve straight out of the
# archive. Mirrors the model's direct resolve edge (pending_input | ready | failed -> resolved) plus
# RESOLVED itself, which makes archive-then-resolve idempotent. FAILED is included because the model
# resolves it directly, so the archive grants it nothing it could not do on its own — and a report
# that failed in processing can only be reached through the archive, because a dismissal is the only
# verdict the inbox offered it.
_RESOLVABLE_STATUSES_BEFORE_SUPPRESSION = frozenset(
    {
        SignalReport.Status.READY,
        SignalReport.Status.PENDING_INPUT,
        SignalReport.Status.RESOLVED,
        SignalReport.Status.CLOSED,
        SignalReport.Status.FAILED,
    }
)


class SignalReportState(models.TextChoices):
    SUPPRESSED = "suppressed", "suppressed"
    POTENTIAL = "potential", "potential"
    RESOLVED = "resolved", "resolved"
    MONITORING = "monitoring", "monitoring"


class SignalReportStateRequestSerializer(serializers.Serializer):
    state = serializers.ChoiceField(
        choices=SignalReportState.choices,
        help_text=(
            "Target state for the report. Use 'suppressed' to dismiss the report from the inbox, "
            "'potential' to snooze/reopen it for later review, or 'resolved' when the report is finished. "
            "Resolving is allowed from ready, pending_input, failed, closed, or monitoring, "
            "or from a suppressed report that previously held one of those statuses or resolved. "
            "Resolving an already resolved report succeeds. Other statuses return 409 (skipped in bulk). "
            "Dismissing or resolving closes the report's open implementation PR, if it has one. "
            "Use 'monitoring' when implementation is complete and outcome verification is pending. "
            "Entry requires the organization rollout and snapshots this report's pending or active, unexpired checks. "
            "Without applicable checks the report resolves directly. Manual completion records caller "
            "attribution, stops remaining follow-up checks, and does not claim automatic verification or an evidence amendment."
        ),
    )
    dismissal_reason = serializers.ChoiceField(
        required=False,
        choices=SIGNAL_REPORT_DISMISSAL_REASON_CHOICES,
        help_text=_DISMISSAL_REASON_HELP_TEXT,
    )
    dismissal_note = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=SIGNAL_REPORT_DISMISSAL_NOTE_MAX_LENGTH,
        help_text="Optional free-form note explaining the dismissal. Capped at 4000 characters.",
    )
    corrected_repository = serializers.CharField(
        required=False,
        allow_blank=False,
        # min_length=1 (not just allow_blank=False) so the non-empty constraint surfaces as
        # `minLength: 1` in the generated OpenAPI/Zod schema, not only as a server-side 400.
        min_length=1,
        max_length=_CORRECTED_REPOSITORY_MAX_LENGTH,
        help_text=(
            "Optional, only allowed with dismissal_reason='wrong_repo'. The repository this report "
            "should have targeted, in 'owner/repo' format (case-insensitive). It is recorded with "
            "the dismissal and fed into future repository selection for this project. When the "
            "repository is connected to the project, it also becomes the report's corrected repo "
            "selection, so restoring the report re-researches against it."
        ),
    )
    snooze_for = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=SIGNAL_REPORT_MAX_SNOOZE_FOR,
        help_text=(
            "Optional, only honored when state is 'potential'. Number of additional signals the report "
            "must accumulate before it is re-promoted into the pipeline — effectively snoozing it until then. "
            "Omit to let the report re-enter the pipeline on the next matching signal."
        ),
    )

    def validate_corrected_repository(self, value: str) -> str:
        # Lowercased on the way in: repo-selection candidate lists, the heavy cache, and connected-repo
        # checks all compare lowercased 'owner/repo' names.
        value = value.strip().lower()
        if not _CORRECTED_REPOSITORY_RE.match(value):
            raise serializers.ValidationError("Must be in 'owner/repo' format.")
        return value

    def validate(self, attrs: dict) -> dict:
        if attrs.get("dismissal_reason") == "verified_manually" and attrs.get("state") != SignalReportState.RESOLVED:
            raise serializers.ValidationError({"dismissal_reason": "Verified manually requires state 'resolved'."})
        if attrs.get("dismissal_reason") == "no_action_needed" and attrs.get("state") != SignalReportState.RESOLVED:
            raise serializers.ValidationError({"dismissal_reason": "No action needed requires state 'resolved'."})
        if (
            attrs.get("state") == SignalReportState.POTENTIAL
            and attrs.get("dismissal_reason") in FIXED_DISMISSAL_REASONS
        ):
            raise serializers.ValidationError(
                {"dismissal_reason": "A fixed reason requires state 'suppressed' or 'resolved'."}
            )
        if attrs.get("corrected_repository") and attrs.get("dismissal_reason") != DISMISSAL_REASON_WRONG_REPO:
            raise serializers.ValidationError(
                {"corrected_repository": "Only allowed when dismissal_reason is 'wrong_repo'."}
            )
        return attrs


class SignalReportBulkStateRequestSerializer(SignalReportStateRequestSerializer):
    ids = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=False,
        max_length=SIGNAL_REPORT_BULK_STATE_MAX_IDS,
        help_text=(
            "Report ids to transition to `state` in one call (1–"
            f"{SIGNAL_REPORT_BULK_STATE_MAX_IDS}). Duplicates are de-duplicated; each id is "
            "processed independently so one disallowed transition does not block the rest. "
            "`dismissal_reason`, `dismissal_note`, `corrected_repository` and `snooze_for` apply to every id."
        ),
    )


class SignalReportBulkStateResultSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="The report id this result refers to.")
    # CharField (not ChoiceField) on purpose: this is a server-generated response value, so it
    # needs no input validation, and a ChoiceField named `outcome` would collide with another
    # product's `OutcomeEnum` in the shared OpenAPI schema. Values come from SignalReportBulkStateOutcome.
    outcome = serializers.CharField(
        help_text=(
            "One of: transitioned, skipped, failed, not_found. transitioned: the state change was applied. "
            "skipped: the transition was not allowed from the report's current status (a 409 on the "
            "single-report endpoint). failed: the request data was invalid for this report. not_found: no "
            "report with this id is visible to you."
        ),
    )
    status = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="The report's status after the transition. Present only when outcome is 'transitioned'.",
    )
    detail = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Human-readable explanation for non-transitioned outcomes (skipped / failed / not_found).",
    )


class SignalReportBulkStateResponseSerializer(serializers.Serializer):
    results = SignalReportBulkStateResultSerializer(
        many=True,
        help_text="One result per requested id, in request order (after de-duplication).",
    )
    transitioned_count = serializers.IntegerField(
        help_text=(
            "Number of reports the call accepted. A report that already had the requested state counts "
            "here too, because a repeat dismiss or resolve still records its feedback."
        )
    )
    skipped_count = serializers.IntegerField(help_text="Number of reports whose transition was not allowed.")
    failed_count = serializers.IntegerField(help_text="Number of reports that failed on invalid request data.")
    not_found_count = serializers.IntegerField(help_text="Number of requested ids not visible to the caller.")


class SignalReportBulkClaimRequestSerializer(serializers.Serializer):
    ids = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=False,
        min_length=1,
        max_length=SIGNAL_REPORT_BULK_STATE_MAX_IDS,
        help_text=(
            "Report ids to claim for the caller in one call (1–"
            f"{SIGNAL_REPORT_BULK_STATE_MAX_IDS}). Duplicates are de-duplicated. Each id is claimed "
            "independently, so a report that cannot be claimed does not block the rest."
        ),
    )
    takeover_agent_claims = serializers.BooleanField(
        default=False,
        help_text=(
            "Take over a report that an agent or an internal task holds. A report that a person holds "
            "directly is never taken over and comes back as a conflict."
        ),
    )


class SignalReportBulkClaimResultSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="The report id this result refers to.")
    # A CharField like the bulk-state outcome, so the response enum cannot collide with another
    # product's `OutcomeEnum` in the shared OpenAPI schema. Values come from SignalReportBulkClaimOutcome.
    outcome = serializers.CharField(
        help_text=(
            "One of: claimed, conflict, not_found. claimed: the caller holds the claim, including when it "
            "already did. conflict: the claim was refused, because someone else holds the report or its "
            "status does not allow a claim (a 409 on the single-report endpoint). not_found: no report "
            "with this id is visible to you."
        ),
    )
    detail = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Human-readable explanation for a conflict or not_found outcome.",
    )


class SignalReportBulkClaimResponseSerializer(serializers.Serializer):
    results = SignalReportBulkClaimResultSerializer(
        many=True,
        help_text="One result per requested id, in request order (after de-duplication).",
    )
    claimed_count = serializers.IntegerField(help_text="Number of reports the caller now holds.")
    conflict_count = serializers.IntegerField(help_text="Number of reports whose claim was refused.")
    not_found_count = serializers.IntegerField(help_text="Number of requested ids not visible to the caller.")


class SignalReportMergeRequestSerializer(serializers.Serializer):
    source_report_ids = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=False,
        # min_length (not just allow_empty=False) so the non-empty constraint surfaces as
        # `minItems: 1` in the generated OpenAPI/Zod schema, not only as a server-side 400.
        min_length=1,
        max_length=MAX_MERGE_SOURCE_REPORTS,
        help_text=(
            "Ids of the duplicate reports to fold into this one (1–"
            f"{MAX_MERGE_SOURCE_REPORTS}). Each must be a live report in this project: a resolved, "
            "archived or deleted report is rejected with 409, as is the survivor's own id. "
            "Duplicates in the list are de-duplicated. The whole merge applies or none of it does."
        ),
    )
    reason = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=MAX_MERGE_REASON_LENGTH,
        help_text=(
            "Optional one-line explanation of why these reports are the same issue. Recorded on "
            "each source's 'duplicate of' link and on the note left on the survivor. Capped at "
            f"{MAX_MERGE_REASON_LENGTH} characters."
        ),
    )


class SignalReportMergeSourceResultSerializer(serializers.Serializer):
    id = serializers.UUIDField(source="report_id", help_text="The source report that was folded into the survivor.")
    artefacts_moved = serializers.IntegerField(
        help_text=(
            "How many work-log artefacts moved to the survivor (notes, findings, pull requests, "
            "task runs, code references, commits, checks)."
        )
    )
    signals_moved = serializers.IntegerField(
        help_text=(
            "How many signals the survivor took on from this source. The signals themselves are "
            "re-pointed asynchronously; the survivor's counters already include them."
        )
    )
    released_claim = serializers.BooleanField(
        help_text="Whether an active work claim held by another actor was released before the move."
    )


class SignalReportMergeResponseSerializer(serializers.Serializer):
    report = SignalReportSerializer(help_text="The surviving report, as it stands after the merge.")
    sources = SignalReportMergeSourceResultSerializer(
        many=True, help_text="One result per merged source, in request order (after de-duplication)."
    )


# The thumbs rating at the end of the report body carries an optional note, capped in the UI at the
# same length as the dismissal note.
SIGNAL_REPORT_FEEDBACK_NOTE_MAX_LENGTH = SIGNAL_REPORT_DISMISSAL_NOTE_MAX_LENGTH


class SignalReportFeedbackSentiment(models.TextChoices):
    POSITIVE = "positive", "positive"
    NEGATIVE = "negative", "negative"


class SignalReportFeedbackRequestSerializer(serializers.Serializer):
    sentiment = serializers.ChoiceField(
        choices=SignalReportFeedbackSentiment.choices,
        allow_null=True,
        help_text="The report rating: 'positive' (thumbs up), 'negative' (thumbs down), or null to clear it.",
    )
    note = serializers.CharField(
        max_length=SIGNAL_REPORT_FEEDBACK_NOTE_MAX_LENGTH,
        required=False,
        allow_blank=True,
        default="",
        help_text=(
            "Free-form note explaining the rating. Capped at "
            f"{SIGNAL_REPORT_FEEDBACK_NOTE_MAX_LENGTH} characters. Optional — a bare thumb carries "
            "none. When present and the report was authored by a scout, the note is forwarded to that "
            "scout as a steering note."
        ),
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs["sentiment"] is None and attrs["note"].strip():
            raise serializers.ValidationError({"note": "Select a rating before you add a note."})
        return attrs


class SignalReportFeedbackStateSerializer(SignalReportFeedbackRequestSerializer):
    note = serializers.CharField(allow_blank=True, help_text="The current user's saved note, or an empty string.")


class SignalReportFeedbackResponseSerializer(serializers.Serializer):
    forwarded = serializers.BooleanField(
        help_text=(
            "Whether the note was forwarded to the report's authoring scout as a steering note. False "
            "when the report has no resolvable authoring scout, or the caller lacks scout-steering access."
        ),
    )


# Whole PR-refund feature gate. Checked server-side (not just in the UI) and keyed on the
# organization, matching the refund window (the org's billing period).
SIGNALS_PR_REFUNDS_FEATURE_FLAG = "signals-pr-refunds"


# User-facing message for each shared `refund_ineligibility_reason` the refund action rejects on
# (`already_refunded` never reaches a 400 — it takes the idempotent 200 path instead).
_REFUND_INELIGIBLE_MESSAGES = {
    REFUND_INELIGIBLE_BILLING_EXEMPT: "This report is marked never-billable, so there is nothing to refund.",
    REFUND_INELIGIBLE_NO_BILLABLE_PR: "This report has no billable implementation PR to refund.",
    REFUND_INELIGIBLE_OUT_OF_PERIOD: "This PR was billed in a previous billing period and can no longer be refunded.",
}


class SignalReportRefundRequestSerializer(serializers.Serializer):
    reason = serializers.ChoiceField(
        choices=SignalReportRefund.Reason.choices,
        help_text=(
            "Why this PR is being refunded. One of: pr_incorrect (the PR doesn't address what the "
            "report promised), pr_not_useful (technically fine but not worth paying for), duplicate "
            "(covers work already charged elsewhere), other. Required — refund reviews key on it."
        ),
    )
    note = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=SIGNAL_REPORT_DISMISSAL_NOTE_MAX_LENGTH,
        help_text=(
            "Optional free-form context for the refund; stored on the refund and echoed in the "
            "report's dismissal artefact. Capped at 4000 characters."
        ),
    )


class SignalReportRefundResponseSerializer(SignalReportRefundSerializer):
    already_refunded = serializers.BooleanField(
        read_only=True,
        default=False,
        help_text=(
            "True when the report already had a refund and that existing refund is returned "
            "unchanged — refunds are one-per-report and repeat calls are idempotent."
        ),
    )

    class Meta(SignalReportRefundSerializer.Meta):
        fields = [*SignalReportRefundSerializer.Meta.fields, "already_refunded"]
        read_only_fields = fields


class SignalReportRefundSummaryResponseSerializer(serializers.Serializer):
    credited_refund_count = serializers.IntegerField(
        help_text=(
            "Number of credited-path refunds across the whole organization whose refunded PR run "
            "falls in the current billing period. Excluded-path refunds never reach billing usage, "
            "so they are deliberately absent."
        ),
    )
    credited_credits = serializers.IntegerField(
        help_text=(
            "Total signals credits those refunds returned (1 credit = $0.01). Divide by the flat "
            "per-PR charge to get the number of PRs to subtract from billing usage."
        ),
    )
    period_billable_credits = serializers.IntegerField(
        help_text=(
            "The organization's live billable signals credits for the current billing period, "
            "computed by the same rules as the nightly usage report — including PRs created today "
            "that billing hasn't recorded yet, and already excluding refund-excluded and "
            "billing-exempt reports. Take the max of this and billing's recorded usage for a live "
            "PR count that reacts to new PRs and same-day refunds immediately."
        ),
    )
    quota_limited = serializers.BooleanField(
        help_text=(
            "Whether autonomous PR generation is currently paused for this project because the "
            "organization is over its self-driving credits quota. Read from the quota limiter, so it "
            "reflects the same state the pipeline gates enforce."
        ),
    )


class SignalReportContentUpdateSerializer(serializers.Serializer):
    """Editable human-facing fields on a signal report (PATCH).

    Both fields are optional so a caller can change either independently, but at least one
    must be supplied. Every other report field — status, weights, judgments — is owned by the
    signals pipeline and is deliberately not writable here.
    """

    # min_length=1 (not just allow_blank=False) so the non-empty constraint surfaces as
    # `minLength: 1` in the generated OpenAPI/Zod schema — otherwise clients only learn an
    # empty string is invalid when the server rejects it.
    title = serializers.CharField(
        required=False,
        allow_blank=False,
        trim_whitespace=True,
        min_length=1,
        max_length=SIGNAL_REPORT_TITLE_MAX_LENGTH,
        help_text="New human-facing title for the report. Omit to leave the title unchanged.",
    )
    summary = serializers.CharField(
        required=False,
        allow_blank=False,
        trim_whitespace=True,
        min_length=1,
        max_length=SIGNAL_REPORT_SUMMARY_MAX_LENGTH,
        help_text=(
            "New summary (the report's description) explaining what the report is about. "
            "Omit to leave the summary unchanged."
        ),
    )

    def validate(self, attrs: dict) -> dict:
        if "title" not in attrs and "summary" not in attrs:
            raise serializers.ValidationError("Provide at least one of 'title' or 'summary' to update.")
        return attrs


def _is_person_at_the_ui(request: Request) -> bool:
    """Whether the caller is a signed-in person in a browser, not an automated credential.

    Consumption evidence (`SignalReportAction`) must prove a person read the report, but every
    credential this API accepts authenticates *as* a user: through ``request.user`` alone, a
    personal API key or a sandbox agent's OAuth token is indistinguishable from the person it
    belongs to. Admitting only a browser session keeps automation — including a scout calling
    the API on its own reports — from manufacturing the engagement that exempts it from the
    inactivity sweep.

    Staff impersonation is excluded for the same reason: it is a browser session, but
    ``request.user`` is the impersonated customer, so a support investigation would otherwise
    write consumption evidence in that customer's name and rescue a scout nobody on their team
    read. (Read-only impersonation can't reach these POSTs at all; read-write can.)
    """
    return (
        isinstance(request.successful_authenticator, SessionAuthentication)
        and isinstance(request.user, User)
        and not is_impersonated_session(request)
    )


# Each action reports only its own outcomes, so the two sets stay separate rather than becoming one
# union that would admit a deletion status on the reingest response.
SIGNAL_REPORT_DELETION_STATUSES = ["deletion_started", "already_running"]
SIGNAL_REPORT_REINGESTION_STATUSES = ["reingestion_started", "already_running"]


class SignalReportDeletionStatusSerializer(serializers.Serializer):
    """Envelope the report delete returns once it has kicked off the deletion workflow."""

    status = serializers.ChoiceField(
        choices=SIGNAL_REPORT_DELETION_STATUSES,
        help_text="Whether this request started the deletion or found one already running.",
    )
    report_id = serializers.UUIDField(help_text="Report being deleted.")


class SignalReportReingestionStatusSerializer(serializers.Serializer):
    """Envelope the reingest action returns once it has kicked off the re-ingestion workflow."""

    status = serializers.ChoiceField(
        choices=SIGNAL_REPORT_REINGESTION_STATUSES,
        help_text="Whether this request started the re-ingestion or found one already running.",
    )
    report_id = serializers.UUIDField(help_text="Report being re-ingested.")


class SignalReportListPagination(LimitOffsetPagination):
    def paginate_queryset(self, queryset, request, view=None):
        # Fetch the page before the count. A page that ends before the limit already gives the
        # total, so the second scan is not needed. A `search` filter rechecks the text of every
        # candidate report, and that scan costs seconds in a large team.
        self.limit = self.get_limit(request)
        if self.limit is None:
            return None
        self.offset = self.get_offset(request)
        self.request = request
        if request.query_params.get("search"):
            page, window_count = self._search_page(queryset, self.offset, self.limit)
        else:
            page, window_count = list(queryset[self.offset : self.offset + self.limit]), None
        if len(page) < self.limit and (page or self.offset == 0):
            self.count = self.offset + len(page)
        elif window_count is not None:
            self.count = window_count
        else:
            self.count = self.get_count(queryset)
        if self.count > self.limit and self.template is not None:
            self.display_page_controls = True
        return page

    def _search_page(self, queryset, offset: int, limit: int) -> tuple[list[SignalReport], int | None]:
        # Ids only, because COUNT(*) OVER () buffers every match and full report rows spill to disk.
        rows = list(
            queryset.annotate(search_total=Window(Count("*"))).values_list("pk", "search_total")[
                offset : offset + limit
            ]
        )
        if not rows:
            return [], None
        reports = {report.pk: report for report in queryset.filter(pk__in=[pk for pk, _ in rows]).order_by()}
        return [reports[pk] for pk, _ in rows if pk in reports], rows[0][1]

    def get_paginated_response_schema(self, schema):
        paginated = super().get_paginated_response_schema(schema)
        paginated["properties"]["ranker"] = {
            "type": "string",
            "nullable": True,
            "description": (
                "The ranker that ordered the page when sort=recommended: priority, or open, action or fix "
                "for that outcome of the served ranking model. Null for every other sort. Each row's "
                "inbox_merge_key belongs to this ranker."
            ),
        }
        return paginated


_SUGGESTED_REVIEWERS_PARAMETER = OpenApiParameter(
    name="suggested_reviewers",
    type=OpenApiTypes.STR,
    location=OpenApiParameter.QUERY,
    required=False,
    description=(
        "Comma-separated list of PostHog user UUIDs. Reports are kept if their suggested reviewers "
        "include any of the given users."
    ),
)
_PRIORITY_PARAMETER = OpenApiParameter(
    name="priority",
    type=OpenApiTypes.STR,
    location=OpenApiParameter.QUERY,
    required=False,
    description=(
        "Comma-separated list of priorities to include. Valid values: P0, P1, P2, P3, P4. "
        "Reports without a priority assignment are excluded when this filter is set."
    ),
)
_REPORT_LIST_PARAMETERS = [
    OpenApiParameter(
        name="status",
        type=OpenApiTypes.STR,
        location=OpenApiParameter.QUERY,
        required=False,
        description=(
            "Comma-separated list of statuses to include. "
            "Valid values: potential, candidate, in_progress, pending_input, ready, resolved, failed, suppressed. "
            "Defaults to all statuses except suppressed."
        ),
    ),
    OpenApiParameter(
        name="include_all_statuses",
        type=OpenApiTypes.BOOL,
        location=OpenApiParameter.QUERY,
        required=False,
        description=(
            "When true, the list includes reports in every status with no default exclusions applied — "
            "currently that adds suppressed (dismissed) reports, which are otherwise hidden. Use it to "
            "see the full inbox state (e.g. deduplicating before creating a report) and read each row's "
            "status (plus dismissal_reason/dismissal_note on dismissed rows) before acting. Deleted "
            "reports are terminal and never returned. Defaults to false, which keeps the existing "
            "default exclusions. Ignored when an explicit 'status' filter is set — that filter alone "
            "decides which statuses are returned."
        ),
    ),
    OpenApiParameter(
        name="unread",
        type=OpenApiTypes.BOOL,
        location=OpenApiParameter.QUERY,
        required=False,
        description="Filter by the current user's report read state.",
    ),
    OpenApiParameter(
        name="search",
        type=OpenApiTypes.STR,
        location=OpenApiParameter.QUERY,
        required=False,
        description="Case-insensitive substring match against report title and summary.",
    ),
    OpenApiParameter(
        name="channel_id",
        type=OpenApiTypes.UUID,
        location=OpenApiParameter.QUERY,
        required=False,
        description=(
            "Narrow to reports assigned to one space (channel). Absent or empty means all "
            "reports regardless of assignment."
        ),
    ),
    OpenApiParameter(
        name="source_product",
        type=OpenApiTypes.STR,
        location=OpenApiParameter.QUERY,
        required=False,
        description=(
            "Comma-separated list of source products to include. Reports are kept if at least one of "
            "their contributing signals comes from one of these products (e.g. error_tracking, session_replay)."
        ),
    ),
    OpenApiParameter(
        name="source_id",
        type=OpenApiTypes.STR,
        location=OpenApiParameter.QUERY,
        required=False,
        description=(
            "Comma-separated list of source record ids. Reports are kept if at least one of their "
            "contributing signals came from one of these records — e.g. pass a support ticket's UUID to "
            "see what the inbox already found for that ticket. Requires exactly one source_product, "
            "since a source id is only unique within its product."
        ),
    ),
    OpenApiParameter(
        name="scout",
        type=OpenApiTypes.STR,
        location=OpenApiParameter.QUERY,
        required=False,
        description=(
            "Comma-separated list of scout skill_name slugs (e.g. signals-scout-error-tracking). "
            "Reports are kept if at least one of their contributing signals was authored by one of "
            "these scouts. Combines with source_product as an AND."
        ),
    ),
    OpenApiParameter(
        name="scout_prefix",
        type=OpenApiTypes.STR,
        location=OpenApiParameter.QUERY,
        required=False,
        description=(
            "Scout skill_name prefix (e.g. signals-scout-customer-analytics). Reports are kept if at "
            "least one of their contributing signals was authored by a scout whose skill_name starts "
            "with this prefix — new scouts in the family match without callers listing every name. "
            "Combines with the other filters as an AND."
        ),
    ),
    _SUGGESTED_REVIEWERS_PARAMETER,
    OpenApiParameter(
        name="actionability",
        type=OpenApiTypes.STR,
        location=OpenApiParameter.QUERY,
        required=False,
        description=(
            "Comma-separated actionability judgments to include. Valid values: immediately_actionable, "
            "requires_human_input, not_actionable. Reports without a judgment are excluded."
        ),
    ),
    OpenApiParameter(
        name="already_addressed",
        type=OpenApiTypes.BOOL,
        location=OpenApiParameter.QUERY,
        required=False,
        description=(
            "Filter by whether the latest actionability judgment says the issue is already being handled. "
            "False also includes older reports where that judgment did not record a value."
        ),
    ),
    OpenApiParameter(
        name="view",
        type=OpenApiTypes.STR,
        location=OpenApiParameter.QUERY,
        required=False,
        description=(
            "Apply an inbox view: actionable, for_you, needs_input, needs_decision, monitoring, resolved, "
            "dismissed, held_back, not_actionable, or all. Each view applies the corresponding status, "
            "actionability, and implementation-PR filters. for_you holds the open, actionable reports that "
            "wait for the requesting user's input, that they claimed, or that name them as a suggested "
            "reviewer. needs_decision also includes failed reports without a judgment. "
            "dismissed and held_back split the suppressed reports: dismissed holds the ones a person or agent "
            "dismissed, merged, or whose pull request closed without merging; held_back holds the ones the "
            "safety or actionability judge suppressed before anyone saw them. Each row's suppression_source "
            "says which."
        ),
    ),
    OpenApiParameter(
        name="scope",
        type=OpenApiTypes.STR,
        location=OpenApiParameter.QUERY,
        required=False,
        description=("Reviewer scope: for_me, entire_project, or teammate. Pass teammate_uuid with teammate."),
    ),
    OpenApiParameter(
        name="teammate_uuid",
        type=OpenApiTypes.UUID,
        location=OpenApiParameter.QUERY,
        required=False,
        description="PostHog user UUID used when scope=teammate.",
    ),
    _PRIORITY_PARAMETER,
    OpenApiParameter(
        name="use_priority_preference",
        type=OpenApiTypes.BOOL,
        location=OpenApiParameter.QUERY,
        required=False,
        description=(
            "When true and priority is omitted, include priorities at or above the requesting user's "
            "personal PR-generation threshold, falling back to the project threshold."
        ),
    ),
    OpenApiParameter(
        name="sort",
        type=OpenApiTypes.STR,
        location=OpenApiParameter.QUERY,
        required=False,
        description=(
            "Inbox sort preset: priority, recommended, last_updated, newest, or oldest. Ignored when "
            "ordering is supplied. recommended resolves per user to a ranker: the priority order, or "
            "the open, action or fix outcome of the served ranking model with unscored and stale reports "
            "in priority order after the scored ones. The response's ranker field names the one used."
        ),
    ),
    OpenApiParameter(
        name="ordering",
        type=OpenApiTypes.STR,
        location=OpenApiParameter.QUERY,
        required=False,
        description=(
            "Comma-separated ordering clauses. Each clause is a field name optionally prefixed with '-' "
            "for descending. Allowed fields: status, is_suggested_reviewer, signal_count, total_weight, "
            f"priority, created_at, updated_at, id, {', '.join(PUBLIC_RANKING_ORDERING_HEADS)}. "
            "Defaults to '-is_suggested_reviewer,status,-updated_at'. Each ranking_<outcome> field sorts by "
            "the served ranking model's probability for that public outcome, with unscored reports last in "
            "either direction. Read inbox-ranking-outcomes-list for what each outcome means. The ranking "
            "fields need staff or the inbox model sort rollout: other users get a 400."
        ),
    ),
    OpenApiParameter(
        name="ranking_min_lift",
        type=OpenApiTypes.STR,
        location=OpenApiParameter.QUERY,
        required=False,
        description=(
            "Comma-separated <outcome>:<lift> pairs, e.g. fix:2,open:1.5. Keeps reports whose served "
            "ranking lift is at least the value for every named outcome. Outcomes: open, action, fix. Read "
            "inbox-ranking-outcomes-list for what each outcome means. Unscored and stale reports never match. "
            "Needs staff or the inbox model sort rollout: other users get a 400."
        ),
    ),
    OpenApiParameter(
        name="ranking_min_probability",
        type=OpenApiTypes.STR,
        location=OpenApiParameter.QUERY,
        required=False,
        description=(
            "Comma-separated <outcome>:<probability> pairs, e.g. fix:0.3. Keeps reports whose served "
            "ranking probability is at least the value for every named outcome. Outcomes: open, action, "
            "fix. Read inbox-ranking-outcomes-list for what each outcome means. Unscored and stale reports "
            "never match. "
            "Needs staff or the inbox model sort rollout: other users get a 400."
        ),
    ),
    OpenApiParameter(
        name="created_after",
        type=OpenApiTypes.DATETIME,
        location=OpenApiParameter.QUERY,
        required=False,
        description="ISO 8601 datetime. Keeps reports created at or after this time.",
    ),
    OpenApiParameter(
        name="task_id",
        type=OpenApiTypes.UUID,
        location=OpenApiParameter.QUERY,
        required=False,
        description="Only reports associated with this task (via the report's task associations).",
    ),
    OpenApiParameter(
        name="has_implementation_pr",
        type=OpenApiTypes.BOOL,
        location=OpenApiParameter.QUERY,
        required=False,
        description=(
            "Filter reports by whether an implementation pull request is attached. "
            "'true' keeps only reports with a PR; 'false' keeps only those without. "
            "Pair with count_only=true to return only the filtered total."
        ),
    ),
    OpenApiParameter(
        name="unclaimed",
        type=OpenApiTypes.BOOL,
        location=OpenApiParameter.QUERY,
        required=False,
        description=(
            "Filter by whether the report has no owner and no draft, open, or unknown PR. "
            "Resolved reports are never unclaimed."
        ),
    ),
    OpenApiParameter(
        name="assignee",
        type=OpenApiTypes.STR,
        location=OpenApiParameter.QUERY,
        required=False,
        enum=["me", "mine"],
        description=(
            "'me' returns reports claimed by exactly the requesting actor: the user, the internal task, or "
            "the MCP agent. 'mine' returns every report the requesting user claimed: their own claims and "
            "claims by MCP agents acting for them. Internal task claims are not included."
        ),
    ),
]
# Section counts set the status and the implementation PR condition themselves, so they reject these.
_SECTION_DEFINING_PARAMETERS = frozenset({"status", "has_implementation_pr", "include_all_statuses", "view"})
_SECTION_COUNTS_PARAMETERS = [
    parameter
    for parameter in _REPORT_LIST_PARAMETERS
    if parameter.name not in _SECTION_DEFINING_PARAMETERS | {"sort", "ordering"}
]


@extend_schema_view(
    destroy=extend_schema(
        summary="Delete a signal report",
        responses={
            200: OpenApiResponse(
                response=SignalReportDeletionStatusSerializer, description="A deletion is already running."
            ),
            202: OpenApiResponse(response=SignalReportDeletionStatusSerializer, description="Deletion started."),
        },
    ),
)
class SignalReportViewSet(
    TeamAndOrgViewSetMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = SignalReportSerializer
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "task"
    queryset = SignalReport.objects.all()
    pagination_class = SignalReportListPagination
    # Shared Q for "ready but not actionable" — used in status ranking and suggested-reviewer suppression.
    _Q_READY_NOT_ACTIONABLE = Q(status=SignalReport.Status.READY) & Q(latest_actionability="not_actionable")
    _DEFAULT_SIGNAL_REPORT_ORDERING = "-is_suggested_reviewer,status,-updated_at"
    _INBOX_SORT_ORDERINGS = {
        "priority": PRIORITY_ORDERING,
        # A feature flag resolves this preset per user. See `_inbox_ranker`.
        "recommended": PRIORITY_ORDERING,
        "last_updated": "-updated_at,status",
        "newest": "-created_at,status,-updated_at",
        "oldest": "created_at,status,-updated_at",
    }
    _INBOX_VIEWS = frozenset(
        {
            "actionable",
            "for_you",
            "needs_input",
            "needs_decision",
            "monitoring",
            "resolved",
            "closed",
            "dismissed",
            "held_back",
            "not_actionable",
            "all",
        }
    )
    _SIGNAL_REPORT_ORDERING_FIELDS: dict[str, str] = {
        "status": "pipeline_status_rank",
        "is_suggested_reviewer": "is_suggested_reviewer",
        "signal_count": "signal_count",
        "total_weight": "total_weight",
        "priority": "priority_sort_rank",
        "created_at": "created_at",
        "updated_at": "updated_at",
        "id": "id",
        **{field: f"{field}_score" for field in RANKING_ORDERING_HEADS},
        "ranking_fixed": "ranking_fix_score",
    }
    _RANKING_ORDERING_HEADS: dict[str, str] = RANKING_ORDERING_HEADS

    @extend_schema(
        responses={200: RankingOutcomesResponseSerializer},
        summary="List the ranking model's public outcomes",
        description=(
            "What each public outcome of the served ranking model predicts, with its horizon, cohort, base rate "
            "and readability from the model that scored this project's reports. Users who cannot see the ranking "
            "model get status not_available and no outcomes."
        ),
        operation_id="signals_reports_ranking_outcomes_list",
    )
    @action(
        detail=False,
        methods=["get"],
        url_path="ranking_outcomes",
        required_scopes=["task:read"],
        pagination_class=None,
    )
    def ranking_outcomes(self, request: Request, **kwargs) -> Response:
        model: str | None = None
        outcomes: list[dict[str, Any]] = []
        if not self._can_view_inbox_ranking:
            status_value = RankingOutcomesStatus.NOT_AVAILABLE
        else:
            model, outcomes = served_outcomes(self.team_id)
            status_value = RankingOutcomesStatus.SCORED if model is not None else RankingOutcomesStatus.UNSCORED
        self._capture_ranking_usage("ranking_outcomes", ranking_status=status_value.value)
        return Response(
            RankingOutcomesResponseSerializer({"status": status_value.value, "model": model, "outcomes": outcomes}).data
        )

    @validated_request(
        query_serializer=PersonalRankingQuerySerializer,
        responses={
            200: OpenApiResponse(response=PersonalRankingSerializer),
            404: OpenApiResponse(description="Personal ranking is not available to the caller."),
        },
        summary="Get your personal ranked inbox",
        description=(
            "Your open inbox reports, ranked for you by one language model call over your activity summary, the "
            "reports that need you and the ranking model's predictions. Each entry has a reason and a compact report. "
            "The request never waits on the model. A current stored list returns at once. Otherwise the request "
            "starts a background build and returns the last stored list with `stale: true`, or your reports in inbox "
            "order with `fallback_reason: building`, and `building: true`. Pass `wait_seconds` to wait a short time "
            "for the new list. Only the user the list is about can read it."
        ),
    )
    @action(detail=False, methods=["get"], url_path="for_me", required_scopes=["task:read"], pagination_class=None)
    def for_me(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        user = request.user
        # A list describes one person, so only that person's own credentials can read it.
        if (
            is_service_auth(request)
            or not isinstance(user, User)
            or trial_store_for_request(request, self.team_id) is not None
            or not user_flag_enabled(PERSONAL_INBOX_RANKING_FLAG, user, self.team)
        ):
            raise NotFound()
        query = request.validated_query_data
        started = time.monotonic()
        served = serve_personal_ranking(
            self.team,
            user,
            limit=query.get("limit"),
            refresh=query["refresh"],
            focus=query.get("focus"),
            wait_seconds=query["wait_seconds"],
        )
        report_user_action(
            user,
            "personal inbox ranking read",
            properties={
                "via_mcp": is_mcp_request(request),
                "status": served.status,
                "cached": served.cached,
                "stale": served.stale,
                "building": served.building,
                "personalized": served.personalized,
                "fallback_reason": served.fallback_reason,
                "refresh": query["refresh"],
                "has_focus": bool(query.get("focus")),
                "wait_seconds": query["wait_seconds"],
                "result_count": len(served.results),
                "duration_ms": round((time.monotonic() - started) * 1000),
            },
            team=self.team,
            request=request,
        )
        return Response(PersonalRankingSerializer(personal_ranking_payload(served)).data)

    @validated_request(
        query_serializer=SignalReportFilterQuerySerializer,
        responses={200: SignalReportSectionCountsSerializer},
        parameters=_SECTION_COUNTS_PARAMETERS,
        description=(
            "Count the ready reports with and without an implementation pull request, in one query. "
            "Accepts the list's filters, so each count matches a `count_only` list request with "
            "`status=ready` and the matching `has_implementation_pr`. Rejects `status`, "
            "`has_implementation_pr`, `include_all_statuses` and `view`, because the counts set those."
        ),
    )
    @action(detail=False, methods=["get"], required_scopes=["task:read"], pagination_class=None)
    @tracer.start_as_current_span("signals.reports.section_counts")
    def section_counts(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        if trial_store_for_request(request, self.team_id) is not None:
            raise exceptions.PermissionDenied("Private scout trials cannot read inbox section counts.")
        rejected = sorted(name for name in _SECTION_DEFINING_PARAMETERS if name in request.query_params)
        if rejected:
            raise serializers.ValidationError(
                dict.fromkeys(rejected, "Section counts set this condition, so they do not accept it.")
            )
        trace.get_current_span().set_attribute("signals.reports.list.cached_filters", self._inbox_cached_filters)
        queryset = self.filter_queryset(self.get_queryset()).filter(status=SignalReport.Status.READY)
        excluded = request.validated_query_data["exclude"]
        if excluded:
            queryset = queryset.exclude(id__in=excluded)
        has_pr = self._implementation_pr_report_filter()
        counts = queryset.order_by().aggregate(
            pull_requests=Count("id", filter=has_pr),
            reports=Count("id", filter=~has_pr),
        )
        return Response(SignalReportSectionCountsSerializer(counts).data)

    @extend_schema(request=ReportReadStateRequestSerializer, responses=ReportReadStateResponseSerializer)
    @action(detail=False, methods=["post"], required_scopes=["task:read"])
    def read_state(self, request, **kwargs):
        serializer = ReportReadStateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if "read" in serializer.validated_data and trial_store_for_request(request, self.team_id) is not None:
            raise exceptions.PermissionDenied("Private scout trials cannot change inbox read state.")
        requested = serializer.validated_data["report_ids"]
        ids = list(self.get_queryset().filter(id__in=requested).values_list("id", flat=True))
        if len(set(requested)) != len(ids):
            raise NotFound("One or more reports are unavailable.")
        states = report_read_states(
            self.team_id, request.user.id, [str(id) for id in ids], serializer.validated_data.get("read")
        )
        return Response(ReportReadStateResponseSerializer({"states": states}).data)

    def get_serializer_class(self) -> type[serializers.BaseSerializer]:
        if self.action == "list":
            return SignalReportListSerializer
        return SignalReportSerializer

    def safely_get_queryset(self, queryset):
        if self.action == "read_state":
            return queryset.filter(team=self.team).exclude(status=SignalReport.Status.DELETED)
        if self.action in {"viewed", "feedback_state", "feedback", "pr_ci_statuses", "refresh_metrics"}:
            # None of these actions renders a report, so they skip the rendering annotations and
            # prefetches every other action's serializer needs. `viewed` is passive telemetry fired
            # right after the detail request that already rendered the report, `pr_ci_statuses` only
            # needs to know which of the requested ids are this team's, and `refresh_metrics` returns
            # metric snapshots alone.
            qs = queryset.filter(team=self.team)
            return self._apply_signal_report_status_filter(qs)
        if self.action in {"retrieve", "signals"}:
            qs = self._scope_signal_report_queryset(queryset)
            qs = self._annotate_artefact_count(qs)
            qs = self._annotate_channel_id(qs)
            qs = self._apply_signal_report_status_filter(qs)
            qs = self._prefetch_signal_report_priority_artefacts(qs)
            qs = self._prefetch_signal_report_ranking_score(qs)
            qs = self._annotate_is_suggested_reviewer(qs)
            return annotate_first_billable_pr_run_at(qs)
        qs = queryset
        qs = self._scope_signal_report_queryset(qs)
        renders_reports = self.action not in self._MULTI_REPORT_ACTIONS
        if renders_reports:
            # Both annotations are correlated subqueries, and the ordering keeps the page limit
            # above them, so they cost one artefact walk per report in the team. `list` reads them
            # from batched per-page lookups instead, and `bulk_state` renders no report.
            qs = self._annotate_artefact_count(qs)
        if renders_reports or self._channel_id_filter_value() is not None:
            qs = self._annotate_channel_id(qs)
        qs = self._apply_signal_report_status_filter(qs)
        qs = self._apply_signal_report_listed_filter(qs)
        qs = self._apply_signal_report_search_filter(qs)
        qs = self._apply_signal_report_created_after_filter(qs)
        unread = self.request.query_params.get("unread")
        if unread is not None:
            if unread not in {"true", "false"}:
                raise serializers.ValidationError({"unread": "Use true or false."})
            read_ids = (
                SignalReportAction.objects.for_team(self.team_id)
                .filter(
                    user_id=cast(User, self.request.user).id,
                    type=SignalReportAction.ActionType.READ,
                    metadata__read=True,
                )
                .values("report_id")
            )
            qs = qs.exclude(id__in=read_ids) if unread == "true" else qs.filter(id__in=read_ids)
        qs = self._apply_signal_report_source_product_filter(qs)
        qs = self._apply_signal_report_source_id_filter(qs)
        qs = self._apply_signal_report_scout_filter(qs)
        qs = self._apply_signal_report_scout_prefix_filter(qs)
        qs = self._apply_signal_report_implementation_pr_filter(qs)
        qs = self._apply_signal_report_unclaimed_filter(qs)
        qs = self._apply_signal_report_assignee_filter(qs)
        qs = self._apply_signal_report_channel_filter(qs)
        qs = self._apply_signal_report_suggested_reviewer_filter(qs)
        qs = self._apply_signal_report_inbox_scope_filter(qs)
        qs = self._apply_signal_report_task_filter(qs)
        qs = self._apply_signal_report_actionability_filter(qs)
        qs = self._apply_signal_report_already_addressed_filter(qs)
        qs = self._apply_signal_report_inbox_view_filter(qs)
        qs = self._annotate_signal_report_status_rank(qs)
        if self._needs_priority_annotation():
            qs = self._annotate_signal_report_priority(qs)
            qs = self._apply_signal_report_priority_filter(qs)
        if self.action == "list":
            qs = self._annotate_signal_report_ranking(qs)
        if self.action in {"list", "section_counts"}:
            qs = self._apply_signal_report_ranking_filters(qs)
        qs = self._prefetch_signal_report_priority_artefacts(qs)
        if self.action not in {"bulk_state", "bulk_claim", "section_counts"}:
            # `bulk_state` and `bulk_claim` answer with one outcome per id, never a serialized report, and
            # the list ordering that reads this value does not apply to them either.
            qs = self._annotate_is_suggested_reviewer(qs)
            qs = self._prefetch_signal_report_ranking_score(qs)
        if self.action not in self._MULTI_REPORT_ACTIONS:
            # This correlated subquery costs one walk per matching row. Multi-row actions do
            # without it: `list` serves the value from a batched page lookup, and `bulk_state`
            # renders no report.
            qs = annotate_first_billable_pr_run_at(qs)
        return qs

    def _scope_signal_report_queryset(self, queryset):
        # The serializer renders the reverse OneToOne rows inline.
        return queryset.filter(team=self.team).select_related("refund", "tracker_issue")

    def _annotate_artefact_count(self, queryset):
        # Count via a correlated subquery instead of `Count("artefacts")`,
        # so the main query doesn't LEFT JOIN + GROUP BY the full artefact table
        artefact_count_subquery = Subquery(
            SignalReportArtefact.objects.filter(report_id=OuterRef("id"))
            .exclude(
                type__in=SignalReportArtefact.SYSTEM_SCORING_ARTEFACT_TYPES
                | SignalReportArtefact.INTERNAL_ARTEFACT_TYPES
                | (
                    {SignalReportArtefact.ArtefactType.CHECK_OBSERVATION}
                    if not self._report_monitoring_enabled
                    else set()
                )
            )
            .values("report_id")
            .annotate(count=Count("*"))
            .values("count"),
            output_field=IntegerField(),
        )
        return queryset.annotate(
            artefact_count=Coalesce(artefact_count_subquery, Value(0), output_field=IntegerField())
        )

    def _annotate_channel_id(self, queryset):
        channel_id_subquery = Subquery(
            SignalReportArtefact.objects.filter(
                report_id=OuterRef("id"),
                type=SignalReportArtefact.ArtefactType.CHANNEL_ASSIGNMENT,
            )
            .annotate(
                live_channel_id=Case(
                    When(channel__deleted=False, then=F("channel_id")),
                    default=Value(None),
                    output_field=models.UUIDField(),
                )
            )
            .order_by("-created_at")
            .values("live_channel_id")[:1],
            output_field=models.UUIDField(),
        )
        return queryset.annotate(channel_id=channel_id_subquery)

    # Deleted reports are terminal, so `deleted` never reaches any endpoint (detail, list,
    # actions) and is never a valid filter target either.
    _FILTERABLE_STATUSES = frozenset(SignalReport.Status.values) - {
        SignalReport.Status.DELETED,
        SignalReport.Status.MONITORING,
    }

    # Actions that work on many reports at once, so per-row annotations are wasted work there.
    _MULTI_REPORT_ACTIONS = frozenset({"list", "bulk_state", "bulk_claim", "section_counts"})

    # Actions allowed to resolve a suppressed report by ID even without an explicit
    # `status` filter. These are the read/reopen paths the inbox's Dismissed tab needs:
    # `state` reopens a dismissed report, `retrieve` loads its detail, and `signals`
    # loads its evidence. `bulk_state` is included so a bulk restore (state='potential')
    # can reach suppressed reports too. `refund` is included so an already-archived but
    # billed report can still be refunded, and `feedback` because the detail view the
    # Dismissed tab renders ends in the thumbs rating, which must be able to forward its
    # note for the report it is displayed on. Mutating-by-ID actions (delete, reingest) are
    # deliberately NOT here, so a suppressed report stays unreachable for those and keeps
    # returning 404 — matching the existing contract.
    # `viewed` follows `retrieve` for the same reason: the Dismissed tab's detail view records its
    # open like any other. `pr_checks` and `pr_comments` are there because that same view renders the
    # read-only PR panel whatever the report's status is.
    _SUPPRESSED_VISIBLE_ACTIONS = frozenset(
        {
            "state",
            "bulk_state",
            "bulk_claim",
            "retrieve",
            "signals",
            "refund",
            "feedback",
            "feedback_state",
            "viewed",
            "pr_checks",
            "pr_comments",
            "claim",
            "priority",
        }
    )

    # Human-readable explanation per bulk outcome, surfaced in each result's `detail` field
    # (transitioned needs none — its `status` already says where the report landed).
    _BULK_STATE_OUTCOME_DETAIL = {
        SignalReportBulkStateOutcome.SKIPPED: "This transition is not allowed from the report's current status.",
        SignalReportBulkStateOutcome.FAILED: "The request data was invalid for this report.",
        SignalReportBulkStateOutcome.NOT_FOUND: "No report with this id is visible to you.",
    }

    @cached_property
    def _report_monitoring_enabled(self) -> bool:
        return organization_report_monitoring_enabled(self.organization.id)

    @cached_property
    def _inbox_cached_filters(self) -> bool:
        # Reads the cached report columns instead of the per-report authorship and PR-link
        # subqueries. Behind a flag until the daily reconcile shows no drift.
        return organization_inbox_cached_filters_enabled(self.organization.id)

    def _resolved_read_statuses(self) -> frozenset[str]:
        statuses = frozenset({SignalReport.Status.RESOLVED})
        if not self._report_monitoring_enabled:
            return statuses | {SignalReport.Status.MONITORING}
        return statuses

    def _apply_signal_report_status_filter(self, queryset):
        # Always a positive `status__in`, never a negated equality: Postgres can put an IN into the
        # `(team, status, promoted_at)` index condition, while `exclude(status=...)` leaves the
        # status as a filter that runs on rows the index already made it read.
        statuses = self._visible_statuses()
        if SignalReport.Status.RESOLVED in statuses:
            statuses |= self._resolved_read_statuses()
        return queryset.filter(status__in=sorted(statuses))

    def _visible_statuses(self) -> frozenset[str]:
        filterable_statuses = self._FILTERABLE_STATUSES
        if self._report_monitoring_enabled:
            filterable_statuses |= {SignalReport.Status.MONITORING}
        status_filter = self.request.query_params.get("status")
        if status_filter:
            statuses = [s.strip() for s in status_filter.split(",") if s.strip()]
            invalid = [s for s in statuses if s not in filterable_statuses]
            if invalid:
                accepted = ", ".join(sorted(filterable_statuses))
                raise serializers.ValidationError(
                    {
                        "status": f"Invalid status value(s): {', '.join(sorted(set(invalid)))}. Accepted values: {accepted}."
                    }
                )
            return frozenset(statuses)
        # A few read/reopen actions must be able to reach a suppressed report by ID
        # (e.g. `state` reopens a dismissed report, `retrieve`/`signals` back the
        # inbox's Dismissed-tab detail view). Everywhere else — including the list and
        # mutating-by-ID actions like delete/reingest — suppressed reports stay hidden
        # unless an explicit `status` filter asks for them, or the caller opts out of
        # the default exclusions with `include_all_statuses=true` (agents deduping
        # against the full inbox state, human dismissals included, without enumerating
        # every status — and without breaking if the status set evolves).
        if (
            self.action in self._SUPPRESSED_VISIBLE_ACTIONS
            or self._include_all_statuses_requested()
            or self.request.query_params.get("view") in {"dismissed", "held_back", "all"}
        ):
            return filterable_statuses
        return filterable_statuses - {SignalReport.Status.SUPPRESSED}

    def _include_all_statuses_requested(self) -> bool:
        # List-only: the flag widens the *list* for full-inbox-state scans (agent dedup). By-ID
        # actions ignore it entirely, so mutating actions like delete/reingest keep their existing
        # contract of 404ing on suppressed reports.
        if self.action != "list":
            return False
        return self._bool_query_param("include_all_statuses") is True

    def _bool_query_param(self, name: str) -> bool | None:
        """Parse a true/false query param. None when the param is absent or blank."""
        raw = self.request.query_params.get(name)
        if raw is None or not raw.strip():
            return None
        value = raw.strip().lower()
        if value in ("1", "true", "yes"):
            return True
        if value in ("0", "false", "no"):
            return False
        raise serializers.ValidationError({name: f"Invalid value: {raw!r}. Allowed: true, false."})

    def _apply_signal_report_listed_filter(self, queryset):
        # List-only: a report a scout kept out of the inbox stays reachable by id and by its other actions.
        if self.action not in {"list", "section_counts"} or self._bool_query_param("include_unlisted") is True:
            return queryset
        return queryset.filter(inbox_hidden_report_filter(self.team_id))

    def _apply_signal_report_search_filter(self, queryset):
        search = self.request.query_params.get("search")
        if not search:
            return queryset
        return queryset.filter(Q(title__icontains=search) | Q(summary__icontains=search))

    def _apply_signal_report_created_after_filter(self, queryset):
        raw = self.request.query_params.get("created_after")
        if not raw:
            return queryset
        try:
            created_after = serializers.DateTimeField().to_internal_value(raw)
        except serializers.ValidationError:
            raise serializers.ValidationError({"created_after": "Use an ISO 8601 datetime."})
        return queryset.filter(created_at__gte=created_after)

    def _apply_signal_report_source_product_filter(self, queryset):
        source_product_filter = self.request.query_params.get("source_product")
        if not source_product_filter:
            return queryset
        # `source_id` already implies its product, so its narrower lookup subsumes this one. Skip
        # rather than run a second ClickHouse query for a strictly wider set.
        if self.request.query_params.get("source_id"):
            return queryset

        source_products = [s.strip() for s in source_product_filter.split(",") if s.strip()]
        if not source_products:
            return queryset

        report_ids_with_source = fetch_report_ids_for_source_products(self.team, source_products)
        return queryset.filter(id__in=report_ids_with_source)

    def _apply_signal_report_source_id_filter(self, queryset):
        """Reports a specific source record contributed to, e.g. one support ticket's reports.

        The owning product asks with the id it already has, instead of reaching into signals.

        Requires a single `source_product`, because a source id is only unique within one: emitters
        pass through the external system's own id, so GitHub issue 42 and Jira issue 42 both arrive as
        `"42"`. `SignalEmissionRecord` says the same thing with its `(team, source_product, source_type,
        source_id)` constraint. Without the product this would quietly mix products together.
        """
        source_id_filter = self.request.query_params.get("source_id")
        if not source_id_filter:
            return queryset

        source_ids = [s.strip() for s in source_id_filter.split(",") if s.strip()]
        if not source_ids:
            return queryset

        source_product = self.request.query_params.get("source_product")
        product = source_product.strip() if source_product else ""
        if not product or "," in product:
            raise exceptions.ValidationError(
                {
                    "source_id": "Pass exactly one source_product alongside source_id. A source id is only "
                    "unique within its product, so filtering without one would mix products together."
                }
            )
        by_source = fetch_live_report_ids_for_source_ids(self.team, source_ids, product)
        report_ids = {report_id for ids in by_source.values() for report_id in ids}
        return queryset.filter(id__in=report_ids)

    def _apply_signal_report_scout_filter(self, queryset):
        scout_filter = self.request.query_params.get("scout")
        if not scout_filter:
            return queryset

        scout_names = [s.strip() for s in scout_filter.split(",") if s.strip()]
        if not scout_names:
            return queryset

        report_ids_with_scout = fetch_report_ids_for_scout_names(self.team, scout_names)
        return queryset.filter(id__in=report_ids_with_scout)

    def _apply_signal_report_scout_prefix_filter(self, queryset):
        scout_prefix = (self.request.query_params.get("scout_prefix") or "").strip()
        if not scout_prefix:
            return queryset

        report_ids_with_prefix = fetch_report_ids_for_scout_prefix(self.team, scout_prefix)
        return queryset.filter(id__in=report_ids_with_prefix)

    def _implementation_pr_report_filter(self) -> Q:
        if self._inbox_cached_filters:
            return Q(has_implementation_pr=True)
        return implementation_pr_report_filter(team_id=self.team.id)

    def _apply_signal_report_implementation_pr_filter(self, queryset):
        # `has_implementation_pr=true|false` filters reports by whether an attached
        # implementation PR exists. Lets the inbox count PR reports (the "Pull
        # requests" tab) with a cheap count query instead of paging the whole list
        # and filtering client-side. Absent or empty param leaves the list
        # unchanged; an unrecognized value is a 400.
        wants_pr = self._bool_query_param("has_implementation_pr")
        if wants_pr is None:
            return queryset
        pr_filter = self._implementation_pr_report_filter()
        return queryset.filter(pr_filter) if wants_pr else queryset.exclude(pr_filter)

    def _apply_signal_report_unclaimed_filter(self, queryset):
        wants_unclaimed = self._bool_query_param("unclaimed")
        if wants_unclaimed is None:
            return queryset
        has_review_pr = (
            Q(has_active_implementation_pr=True)
            if self._inbox_cached_filters
            else implementation_pr_report_filter(team_id=self.team.id, active_only=True)
        )
        is_unclaimed = (
            ~Q(status__in={SignalReport.Status.RESOLVED, SignalReport.Status.MONITORING, SignalReport.Status.CLOSED})
            & ~reports_with_active_claim(team_id=self.team_id)
            & ~has_review_pr
        )
        return queryset.filter(is_unclaimed) if wants_unclaimed else queryset.exclude(is_unclaimed)

    def _apply_signal_report_assignee_filter(self, queryset):
        raw = self.request.query_params.get("assignee")
        if raw is None or not raw.strip():
            return queryset
        value = raw.strip().lower()
        if value == "mine":
            user_id = self.request.user.id
            if user_id is None:  # unreachable behind authentication
                raise exceptions.NotAuthenticated()
            return queryset.filter(reports_claimed_for_user(team_id=self.team_id, user_id=user_id))
        if value != "me":
            raise serializers.ValidationError({"assignee": "Invalid value. Allowed: me, mine."})
        actor = self._request_attribution()
        return queryset.filter(reports_with_active_claim(team_id=self.team_id, actor=actor))

    def _channel_id_filter_value(self) -> uuid.UUID | None:
        # `channel_id=<uuid>` narrows to reports assigned to one space. Absent or empty
        # leaves the list unchanged (the general view lists every report); a non-UUID is a 400.
        raw = self.request.query_params.get("channel_id")
        if raw is None or not raw.strip():
            return None
        try:
            return uuid.UUID(raw.strip())
        except (ValueError, AttributeError):
            raise serializers.ValidationError({"channel_id": f"Invalid value: {raw!r}. Expected a UUID."})

    def _apply_signal_report_channel_filter(self, queryset):
        channel_id = self._channel_id_filter_value()
        if channel_id is None:
            return queryset
        return queryset.filter(channel_id=channel_id)

    def _apply_signal_report_suggested_reviewer_filter(self, queryset):
        suggested_reviewer_filter = self.request.query_params.get("suggested_reviewers")
        if not suggested_reviewer_filter:
            return queryset

        reviewer_user_uuids = [s.strip() for s in suggested_reviewer_filter.split(",") if s.strip()]
        return self._filter_signal_reports_by_suggested_reviewers(queryset, reviewer_user_uuids)

    def _filter_signal_reports_by_suggested_reviewers(self, queryset, reviewer_user_uuids: list[str]):
        try:
            reviewer_user_uuids = [str(uuid.UUID(user_uuid)) for user_uuid in reviewer_user_uuids]
        except (ValueError, AttributeError) as e:
            raise serializers.ValidationError({"suggested_reviewers": f"Invalid user UUID: {e}"})

        # A reviewer entry identifies its person by `user_uuid`, by `github_login`, or by both, so
        # match on either: the requested users' own uuids, plus their logins for the entries written
        # before reviewers carried a uuid.
        reviewer_github_logins = list(
            get_org_member_github_logins_by_user_uuid(self.team.id, reviewer_user_uuids).values()
        )
        if not reviewer_user_uuids and not reviewer_github_logins:
            return queryset.none()
        return queryset.filter(
            id__in=report_ids_naming_reviewers(
                team_id=self.team.id,
                user_uuids=reviewer_user_uuids,
                github_logins=reviewer_github_logins,
                logins_match_unidentified_only=True,
            )
        )

    def _apply_signal_report_inbox_scope_filter(self, queryset):
        scope = self.request.query_params.get("scope")
        if not scope or scope == "entire_project":
            return queryset
        if scope == "for_me":
            user = cast(User, self.request.user)
            return self._filter_signal_reports_by_suggested_reviewers(queryset, [str(user.uuid)])
        if scope == "teammate":
            teammate_uuid = (self.request.query_params.get("teammate_uuid") or "").strip()
            if not teammate_uuid:
                raise serializers.ValidationError({"teammate_uuid": "This field is required when scope is teammate."})
            return self._filter_signal_reports_by_suggested_reviewers(queryset, [teammate_uuid])
        raise serializers.ValidationError(
            {"scope": f"Invalid value: {scope!r}. Allowed: for_me, entire_project, teammate."}
        )

    def _apply_signal_report_task_filter(self, queryset):
        # Reports a given task is associated with — used by running agents ("which reports am I
        # working against?") and by the agent harness to fan commit artefacts out to them. Uses the
        # unified association (task_run artefacts + legacy SignalReportTask); the team-scoped outer
        # queryset keeps the result within the project.
        task_filter = self.request.query_params.get("task_id")
        if not task_filter:
            return queryset
        try:
            task_uuid = uuid.UUID(task_filter.strip())
        except (ValueError, AttributeError) as e:
            raise serializers.ValidationError({"task_id": f"Invalid task UUID: {e}"})
        return queryset.filter(SignalReport.reports_for_task_filter(task_uuid))

    def _apply_signal_report_priority_filter(self, queryset):
        # Filters on the `priority_sort_rank` annotation, which must be applied first.
        # Reports without a priority artefact rank after every priority, so this filter excludes them.
        priority_filter = self.request.query_params.get("priority")
        if not priority_filter and self.request.query_params.get("use_priority_preference", "false").lower() == "true":
            user = cast(User, self.request.user)
            personal_threshold = (
                SignalUserAutonomyConfig.objects.filter(user=user).values_list("autostart_priority", flat=True).first()
            )
            project_threshold = (
                SignalTeamConfig.objects.filter(team=self.team)
                .values_list("default_autostart_priority", flat=True)
                .first()
                or AutonomyPriority.P4
            )
            threshold = personal_threshold or project_threshold
            values = AutonomyPriority.values[: AutonomyPriority.values.index(threshold) + 1]
            return queryset.filter(priority_sort_rank__in=self._priority_ranks(values))
        if not priority_filter:
            return queryset

        values = [p.strip().upper() for p in priority_filter.split(",") if p.strip()]
        if not values:
            return queryset

        allowed = set(AutonomyPriority.values)
        invalid = [v for v in values if v not in allowed]
        if invalid:
            raise serializers.ValidationError(
                {
                    "priority": f"Invalid priority value(s): {', '.join(sorted(set(invalid)))}. Allowed: {', '.join(sorted(allowed))}."
                }
            )

        return queryset.filter(priority_sort_rank__in=self._priority_ranks(values))

    @staticmethod
    def _priority_ranks(priorities: Iterable[str]) -> list[int]:
        return [AutonomyPriority.values.index(priority) for priority in priorities]

    def _apply_signal_report_actionability_filter(self, queryset):
        # Filters on `latest_actionability`, the column cached from the report's latest
        # actionability_judgment artefact. Powers the inbox's actionability-keyed tabs: the
        # Reports tab passes the two actionable values, the staff-only Not-actionable tab
        # passes `not_actionable`. Reports without an actionability judgment (column is NULL)
        # are excluded when this filter is set. Absent or empty param leaves the list
        # unchanged; an unrecognized value is a 400.
        actionability_filter = self.request.query_params.get("actionability")
        if not actionability_filter:
            return queryset

        values = [a.strip() for a in actionability_filter.split(",") if a.strip()]
        if not values:
            return queryset

        allowed = {choice.value for choice in ActionabilityChoice}
        invalid = [v for v in values if v not in allowed]
        if invalid:
            raise serializers.ValidationError(
                {
                    "actionability": f"Invalid actionability value(s): {', '.join(sorted(set(invalid)))}. "
                    f"Allowed: {', '.join(sorted(allowed))}."
                }
            )

        return queryset.filter(latest_actionability__in=values)

    def _apply_signal_report_already_addressed_filter(self, queryset):
        already_addressed = self._bool_query_param("already_addressed")
        if already_addressed is None:
            return queryset
        # `=False`, not `exclude(=True)`: a report with no parseable judgment holds NULL, and
        # "not already addressed" has never covered reports nobody judged.
        return queryset.filter(latest_already_addressed=already_addressed)

    def _apply_signal_report_inbox_view_filter(self, queryset):
        inbox_view = self.request.query_params.get("view")
        if not inbox_view:
            return queryset
        if inbox_view not in self._INBOX_VIEWS:
            allowed = ", ".join(sorted(self._INBOX_VIEWS))
            raise serializers.ValidationError({"view": f"Invalid value: {inbox_view!r}. Allowed: {allowed}."})
        if inbox_view == "actionable":
            return queryset.filter(
                status=SignalReport.Status.READY,
                latest_actionability=ActionabilityChoice.IMMEDIATELY_ACTIONABLE.value,
                latest_already_addressed=False,
            ).exclude(self._implementation_pr_report_filter())
        if inbox_view == "for_you":
            for_person = reports_for_person(self.team_id, cast(User, self.request.user))
            return queryset.filter(id__in=for_person.values("id"))
        if inbox_view == "needs_input":
            return queryset.filter(
                status=SignalReport.Status.PENDING_INPUT,
                latest_actionability=ActionabilityChoice.REQUIRES_HUMAN_INPUT.value,
            )
        if inbox_view == "needs_decision":
            return queryset.filter(
                Q(status=SignalReport.Status.FAILED)
                | Q(status__in=[SignalReport.Status.MONITORING] if self._report_monitoring_enabled else [])
                | (
                    Q(
                        status__in=[SignalReport.Status.READY, SignalReport.Status.PENDING_INPUT],
                        latest_actionability__in=[
                            ActionabilityChoice.IMMEDIATELY_ACTIONABLE.value,
                            ActionabilityChoice.REQUIRES_HUMAN_INPUT.value,
                        ],
                    )
                    & ~self._implementation_pr_report_filter()
                )
            )
        if inbox_view == "monitoring":
            return queryset.filter(status=SignalReport.Status.READY).filter(self._implementation_pr_report_filter())
        if inbox_view == "resolved":
            return queryset.filter(status__in=self._resolved_read_statuses())
        if inbox_view == "closed":
            return queryset.filter(status=SignalReport.Status.CLOSED)
        if inbox_view in {"dismissed", "held_back"}:
            # Every path that suppresses a report on someone's behalf writes a dismissal artefact: a
            # person or agent dismissing it, a merge, a closed pull request. A suppressed report with
            # none was held back by a judge, and nobody has looked at it yet.
            has_dismissal = Exists(
                SignalReportArtefact.objects.filter(
                    report_id=OuterRef("id"), type=SignalReportArtefact.ArtefactType.DISMISSAL
                )
            )
            queryset = queryset.filter(status=SignalReport.Status.SUPPRESSED)
            return queryset.filter(has_dismissal if inbox_view == "dismissed" else ~has_dismissal)
        if inbox_view == "not_actionable":
            return queryset.filter(latest_actionability=ActionabilityChoice.NOT_ACTIONABLE.value)
        return queryset

    def _annotate_signal_report_status_rank(self, queryset):
        # `ordering=status` uses semantic stage rank (annotation), not lexicographic `status` column order.
        # `status=ready` splits into two virtual stages:
        # 0 = ready + actionable (or no judgment yet), 1 = ready + not_actionable; then other stages.
        return queryset.annotate(
            pipeline_status_rank=Case(
                When(self._Q_READY_NOT_ACTIONABLE, then=Value(1)),
                When(status=SignalReport.Status.READY, then=Value(0)),
                When(status=SignalReport.Status.PENDING_INPUT, then=Value(2)),
                When(status=SignalReport.Status.IN_PROGRESS, then=Value(3)),
                When(status=SignalReport.Status.CANDIDATE, then=Value(4)),
                When(status=SignalReport.Status.POTENTIAL, then=Value(5)),
                When(status=SignalReport.Status.FAILED, then=Value(6)),
                When(status=SignalReport.Status.MONITORING, then=Value(6 if self._report_monitoring_enabled else 7)),
                When(status__in=self._resolved_read_statuses(), then=Value(7)),
                When(status=SignalReport.Status.CLOSED, then=Value(7)),
                When(status=SignalReport.Status.SUPPRESSED, then=Value(8)),
                When(status=SignalReport.Status.DELETED, then=Value(9)),
                default=Value(50),
                output_field=IntegerField(),
            )
        )

    def _annotate_signal_report_priority(self, queryset):
        # `ordering=priority` sorts by the priority value ("P0"–"P4") from the latest priority_judgment
        # artefact, as its index in `AutonomyPriority.values`. Reports without a priority rank after "P4".
        return queryset.annotate(priority_sort_rank=latest_priority_rank())

    def _annotate_signal_report_ranking(self, queryset):
        # `ordering=ranking_<head>` sorts by the served model's probability for that head, read from
        # the latest ranking_score artefact as `results -> <served_key> -> scores -> <head>`. Only
        # the heads the ordering names are annotated, because each one is a correlated subquery.
        ordered_fields = {clause.lstrip("-") for clause in self._parse_signal_report_ordering()}
        annotated: set[str] = set()
        for field, head in self._RANKING_ORDERING_HEADS.items():
            annotation = self._SIGNAL_REPORT_ORDERING_FIELDS[field]
            # An alias shares its annotation with the field it renames, so annotate each one once.
            if annotation not in ordered_fields or annotation in annotated:
                continue
            annotated.add(annotation)
            latest_score = latest_ranking_value(head, "scores")
            if self._inbox_ranker is not None:
                queryset = queryset.annotate(
                    **{self._ranking_decile_annotation(annotation): score_decile(latest_score)}
                )
            else:
                queryset = queryset.annotate(**{annotation: latest_score})
        return queryset

    @staticmethod
    def _ranking_decile_annotation(score_annotation: str) -> str:
        return f"{score_annotation}_decile"

    def _apply_signal_report_ranking_filters(self, queryset):
        # Each named head is one correlated subquery, compared with `>=`. NULL never matches, so
        # unscored and stale reports drop out of every ranking filter.
        filters: tuple[tuple[str, Literal["scores", "lifts"]], ...] = (
            ("ranking_min_lift", "lifts"),
            ("ranking_min_probability", "scores"),
        )
        for param, key in filters:
            minimums = self._parse_ranking_minimums(param)
            if not minimums:
                continue
            for outcome, minimum in minimums.items():
                head = MODEL_HEAD_BY_OUTCOME[outcome]
                queryset = queryset.filter(GreaterThanOrEqual(latest_ranking_value(head, key), minimum))
        return queryset

    def _parse_ranking_minimums(self, param: str) -> dict[str, float]:
        raw = self.request.query_params.get(param)
        if raw is None or not raw.strip():
            return {}
        if not self._can_view_inbox_ranking:
            # The serializer hides ranking scores from these users, and the filter would leak them.
            raise serializers.ValidationError({param: f"Filtering by {param} is not available to you."})
        valid = ", ".join(PUBLIC_OUTCOME_NAMES)
        minimums: dict[str, float] = {}
        for pair in raw.split(","):
            outcome, sep, value = pair.strip().partition(":")
            outcome = outcome.strip()
            if outcome not in PUBLIC_OUTCOME_NAMES:
                raise serializers.ValidationError({param: f"Unknown outcome {outcome!r}. Valid outcomes: {valid}."})
            try:
                minimum = float(value) if sep else math.nan
            except ValueError:
                minimum = math.nan
            if not math.isfinite(minimum) or minimum < 0:
                raise serializers.ValidationError(
                    {
                        param: f"Use <outcome>:<number> pairs with a number of 0 or more, e.g. fix:2. Valid outcomes: {valid}."
                    }
                )
            # A report must meet every pair, so a repeated outcome keeps its strictest minimum.
            minimums[outcome] = max(minimum, minimums.get(outcome, minimum))
        return minimums

    def _needs_priority_annotation(self) -> bool:
        # The priority value is a correlated subquery too, and the serializer renders priority from
        # the prefetched artefacts instead, so only a priority filter or a priority sort needs it.
        params = self.request.query_params
        if params.get("priority") or params.get("use_priority_preference", "false").lower() == "true":
            return True
        priority_clause = self._SIGNAL_REPORT_ORDERING_FIELDS["priority"]
        return any(clause.lstrip("-") == priority_clause for clause in self._parse_signal_report_ordering())

    def _prefetch_signal_report_priority_artefacts(self, queryset):
        return queryset.prefetch_related(
            Prefetch(
                "artefacts",
                queryset=SignalReportArtefact.objects.filter(
                    type=SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT
                ).order_by("-created_at"),
                to_attr="prefetched_priority_artefacts",
            ),
            Prefetch(
                "artefacts",
                queryset=SignalReportArtefact.objects.filter(
                    type=SignalReportArtefact.ArtefactType.ACTIONABILITY_JUDGMENT
                ).order_by("-created_at"),
                to_attr="prefetched_actionability_artefacts",
            ),
            Prefetch(
                "artefacts",
                queryset=SignalReportArtefact.objects.filter(type=SignalReportArtefact.ArtefactType.DISMISSAL).order_by(
                    "-created_at"
                ),
                to_attr="prefetched_dismissal_artefacts",
            ),
            Prefetch(
                "artefacts",
                queryset=SignalReportArtefact.objects.filter(
                    type=SignalReportArtefact.ArtefactType.REPO_SELECTION
                ).order_by("-created_at")[:1],
                to_attr="prefetched_repo_selection_artefacts",
            ),
            Prefetch(
                "artefacts",
                queryset=SignalReportArtefact.objects.filter(
                    type=SignalReportArtefact.ArtefactType.SAFETY_JUDGMENT
                ).order_by("-created_at")[:1],
                to_attr="prefetched_safety_artefacts",
            ),
        )

    @cached_property
    def _can_view_inbox_ranking(self) -> bool:
        return can_view_inbox_ranking(cast(User, self.request.user), self.team)

    def _prefetch_signal_report_ranking_score(self, queryset):
        # Only requests that may see the score pay for the lookup.
        if not self._can_view_inbox_ranking:
            return queryset
        return queryset.prefetch_related(
            Prefetch(
                "artefacts",
                queryset=SignalReportArtefact.objects.filter(
                    type=SignalReportArtefact.ArtefactType.RANKING_SCORE
                ).order_by("-created_at")[:1],
                to_attr="prefetched_ranking_score_artefacts",
            ),
            Prefetch(
                "artefacts",
                queryset=SignalReportArtefact.objects.filter(type__in=EDIT_ARTEFACT_TYPES)
                .only("id", "report", "created_at")
                .order_by("-created_at")[:1],
                to_attr="prefetched_latest_edit_artefacts",
            ),
        )

    def _annotate_is_suggested_reviewer(self, queryset):
        # Annotate is_suggested_reviewer by resolving the current user's GitHub login
        # and matching it against the indexed reviewer rows. This stays fresh
        # even when a user connects their GitHub account after the report was generated.
        # Never true for ready + not_actionable — there is nothing actionable to review.
        # Failed reports are excluded too — pipelines that errored should not bubble as "needs your review".
        # Match the user's own uuid as well as their login: a reviewer with no linked GitHub
        # account is stored by uuid alone, and entries predating `user_uuid` carry only a login.
        user = cast(User, self.request.user)
        github_login = self._get_github_login(user)
        matching_report_ids = report_ids_naming_reviewers(
            team_id=self.team.id,
            user_uuids=[str(user.uuid)],
            github_logins=[github_login] if github_login else [],
            logins_match_unidentified_only=False,
        )
        names_the_user = (
            Q(id__in=matching_report_ids)
            if self.action == "list"
            else Q(Exists(matching_report_ids.filter(report_id=OuterRef("id"))))
        )
        return queryset.annotate(
            is_suggested_reviewer=Case(
                When(self._Q_READY_NOT_ACTIONABLE, then=Value(False)),
                When(status=SignalReport.Status.FAILED, then=Value(False)),
                When(names_the_user, then=Value(True)),
                default=Value(False),
                output_field=BooleanField(),
            ),
        )

    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)
        if self.action != "list":
            # A by-ID lookup has nothing to order. More importantly, keeping list ordering here
            # forces every detail request to compute status/priority/reviewer annotations that
            # cannot affect which primary-key row is returned.
            return queryset
        return self._apply_signal_report_ordering(queryset)

    def _parse_ordering_string(self, raw: str, *, allow_ranking: bool = False) -> list[str]:
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        clauses: list[str] = []
        for part in parts:
            descending = part.startswith("-")
            name = part[1:] if descending else part
            db_field = self._SIGNAL_REPORT_ORDERING_FIELDS.get(name)
            if db_field is None:
                continue
            if name in self._RANKING_ORDERING_HEADS and not allow_ranking and not self._can_view_inbox_ranking:
                # The serializer hides ranking scores from these users, and the order would leak them.
                raise serializers.ValidationError({"ordering": f"Ordering by {name} is not available to you."})
            clause = f"-{db_field}" if descending else db_field
            clauses.append(clause)
        return clauses

    @property
    def _default_signal_report_ordering_clauses(self) -> list[str]:
        return self._parse_ordering_string(self._DEFAULT_SIGNAL_REPORT_ORDERING)

    @cached_property
    def _inbox_ranker(self) -> InboxRanker | None:
        params = self.request.query_params
        if params.get("ordering") is not None or params.get("sort") != "recommended":
            return None
        return resolve_recommended_ranker(self.team, cast(User, self.request.user))

    def _parse_signal_report_ordering(self) -> list[str]:
        ranker = self._inbox_ranker
        if ranker is not None:
            # The preset exposes only the score decile, through `inbox_merge_key`, so non-staff users may use it.
            return self._parse_ordering_string(RANKER_ORDERINGS[ranker], allow_ranking=True)
        raw = self.request.query_params.get("ordering")
        if raw is None:
            inbox_sort = self.request.query_params.get("sort")
            if inbox_sort:
                raw = self._INBOX_SORT_ORDERINGS.get(inbox_sort)
                if raw is None:
                    allowed = ", ".join(sorted(self._INBOX_SORT_ORDERINGS))
                    raise serializers.ValidationError({"sort": f"Invalid value: {inbox_sort!r}. Allowed: {allowed}."})
            else:
                raw = self._DEFAULT_SIGNAL_REPORT_ORDERING
        if not raw or not str(raw).strip():
            return self._default_signal_report_ordering_clauses
        clauses = self._parse_ordering_string(str(raw).strip())
        return clauses if clauses else self._default_signal_report_ordering_clauses

    def _apply_signal_report_ordering(self, queryset):
        clauses = self._parse_signal_report_ordering()
        has_id = any((c[1:] if c.startswith("-") else c) == "id" for c in clauses)
        if not has_id:
            clauses = [*clauses, "id"]
        ranking_annotations = {self._SIGNAL_REPORT_ORDERING_FIELDS[field] for field in self._RANKING_ORDERING_HEADS}
        order_by: list[str | OrderBy] = []
        for clause in clauses:
            name = clause.lstrip("-")
            if name in ranking_annotations:
                # The recommended preset sorts by the score decile, so the order shows no more than `inbox_merge_key`.
                expression = F(self._ranking_decile_annotation(name) if self._inbox_ranker is not None else name)
                # Unscored reports sort after every scored report, in both directions.
                order_by.append(
                    expression.desc(nulls_last=True) if clause.startswith("-") else expression.asc(nulls_last=True)
                )
            else:
                order_by.append(clause)
        return queryset.order_by(*order_by)

    @staticmethod
    def _get_github_login(user) -> str | None:
        login = user.get_github_login()
        return login.lower() if login else None

    def get_serializer_context(self):
        return {
            **super().get_serializer_context(),
            "team": self.team,
            # Called only when a report renders its `ranking` field, so other requests skip the flag check.
            "can_view_inbox_ranking": lambda: self._can_view_inbox_ranking,
            "report_monitoring_enabled_by_team": {self.team_id: self._report_monitoring_enabled},
            # For the serializer's refund_ineligibility_reason field — computed once per request,
            # not per report (the bounds are org-level).
            "billing_period_bounds": current_billing_period_bounds(self.organization),
        }

    @staticmethod
    def _claim_and_pull_request_context(
        report_ids: list[str],
        pull_requests_map: dict[str, list[ImplementationPr]],
        claims: dict[str, ReportClaim],
    ) -> dict[str, object]:
        implementation_pr_by_report = {rid: primary_pull_request(prs) for rid, prs in pull_requests_map.items()}
        return {
            "pull_requests_map": pull_requests_map,
            "claims_map": dict.fromkeys(report_ids) | claims,
            "claim_responsible_users_map": responsible_users(claims.values()),
            "implementation_pr_url_map": {rid: pr.url for rid, pr in implementation_pr_by_report.items()},
            "implementation_pr_state_map": {rid: pr.state for rid, pr in implementation_pr_by_report.items()},
            "implementation_pr_merged_ids": {rid for rid, pr in implementation_pr_by_report.items() if pr.merged},
        }

    def _enriched_report_context(self, report: SignalReport) -> dict:
        # Detail-view parity with list(): inject the source metadata map the serializer reads.
        # This lookup is best-effort so a ClickHouse failure cannot hide the report.
        report_ids = [str(report.id)]
        try:
            signal_meta_map = fetch_source_products_for_reports(self.team, report_ids)
        except Exception:
            logger.exception("signals.enriched_context.source_products_failed", report_id=str(report.id))
            signal_meta_map = {}
        try:
            pull_requests_map = fetch_implementation_prs_for_reports(report_ids, team_id=self.team_id)
        except Exception:
            logger.exception("signals.enriched_context.implementation_pr_failed", report_id=str(report.id))
            pull_requests_map = {}
        try:
            source_suggestion = current_source_suggestion(self.team, str(report.id))
        except Exception:
            logger.exception("signals.enriched_context.source_suggestion_failed", report_id=str(report.id))
            source_suggestion = None
        try:
            plan = report_plan(team_id=self.team_id, report_id=str(report.id))
        except Exception:
            logger.exception("signals.enriched_context.report_plan_failed", report_id=str(report.id))
            plan = None
        claims = get_active_claims(team_id=self.team_id, report_ids=report_ids)
        return {
            **self.get_serializer_context(),
            "source_products_map": {rid: meta.source_products for rid, meta in signal_meta_map.items()},
            "scout_names_map": {rid: meta.scout_name for rid, meta in signal_meta_map.items() if meta.scout_name},
            **self._claim_and_pull_request_context(report_ids, pull_requests_map, claims),
            "source_suggestions_map": {str(report.id): source_suggestion},
            "report_plans_map": {str(report.id): plan},
        }

    def retrieve(self, request, *args, **kwargs):
        with trial_state_errors():
            store = trial_store_for_request(request, self.team_id)
            if store is not None:
                private = TrialInboxReads(self, store).detail(str(kwargs["pk"]))
                if private is not None:
                    return Response(private)
        report = self.get_object()
        serializer = self.get_serializer(report, context=self._enriched_report_context(report))
        return Response(serializer.data)

    @extend_schema(
        request=SignalReportClaimSerializer,
        responses={
            200: OpenApiResponse(response=SignalReportSerializer, description="Current report and assignment."),
            400: OpenApiResponse(description="The pull request URL or request shape is invalid."),
            409: OpenApiResponse(description="The report cannot be claimed or released in its current state."),
        },
        summary="Claim or release a signal report",
        description=(
            "Start or update work for the current user, internal task, or external agent. "
            "Supply claim_id to resume, pull_requests to add PRs, takeover=true to explicitly take ownership, "
            "or release=true to end ownership while preserving work history and PR links."
        ),
        operation_id="signals_reports_claim",
    )
    @action(detail=True, methods=["post"], url_path="claim", required_scopes=["task:write"])
    def claim(self, request: Request, *args, **kwargs) -> Response:
        request_serializer = SignalReportClaimSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        report = cast(SignalReport, self.get_object())
        data = request_serializer.validated_data
        try:
            claim_report(
                report=report,
                actor=self._request_attribution(),
                user=cast(User, request.user),
                was_impersonated=is_impersonated_session(request),
                pr_url=data.get("pr_url"),
                release=data["release"],
                pull_requests=data.get("pull_requests"),
                claim_id=str(data["claim_id"]) if data.get("claim_id") else None,
                takeover=data["takeover"],
                takeover_claim_id=str(data["takeover_claim_id"]) if data.get("takeover_claim_id") else None,
            )
        except InvalidPullRequestUrl as err:
            raise serializers.ValidationError({"pr_url": str(err)})
        except ReportClaimConflict as err:
            return Response({"detail": str(err)}, status=status.HTTP_409_CONFLICT)

        updated_report = self._scope_signal_report_queryset(SignalReport.objects.all()).get(id=report.id)
        response_serializer = self.get_serializer(
            updated_report,
            context=self._enriched_report_context(updated_report),
        )
        return Response(response_serializer.data)

    @validated_request(
        request_serializer=SignalReportPriorityUpdateSerializer,
        responses={200: SignalReportSerializer},
        summary="Change a report's priority",
        description="Append an attributed priority correction, preserving the previous judgment for future learning.",
        operation_id="signals_reports_priority_update",
    )
    @action(detail=True, methods=["put"], required_scopes=["task:write"])
    def priority(self, request: ValidatedRequest, *args: object, **kwargs: object) -> Response:
        report = cast(SignalReport, self.get_object())
        update_report_priority(
            report=report,
            priority=ReportPriority(request.validated_data["priority"]),
            attribution=self._request_attribution(),
        )
        report.__dict__.pop("prefetched_priority_artefacts", None)
        return Response(SignalReportSerializer(report, context=self._enriched_report_context(report)).data)

    @validated_request(
        request_serializer=SignalReportContentUpdateSerializer,
        responses={
            200: OpenApiResponse(response=SignalReportSerializer, description="Report updated."),
            400: OpenApiResponse(description="Neither title nor summary supplied, or a value failed validation."),
            404: OpenApiResponse(description="Report not found for this project."),
        },
        summary="Edit a report's title or summary",
        description=(
            "Edit the human-facing title and/or summary (description) of a signal report, addressed "
            "by id. Both fields are optional — supply only the ones you want to change; at least one "
            "is required. Every other report field (status, weights, judgments) is managed by the "
            "signals pipeline and cannot be set here. Returns the full updated report."
        ),
        operation_id="signals_reports_partial_update",
    )
    def partial_update(self, request: ValidatedRequest, *args, **kwargs) -> Response:
        report = cast(SignalReport, self.get_object())
        data = request.validated_data
        # Attribution mirrors the other artefact-writing paths (suggested reviewers, commit/task_run):
        # the edit is the agent's task when an `X-PostHog-Task-Id` header is present, otherwise the
        # requesting user. Resolved up front so a bad task header 400s before we mutate anything.
        attribution = resolve_request_attribution(request, self.team.id)
        update_fields: list[str] = []
        # Each real change is logged as its own append-only edit-history artefact capturing the
        # before/after, so the report carries an audit trail of human/agent title & summary edits.
        edit_artefacts: list[TitleChange | SummaryChange] = []
        if "title" in data and data["title"] != report.title:
            edit_artefacts.append(TitleChange(old_title=report.title, new_title=data["title"]))
            report.title = data["title"]
            update_fields.append("title")
        if "summary" in data and data["summary"] != report.summary:
            edit_artefacts.append(SummaryChange(old_summary=report.summary, new_summary=data["summary"]))
            report.summary = data["summary"]
            update_fields.append("summary")
            # The suggested prompts were written against the prose this edit replaces, so they go
            # down with it — the same rule the research pipeline applies when it rewrites a summary.
            # Leaving them would offer prompts about a report that no longer says what they point
            # at, and this field is read-only here, so nothing could take them back down.
            if report.suggested_prompts:
                report.suggested_prompts = []
                update_fields.append("suggested_prompts")

        if update_fields:
            # `updated_at` is auto_now, but `update_fields` saves only the listed columns, so add it
            # explicitly to keep the edit timestamped.
            update_fields.append("updated_at")
            # This text has not been through the safety judge, and the report's existing verdict was
            # reached on the text this edit replaces. Marking the save retracts the report's embedding
            # rather than indexing unreviewed content under a stale approval (see receivers.py).
            report._unreviewed_edit = True  # type: ignore[attr-defined]
            with transaction.atomic():
                report.save(update_fields=update_fields)
                for content in edit_artefacts:
                    SignalReportArtefact.add_log(
                        team_id=self.team.id,
                        report_id=str(report.id),
                        content=content,
                        attribution=attribution,
                    )
            # The prefetch predates these edits, so the response would mark a now-stale score fresh.
            report.__dict__.pop("prefetched_latest_edit_artefacts", None)
        return Response(SignalReportSerializer(report, context=self._enriched_report_context(report)).data)

    @validated_request(
        query_serializer=SignalReportListQuerySerializer,
        responses={200: SignalReportListSerializer},
        parameters=_REPORT_LIST_PARAMETERS,
    )
    @tracer.start_as_current_span("signals.reports.list")
    def list(self, request: ValidatedRequest, *args, **kwargs):
        count_only: bool = request.validated_query_data["count_only"]
        include_source_metadata: bool = request.validated_query_data["include_source_metadata"]
        excluded = request.validated_query_data["exclude"]
        if count_only:
            # A count orders nothing, so it must not record a flag exposure for the ranker.
            self._inbox_ranker = None
        with trial_state_errors():
            store = trial_store_for_request(request, self.team_id)
            if store is not None:
                # Private trial reads compare against the priority order, never a flag arm.
                self._inbox_ranker = None
                return TrialInboxReads(self, store).list(
                    count_only=count_only, include_source_metadata=include_source_metadata
                )
        # The reports list is the primary inbox-load endpoint. Each phase gets its own child span
        # so a slow load can be attributed to Postgres (queryset annotations), ClickHouse (source
        # products), the task facade (PR urls), or serialization, rather than one opaque request.
        list_span = trace.get_current_span()
        list_span.set_attribute(
            "signals.reports.list.client", classify_report_list_client(request.headers.get("user-agent"))
        )
        list_span.set_attribute("signals.reports.list.count_only", count_only)
        list_span.set_attribute("signals.reports.list.include_source_metadata", include_source_metadata)
        list_span.set_attribute("signals.reports.list.cached_filters", self._inbox_cached_filters)

        with tracer.start_as_current_span("signals.reports.list.queryset"):
            queryset = self.filter_queryset(self.get_queryset())
            if excluded:
                queryset = queryset.exclude(id__in=excluded)
            if count_only:
                total_count = queryset.count()
            else:
                page = self.paginate_queryset(queryset)
                reports = list(page if page is not None else queryset)

        if count_only:
            list_span.set_attribute("signals.reports.list.total_count", total_count)
            self._capture_list_ranking_usage(total_count)
            return Response({"count": total_count, "next": None, "previous": None, "results": []})

        report_ids = [str(r.id) for r in reports]
        list_span.set_attribute("signals.reports.list.count", len(report_ids))
        if page is not None:
            page_limit = getattr(self.paginator, "limit", None)
            page_offset = getattr(self.paginator, "offset", None)
            total_count = getattr(self.paginator, "count", None)
            if isinstance(page_limit, int):
                list_span.set_attribute("signals.reports.list.page_limit", page_limit)
            if isinstance(page_offset, int):
                list_span.set_attribute("signals.reports.list.page_offset", page_offset)
            if isinstance(total_count, int):
                list_span.set_attribute("signals.reports.list.total_count", total_count)
                if isinstance(page_offset, int):
                    list_span.set_attribute(
                        "signals.reports.list.has_next_page", page_offset + len(report_ids) < total_count
                    )

        data = self._render_report_rows(reports, include_source_metadata=include_source_metadata)
        self._capture_list_ranking_usage(total_count if page is not None else len(reports))

        if page is not None:
            response = self.get_paginated_response(data)
            response.data["ranker"] = self._inbox_ranker
            return response
        return Response(data)

    def _capture_list_ranking_usage(self, result_count: int | None) -> None:
        if classify_report_list_client(self.request.headers.get("user-agent")) in {"web", "desktop"}:
            # The inbox clients capture their own list loads with the sort and the ranker.
            return
        raw_ordering = self.request.query_params.get("ordering") or ""
        ordering_outcomes = sorted(
            {
                _OUTCOME_BY_MODEL_HEAD.get(RANKING_ORDERING_HEADS[name], "internal")
                for name in (part.strip().removeprefix("-") for part in raw_ordering.split(","))
                if name in RANKING_ORDERING_HEADS
            }
        )
        min_lift = self._parse_ranking_minimums("ranking_min_lift")
        min_probability = self._parse_ranking_minimums("ranking_min_probability")
        if not (ordering_outcomes or self._inbox_ranker or min_lift or min_probability):
            return
        self._capture_ranking_usage(
            "list",
            ordering_outcomes=ordering_outcomes,
            min_lift=min_lift,
            min_probability=min_probability,
            result_count=result_count,
        )

    def _capture_ranking_usage(
        self,
        endpoint: Literal["list", "ranking_outcomes"],
        *,
        ordering_outcomes: Sequence[str] | None = None,
        min_lift: dict[str, float] | None = None,
        min_probability: dict[str, float] | None = None,
        ranking_status: str | None = None,
        result_count: int | None = None,
    ) -> None:
        # The properties describe the request only. They never carry report content.
        report_user_action(
            self.request.user,
            "signals_inbox_ranking_used",
            properties={
                "team_id": self.team_id,
                "surface": "mcp" if is_mcp_request(self.request) else "api",
                "endpoint": endpoint,
                "ordering_outcomes": ordering_outcomes or [],
                "ranker": self._inbox_ranker if endpoint == "list" else None,
                "min_lift": min_lift or {},
                "min_probability": min_probability or {},
                "ranking_status": ranking_status,
                "result_count": result_count,
            },
            team=self.team,
            request=self.request,
        )

    def _render_report_rows(
        self, reports: Sequence[SignalReport], *, include_source_metadata: bool
    ) -> Sequence[dict[str, object]]:
        """Serialize report rows the way the inbox list does, with batched lookups instead of per-row queries."""
        report_ids = [str(report.id) for report in reports]
        # Source metadata is decorative. The serializer degrades to empty values when ClickHouse is
        # unavailable, so a metadata failure does not hide otherwise available reports. The web inbox
        # opts out and loads it after the rows render, so the page does not wait on ClickHouse.
        signal_meta_map: dict[str, ReportSignalMeta] = {}
        if include_source_metadata and report_ids:
            with tracer.start_as_current_span("signals.reports.list.fetch_source_products"):
                try:
                    signal_meta_map = fetch_source_products_for_reports(self.team, report_ids)
                except Exception:
                    logger.exception("signals.reports.list.source_products_failed", report_count=len(report_ids))

        with tracer.start_as_current_span("signals.reports.list.fetch_implementation_prs"):
            try:
                pull_requests_map = fetch_implementation_prs_for_reports(report_ids, team_id=self.team_id)
            except Exception:
                logger.exception("signals.reports.list.implementation_pr_failed", report_count=len(report_ids))
                pull_requests_map = {}

        # One grouped query for the whole page, in place of the per-row annotation the other
        # actions carry, for the serializer's refund_ineligibility_reason field.
        with tracer.start_as_current_span("signals.reports.list.fetch_billable_pr_runs"):
            first_billable_pr_run_at_map = first_billable_pr_run_at_by_report(report_ids, team_id=self.team_id)

        # Same trade for the two artefact-derived fields the row renders: one query each over the
        # page, rather than a correlated subquery the sort makes Postgres run for every report in
        # the team. The serializer reads both off the instance, as it does for the other actions.
        with tracer.start_as_current_span("signals.reports.list.fetch_artefact_fields"):
            artefact_counts = SignalReportArtefact.counts_by_report(
                report_ids, monitoring_enabled=self._report_monitoring_enabled
            )
            live_channel_ids = SignalReportArtefact.live_channel_ids_by_report(report_ids)
            for report in reports:
                report.__dict__.update(
                    artefact_count=artefact_counts.get(str(report.id), 0),
                    channel_id=live_channel_ids.get(str(report.id)),
                )
        claims = get_active_claims(team_id=self.team_id, report_ids=report_ids)
        context = {
            **self.get_serializer_context(),
            "source_products_map": {rid: meta.source_products for rid, meta in signal_meta_map.items()},
            "scout_names_map": {rid: meta.scout_name for rid, meta in signal_meta_map.items() if meta.scout_name},
            **self._claim_and_pull_request_context(report_ids, pull_requests_map, claims),
            "first_billable_pr_run_at_map": first_billable_pr_run_at_map,
            "inbox_ranker": self._inbox_ranker,
        }
        serializer = self.get_serializer(reports, many=True, context=context)

        with tracer.start_as_current_span("signals.reports.list.serialize"):
            return serializer.data

    @extend_schema(
        summary="List the org members who can be suggested as reviewers",
        parameters=[
            OpenApiParameter(
                name="query",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Case-insensitive filter on name or email. Use search to find members outside the first 100 results.",
            )
        ],
        # A map keyed by user UUID, so there is no serializer shape to declare.
        responses={
            200: OpenApiResponse(
                response={
                    "type": "object",
                    "additionalProperties": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Member's full name."},
                            "email": {"type": "string", "description": "Member's email address."},
                        },
                        "required": ["name", "email"],
                    },
                },
                description="Up to 100 candidate reviewers keyed by user UUID.",
            )
        },
    )
    @action(detail=False, methods=["get"], url_path="available_reviewers", required_scopes=["task:read"])
    def available_reviewers(self, request, **kwargs):
        with tracer.start_as_current_span("signals.available_reviewers") as span:
            # Search all org members, not only the GitHub-linked ones: a reviewer is a PostHog user,
            # so a teammate who never connected GitHub is still pickable — and can pick themselves.
            query = (request.query_params.get("query") or "").strip().lower()
            users_by_uuid = (
                search_org_member_users_by_uuid(
                    self.team.id,
                    query=query,
                    limit=AVAILABLE_REVIEWERS_LIMIT,
                )
                or {}
            )

            reviewers = {
                user_uuid: {
                    "name": f"{user.first_name} {user.last_name}".strip(),
                    "email": user.email or "",
                }
                for user_uuid, user in users_by_uuid.items()
            }

            span.set_attribute("signals.available_reviewers.result_count", len(reviewers))

            return Response(reviewers)

    @extend_schema(
        summary="Set a report's suggested reviewers",
        request=SignalReportArtefactWriteSerializer,
        responses={200: SignalReportSuggestedReviewersArtefactSerializer},
    )
    @action(detail=True, methods=["put"], url_path="reviewers", required_scopes=["task:write"])
    def reviewers(self, request, **kwargs):
        """Apply a human reviewer edit, including on reports without a reviewer artefact."""
        report = cast(SignalReport, self.get_object())

        write_serializer = SignalReportArtefactWriteSerializer(data=request.data)
        write_serializer.is_valid(raise_exception=True)
        entries = write_serializer.validated_data.get("targets", write_serializer.validated_data["content"])

        try:
            new_artefact = append_suggested_reviewers(
                team=self.team,
                report_id=str(report.id),
                entries=entries,
                request=request,
                edit=ReviewerEdit(
                    action=write_serializer.validated_data["action"],
                    expected_state=write_serializer.validated_data.get("expected_reviewers"),
                ),
                removal_reason=write_serializer.validated_data.get("removal_reason"),
                removal_note=write_serializer.validated_data.get("removal_note"),
            )
        except StaleReviewerProposal as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
        except ReviewerWriteError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        # Return the read-shape (enriched) so the client sees the canonical result, matching the artefact PUT.
        read_serializer = SignalReportSuggestedReviewersArtefactSerializer(
            new_artefact, context=self.get_serializer_context()
        )
        return Response(read_serializer.data)

    @extend_schema(
        methods=["DELETE"],
        summary="Step off a report's suggested reviewers",
        description=(
            "Take the calling user off this report's suggested reviewers, leaving the other reviewers "
            "as they are. The report itself is untouched: it stays open for whoever is left, and for "
            "the project. Succeeds whether or not the caller was on the list. POST to the same path to "
            "say why."
        ),
        request=None,
        responses={
            204: OpenApiResponse(description="The caller is no longer a suggested reviewer."),
            400: OpenApiResponse(description="A reviewer who stays no longer resolves to a member of this team."),
        },
    )
    @extend_schema(
        methods=["POST"],
        summary="Step off a report's suggested reviewers, with a reason",
        description=(
            "Take the calling user off this report's suggested reviewers, and record why. The other reviewers "
            "stay, and the report stays open. Succeeds whether or not the caller was on the list."
        ),
        request=SignalReportLeaveReviewersSerializer,
        responses={
            204: OpenApiResponse(description="The caller is no longer a suggested reviewer."),
            400: OpenApiResponse(description="The reason is invalid, or a reviewer who stays no longer resolves."),
        },
    )
    @action(detail=True, methods=["delete", "post"], url_path="reviewers/me", required_scopes=["task:write"])
    def leave_reviewers(self, request, **kwargs):
        report = cast(SignalReport, self.get_object())
        removal = SignalReportLeaveReviewersSerializer(data=request.data if request.method == "POST" else {})
        removal.is_valid(raise_exception=True)
        scoped_team_ids = get_authenticator_scoped_team_ids(request.successful_authenticator)
        try:
            remove_suggested_reviewer(
                team=self.team,
                report_id=str(report.id),
                user=cast(User, request.user),
                scoped_team_ids=tuple(scoped_team_ids) if scoped_team_ids is not None else None,
                was_impersonated=is_impersonated_session(request),
                removal_reason=removal.validated_data.get("removal_reason"),
                removal_note=removal.validated_data.get("removal_note"),
            )
        except StaleReviewerProposal as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
        except ReviewerWriteError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(status=status.HTTP_204_NO_CONTENT)

    def destroy(self, request, *args, **kwargs):
        """Soft-delete a report and its signals via the deletion workflow."""
        report = cast(SignalReport, self.get_object())
        report_id = str(report.id)
        team_id = self.team.id

        try:
            client = sync_connect()
            async_to_sync(client.start_workflow)(  # type: ignore
                "signal-report-deletion",  # type: ignore
                SignalReportDeletionWorkflowInputs(team_id=team_id, report_id=report_id),  # type: ignore
                id=SignalReportDeletionWorkflow.workflow_id_for(team_id, report_id),
                task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
                execution_timeout=timedelta(minutes=30),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
        except WorkflowAlreadyStartedError:
            return Response({"status": "already_running", "report_id": report_id}, status=status.HTTP_200_OK)
        except Exception:
            logger.exception("Failed to start deletion workflow for report %s", report_id)
            return Response(
                {"error": "Failed to start deletion workflow."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # Hide the report from the list immediately while signal deletion continues asynchronously.
        updated_fields = report.transition_to(SignalReport.Status.DELETED)
        report._transition_actor = self._request_attribution()  # type: ignore[attr-defined]
        report.save(update_fields=updated_fields)

        return Response({"status": "deletion_started", "report_id": report_id}, status=status.HTTP_202_ACCEPTED)

    @extend_schema(
        summary="List a report's signals",
        description="Fetch all signals for a report from ClickHouse, including full metadata.",
        responses={200: ReportSignalsResponseSerializer},
    )
    @action(detail=True, methods=["get"], url_path="signals", required_scopes=["task:read"])
    def signals(self, request, pk=None, **kwargs):
        """Fetch all signals for a report from ClickHouse, including full metadata."""
        with trial_state_errors():
            store = trial_store_for_request(request, self.team_id)
            if store is not None:
                private = store.get_report(str(pk))
                if private is not None:
                    document = TrialInboxReads(self, store).detail(str(pk))
                    evidence = fetch_signals_for_report_sync(self.team, str(pk)) if private.source_report_id else []
                    return Response(
                        ReportSignalsResponseSerializer(
                            {"report": document, "signals": [*evidence, *private.evidence]}
                        ).data
                    )
        report = self.get_object()
        report_data = SignalReportSerializer(report, context=self._enriched_report_context(report)).data
        signals_list = fetch_signals_for_report_sync(self.team, str(report.id))
        return Response(ReportSignalsResponseSerializer({"report": report_data, "signals": signals_list}).data)

    @extend_schema(
        request=SignalReportStateRequestSerializer,
        responses={200: SignalReportSerializer},
    )
    @action(detail=True, methods=["post"], url_path="state", required_scopes=["task:write"])
    def state(self, request, pk=None, **kwargs):
        """
        Transition a report to a new state. The model validates allowed transitions, except that a
        verdict the report already holds (dismissing a suppressed report, resolving a resolved one)
        is a 200 that records the dismissal feedback without touching the status.

        The request body is validated by SignalReportStateRequestSerializer — only the
        fields it declares (state, dismissal_reason, dismissal_note, corrected_repository,
        snooze_for) are read, and only snooze_for is ever forwarded to transition_to. Any
        other key is ignored, so internal transition_to kwargs (reset_weight, error, ...)
        can't be injected.

        Body: {
            "state": "suppressed" | "potential" | "resolved",
            # Optional dismissal feedback (honored when state == "suppressed", "potential", or "resolved"):
            "dismissal_reason": "<canonical reason code, see SIGNAL_REPORT_DISMISSAL_REASON_CHOICES>",
            "dismissal_note": "free-form text",
            # Optional, only allowed with dismissal_reason == "wrong_repo":
            "corrected_repository": "owner/repo the report should have targeted",
            # Optional, only honored for state == "potential":
            "snooze_for": <number of additional signals before re-promotion>,
        }
        """
        report = cast(SignalReport, self.get_object())

        serializer = SignalReportStateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        outcome, detail = self._transition_report_state(
            report,
            target=data["state"],
            dismissal_reason=data.get("dismissal_reason"),
            dismissal_note=data.get("dismissal_note"),
            corrected_repository=data.get("corrected_repository"),
            snooze_for=data.get("snooze_for"),
        )

        if outcome == SignalReportBulkStateOutcome.SKIPPED:
            return Response(
                {"error": detail or "Invalid state transition for this report."},
                status=status.HTTP_409_CONFLICT,
            )
        if outcome == SignalReportBulkStateOutcome.FAILED:
            return Response(
                {"error": detail or "Invalid data for state transition."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        self._forward_dismissal_note(
            reports=[report],
            dismissal_reason=data.get("dismissal_reason"),
            dismissal_note=data.get("dismissal_note"),
        )
        self._remove_wrong_assignee(
            reports=[report],
            dismissal_reason=data.get("dismissal_reason"),
            dismissal_note=data.get("dismissal_note"),
        )
        self._capture_background_dismissals(
            reports=[report] if getattr(report, "_newly_suppressed", False) else [],
            target=data["state"],
            dismissal_reason=data.get("dismissal_reason"),
        )

        return Response(SignalReportSerializer(report, context=self._enriched_report_context(report)).data)

    @validated_request(
        request_serializer=SignalReportMergeRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=SignalReportMergeResponseSerializer,
                description="The surviving report after the merge, plus one result per merged source.",
            ),
            404: OpenApiResponse(description="The surviving report was not found in this project."),
            409: OpenApiResponse(
                description=(
                    "Both ends of a merge must be a live report of this project. Returned when "
                    "the survivor is resolved, or when a source is the survivor itself, is resolved "
                    "or archived, is still being researched, carries more signals than one merge "
                    "can move, or belongs to another project. Nothing is applied."
                )
            ),
        },
        summary="Merge duplicate reports into this one",
        description=(
            "Fold one or more duplicate reports into this report, which survives. The sources' "
            "signals, work-log artefacts, pull requests, task runs and checks move onto the "
            "survivor, the survivor's signal counters take on theirs, and each source is archived "
            "with a 'duplicate of' link back to the survivor. A source's open pull request stays "
            "open, because the survivor holds it after the move. Pick the survivor deliberately: "
            "prefer the older report, and prefer the one with an open implementation PR or an "
            "active claim. Any active claim on a source is released, so re-claim the survivor if "
            "you were working on one. Titles and summaries are not combined, so edit it afterwards "
            "if it needs a rewrite. A merged report keeps its URL but cannot be restored, because "
            "its signals now belong to the survivor."
        ),
        operation_id="signals_reports_merge_create",
    )
    @action(detail=True, methods=["post"], url_path="merge", required_scopes=["task:write"])
    def merge(self, request: ValidatedRequest, pk=None, **kwargs):
        survivor = cast(SignalReport, self.get_object())
        data = request.validated_data
        # Resolved before the merge transaction, so a bad X-PostHog-Task-Id header 400s before
        # anything moves (the same rule as the refund and artefact write paths).
        attribution = resolve_request_attribution(request, self.team.id)

        try:
            result = merge_reports(
                team=self.team,
                survivor=survivor,
                source_ids=[str(source_id) for source_id in data["source_report_ids"]],
                attribution=attribution,
                reason=(data.get("reason") or "").strip() or None,
            )
        except ReportMergeError as e:
            return Response({"error": e.detail}, status=status.HTTP_409_CONFLICT)

        report_user_action(
            request.user,
            "signals_report_merged",
            properties={
                "team_id": self.team.id,
                "organization_id": str(self.organization.id),
                "report_id": result.survivor_id,
                "actor_kind": attribution.kind,
                "task_id": attribution.task_id,
                "scout_skill_name": result.scout_skill_name,
                "source_count": len(result.sources),
                "released_claim_count": sum(1 for source in result.sources if source.released_claim),
                "signals_moved": sum(source.signals_moved for source in result.sources),
            },
            team=self.team,
            organization=self.organization,
            request=request,
        )

        survivor.refresh_from_db()
        return Response(
            SignalReportMergeResponseSerializer(
                {"report": survivor, "sources": result.sources},
                context=self._enriched_report_context(survivor),
            ).data
        )

    @staticmethod
    def _task_action_error(
        code: str, detail: str, status_code: int, *, task_id: str | None = None, run_id: str | None = None
    ) -> Response:
        body: dict[str, str] = {"code": code, "detail": detail}
        if task_id is not None and run_id is not None:
            body |= {"task_id": task_id, "run_id": run_id}
        return Response(SignalReportTaskActionErrorSerializer(body).data, status=status_code)

    @extend_schema(
        responses={200: SignalReportTaskActionListResponseSerializer},
        summary="List the report actions that start an agent run",
        description=(
            "List the actions on this report that start an agent run, read from the report's current state. "
            "`get_it_merged` is available only while the report has an open, approved pull request. "
            "`make_it_green` is available only while CI fails on the report's open pull request. "
            "`suggested_prompt` has one entry per prompt the report suggests. Start one with the run endpoint."
        ),
        operation_id="signals_reports_actions_list",
    )
    @action(detail=True, methods=["get"], url_path="actions", required_scopes=["task:read"])
    def task_actions(self, request: Request, *args, **kwargs) -> Response:
        report = cast(SignalReport, self.get_object())
        context = ReportTaskActionContext(team=self.team, user=cast(User, request.user))
        actions = list_report_task_actions(context, report)
        return Response(
            SignalReportTaskActionListResponseSerializer(
                {
                    "results": [
                        {
                            "action": item.kind.value,
                            "available": item.available,
                            "disabled_reason": item.disabled_reason,
                            "suggested_prompt_index": item.suggested_prompt_index,
                            "text": item.question,
                        }
                        for item in actions
                    ]
                }
            ).data
        )

    @validated_request(
        request_serializer=SignalReportTaskActionRunRequestSerializer,
        responses={
            201: OpenApiResponse(response=SignalReportTaskActionRunResponseSerializer, description="Task created"),
            400: OpenApiResponse(
                response=SignalReportTaskActionErrorSerializer,
                description="The action is not available on this report now (code `report_action_unavailable`)",
            ),
            402: OpenApiResponse(
                description="The organization is on a Self-driving free trial (code `self_driving_free_trial`)"
            ),
            403: OpenApiResponse(
                response=SignalReportTaskActionErrorSerializer,
                description="AI data processing is not approved, or the request came from a task sandbox",
            ),
            404: OpenApiResponse(description="The report has no suggested prompt at that index"),
            409: OpenApiResponse(
                response=SignalReportTaskActionErrorSerializer,
                description=(
                    "A run is already working on this report's pull request (code `report_action_run_active`). "
                    "The body carries its `task_id` and `run_id`."
                ),
            ),
            429: OpenApiResponse(
                response=SignalReportTaskActionErrorSerializer,
                description=(
                    "The report reached its task limit (code `signal_report_task_cap`), the per-user creation "
                    "limit fired (code `throttled`), or the organization reached its usage limit or is deactivated"
                ),
            ),
        },
        summary="Start a report action as a background agent run",
        description=(
            "Create a task linked to the report and start its first run in the background, with the "
            "instructions the inbox uses for the same action. `ask` sends your own message with the framing "
            "of the inbox's Ask AI. The run shows in the report's runs and counts "
            "toward the report's task limit. Nobody can answer questions in a background run, so the agent "
            "writes a note to the report's work log when it needs a decision."
        ),
        operation_id="signals_reports_actions_run_create",
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="actions/run",
        required_scopes=["task:write"],
        throttle_classes=[ReportTaskActionRunBurstThrottle, ReportTaskActionRunSustainedThrottle],
    )
    def run_task_action(self, request: ValidatedRequest, *args, **kwargs) -> Response:
        if is_sandbox_origin_request(request):
            return self._task_action_error(
                "report_action_sandbox_refused",
                "A task sandbox cannot start report actions.",
                status.HTTP_403_FORBIDDEN,
            )
        report = cast(SignalReport, self.get_object())
        user = cast(User, request.user)
        context = ReportTaskActionContext(team=self.team, user=user)
        data = request.validated_data
        kind = ReportTaskActionKind(data["action"])
        state = ReportActionState.read(report)
        report_action = resolve_report_task_action(
            context, report, kind, data.get("suggested_prompt_index"), state=state, message=data.get("message")
        )
        if report_action is None:
            raise exceptions.NotFound("This report has no suggested prompt at that index.")

        def capture(outcome: str, limit_code: str | None = None) -> None:
            report_user_action(
                user,
                INBOX_REPORT_ACTION_EVENT,
                inbox_report_action_properties(
                    report, report_action, outcome=outcome, state=state, limit_code=limit_code
                ),
                team=self.team,
                organization=self.organization,
                request=request,
            )

        if report_action.disabled_reason is not None:
            capture("blocked")
            error_status: int = (
                status.HTTP_403_FORBIDDEN
                if report_action.disabled_reason == AI_CONSENT_DISABLED_REASON
                else status.HTTP_400_BAD_REQUEST
            )
            return self._task_action_error("report_action_unavailable", report_action.disabled_reason, error_status)

        if kind in (ReportTaskActionKind.GET_IT_MERGED, ReportTaskActionKind.MAKE_IT_GREEN) and (
            active := active_pull_request_run(team_id=self.team.id, report_id=str(report.id))
        ):
            capture("limited", "report_action_run_active")
            return self._task_action_error(
                "report_action_run_active",
                PULL_REQUEST_RUN_ACTIVE_DETAIL,
                status.HTTP_409_CONFLICT,
                task_id=active.task_id,
                run_id=active.run_id,
            )

        if limit_response := usage_limit_response(user, self.team_id):
            capture("limited", "usage_limit")
            return self._task_action_error(
                str(limit_response.data["code"]), str(limit_response.data["error"]), limit_response.status_code
            )

        # The run starts repo-less unless the caller passes the Desktop gate, the same rule the tasks
        # create endpoint applies to an inbox discussion.
        code_access_allowed = code_access_required_response(request, self.organization) is None
        try:
            started = start_report_task_action(context, report, report_action, code_access_allowed=code_access_allowed)
        except ReportTaskCapExceeded as error:
            capture("limited", "signal_report_task_cap")
            return self._task_action_error("signal_report_task_cap", error.detail, status.HTTP_429_TOO_MANY_REQUESTS)
        except ReportTaskActionStartError as error:
            capture("failure")
            return self._task_action_error("report_action_start_failed", error.detail, status.HTTP_400_BAD_REQUEST)
        capture("failure" if started.run_error else "success")
        return Response(
            SignalReportTaskActionRunResponseSerializer(
                {
                    "task_id": started.task_id,
                    "run_id": started.run_id,
                    "task_url": started.task_url,
                    "run_error": started.run_error,
                }
            ).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(responses=SignalReportFeedbackStateSerializer)
    @action(detail=True, methods=["get"], required_scopes=["task:read"])
    def feedback_state(self, request: Request, pk=None, **kwargs) -> Response:
        report = self.get_object()
        metadata = (
            SignalReportAction.objects.for_team(self.team.id)
            .filter(report=report, user=cast(User, request.user), type=SignalReportAction.ActionType.FEEDBACK)
            .values_list("metadata", flat=True)
            .first()
        ) or {}
        return Response(
            SignalReportFeedbackStateSerializer(
                {"sentiment": metadata.get("sentiment"), "note": metadata.get("note", "")}
            ).data
        )

    @extend_schema(
        summary="Leave feedback on a report",
        description=(
            "Record the thumbs rating at the end of a report, with an optional note. For "
            "browser-session requests the rating is persisted as a per-person report action, which "
            "counts as consumption evidence for the scout that authored the report (scouts whose "
            "output nobody consumes are eventually paused); requests authenticated any other way "
            "record no action. When a note is present and the report was authored by a scout, the note is also "
            "forwarded to that scout as a steering note it reads on its next run; for any other report "
            "there is nothing to steer. The report's state is never changed."
        ),
        request=SignalReportFeedbackRequestSerializer,
        responses={200: SignalReportFeedbackResponseSerializer},
    )
    @action(detail=True, methods=["post"], url_path="feedback", required_scopes=["task:read"])
    def feedback(self, request, pk=None, **kwargs):
        """Persist a report's thumbs rating and forward its note to the authoring scout.

        Feedback-only: unlike `state`, this never transitions the report. Note forwarding is
        best-effort and never fails the request; the action row is what the scout inactivity
        sweep reads as consumption evidence.
        """
        report = cast(SignalReport, self.get_object())

        serializer = SignalReportFeedbackRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        note = data["note"].strip()

        if _is_person_at_the_ui(request):
            # The inbox posts the bare rating on click and the optional note afterwards, so a
            # note-carrying request amends a rating the row already counted — bumping again
            # would record one thumb choice as two interactions.
            SignalReportAction.record(
                team_id=self.team.id,
                report_id=str(report.id),
                user_id=request.user.id,
                action_type=SignalReportAction.ActionType.FEEDBACK,
                metadata={"sentiment": data["sentiment"], **({"note": note} if note else {})},
                bump_count=not note and data["sentiment"] is not None,
            )
            if not note and data["sentiment"] is not None:
                capture_background_report_events(
                    team=self.team,
                    user=request.user,
                    event=BACKGROUND_REPORT_RATED_EVENT,
                    report_ids=[str(report.id)],
                    properties={"sentiment": data["sentiment"]},
                )

        if not note:
            return Response(SignalReportFeedbackResponseSerializer({"forwarded": False}).data)

        note_id = forward_feedback_note(
            team=self.team,
            report_id=str(report.id),
            sentiment=data["sentiment"],
            note=note,
            user_id=request.user.id if isinstance(request.user, User) else None,
            scoped_team_ids=get_authenticator_scoped_team_ids(request.successful_authenticator),
            api_scopes=get_authenticator_scopes(request.successful_authenticator),
        )
        return Response(SignalReportFeedbackResponseSerializer({"forwarded": note_id is not None}).data)

    @extend_schema(
        summary="Record that a person viewed a report",
        description=(
            "Record that the caller opened this report's detail view. One row per person per report is "
            "kept (repeat views bump a counter), and the record counts as consumption evidence for the "
            "scout that authored the report — scouts whose reports nobody consumes are eventually "
            "paused. Intended as fire-and-forget from the inbox UI when a person opens a report. Only "
            "browser-session requests leave a record; a call with any other credential (personal API "
            "key, OAuth token) returns 204 but records nothing."
        ),
        request=None,
        responses={204: None},
    )
    # task:read, not task:write: recording that someone read a report is part of reading it.
    # Under resource-level RBAC a `:write` scope demands editor access, which would 403 the
    # viewer-level members whose reads this endpoint exists to capture. Token automation is
    # already excluded by the session-authentication gate, not by scope.
    @action(detail=True, methods=["post"], url_path="viewed", required_scopes=["task:read"])
    def viewed(self, request, pk=None, **kwargs):
        """Upsert a per-person view record for the report.

        Only session-authenticated callers leave a record; any other credential is a silent
        no-op (204, nothing written), since the row exists to prove a person looked.
        """
        report = cast(SignalReport, self.get_object())
        if _is_person_at_the_ui(request):
            SignalReportAction.record(
                team_id=self.team.id,
                report_id=str(report.id),
                user_id=request.user.id,
                action_type=SignalReportAction.ActionType.VIEW,
            )
            capture_background_report_events(
                team=self.team, user=request.user, event=BACKGROUND_REPORT_VIEWED_EVENT, report_ids=[str(report.id)]
            )
        return Response(status=status.HTTP_204_NO_CONTENT)

    # `list` names the viewset's own action inside the class body, so the annotations use `Sequence`.
    def _refreshable_reports_in_request_order(self, requested_ids: Sequence[str]) -> Sequence[SignalReport]:
        by_id = {
            str(report.id): report
            for report in self.get_queryset().filter(id__in=requested_ids, status__in=CURRENT_REPORT_STATUSES)
        }
        return [by_id[report_id] for report_id in dict.fromkeys(requested_ids) if report_id in by_id]

    @validated_request(
        request_serializer=SignalReportMetricRefreshRequestSerializer,
        responses={200: OpenApiResponse(response=SignalReportMetricRefreshResponseSerializer)},
        summary="Refresh the saved metric snapshots of the reports on screen",
        description=(
            "Re-run the stored metric queries of the given reports through the query cache and save "
            "the newest values as their snapshots. Call it when a person opens the inbox list or a "
            "report, with the ids on screen. Report titles and summaries are point-in-time text and "
            "never change here; only value, value_at, and series do, and legacy comparisons are cleared. "
            "A snapshot measured in the last "
            "15 minutes is served as is. Each call runs at most 40 source series inside a 20-second "
            "budget, row metrics first; the rest keep their previous snapshot until the next open. "
            "Returns snapshot-only metrics for every requested report the caller can read whose status "
            "is ready or pending_input. A report in any other status is left out of the response, and "
            "its saved snapshots stay as they are."
        ),
        operation_id="signals_reports_refresh_metrics_create",
    )
    # task:read, like `viewed`: refreshing a number a person is looking at is part of reading it,
    # and the write is a cache of query output rather than report content.
    @action(
        detail=False,
        methods=["post"],
        url_path="refresh_metrics",
        required_scopes=["task:read"],
        throttle_classes=[
            ReportMetricRefreshThrottle,
            ClickHouseBurstRateThrottle,
            ClickHouseSustainedRateThrottle,
        ],
    )
    def refresh_metrics(self, request: ValidatedRequest, **kwargs) -> Response:
        requested_ids = [str(report_id) for report_id in request.validated_data["report_ids"]]
        reports = self._refreshable_reports_in_request_order(requested_ids)
        policy = ReportMetricAccessPolicy(request=request, team=self.team)
        refresh_report_metric_snapshots(team=self.team, reports=reports, policy=policy)
        # A refresh runs its queries between the read above and each compare-and-swap, and an edit
        # landing in that window wins. Read the rows back so the response carries what the edit
        # left rather than the state this request measured against.
        serializer = SignalReportMetricRefreshResponseSerializer(
            {"reports": self._refreshable_reports_in_request_order(requested_ids)},
            context=self.get_serializer_context(),
        )
        return Response(serializer.data)

    @validated_request(
        request_serializer=SignalReportSourceMetadataRequestSerializer,
        responses={200: OpenApiResponse(response=SignalReportSourceMetadataResponseSerializer)},
        summary="Get the source products and authoring scout of the reports on screen",
        description=(
            "Read which source products contributed signals to each given report, and which scout "
            "authored it. These values come from ClickHouse, so the inbox list skips them "
            "(`include_source_metadata=false`) and calls this after the rows render. Returns one entry "
            "per requested id. An id with no signals in this project gets empty values."
        ),
        operation_id="signals_reports_source_metadata_create",
    )
    # POST, like `refresh_metrics`, so a page of ids never has to fit in a URL.
    @action(
        detail=False,
        methods=["post"],
        url_path="source_metadata",
        required_scopes=["task:read"],
        throttle_classes=[ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle],
    )
    @tracer.start_as_current_span("signals.reports.source_metadata")
    def source_metadata(self, request: ValidatedRequest, **kwargs) -> Response:
        # No Postgres read: the signal store is scoped to this team, so an id from another project
        # matches no rows and comes back empty.
        report_ids = list(dict.fromkeys(str(report_id) for report_id in request.validated_data["report_ids"]))
        signal_meta_map = fetch_source_products_for_reports(self.team, report_ids)
        empty = ReportSignalMeta(source_products=[], scout_name=None)
        serializer = SignalReportSourceMetadataResponseSerializer(
            {
                "reports": [
                    {
                        "id": report_id,
                        "source_products": signal_meta_map.get(report_id, empty).source_products,
                        "scout_name": signal_meta_map.get(report_id, empty).scout_name,
                    }
                    for report_id in report_ids
                ]
            }
        )
        return Response(serializer.data)

    def _capture_background_dismissals(
        self, *, reports: Sequence[SignalReport], target: str, dismissal_reason: str | None
    ) -> None:
        if target != SignalReport.Status.SUPPRESSED or not reports:
            return
        capture_background_report_events(
            team=self.team,
            user=self.request.user if isinstance(self.request.user, User) else None,
            event=BACKGROUND_REPORT_DISMISSED_EVENT,
            report_ids=[str(report.id) for report in reports],
            properties={"dismissal_reason": dismissal_reason},
        )

    def _forward_dismissal_note(
        self,
        *,
        # `Sequence`, not `list`: this class defines a `list` action, which shadows the builtin for
        # annotations evaluated in the class body at import time.
        reports: Sequence[SignalReport],
        dismissal_reason: str | None,
        dismissal_note: str | None,
    ) -> None:
        """Leave the caller's dismissal note where scout runs actually read it.

        Called once per request with every report that transitioned, so one note applied to a bulk
        dismissal reaches each affected scout once instead of once per report. Runs after the
        transitions have committed, because the note is derived context and the `dismissal` artefact
        written alongside each transition remains the record of the feedback. Forwarding resolves
        the reports' resulting status itself, drops the transitions this channel has nothing to say
        about, and authorizes the caller against the scout-note write gates, so this call site only
        hands it the request's principal.
        """
        forward_dismissal_note(
            team=self.team,
            reports=reports,
            reason=dismissal_reason,
            note=dismissal_note,
            request=self.request,
        )

    def _remove_wrong_assignee(
        self,
        *,
        reports: Sequence[SignalReport],
        dismissal_reason: str | None,
        dismissal_note: str | None,
    ) -> None:
        """Take the caller off the reviewers of reports they dismissed as sent to the wrong person.

        The dismissal note reaches only the scout that filed the report, while research reads the
        reviewer corrections. The same verdict therefore also lands as a removal with a reason. The
        dismissal has already committed, so a failed removal is logged and not raised.
        """
        if dismissal_reason != DISMISSAL_REASON_WRONG_ASSIGNEE or not reports:
            return
        user = cast(User, self.request.user)
        login = user.get_github_login()
        # One indexed read keeps a bulk dismissal from running the removal for reports that never named the caller.
        named = {
            str(row["report_id"])
            for row in report_ids_naming_reviewers(
                team_id=self.team.id,
                user_uuids=[str(user.uuid)],
                github_logins=[login.lower()] if login else [],
                logins_match_unidentified_only=False,
            ).filter(report_id__in=[report.id for report in reports])
        }
        if not named:
            return
        scoped_team_ids = get_authenticator_scoped_team_ids(self.request.successful_authenticator)
        was_impersonated = is_impersonated_session(self.request)
        note = (dismissal_note or "").strip()[: SignalReportArtefactWriteSerializer.REMOVAL_NOTE_MAX_LENGTH] or None
        for report in reports:
            if str(report.id) not in named:
                continue
            try:
                remove_suggested_reviewer(
                    team=self.team,
                    report_id=str(report.id),
                    user=user,
                    scoped_team_ids=tuple(scoped_team_ids) if scoped_team_ids is not None else None,
                    was_impersonated=was_impersonated,
                    removal_reason=ReviewerRemovalReason.WRONG_AREA,
                    removal_note=note,
                    # The dismissal already sent each scout one note for the whole batch, so a bulk
                    # request does not add one correction note per report on top of it.
                    forward_note=len(reports) == 1,
                )
            except (StaleReviewerProposal, ReviewerWriteError, NotFound):
                logger.warning("signals.wrong_assignee_removal_failed", team_id=self.team.id, report_id=str(report.id))
            except Exception:
                logger.exception(
                    "signals.wrong_assignee_removal_failed", team_id=self.team.id, report_id=str(report.id)
                )

    def _request_attribution(self) -> ArtefactAttribution:
        """Attribution for this request, resolved once and reused.

        `resolve_request_attribution` validates the `X-PostHog-Task-Id` header with a DB lookup, and
        both the request and the team are invariant across a call — so bulk_state, which transitions
        up to the per-call id cap in a loop, would otherwise repeat the identical query per report.
        """
        if not hasattr(self, "_cached_request_attribution"):
            self._cached_request_attribution = resolve_request_attribution(self.request, self.team.id)
        return self._cached_request_attribution

    def _latest_selected_repository(self, report_id: str) -> str | None:
        """The repository named by the report's latest repo_selection artefact, if any."""
        artefact = (
            SignalReportArtefact.objects.filter(
                report_id=report_id, type=SignalReportArtefact.ArtefactType.REPO_SELECTION
            )
            .order_by("-created_at")
            .first()
        )
        if artefact is None:
            return None
        try:
            return RepoSelectionResult.model_validate_json(artefact.content).repository
        except PydanticValidationError:
            # Legacy or malformed rows degrade to "unknown" rather than failing the dismissal.
            return None

    def _connected_repositories(self) -> set[str]:
        """Lowercased 'owner/repo' names connected to this team, cached for the request.

        Cached because bulk_state calls the transition helper per report, and the underlying
        lookup reads the integration's cached repository list.
        """
        if not hasattr(self, "_cached_connected_repositories"):
            from products.tasks.backend.facade.repo_selection import (  # noqa: PLC0415 — keeps repo-selection agent imports off the API import path
                list_team_connected_repositories,
            )

            self._cached_connected_repositories = set(list_team_connected_repositories(self.team.id))
        return self._cached_connected_repositories

    def _apply_wrong_repo_selection(self, report: SignalReport, corrected_repository: str | None) -> None:
        """Persist a wrong-repo dismissal onto the report's repo_selection history, latest-wins.

        Research reuses the report's newest repo_selection whenever it names a repository, so a
        wrong-repo dismissal must not leave the rejected pick as that newest row. A correction
        naming a connected repository becomes the new selection: the report's next research run
        (once new signals re-promote it; restore itself does not re-research) targets it. Any
        other wrong-repo dismissal (no correction named, or the named repository not connected;
        research clones through the team integration, so an unconnected target would guarantee a
        clone failure) clears the selection instead, so the next run re-selects from scratch with
        the corrections feed in its prompt rather than reusing the rejected pick. The correction
        itself is recorded on the dismissal artefact either way.
        """
        corrected_and_connected = (
            corrected_repository is not None and corrected_repository in self._connected_repositories()
        )
        if not corrected_and_connected and self._latest_selected_repository(str(report.id)) is None:
            # Nothing to clear: with no reusable selection, the next run re-selects anyway.
            return
        if corrected_and_connected:
            content = RepoSelectionResult(
                repository=corrected_repository,
                reason="A reviewer dismissed this report as targeting the wrong repository and named this one instead.",
                # A correction names the repo a person would target; it never signals PR intent, so
                # it must not outrank an earlier selection's False stamp on the autostart path.
                autostart_eligible=False,
            )
        else:
            content = RepoSelectionResult(
                repository=None,
                reason=(
                    "A reviewer dismissed this report as targeting the wrong repository; "
                    "the selection is cleared so the next research run picks again."
                ),
                autostart_eligible=False,
            )
        SignalReportArtefact.append_status(
            team_id=self.team.id,
            report_id=str(report.id),
            content=content,
            attribution=self._request_attribution(),
        )

    def _transition_report_state(
        self,
        report: SignalReport,
        *,
        target: str,
        dismissal_reason: str | None,
        dismissal_note: str | None,
        snooze_for: int | None,
        corrected_repository: str | None = None,
    ) -> "tuple[SignalReportBulkStateOutcome, str | None]":
        """
        Apply one report state transition (plus optional dismissal artefact) and return a
        compact `(outcome, detail)` pair — `detail` is a caller-facing explanation for
        non-transitioned outcomes when the generic per-outcome message isn't enough. Shared by
        the single `state` action and the bulk `bulk_state` action so both honour the same
        restore/snooze semantics and transition guards. Expected invalid transitions are
        returned as outcomes (never raised) so a bulk run can record a per-id result and keep
        going.

        Only `snooze_for` (on a snooze back to "potential") is caller-controllable. Every other
        `transition_to` kwarg (signals_at_run_increment, reset_weight, title, summary, error) is an
        internal pipeline concern and must never be reachable from this public API surface, so it is
        passed explicitly rather than splatting caller-supplied kwargs.

        `corrected_repository` (validated upstream: wrong_repo dismissals only) is recorded on the
        dismissal artefact; a wrong-repo dismissal also rewrites the report's newest repo_selection
        artefact — the corrected repository when connected, cleared otherwise; see
        `_apply_wrong_repo_selection`.
        """
        target_status = SignalReport.Status(target)
        if target_status == SignalReport.Status.MONITORING and not self._report_monitoring_enabled:
            return SignalReportBulkStateOutcome.SKIPPED, "Monitoring is unavailable for this organization."

        # Release the delivery lock after commit so workers cannot read the previous verdict.
        with ExitStack() as completion_locks, transaction.atomic():
            # Lock the report row for the whole guard + transition so it serializes with the refund
            # path (which locks the same row before suppressing). Re-read committed state under the
            # lock: a resolve/restore that raced a refund must observe the refund's SUPPRESSED status
            # and refund row and refuse, instead of overwriting the suppression and re-opening
            # already-refunded work.
            if (
                SignalReport.objects.select_for_update(no_key=True).filter(id=report.id, team_id=self.team.id).first()
                is not None
            ):
                report.refresh_from_db()
            if (
                SignalReportMonitoringAttempt.objects.for_team(self.team.id)
                .filter(
                    report_id=report.id,
                    tracker_issue_close_requested_at__isnull=False,
                    tracker_issue_close_processed_at__isnull=True,
                )
                .exists()
            ):
                acquired = completion_locks.enter_context(
                    tracker_issue_completion_lock(team_id=self.team.id, report_id=str(report.id))
                )
                if not acquired:
                    return (
                        SignalReportBulkStateOutcome.SKIPPED,
                        "This report is being finalized. Try again in a moment.",
                    )
            if dismissal_reason == "verified_manually" and (
                not self._report_monitoring_enabled
                or report.monitoring_started_at is None
                or not (
                    report.status in {SignalReport.Status.MONITORING, SignalReport.Status.RESOLVED}
                    or (
                        report.status == SignalReport.Status.SUPPRESSED
                        and report.status_before_suppression == SignalReport.Status.MONITORING
                    )
                )
            ):
                return (
                    SignalReportBulkStateOutcome.SKIPPED,
                    "Manual verification requires an enabled Monitoring period.",
                )
            is_refunded = SignalReportRefund.objects.filter(report_id=report.id).exists()

            # Refund guard: a refunded report can never be billed again (see billing.py), so putting
            # it back where the pipeline can pick it up again is repeatable free work. POTENTIAL is
            # the live status — a potential report re-promotes to candidate on new signals and can
            # spawn a fresh research run (grouping.py). The refund is final, so any transition of a
            # refunded report back to POTENTIAL is refused, whether it currently sits in SUPPRESSED
            # (refund's own archive step) or in RESOLVED (a refunded merged-PR report stays resolved,
            # so the guard can't key on SUPPRESSED alone). RESOLVED is terminal and never re-promotes,
            # so resolving a refunded report is refused only out of the archive, to keep the refund's
            # suppression — and the PR close it triggers — from being undone.
            if is_refunded and (
                target_status == SignalReport.Status.POTENTIAL
                or (
                    report.status == SignalReport.Status.SUPPRESSED
                    and target_status in {SignalReport.Status.RESOLVED, SignalReport.Status.MONITORING}
                )
            ):
                return SignalReportBulkStateOutcome.SKIPPED, "Refunded reports can't be restored."

            # A merged report has no signals of its own left: they moved to the survivor, and
            # so did its work log. Restoring it would put an empty duplicate back in the inbox
            # and start it collecting again alongside the report it was folded into.
            if (
                report.status == SignalReport.Status.SUPPRESSED
                and target_status
                in {SignalReport.Status.POTENTIAL, SignalReport.Status.RESOLVED, SignalReport.Status.MONITORING}
                and was_merged_away(report)
            ):
                return (
                    SignalReportBulkStateOutcome.SKIPPED,
                    "This report was merged into another one and can't be restored. Open the report it was "
                    "merged into instead.",
                )

            # Archiving must not grant a transition the report couldn't make directly. "Any
            # non-deleted status can be suppressed", so without this a report could be laundered
            # through the archive into RESOLVED from candidate/in_progress with no title or summary.
            # A suppressed report may
            # only resolve when it was in a directly-resolvable status before being archived.
            # Deliberately narrower than restore_target_status()'s researched set, which exists to
            # answer "where does restore put this report back", not "may it resolve".
            if (
                report.status == SignalReport.Status.SUPPRESSED
                and target_status == SignalReport.Status.RESOLVED
                and report.status_before_suppression
                not in _RESOLVABLE_STATUSES_BEFORE_SUPPRESSION | {SignalReport.Status.MONITORING}
            ):
                return (
                    SignalReportBulkStateOutcome.SKIPPED,
                    "Only a report that was ready, awaiting input, failed, or already resolved when it was "
                    "archived can be resolved from the archive.",
                )

            # "potential" on a suppressed report means "restore" (un-archive): return it to the state
            # it held before suppression when that was a researched, user-visible report, instead of
            # always dropping back to potential.
            effective_target = target_status
            if report.status == SignalReport.Status.SUPPRESSED and target_status == SignalReport.Status.POTENTIAL:
                if snooze_for is not None or dismissal_reason == "already_fixed":
                    return (
                        SignalReportBulkStateOutcome.SKIPPED,
                        "This report is archived. Refresh it before continuing.",
                    )
                effective_target = report.restore_target_status()

            if target_status == SignalReport.Status.MONITORING and report.status != SignalReport.Status.MONITORING:
                try:
                    complete_implementation(
                        team_id=self.team.id,
                        report_id=report.id,
                        monitoring_started_at=timezone.now(),
                        attribution=self._request_attribution(),
                        actor_user=self.request.user if isinstance(self.request.user, User) else None,
                        close_pr_on_resolve=True,
                    )
                except (InvalidStatusTransition, ValueError):
                    return SignalReportBulkStateOutcome.SKIPPED, None
                report.refresh_from_db()
                return SignalReportBulkStateOutcome.TRANSITIONED, None

            effective_snooze_for = snooze_for if target == "potential" else None

            # A verdict the report already holds is honoured, not refused: the open detail view lags
            # the server once GitHub closes the PR (webhook suppresses the report), and that click
            # still carries feedback for the agent. Skipping the save keeps every receiver quiet, so
            # no second PR close is queued. A repeat restore carries no feedback, so it stays a 409.
            already_holds_verdict = target_status == report.effective_status and target_status in (
                SignalReport.Status.SUPPRESSED,
                SignalReport.Status.RESOLVED,
                SignalReport.Status.MONITORING,
            )

            stopping_monitoring = (
                target_status == SignalReport.Status.RESOLVED
                and not already_holds_verdict
                and self._report_monitoring_enabled
                and (
                    report.status == SignalReport.Status.MONITORING
                    or (
                        report.status == SignalReport.Status.SUPPRESSED
                        and report.status_before_suppression == SignalReport.Status.MONITORING
                    )
                )
            )
            writes_dismissal_feedback = target in ("suppressed", "potential", "resolved") and bool(
                dismissal_reason or dismissal_note or stopping_monitoring
            )
            feedback_state = (
                None
                if report.status == SignalReport.Status.SUPPRESSED and target == "potential"
                else cast(Literal["resolved", "suppressed", "potential"], target)
            )

            if not already_holds_verdict:
                try:
                    updated_fields = report.transition_to(effective_target, snooze_for=effective_snooze_for)
                except InvalidStatusTransition as e:
                    logger.warning("Invalid status transition for SignalReport %s: %s", report.id, e, exc_info=True)
                    return SignalReportBulkStateOutcome.SKIPPED, None
                except (ValueError, TypeError) as e:
                    logger.warning("Invalid data when transitioning SignalReport %s: %s", report.id, e, exc_info=True)
                    return SignalReportBulkStateOutcome.FAILED, None

                if stopping_monitoring:
                    for check in (
                        SignalReportCheck.objects.for_team(self.team.id)
                        .filter(report_id=report.id, status__in=SignalReportCheck.OPEN_STATUSES)
                        .order_by("id")
                    ):
                        cancel_check(check, reason="stopped_by_person", attribution=self._request_attribution())

                # Tell the status-changed receiver that this transition carries caller-supplied feedback,
                # so the label picks up the artefact written just below. Set before the save because the
                # post_save receiver snapshots it there. Matters most for resolve: a resolve driven by
                # the PR-merge webhook has no feedback, and only this flag distinguishes the two.
                report._wrote_dismissal_feedback = writes_dismissal_feedback  # type: ignore[attr-defined]
                # A resolve through this API says the work is done without the inbox PR, so that PR is
                # superseded and the receiver closes it. The PR-merge webhook resolves through
                # transition_to directly and never sets this, so a merged PR is left alone.
                report._close_pr_on_resolve = target_status == SignalReport.Status.RESOLVED  # type: ignore[attr-defined]
                # Name the caller in the status-change label and in the comments the receiver leaves
                # on the linked pull request and tracker issue. An external agent keeps its user
                # principal, so it names the person who ran it rather than nobody.
                report._transition_actor = self._request_attribution()  # type: ignore[attr-defined]
                report._transition_actor_user = self.request.user  # type: ignore[attr-defined]
                # Read under the row lock, so two concurrent dismissals count as one new suppression.
                report._newly_suppressed = target_status == SignalReport.Status.SUPPRESSED  # type: ignore[attr-defined]

                report.save(update_fields=updated_fields)

                if stopping_monitoring:
                    SignalReportArtefact.add_log(
                        team_id=self.team.id,
                        report_id=str(report.id),
                        content=NoteArtefact(
                            note="Monitoring stopped manually. Automatic verification and an evidence amendment were not performed."
                        ),
                        attribution=self._request_attribution(),
                    )

            # Persist the dismissal feedback as its own artefact so it survives status changes
            # and so multiple dismissals (with different rationales) can stack over time.
            # Captured for suppress, snooze (transition to potential), and resolve flows — on a
            # resolve it records why the report was resolved with user attribution.
            if writes_dismissal_feedback or (
                target_status == SignalReport.Status.SUPPRESSED and not already_holds_verdict
            ):
                user = self.request.user
                is_authenticated = getattr(user, "is_authenticated", False)
                user_uuid = getattr(user, "uuid", None) if is_authenticated else None
                is_wrong_repo = dismissal_reason == DISMISSAL_REASON_WRONG_REPO
                # Denormalized so a wrong-repo dismissal is self-contained: the correction feed reads
                # which repo was wrong straight off this artefact instead of joining the repo_selection
                # history at selection time. Shape-checked because the persisted repo_selection value is
                # unconstrained (writable through the generic artefacts API) while this field is capped,
                # so an oversized or malformed value degrades to unknown rather than failing the dismissal.
                selected_repository = (
                    sanitized_repository(self._latest_selected_repository(str(report.id))) if is_wrong_repo else None
                )
                # A connected correction becomes the report's newest selection, so a repeat wrong-repo
                # dismissal reads that correction back here. Recording it as the rejected pick would
                # claim the reviewer rejected the repository they just named: the scout note would say
                # "do not pick it again" about the correction, and the selection prompt would render a
                # lesson that contradicts itself. Record the selection as unknown, so both keep the
                # half that is true.
                if selected_repository is not None and selected_repository == sanitized_repository(
                    corrected_repository
                ):
                    selected_repository = None
                SignalReportArtefact.append_dismissal(
                    team_id=self.team.id,
                    report_id=str(report.id),
                    content=Dismissal(
                        state=feedback_state,
                        reason=dismissal_reason,
                        note=dismissal_note,
                        selected_repository=selected_repository,
                        corrected_repository=corrected_repository if is_wrong_repo else None,
                        user_id=getattr(user, "id", None) if is_authenticated else None,
                        user_uuid=str(user_uuid) if user_uuid else None,
                    ),
                    attribution=self._request_attribution(),
                )
                if target_status == SignalReport.Status.RESOLVED and dismissal_reason == "no_action_needed":
                    for check in SignalReportCheck.objects.for_team(self.team.id).filter(
                        report_id=report.id, status__in=SignalReportCheck.OPEN_STATUSES
                    ):
                        cancel_check(check, reason="stopped_by_person", attribution=self._request_attribution())
                if is_wrong_repo:
                    self._apply_wrong_repo_selection(report, corrected_repository)
                    # The wrong-repo path just wrote a new repo_selection artefact; drop the
                    # stale prefetch so a follow-up serializer reads the corrected/cleared slug.
                    if hasattr(report, "prefetched_repo_selection_artefacts"):
                        del report.prefetched_repo_selection_artefacts
                # The dismissal prefetch may have been evaluated before this artefact
                # existed; drop the stale cache so a follow-up serializer re-reads the
                # just-written reason/note instead of the previous (or empty) dismissal.
                if hasattr(report, "prefetched_dismissal_artefacts"):
                    del report.prefetched_dismissal_artefacts
                if already_holds_verdict:
                    capture_verdict_reason_added_analytics(report)

        # A dismissal (transition into SUPPRESSED) or a resolve closes the linked implementation PR —
        # handled centrally by the post_save receiver (receivers.close_pr_when_report_dismissed), so
        # this method doesn't special-case it. Restore/snooze to "potential" leaves the PR alone.
        return SignalReportBulkStateOutcome.TRANSITIONED, None

    @extend_schema(
        request=SignalReportBulkStateRequestSerializer,
        responses={200: SignalReportBulkStateResponseSerializer},
    )
    # nosemgrep: api-path-underscore -- shipped public API path, a rename breaks clients
    @action(detail=False, methods=["post"], url_path="bulk-state", required_scopes=["task:write"])
    def bulk_state(self, request, **kwargs):
        """
        Transition many reports to a new state in one call.

        Each id is processed independently: a report whose transition isn't allowed from its
        current status is reported as `skipped` (a 409 on the single-report endpoint) and the
        rest still go through. Returns one result per requested id (in request order, after
        de-duplication) plus per-outcome counts. The whole call is 200 even on partial failure —
        inspect `results` / the counts to see what happened.
        """
        serializer = SignalReportBulkStateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        target = data["state"]
        dismissal_reason = data.get("dismissal_reason")
        dismissal_note = data.get("dismissal_note")
        corrected_repository = data.get("corrected_repository")
        snooze_for = data.get("snooze_for")

        # De-duplicate while preserving request order so the response lines up with what was asked.
        ordered_ids: list[str] = []
        seen: set[str] = set()
        for raw_id in data["ids"]:
            key = str(raw_id)
            if key not in seen:
                seen.add(key)
                ordered_ids.append(key)

        # One team-scoped fetch for every requested report. get_queryset() scopes to the team and
        # excludes deleted reports; suppressed reports are reachable because bulk_state is in
        # _SUPPRESSED_VISIBLE_ACTIONS, so bulk restore (state='potential') works too.
        reports_by_id = {str(report.id): report for report in self.get_queryset().filter(id__in=ordered_ids)}

        results: list[dict] = []
        counts: dict[str, int] = {outcome.value: 0 for outcome in SignalReportBulkStateOutcome}
        transitioned: list[SignalReport] = []
        newly_dismissed: list[SignalReport] = []
        for report_id in ordered_ids:
            report = reports_by_id.get(report_id)
            if report is None:
                outcome = SignalReportBulkStateOutcome.NOT_FOUND
                detail = None
                report_status = None
            else:
                outcome, detail = self._transition_report_state(
                    report,
                    target=target,
                    dismissal_reason=dismissal_reason,
                    dismissal_note=dismissal_note,
                    corrected_repository=corrected_repository,
                    snooze_for=snooze_for,
                )
                report_status = (
                    report.effective_status if outcome == SignalReportBulkStateOutcome.TRANSITIONED else None
                )
                if outcome == SignalReportBulkStateOutcome.TRANSITIONED:
                    transitioned.append(report)
                    if getattr(report, "_newly_suppressed", False):
                        newly_dismissed.append(report)
            results.append(
                {
                    "id": report_id,
                    "outcome": outcome.value,
                    "status": report_status,
                    "detail": detail or self._BULK_STATE_OUTCOME_DETAIL.get(outcome),
                }
            )
            counts[outcome.value] += 1

        self._forward_dismissal_note(
            reports=transitioned,
            dismissal_reason=dismissal_reason,
            dismissal_note=dismissal_note,
        )
        self._remove_wrong_assignee(
            reports=transitioned,
            dismissal_reason=dismissal_reason,
            dismissal_note=dismissal_note,
        )
        self._capture_background_dismissals(reports=newly_dismissed, target=target, dismissal_reason=dismissal_reason)

        return Response(
            {
                "results": results,
                "transitioned_count": counts[SignalReportBulkStateOutcome.TRANSITIONED.value],
                "skipped_count": counts[SignalReportBulkStateOutcome.SKIPPED.value],
                "failed_count": counts[SignalReportBulkStateOutcome.FAILED.value],
                "not_found_count": counts[SignalReportBulkStateOutcome.NOT_FOUND.value],
            }
        )

    @validated_request(
        request_serializer=SignalReportBulkClaimRequestSerializer,
        responses={200: OpenApiResponse(response=SignalReportBulkClaimResponseSerializer)},
        summary="Claim many signal reports",
        description=(
            "Claim many reports for the current user, internal task, or external agent in one call. Each id is "
            "claimed independently, and the call is 200 even when some claims are refused: inspect `results` "
            "and the counts. Use the single-report claim endpoint to release a claim or to add pull requests."
        ),
        operation_id="signals_reports_bulk_claim",
    )
    @action(detail=False, methods=["post"], url_path="bulk_claim", required_scopes=["task:write"])
    def bulk_claim(self, request: ValidatedRequest, *args: object, **kwargs: object) -> Response:
        data = request.validated_data
        ordered_ids = list(dict.fromkeys(str(raw_id) for raw_id in data["ids"]))
        reports_by_id = {str(report.id): report for report in self.get_queryset().filter(id__in=ordered_ids)}
        actor = self._request_attribution()
        claims = get_active_claims(team_id=self.team.id, report_ids=list(reports_by_id))
        user = cast(User, request.user)
        was_impersonated = is_impersonated_session(request)

        results: list[dict] = []
        counts: dict[str, int] = {outcome.value: 0 for outcome in SignalReportBulkClaimOutcome}
        for report_id in ordered_ids:
            report = reports_by_id.get(report_id)
            detail: str | None = None
            if report is None:
                outcome = SignalReportBulkClaimOutcome.NOT_FOUND
                detail = "No report with this id is visible to you."
            else:
                claim = claims.get(report_id)
                # The expected claim id makes the server refuse the takeover when a person claims the
                # report between the read above and this write.
                takeover_claim_id = (
                    str(claim.claim_id)
                    if data["takeover_agent_claims"]
                    and claim is not None
                    and claim.actor_kind in (SignalActorKind.AGENT, SignalActorKind.TASK)
                    and not actor_works_under_claim(claim, actor)
                    else None
                )
                try:
                    claim_report(
                        report=report,
                        actor=actor,
                        user=user,
                        was_impersonated=was_impersonated,
                        takeover=takeover_claim_id is not None,
                        takeover_claim_id=takeover_claim_id,
                    )
                    outcome = SignalReportBulkClaimOutcome.CLAIMED
                except ReportClaimConflict as err:
                    outcome = SignalReportBulkClaimOutcome.CONFLICT
                    detail = str(err)
            results.append({"id": report_id, "outcome": outcome.value, "detail": detail})
            counts[outcome.value] += 1

        return Response(
            {
                "results": results,
                "claimed_count": counts[SignalReportBulkClaimOutcome.CLAIMED.value],
                "conflict_count": counts[SignalReportBulkClaimOutcome.CONFLICT.value],
                "not_found_count": counts[SignalReportBulkClaimOutcome.NOT_FOUND.value],
            }
        )

    def _signals_pr_refunds_enabled(self) -> bool:
        # Server-side feature gate, keyed on the org (the refund window is the org's billing
        # period). Same call shape as the quota-limiting data-retention flag check.
        return (
            posthoganalytics.feature_enabled(
                SIGNALS_PR_REFUNDS_FEATURE_FLAG,
                str(self.organization.id),
                groups={"organization": str(self.organization.id)},
                group_properties={"organization": {"id": str(self.organization.id)}},
            )
            is True
        )

    def _refund_response(self, refund: SignalReportRefund, *, already_refunded: bool = False) -> Response:
        if already_refunded:
            # SignalReportRefundResponseSerializer reads the attribute; absent it falls back to
            # the field default (False), so only the idempotent-replay path sets it.
            refund.already_refunded = True  # type: ignore[attr-defined]
        return Response(SignalReportRefundResponseSerializer(refund).data)

    @validated_request(
        request_serializer=SignalReportRefundRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=SignalReportRefundResponseSerializer,
                description=(
                    "The refund (created, or the existing one with already_refunded=true when the "
                    "report was refunded before)."
                ),
            ),
            400: OpenApiResponse(
                description=(
                    "Report is not refundable: no billable implementation PR, the PR run is outside "
                    "the current billing period, or the report is system-marked never-billable."
                )
            ),
            404: OpenApiResponse(description="Report not found, or refunds are not enabled for this organization."),
        },
        summary="Refund a report's implementation PR",
        description=(
            "Refund the flat charge for this report's implementation PR and archive the report. "
            "Refunds auto-approve: the charge is either excluded from usage before it is ever "
            "reported to billing (refund on the same UTC day as the PR run) or returned as a Stripe "
            "customer-balance credit on the next invoice. A refunded PR does not count toward the "
            "free monthly PR allowance. One refund per report, ever — repeat calls return the "
            "existing refund with already_refunded=true. The report is archived as part of the "
            "refund (a resolved report stays resolved) and can't be restored afterwards."
        ),
        operation_id="signals_reports_refund_create",
    )
    @action(detail=True, methods=["post"], url_path="refund", required_scopes=["task:write"])
    def refund(self, request: ValidatedRequest, pk=None, **kwargs):
        if not self._signals_pr_refunds_enabled():
            raise NotFound("PR refunds are not enabled for this organization.")

        report = cast(SignalReport, self.get_object())
        data = request.validated_data
        note = data.get("note") or ""
        # Resolved before the locked transaction — a bad X-PostHog-Task-Id header must 400
        # before anything mutates (mirrors the artefact write paths).
        attribution = resolve_request_attribution(request, self.team.id)
        user = cast(User, request.user)

        with transaction.atomic():
            # Row-lock the report so double-clicks serialize (precedent: the Slack suppression
            # flow); the refund OneToOne is the backstop if something bypasses the lock.
            report = cast(
                SignalReport,
                SignalReport.objects.select_for_update().get(id=report.id, team_id=self.team_id),
            )

            existing = getattr(report, "refund", None)
            if existing is not None:
                return self._refund_response(existing, already_refunded=True)

            # Same decision the serializer's `refund_ineligibility_reason` field renders from,
            # so the UI's button state and this endpoint's 400s can never disagree.
            billable_run = first_billable_pr_run(report.id, team_id=report.team_id)
            # Computed once and frozen onto the refund row below: the credited-path sync must
            # report the period the refund was accepted in, not whatever period is current when
            # the Celery task eventually reaches billing.
            period = current_billing_period_bounds(self.organization)
            ineligibility = refund_ineligibility_reason(
                has_refund=False,  # the idempotent 200 above already handled existing refunds
                billing_exempt=bool(report.billing_exempt_reason),
                billable_run_at=billable_run.created_at if billable_run else None,
                period=period,
            )
            if ineligibility is not None:
                return Response(
                    {"error": _REFUND_INELIGIBLE_MESSAGES[ineligibility]},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            assert billable_run is not None  # narrowed by the no_billable_pr reason above

            # Freeze the billing path by the UTC-day rule: refunds committed on the PR run's own
            # UTC day land before any usage send covering that day (all sends happen ≥3h45m into
            # the next UTC day), so the report can simply be excluded from usage; anything later
            # must go through a billing-service credit. Decided once, stored, never recomputed.
            now = timezone.now()
            # Derived from the persisted merge flag, not the report status: a report can be resolved
            # manually without a merged PR, so RESOLVED no longer implies the PR shipped. Asked about
            # the PR being refunded specifically — it's that PR the refund reverses the charge for,
            # and that PR which has to be closed if it never merged.
            pr_merged = report_pr_is_merged(report.id, billable_run.pr_url, team_id=self.team_id)
            billing_path = (
                SignalReportRefund.BillingPath.EXCLUDED
                if billable_run.created_at.astimezone(UTC).date() == now.astimezone(UTC).date()
                else SignalReportRefund.BillingPath.CREDITED
            )

            try:
                # Savepoint so a unique-constraint loser doesn't poison the outer transaction.
                with transaction.atomic():
                    refund = SignalReportRefund.objects.create(
                        team_id=report.team_id,
                        report=report,
                        created_by=user if user.is_authenticated else None,
                        reason=data["reason"],
                        note=note,
                        billing_path=billing_path,
                        credits=SIGNALS_CREDITS_PER_REPORT_WITH_PR,
                        pr_url=billable_run.pr_url,
                        pr_run_created_at=billable_run.created_at,
                        period_start=period.start,
                        period_end=period.end,
                    )
            except IntegrityError:
                existing = SignalReportRefund.objects.filter(report_id=report.id).first()
                if existing is None:
                    raise
                return self._refund_response(existing, already_refunded=True)

            # Refund doubles as archive: suppress the report so it leaves the inbox, and so the
            # dismissal receiver closes the implementation PR that was paid for and then refunded.
            # The one exception is a report resolved by a merged PR: that PR shipped, so the report
            # stays put as a genuine terminal state and there is no open PR to close. A report
            # resolved manually without a merged PR is NOT exempt — its PR may still be open, and
            # leaving it resolved would let the caller keep the implementation work after the refund.
            # Already-suppressed reports need no transition. The dismissal artefact records the
            # rationale; the structured truth lives on the refund row.
            resolved_via_merged_pr = report.effective_status == SignalReport.Status.RESOLVED and pr_merged
            if report.status != SignalReport.Status.SUPPRESSED and not resolved_via_merged_pr:
                updated_fields = report.transition_to(SignalReport.Status.SUPPRESSED)
                report._transition_actor = attribution  # type: ignore[attr-defined]
                report.save(update_fields=updated_fields)
            SignalReportArtefact.append_dismissal(
                team_id=self.team.id,
                report_id=str(report.id),
                content=Dismissal(
                    state="resolved" if resolved_via_merged_pr else "suppressed",
                    reason="refunded",
                    note=note or None,
                    user_id=user.id if user.is_authenticated else None,
                    user_uuid=str(user.uuid) if user.is_authenticated else None,
                ),
                attribution=attribution,
            )

            if billing_path == SignalReportRefund.BillingPath.CREDITED:
                refund_id = str(refund.id)
                transaction.on_commit(lambda: sync_signals_refund_credit.delay(refund_id))

        # A refund suppresses the report, which is a judgement the authoring scout should hear, so it
        # forwards on the same channel as any other dismissal. `refund.reason` rather than the
        # `refunded` code the artefact records, because `pr_incorrect` tells a scout the PR missed
        # what its report promised while `refunded` only says money moved. Outside the atomic block
        # because forwarding writes rows of its own and must not be able to roll back the refund it
        # reports; a report left RESOLVED by a merged PR is dropped by the forwarding path itself.
        self._forward_dismissal_note(
            reports=[report],
            dismissal_reason=refund.reason,
            dismissal_note=note,
        )

        report_user_action(
            user,
            "signals_pr_refund_created",
            properties={
                "team_id": self.team.id,
                "organization_id": str(self.organization.id),
                "report_id": str(report.id),
                "refund_id": str(refund.id),
                "billing_path": billing_path,
                "credits": refund.credits,
                "reason": refund.reason,
                "pr_merged": pr_merged,
                "days_since_pr": (now - billable_run.created_at).days,
            },
            team=self.team,
            organization=self.organization,
            request=request,
        )

        return self._refund_response(refund)

    @extend_schema(
        responses={
            200: OpenApiResponse(
                response=SignalReportRefundSummaryResponseSerializer,
                description="Org-wide credited-refund totals for the current billing period.",
            ),
            404: OpenApiResponse(description="Refunds are not enabled for this organization."),
        },
        summary="Summarize credited PR refunds for the billing period",
        description=(
            "Aggregate credited-path refunds across the whole organization for the current billing "
            "period — counts only, no per-team detail. The billing usage widget needs this because "
            "billing usage is org-wide while reports (and their refunds) are team-scoped: subtract "
            "the refunded credits from billing usage to show the net PR count. Excluded-path "
            "refunds never reach billing usage, so no adjustment is needed for them. Also carries "
            "the org's live billable credits for the period (billing's recorded usage lags by up "
            "to a day), so the widget can count just-created PRs and react to same-day refunds."
        ),
        operation_id="signals_reports_refund_summary_retrieve",
    )
    # nosemgrep: api-path-underscore -- shipped public API path, a rename breaks clients
    @action(detail=False, methods=["get"], url_path="refund-summary", required_scopes=["task:read"])
    def refund_summary(self, request: Request, **kwargs):
        # Two independent flags can each make this endpoint matter: refunds (the netting numbers)
        # and quota enforcement (`quota_limited` drives the widget's paused banner, and enforcement
        # can roll out before refunds). Gating on refunds alone would hide the paused state for
        # enforcement-only orgs.
        if not (self._signals_pr_refunds_enabled() or self_driving_quota_enforcement_enabled(self.team)):
            raise NotFound("PR refunds are not enabled for this organization.")

        period = current_billing_period_bounds(self.organization)
        aggregates = (
            # Org-wide on purpose (unscoped + org filter): the usage this offsets is org-level.
            SignalReportRefund.objects.unscoped()
            .filter(
                team__organization_id=self.organization.id,
                billing_path=SignalReportRefund.BillingPath.CREDITED,
                pr_run_created_at__gte=period.start,
                pr_run_created_at__lt=period.end,
            )
            .aggregate(credited_refund_count=Count("id"), credited_credits=Sum("credits"))
        )
        return Response(
            {
                "credited_refund_count": aggregates["credited_refund_count"] or 0,
                "credited_credits": aggregates["credited_credits"] or 0,
                "period_billable_credits": period_billable_credits_for_org(self.organization.id, period=period),
                "quota_limited": self_driving_quota_gate(self.team).enforced,
            }
        )

    @extend_schema(
        summary="Re-ingest a report's signals",
        request=None,
        responses={
            200: OpenApiResponse(
                response=SignalReportReingestionStatusSerializer, description="A re-ingestion is already running."
            ),
            202: OpenApiResponse(response=SignalReportReingestionStatusSerializer, description="Re-ingestion started."),
        },
    )
    @action(detail=True, methods=["post"], url_path="reingest", required_scopes=["task:write"])
    def reingest(self, request, pk=None, **kwargs):
        """Re-ingest a report's signals (same team access as other report actions)."""
        report = cast(SignalReport, self.get_object())
        report_id = str(report.id)
        team_id = self.team.id

        try:
            client = sync_connect()
            async_to_sync(client.start_workflow)(  # type: ignore
                "signal-report-reingestion",  # type: ignore
                SignalReportReingestionWorkflowInputs(team_id=team_id, report_id=report_id),  # type: ignore
                id=SignalReportReingestionWorkflow.workflow_id_for(team_id, report_id),
                task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
                execution_timeout=timedelta(minutes=30),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
        except WorkflowAlreadyStartedError:
            return Response({"status": "already_running", "report_id": report_id}, status=status.HTTP_200_OK)
        except Exception:
            logger.exception("Failed to start reingestion workflow for report %s", report_id)
            return Response(
                {"error": "Failed to start reingestion workflow."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response({"status": "reingestion_started", "report_id": report_id}, status=status.HTTP_202_ACCEPTED)

    def _resolve_report_pr_reference(self, report: SignalReport) -> tuple[str, int] | None:
        """Resolve a report's implementation PR to ``(owner/repo, pr_number)``, or None if it has none
        (or the stored URL isn't a parseable GitHub PR URL)."""
        prs = fetch_implementation_prs_for_reports([str(report.id)], team_id=report.team_id).get(str(report.id), [])
        requested_id = self.request.query_params.get("pull_request_id")
        if requested_id:
            pr = next((pr for pr in prs if pull_request_matches_id(pr, requested_id, report.team_id)), None)
            if pr is None:
                raise NotFound("Pull request is not linked to this report.")
        else:
            pr = primary_pull_request(prs) if prs else None
        if pr is None:
            return None
        parsed = GitHubIntegration.parse_pull_request_url(pr.url)
        if parsed is None:
            return None
        return parsed.repository, parsed.number

    @extend_schema(
        parameters=[_PULL_REQUEST_ID_PARAMETER],
        responses={
            200: OpenApiResponse(
                response=PullRequestChecksResponseSerializer,
                description="The CI checks on the report's implementation pull request.",
            ),
            404: OpenApiResponse(
                description="Report has no implementation PR, or no GitHub integration can access it."
            ),
            403: OpenApiResponse(
                response=PullRequestChecksPermissionErrorSerializer,
                description="GitHub is connected without permission to read pull request checks.",
            ),
            502: OpenApiResponse(description="GitHub could not return the checks."),
            503: OpenApiResponse(description="The GitHub egress budget is temporarily unavailable."),
        },
        summary="Fetch CI checks for a report's implementation PR",
        description=(
            "Fetch the CI status (GitHub Actions check runs and legacy commit statuses) of the pull "
            "request attached to the report, via the team's GitHub integration."
        ),
        operation_id="signals_report_pr_checks",
    )
    @action(detail=True, methods=["get"], url_path="pr_checks", required_scopes=["task:read"])
    def pr_checks(self, request: Request, *args, **kwargs) -> Response:
        return self._pr_github_passthrough(
            cast(SignalReport, self.get_object()), "get_pull_request_checks", "checks", "checks"
        )

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "report_ids",
                OpenApiTypes.STR,
                description=(
                    "Comma-separated report UUIDs to resolve CI state for, at most "
                    f"{PR_CI_STATUS_MAX_REPORTS} per request."
                ),
                required=True,
            )
        ],
        responses={
            200: OpenApiResponse(
                response=PullRequestCiStatusesResponseSerializer,
                description="The CI rollup of each requested report's implementation pull request.",
            ),
            400: OpenApiResponse(description="`report_ids` is missing, not a list of UUIDs, or over the cap."),
        },
        summary="Fetch CI status for several reports' implementation PRs",
        description=(
            "Resolve the coarse CI rollup of the pull requests several reports opened, so a list of "
            "reports can show which pull requests are red without opening each report. One GitHub "
            "call covers the whole batch, and the answers are cached briefly and shared across "
            "callers. A report is left out when it has no open implementation pull request, and also "
            "when GitHub could not answer for it (no integration reaches the repository, a rate "
            "limit, an upstream failure), so a caller shows no CI state for it rather than an error. "
            "For the individual checks behind the rollup, use `pr_checks`."
        ),
        operation_id="signals_reports_pr_ci_statuses",
    )
    @action(detail=False, methods=["get"], url_path="pr_ci_statuses", required_scopes=["task:read"])
    def pr_ci_statuses(self, request: Request, **kwargs) -> Response:
        requested_ids = parse_pr_ci_status_report_ids(request.query_params.get("report_ids"))
        # Team-scoped via `get_queryset`, so an id belonging to another team resolves to nothing.
        # A report in a terminal status is dropped here rather than fetched: its pull request has been
        # closed or landed, so the pill reads "merged" or "closed" and the reader has nothing to act
        # on. This mirrors the frontend's `derivePrState`, which paints a glyph on an open pill only.
        report_ids = [
            str(report_id)
            for report_id, report_status in self.get_queryset().filter(id__in=requested_ids).values_list("id", "status")
            if report_status not in _PR_CI_STATUS_TERMINAL_REPORT_STATUSES | self._resolved_read_statuses()
        ]
        if not report_ids:
            return self._pr_ci_statuses_response([])

        try:
            prs_by_report = fetch_implementation_prs_for_reports(report_ids, team_id=self.team_id)
        except Exception:
            # Decorative metadata: a lookup failure must leave the list unpainted, not broken.
            logger.exception("signals.reports.pr_ci_statuses.implementation_pr_lookup_failed")
            return self._pr_ci_statuses_response([])

        references: dict[str, list[PullRequestRef]] = {}
        for report_id, prs in prs_by_report.items():
            references[report_id] = [
                parsed
                for pr in prs
                if not pr.merged and pr.state != "closed"
                if (parsed := GitHubIntegration.parse_pull_request_url(pr.url)) is not None
            ]

        statuses = pr_ci_statuses_for_references(self.team.id, [ref for refs in references.values() for ref in refs])
        rollups = [
            {"report_id": report_id, "ci_status": rollup}
            for report_id, refs in references.items()
            if (rollup := rollup_ci_status(refs, statuses)) is not None
        ]
        return self._pr_ci_statuses_response(rollups)

    @staticmethod
    # `list` names the viewset's own action inside the class body, so the annotation uses `Sequence`.
    def _pr_ci_statuses_response(statuses: Sequence[dict[str, str]]) -> Response:
        """Render the batch CI-status payload through its declared response serializer, so the wire
        shape cannot drift from the OpenAPI schema the frontend types and MCP tools are built from."""
        return Response(PullRequestCiStatusesResponseSerializer({"statuses": statuses}).data)

    @extend_schema(
        parameters=[_PULL_REQUEST_ID_PARAMETER],
        responses={
            200: OpenApiResponse(
                response=PullRequestCommentsResponseSerializer,
                description="Conversation and review comments on the report's implementation pull request.",
            ),
            404: OpenApiResponse(
                description="Report has no implementation PR, or no GitHub integration can access it."
            ),
            502: OpenApiResponse(description="GitHub could not return the comments."),
            503: OpenApiResponse(description="The GitHub egress budget is temporarily unavailable."),
        },
        summary="Fetch comments for a report's implementation PR",
        description=(
            "Fetch the pull request's conversation comments and inline review comments, merged "
            "chronologically, via the team's GitHub integration."
        ),
        operation_id="signals_report_pr_comments",
    )
    @action(detail=True, methods=["get"], url_path="pr_comments", required_scopes=["task:read"])
    def pr_comments(self, request: Request, *args, **kwargs) -> Response:
        return self._pr_github_passthrough(
            cast(SignalReport, self.get_object()), "get_pull_request_comments", "comments", "comments"
        )

    @extend_schema(
        parameters=[_PULL_REQUEST_ID_PARAMETER],
        request=PullRequestReviewCommentCreateSerializer,
        responses={
            201: OpenApiResponse(
                response=PullRequestReviewCommentCreateResponseSerializer,
                description="The created review comment, in the normalized PR-comment shape.",
            ),
            400: OpenApiResponse(description="Invalid comment payload."),
            403: OpenApiResponse(
                description="Not a signed-in user, or the requesting user has no usable personal GitHub "
                "connection (reconnect GitHub)."
            ),
            404: OpenApiResponse(
                description="Report has no implementation PR, or no GitHub integration can access it."
            ),
            502: OpenApiResponse(description="GitHub rejected the comment."),
            503: OpenApiResponse(description="The GitHub egress budget is temporarily unavailable."),
        },
        summary="Post an inline review comment on a report's implementation PR",
        description=(
            "Post an inline review comment on the report's implementation pull request, attributed to the "
            "requesting user's own GitHub identity via their personal GitHub connection. Either replies to "
            "an existing thread (`in_reply_to`) or starts a new thread on a diff line (`path` + `line`)."
        ),
        operation_id="signals_report_pr_review_comments_create",
    )
    @action(detail=True, methods=["post"], url_path="pr_review_comments", required_scopes=["task:write"])
    def pr_review_comments(self, request: Request, *args, **kwargs) -> Response:
        report = cast(SignalReport, self.get_object())
        serializer = PullRequestReviewCommentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        params = serializer.validated_data

        resolved = self._resolve_user_github_and_pr(report, request)
        if isinstance(resolved, Response):
            return resolved
        user_github, repository, pr_number = resolved

        commit_id: str | None = None
        if not params.get("in_reply_to"):
            # New threads anchor to the PR head commit; resolve it via the team integration
            # (read path), so the user token is only used for the write itself.
            github, repository, pr_number, error = self._github_for_report_pr(report, reference=(repository, pr_number))
            if error is not None:
                return error
            assert github is not None
            pr_details = github.get_pull_request(repository, pr_number)
            commit_id = pr_details.get("head_sha") if pr_details.get("success") else None
            if not commit_id:
                return Response(
                    {"error": "Could not resolve the pull request's head commit."},
                    status=status.HTTP_502_BAD_GATEWAY,
                )

        result = self._run_user_github_write(
            lambda: user_github.create_pull_request_review_comment(
                repository,
                pr_number,
                params["body"],
                in_reply_to=params.get("in_reply_to"),
                commit_id=commit_id,
                path=params.get("path"),
                line=params.get("line"),
                side=params.get("side"),
            ),
            repository,
            pr_number,
            noun="comment",
        )
        if isinstance(result, Response):
            return result

        self._bust_pr_comments_cache(repository, pr_number)
        return self._pr_review_comment_response(result["comment"], status_code=status.HTTP_201_CREATED)

    @extend_schema(
        methods=["PATCH"],
        parameters=[
            _PULL_REQUEST_ID_PARAMETER,
            OpenApiParameter("comment_id", OpenApiTypes.STR, OpenApiParameter.PATH),
        ],
        request=PullRequestReviewCommentUpdateSerializer,
        responses={
            200: OpenApiResponse(
                response=PullRequestReviewCommentCreateResponseSerializer,
                description="The edited review comment, in the normalized PR-comment shape.",
            ),
            403: OpenApiResponse(
                description="Not a signed-in user, no usable personal GitHub connection, or not the comment's author."
            ),
            404: OpenApiResponse(description="Report has no implementation PR, or the comment isn't on it."),
            502: OpenApiResponse(description="GitHub rejected the edit."),
            503: OpenApiResponse(description="The GitHub egress budget is temporarily unavailable."),
        },
        summary="Edit one of the requesting user's own review comments",
        operation_id="signals_report_pr_review_comment_update",
    )
    @extend_schema(
        methods=["DELETE"],
        parameters=[
            _PULL_REQUEST_ID_PARAMETER,
            OpenApiParameter("comment_id", OpenApiTypes.STR, OpenApiParameter.PATH),
        ],
        responses={
            204: OpenApiResponse(description="Comment deleted."),
            403: OpenApiResponse(
                description="Not a signed-in user, no usable personal GitHub connection, or not the comment's author."
            ),
            404: OpenApiResponse(description="Report has no implementation PR, or the comment isn't on it."),
            502: OpenApiResponse(description="GitHub rejected the delete."),
            503: OpenApiResponse(description="The GitHub egress budget is temporarily unavailable."),
        },
        summary="Delete one of the requesting user's own review comments",
        operation_id="signals_report_pr_review_comment_destroy",
    )
    @action(
        detail=True,
        methods=["patch", "delete"],
        url_path=r"pr_review_comments/(?P<comment_id>[0-9]+)",
        required_scopes=["task:write"],
    )
    def pr_review_comment(self, request: Request, *args, **kwargs) -> Response:
        report = cast(SignalReport, self.get_object())
        comment_id = str(kwargs["comment_id"])
        resolved = self._resolve_user_github_and_pr(report, request, comment_id=comment_id)
        if isinstance(resolved, Response):
            return resolved
        user_github, repository, pr_number = resolved

        def run() -> dict[str, Any]:
            if request.method == "DELETE":
                return user_github.delete_pull_request_review_comment(repository, comment_id)
            serializer = PullRequestReviewCommentUpdateSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            return user_github.update_pull_request_review_comment(
                repository, comment_id, serializer.validated_data["body"]
            )

        result = self._run_user_github_write(run, repository, pr_number, noun="comment")
        if isinstance(result, Response):
            return result

        self._bust_pr_comments_cache(repository, pr_number)
        if request.method == "DELETE":
            return Response(status=status.HTTP_204_NO_CONTENT)
        return self._pr_review_comment_response(result["comment"], status_code=status.HTTP_200_OK)

    @extend_schema(
        request=PullRequestReviewCommentReactionCreateSerializer,
        responses={
            201: OpenApiResponse(
                response=PullRequestReviewCommentReactionCreateResponseSerializer,
                description="The created reaction.",
            ),
            403: OpenApiResponse(description="Not a signed-in user, or no usable personal GitHub connection."),
            404: OpenApiResponse(description="Report has no implementation PR, or the comment isn't on it."),
            502: OpenApiResponse(description="GitHub rejected the reaction."),
            503: OpenApiResponse(description="The GitHub egress budget is temporarily unavailable."),
        },
        summary="React to a review comment as the requesting user",
        operation_id="signals_report_pr_review_comment_reactions_create",
        parameters=[
            _PULL_REQUEST_ID_PARAMETER,
            OpenApiParameter("comment_id", OpenApiTypes.STR, OpenApiParameter.PATH),
        ],
    )
    @action(
        detail=True,
        methods=["post"],
        url_path=r"pr_review_comments/(?P<comment_id>[0-9]+)/reactions",
        required_scopes=["task:write"],
    )
    def pr_review_comment_reactions(self, request: Request, *args, **kwargs) -> Response:
        report = cast(SignalReport, self.get_object())
        comment_id = str(kwargs["comment_id"])
        serializer = PullRequestReviewCommentReactionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        resolved = self._resolve_user_github_and_pr(report, request, comment_id=comment_id)
        if isinstance(resolved, Response):
            return resolved
        user_github, repository, pr_number = resolved

        result = self._run_user_github_write(
            lambda: user_github.add_pull_request_review_comment_reaction(
                repository, comment_id, serializer.validated_data["content"]
            ),
            repository,
            pr_number,
            noun="reaction",
        )
        if isinstance(result, Response):
            return result

        self._bust_pr_comments_cache(repository, pr_number)
        raw = result.get("reaction") or {}
        reaction = {
            "id": str(raw["id"]) if raw.get("id") is not None else "",
            "content": raw.get("content"),
            "user_login": (raw.get("user") or {}).get("login"),
        }
        return Response({"reaction": reaction}, status=status.HTTP_201_CREATED)

    @extend_schema(
        responses={
            204: OpenApiResponse(description="Reaction removed."),
            403: OpenApiResponse(description="Not a signed-in user, or no usable personal GitHub connection."),
            404: OpenApiResponse(description="Report has no implementation PR, or the comment isn't on it."),
            502: OpenApiResponse(description="GitHub rejected the removal."),
            503: OpenApiResponse(description="The GitHub egress budget is temporarily unavailable."),
        },
        summary="Remove one of the requesting user's own reactions from a review comment",
        operation_id="signals_report_pr_review_comment_reaction_destroy",
        parameters=[
            _PULL_REQUEST_ID_PARAMETER,
            OpenApiParameter("comment_id", OpenApiTypes.STR, OpenApiParameter.PATH),
            OpenApiParameter("reaction_id", OpenApiTypes.STR, OpenApiParameter.PATH),
        ],
    )
    @action(
        detail=True,
        methods=["delete"],
        url_path=r"pr_review_comments/(?P<comment_id>[0-9]+)/reactions/(?P<reaction_id>[0-9]+)",
        required_scopes=["task:write"],
    )
    def pr_review_comment_reaction(self, request: Request, *args, **kwargs) -> Response:
        report = cast(SignalReport, self.get_object())
        comment_id = str(kwargs["comment_id"])
        reaction_id = str(kwargs["reaction_id"])
        resolved = self._resolve_user_github_and_pr(report, request, comment_id=comment_id)
        if isinstance(resolved, Response):
            return resolved
        user_github, repository, pr_number = resolved

        result = self._run_user_github_write(
            lambda: user_github.delete_pull_request_review_comment_reaction(repository, comment_id, reaction_id),
            repository,
            pr_number,
            noun="reaction",
        )
        if isinstance(result, Response):
            return result
        self._bust_pr_comments_cache(repository, pr_number)
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _bust_pr_comments_cache(self, repository: str, pr_number: int) -> None:
        """Drop the short PR-comments read cache so a just-made change shows on the next fetch."""
        cache.delete(f"signals:pr-github:{self.team.id}:{repository}:{pr_number}:get_pull_request_comments")

    @staticmethod
    def _pr_review_comment_response(raw: object, *, status_code: int) -> Response:
        """Shape a raw GitHub review comment via the shared read-path normalizer (a fresh write never
        carries reactions). The shared transport treats a body-less success as valid, so a write result
        we can't normalize is an upstream failure rather than anything the caller did wrong."""
        normalized = GitHubIntegrationBase.normalize_pr_comment(raw, "review")
        if normalized is None:
            return Response(
                {"error": "GitHub returned the comment in an unexpected format. Reload to see the latest."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response({"comment": normalized}, status=status_code)

    def _resolve_user_github_and_pr(
        self, report: SignalReport, request: Request, *, comment_id: str | None = None
    ) -> tuple[UserGitHubIntegration, str, int] | Response:
        """Resolve the requesting user's personal GitHub integration and the report's PR, or a Response
        error (404 no PR, 403 not a human caller or no personal GitHub connection) to return as-is.

        Every write that reaches GitHub under a human's own identity funnels through here, so the
        human-caller check lives here too rather than on each action. It admits only a browser
        session instead of rejecting known token types, because every credential that authenticates
        *as* the user would otherwise inherit their linked GitHub account: a sandbox agent token is
        minted as the task actor and carries ``task:write``, and a personal API key holding the same
        scope is issued for automation rather than for acting as that person on GitHub. Either one
        could comment, edit, delete, or merge as them.

        ``comment_id``, when given, is resolved and required to sit on the report's own PR. GitHub's
        review-comment edit, delete, and reaction endpoints are repository-wide, so this is the only
        thing keeping a report from reaching comments on every other PR in its repository.
        """
        if not isinstance(request.successful_authenticator, SessionAuthentication):
            return Response(
                {"error": "This must be done by a signed-in user, not an automated token."},
                status=status.HTTP_403_FORBIDDEN,
            )
        user = cast(User, request.user)
        reference = self._resolve_report_pr_reference(report)
        if reference is None:
            return Response(
                {"error": "This report has no implementation pull request."}, status=status.HTTP_404_NOT_FOUND
            )
        user_integration = (
            UserIntegration.objects.filter(user=user, kind=UserIntegration.IntegrationKind.GITHUB)
            .order_by("created_at")
            .first()
        )
        if user_integration is None:
            return Response(
                {"error": "Connect your GitHub account in settings to comment on pull requests."},
                status=status.HTTP_403_FORBIDDEN,
            )
        repository, pr_number = reference
        user_github = UserGitHubIntegration(user_integration, source="signals_api", priority=Priority.CRITICAL)
        if comment_id is not None:
            lookup = self._run_user_github_write(
                lambda: user_github.get_pull_request_review_comment(repository, comment_id),
                repository,
                pr_number,
                noun="comment",
            )
            if isinstance(lookup, Response):
                return lookup
            # Matched on the suffix, not the whole URL: the repository is already pinned by the path we
            # just fetched, while the report's stored PR URL can differ from GitHub's canonical casing.
            pull_request_url = (lookup.get("comment") or {}).get("pull_request_url")
            if not isinstance(pull_request_url, str) or not pull_request_url.endswith(f"/pulls/{pr_number}"):
                return Response(
                    {"error": "This comment isn't on this report's pull request. Refresh the page and try again."},
                    status=status.HTTP_404_NOT_FOUND,
                )
        return user_github, repository, pr_number

    def _run_user_github_write(
        self, fn: Callable[[], dict[str, Any]], repository: str, pr_number: int, *, noun: str
    ) -> dict[str, Any] | Response:
        """Run a user-authored GitHub write, mapping the shared failure modes to Responses. Returns the
        call's result dict on success, or a Response to return as-is. GitHub 403 (e.g. editing someone
        else's comment) surfaces as a 403."""
        try:
            result = fn()
        except ReauthorizationRequired:
            return Response(
                {"error": "Your GitHub connection has expired. Reconnect GitHub in settings."},
                status=status.HTTP_403_FORBIDDEN,
            )
        except GitHubRateLimitError as e:
            return github_rate_limited_response(e)
        except GitHubEgressBudgetExhausted:
            return Response(
                {"error": "GitHub is temporarily busy. Try again shortly."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except Exception:  # noqa: BLE001 — never let an upstream GitHub failure 500 this endpoint
            logger.warning(f"signals pr review {noun} write errored", repository=repository, pr_number=pr_number)
            return Response({"error": f"GitHub could not accept the {noun}."}, status=status.HTTP_502_BAD_GATEWAY)

        if not result.get("success"):
            forbidden = result.get("status_code") == 403
            return Response(
                {"error": result.get("error") or f"GitHub could not accept the {noun}."},
                status=status.HTTP_403_FORBIDDEN if forbidden else status.HTTP_502_BAD_GATEWAY,
            )
        return result

    def _pr_github_passthrough(self, report: SignalReport, fetch_name: str, key: str, noun: str) -> Response:
        """Shared body for the ``pr_checks`` / ``pr_comments`` actions: resolve the report's PR and the
        GitHub integration that can read it, call ``fetch_name`` on the client, and return ``{key: ...}``.
        A missing PR/integration maps to 404, a rate limit to its response, and any other upstream GitHub
        failure to 502 — an upstream hiccup never 500s the endpoint."""
        reference = self._resolve_report_pr_reference(report)
        if reference is None:
            return Response(
                {"error": "This report has no implementation pull request."},
                status=status.HTTP_404_NOT_FOUND,
            )
        repository, pr_number = reference
        cache_key = f"signals:pr-github:{self.team.id}:{repository}:{pr_number}:{fetch_name}"
        cached_result = cache.get(cache_key)
        if isinstance(cached_result, dict) and key in cached_result:
            return Response({key: cached_result[key]})

        github, repository, pr_number, error = self._github_for_report_pr(report, reference=reference)
        if error is not None:
            return error
        assert github is not None  # `error is None` guarantees a resolved integration
        try:
            result: dict[str, Any] = getattr(github, fetch_name)(repository, pr_number)
        except GitHubRateLimitError as e:
            return github_rate_limited_response(e)
        except GitHubEgressBudgetExhausted:
            return Response(
                {"error": "GitHub is temporarily busy. Try again shortly."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except Exception:  # noqa: BLE001 — never let an upstream GitHub failure 500 this endpoint
            logger.warning(f"signals pr {noun} fetch errored", repository=repository, pr_number=pr_number)
            return Response(
                {"error": f"GitHub could not return the {noun} for this pull request."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        if result.get("error_code") == "github_checks_permission_missing":
            logger.info(
                "signals pr checks missing GitHub Checks permission",
                team_id=self.team.id,
                repository=repository,
                pr_number=pr_number,
            )
            return Response(
                PullRequestChecksPermissionErrorSerializer(
                    {
                        "code": "github_checks_permission_missing",
                        "error": (
                            "GitHub can't read pull request checks. A project admin must reconnect GitHub and grant "
                            "the Checks permission."
                        ),
                        "remediation_url": f"/project/{self.team.id}/settings/project-integrations",
                    }
                ).data,
                status=status.HTTP_403_FORBIDDEN,
            )
        if not result.get("success"):
            return Response(
                {"error": result.get("error") or f"GitHub could not return the {noun} for this pull request."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        cache.set(cache_key, result, timeout=PR_GITHUB_CACHE_SECONDS)
        return Response({key: result[key]})

    def _github_for_report_pr(
        self,
        report: SignalReport,
        *,
        reference: tuple[str, int] | None = None,
    ) -> tuple[GitHubIntegration | None, str, int, Response | None]:
        """Resolve the report's implementation PR and the GitHub integration that can read it.

        Returns ``(github, repository, pr_number, error_response)`` — on any failure ``error_response``
        is set (and should be returned as-is) and ``github`` is None. Mirrors the connection-boundary
        scoping of the artefact `diff` action: access is bounded to repos the team's installation can
        reach, not to a single per-report repository.
        """
        reference = reference or self._resolve_report_pr_reference(report)
        if reference is None:
            return (
                None,
                "",
                0,
                Response(
                    {"error": "This report has no implementation pull request."},
                    status=status.HTTP_404_NOT_FOUND,
                ),
            )
        repository, pr_number = reference
        try:
            github = GitHubIntegration.first_for_team_repository(
                self.team.id,
                repository,
                source="signals_pr_detail",
                priority=Priority.NORMAL,
            )
        except GitHubRateLimitError as e:
            return None, repository, pr_number, github_rate_limited_response(e)
        except GitHubEgressBudgetExhausted:
            return (
                None,
                repository,
                pr_number,
                Response(
                    {"error": "GitHub is temporarily busy. Try again shortly."},
                    status=status.HTTP_503_SERVICE_UNAVAILABLE,
                ),
            )
        if github is None:
            return (
                None,
                repository,
                pr_number,
                Response(
                    {"error": f"No GitHub integration can access '{repository}'."},
                    status=status.HTTP_404_NOT_FOUND,
                ),
            )
        return github, repository, pr_number, None


# `report_id` addresses a report's UUID primary key. Agents whose prompt only carries a
# `signal_id` sometimes pass that (e.g. `sig_praise`) here instead, so make the constraint
# explicit in the schema — a non-UUID value can never match a report.
_REPORT_ID_PARAMETER = OpenApiParameter(
    name="report_id",
    type=OpenApiTypes.UUID,
    location=OpenApiParameter.PATH,
    description=(
        "UUID of the report whose artefacts you're addressing. This must be a report id (the "
        "report's own UUID), not a signal id such as `sig_praise` — a non-report id returns 404."
    ),
)


@frozen
class _ResolvedReviewerWrite:
    """One reviewer write entry after identity resolution, ready to merge onto the stored list.

    `explicit_name` / `explicit_reason` separate "supplied, possibly as an empty string to clear"
    from "field absent": only an absent field falls back to what the report already stored.
    """

    user_uuid: str | None
    github_login: str | None
    github_name: str | None
    explicit_name: bool
    reason: str | None
    explicit_reason: bool

    @property
    def identity_label(self) -> str:
        return self.github_login or f"user:{self.user_uuid}"


def _reviewer_identity_label(payload: dict) -> str:
    """How a stored reviewer entry names its person in the activity log and in dedupe.

    A GitHub login where there is one, so existing rows and the scout-facing correction history
    read exactly as before; the user's uuid where there is not.
    """
    login = str(payload.get("github_login") or "").strip().lower()
    if login:
        return login
    user_uuid = payload.get("user_uuid")
    return f"user:{user_uuid}" if user_uuid else ""


def _schedule_reviewer_added_slack_notifications(
    *,
    team_id: int,
    report_id: str,
    added_logins: Sequence[str],
    added_user_uuids: Sequence[str],
    actor_user_id: int | None,
) -> None:
    """After commit, Slack-notify reviewers a human just added to this report.

    Enqueued on commit so nothing is sent if the write rolls back, and so delivery's
    network calls (metadata lookups, Slack) run on a worker instead of holding up the
    request. Best-effort — a Slack failure must never break the reviewer edit.
    """
    # robust=True: a broker outage while enqueuing must not 500 an edit that already committed.
    if not assignment_side_effects_allowed(team_id=team_id, report_id=report_id):
        return

    transaction.on_commit(
        lambda: send_reviewer_added_slack_notifications.delay(
            report_id=report_id,
            team_id=team_id,
            # Keep the old task argument shape so workers from the prior release accept this job.
            added_github_logins=[*added_logins, *(f"user:{value}" for value in added_user_uuids)],
            exclude_user_id=actor_user_id,
        ),
        robust=True,
    )


def append_suggested_reviewers(
    *,
    team: Team,
    report_id: str,
    entries: list[dict],
    request: Request,
    edit: ReviewerEdit | None = None,
    removal_reason: str | None = None,
    removal_note: str | None = None,
) -> SignalReportArtefact:
    """Append a new `suggested_reviewers` status row for a report, merging forward from the current
    (latest) reviewers. Works whether or not the report already has a reviewers artefact — the first
    write for a report with none simply creates the first row. Shared by the app-only reviewers PUT
    on both the report and artefact viewsets. Returns the new artefact.
    Raises `ReviewerWriteError` on unresolvable entries."""
    edit = edit or ReviewerEdit(action="replace")
    # App/user-only write (agents append reviewers via the artefacts POST), so always attribute to
    # the requesting user — never the X-PostHog-Task-Id header. A task-attributed reviewers row has
    # no created_by_id, which makes auto-start treat the list as agent-authored and run the
    # implementation task as a named colleague instead of the editor — the reviewer-impersonation
    # path the `triggering_user_id` guard in `auto_start` exists to close.
    user_id = request.user.id
    if user_id is None:  # unreachable behind authentication, but keeps attribution honest
        raise serializers.ValidationError("Cannot attribute a reviewer edit to an anonymous user.")
    attribution = ArtefactAttribution.from_user(user_id)
    # Read off the request here: scout note forwarding runs after commit, where there is no request.
    scoped_team_ids = get_authenticator_scoped_team_ids(request.successful_authenticator)
    scoped_team_id_tuple = tuple(scoped_team_ids) if scoped_team_ids is not None else None

    # Resolve a supplied user_uuid to the org member it names, and a supplied login to that member's
    # uuid. A reviewer is a PostHog user, so an entry needs org membership rather than a GitHub
    # account: a member who never connected GitHub is stored by uuid, with a null login.
    uuids_to_resolve = [str(e["user_uuid"]) for e in entries if e.get("user_uuid")]
    uuid_to_user = resolve_org_users_by_uuid(team.id, uuids_to_resolve) if uuids_to_resolve else {}
    logins_to_resolve = {
        str(e["github_login"]).strip().lower()
        for e in entries
        if not e.get("user_uuid") and str(e.get("github_login") or "").strip()
    }
    login_to_org_user = resolve_org_github_login_to_users(team.id, logins_to_resolve) if logins_to_resolve else {}

    # The bool tuple elements distinguish "github_name / reason explicitly supplied
    # (incl. empty string to clear)" from "field absent" — the merge step below
    # only falls back to the prior value when the field is absent.
    resolved_entries: list[_ResolvedReviewerWrite] = []
    for idx, entry in enumerate(entries):
        user_uuid = entry.get("user_uuid")
        if user_uuid is not None:
            member = uuid_to_user.get(str(user_uuid))
            if member is None and edit.action != "remove":
                raise ReviewerWriteError(f"content[{idx}]: user_uuid '{user_uuid}' is not an org member of this team.")
            uuid_str: str | None = str(member.uuid) if member else str(user_uuid)
            member_login = member.get_github_login() if member else None
            login_lc = member_login.lower() if member_login else None
        else:
            raw_login = entry.get("github_login") or ""
            login_lc = raw_login.strip().lower() or None
            if not login_lc:
                raise ReviewerWriteError(f"content[{idx}]: github_login resolved to empty after normalization.")
            # Store the uuid alongside a login that names an org member, so the entry keeps routing
            # if they later unlink GitHub.
            member = login_to_org_user.get(login_lc)
            uuid_str = str(member.uuid) if member is not None else None

        explicit_name = "github_name" in entry
        github_name = entry.get("github_name") if explicit_name else None
        explicit_reason = "reason" in entry
        reason = entry.get("reason") if explicit_reason else None
        resolved_entries.append(
            _ResolvedReviewerWrite(
                user_uuid=uuid_str,
                github_login=login_lc,
                github_name=github_name,
                explicit_name=explicit_name,
                reason=reason,
                explicit_reason=explicit_reason,
            )
        )

    # Lock the report for the read-merge-append so concurrent reviewer edits serialize — each
    # write reads the current (latest) reviewers and appends a new row, so without the lock two
    # simultaneous edits would both read the same row and one would be silently lost.
    seen: set[str] = set()
    with transaction.atomic():
        report = (
            SignalReport.objects.select_for_update()
            .filter(id=report_id, team_id=team.id)
            .exclude(status=SignalReport.Status.DELETED)
            .first()
        )
        if report is None:
            # The report was concurrently soft-deleted between the caller's fetch and this lock;
            # don't append a stale reviewers row to a dead report.
            raise NotFound()

        # Merge commits/names forward from the *current* reviewers (the latest status row).
        # `suggested_reviewers` is append-only and latest-wins.
        current = (
            SignalReportArtefact.objects.filter(
                report_id=report_id,
                type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
            )
            .order_by("-created_at", "-id")
            .first()
        )
        try:
            prior_content = json.loads(current.content) if current else []
        except (json.JSONDecodeError, ValueError):
            prior_content = []
        if not isinstance(prior_content, list):
            prior_content = []
        prior_index = ReviewerPayloadIndex.build(prior_content)
        prior_payloads_by_identity: dict[str, dict] = {}
        for prior in prior_content:
            if isinstance(prior, dict) and (identity := _reviewer_identity_label(prior)):
                prior_payloads_by_identity.setdefault(identity, prior)
        prior_payloads = list(prior_payloads_by_identity.values())

        # Newly-added reviewers carry no routing evidence, so record who added them and when
        # (this path is always attributed to request.user). Dates use the report's project timezone.
        actor = cast(User, request.user)
        # Build the date without the platform-specific %-d directive (fails on non-Unix).
        now_local = timezone.now().astimezone(team.timezone_info)
        added_on = f"{now_local:%b} {now_local.day}, {now_local.year}"
        manual_add_reason = f"Added as a reviewer by {actor.get_full_name().strip() or actor.email} on {added_on}"

        # Dedupe by identity (a login and its owner's uuid are the same person), preserve
        # first-seen order.
        new_content: list[dict] = []
        # Identity of the prior entry each kept reviewer matched, so a reviewer whose stored entry
        # only carried a login and now carries a uuid too reads as kept, not as a remove plus an add.
        matched_prior_ids: set[int] = set()
        for resolved in resolved_entries:
            identity = resolved.identity_label
            if identity in seen:
                continue
            seen.add(identity)
            prior = prior_index.get(user_uuid=resolved.user_uuid, github_login=resolved.github_login)
            if prior is not None:
                matched_prior_ids.add(id(prior))
            prior_name = prior.get("github_name") if prior else None
            prior_reason = prior.get("reason") if prior else None
            prior_commits = prior.get("relevant_commits") if prior else None
            # If the client supplied github_name (incl. ""), honour it. Otherwise
            # carry over the prior one so kept reviewers don't lose their name.
            # Same rule for reason. Only fall back to the manual-add note when the field was
            # omitted for a brand-new reviewer — an explicit null clears the reason, as for kept ones.
            effective_name = resolved.github_name if resolved.explicit_name else prior_name
            effective_reason = resolved.reason if resolved.explicit_reason else bounded_reviewer_reason(prior_reason)
            if not resolved.explicit_reason and prior is None:
                effective_reason = manual_add_reason
            safe_commits = []
            for commit in prior_commits if isinstance(prior_commits, list) else []:
                if not isinstance(commit, dict):
                    continue
                try:
                    safe_commits.append(
                        RelevantCommit.model_validate(
                            {**commit, "reason": bounded_reviewer_reason(commit.get("reason")) or ""}
                        ).model_dump()
                    )
                except PydanticValidationError:
                    continue
            prior_source_skill = prior.get("source_skill") if prior else None
            new_content.append(
                {
                    "github_login": resolved.github_login,
                    "user_uuid": resolved.user_uuid,
                    "github_name": effective_name if isinstance(effective_name, str) else None,
                    "relevant_commits": safe_commits,
                    "reason": effective_reason or None,
                    "source_skill": prior_source_skill if isinstance(prior_source_skill, str) else None,
                    "is_skill_owner": bool(prior.get("is_skill_owner")) if prior else False,
                    "is_default_owner": bool(prior.get("is_default_owner")) if prior else False,
                }
            )

        new_artefact = SignalReportArtefact.append_status(
            team_id=team.id,
            report_id=str(report_id),
            content=SuggestedReviewers.model_validate(new_content),
            attribution=attribution,
            reviewer_edit=edit,
            reevaluate_autostart=edit.action not in {"remove", "confirm"}
            and any(
                not prior_index.get(user_uuid=entry["user_uuid"], github_login=entry["github_login"])
                for entry in new_content
            ),
        )
        if current is not None and new_artefact.id == current.id:
            return new_artefact
        new_content = SuggestedReviewers.model_validate_json(new_artefact.content).model_dump(mode="json")
        matched_prior_ids = {
            id(prior)
            for entry in new_content
            if (prior := prior_index.get(user_uuid=entry["user_uuid"], github_login=entry["github_login"])) is not None
        }
        # Human reviewer corrections are a routing signal (scouts query them via the
        # activity log to learn who owns an area), so log them — but only genuine
        # membership changes by a human, not agent writes or order-only rewrites.
        # Membership is compared by which prior entry each new one matched, so before/after read
        # symmetrically even where the two rows identify the same person by different fields. A
        # reviewer is labelled by their login when they have one, and by their uuid when they don't.
        removed_payloads = [prior for prior in prior_payloads if id(prior) not in matched_prior_ids]
        added_entries = [
            entry
            for entry in new_content
            if not prior_index.get(user_uuid=entry["user_uuid"], github_login=entry["github_login"])
        ]
        prior_identities = list(dict.fromkeys(_reviewer_identity_label(prior) for prior in prior_payloads))
        new_identities = list(dict.fromkeys(_reviewer_identity_label(entry) for entry in new_content))
        # Member validation can drop a reviewer who lost project access in the same write. Only the
        # people the editor chose to remove carry the editor's verdict and reason.
        requested = ReviewerPayloadIndex.build(
            [{"user_uuid": entry.user_uuid, "github_login": entry.github_login} for entry in resolved_entries]
        )
        chosen_removals = [
            _reviewer_identity_label(prior)
            for prior in removed_payloads
            if (requested.get(user_uuid=prior.get("user_uuid"), github_login=prior.get("github_login")) is not None)
            == (edit.action == "remove")
        ]
        default_owner_labels = _default_owner_labels(prior_payloads)
        evidence_removals = [label for label in chosen_removals if label not in default_owner_labels]
        correction: ReviewerCorrection | None = None
        if attribution.kind == "user" and (removed_payloads or added_entries):
            # Read impersonation once: the activity row records it, and a support-staff edit made
            # while impersonating must not become scout routing precedent. The reviewer-corrections
            # profile already excludes impersonated rows (`_recent_reviewer_corrections`), so the
            # note channel gates on the same signal to keep the two reviewer-correction paths agreeing.
            was_impersonated = is_impersonated_session(request)
            shared_note = _scout_readable_removal_note(
                team=team,
                user=cast(User, request.user),
                scoped_team_ids=scoped_team_id_tuple,
                note=removal_note if evidence_removals else None,
            )
            log_activity(
                organization_id=None,
                team_id=team.id,
                user=cast(User, request.user),
                was_impersonated=was_impersonated,
                item_id=report_id,
                scope="SignalReport",
                activity="suggested_reviewers_changed",
                detail=Detail(
                    name=report.title,
                    changes=[
                        Change(
                            type="SignalReport",
                            action="changed",
                            field="suggested_reviewers",
                            before=prior_identities,
                            after=new_identities,
                        ),
                        *_removal_reason_changes(removal_reason if evidence_removals else None, evidence_removals),
                        *_default_owner_changes(default_owner_labels),
                    ],
                ),
            )

            # A human added reviewers: ping the newly-added ones on their own Slack channel so
            # someone added after generation still hears about an actionable report, mirroring
            # the notification sent when it first went ready. Removals aren't notified.
            added_github_logins = [e["github_login"] for e in added_entries if e["github_login"]]
            if added_entries:
                _schedule_reviewer_added_slack_notifications(
                    team_id=team.id,
                    report_id=str(report_id),
                    added_logins=added_github_logins,
                    added_user_uuids=[
                        e["user_uuid"] for e in added_entries if e["user_uuid"] and not e["github_login"]
                    ],
                    actor_user_id=attribution.user_id,
                )

            # A changed reviewer set may change the automatic PR owners in either direction.
            # The worker protects human and unknown-origin assignments before it mutates GitHub.
            if added_entries or removed_payloads:
                for pr in fetch_implementation_prs_for_reports([str(report_id)], team_id=team.id).get(
                    str(report_id), []
                ):
                    schedule_reviewer_pr_assignment(
                        team_id=team.id,
                        report_id=str(report_id),
                        pr_url=pr.url,
                        pr_state=pr.state,
                    )

            # The same correction also steers the scouts that route on the logins it changed, which
            # is the only return path a scout has for routing memory it already cached — but only for
            # a genuine team edit. An impersonated operator edit is not team ownership evidence, so it
            # steers nothing, matching the reviewer-corrections profile's impersonation filter.
            if not was_impersonated:
                correction = ReviewerCorrection(
                    report_id=str(report_id),
                    added_reviewers=tuple(_reviewer_identity_label(entry) for entry in added_entries),
                    removed_reviewers=tuple(evidence_removals),
                    actor_user_id=user_id,
                    scoped_team_ids=scoped_team_id_tuple,
                    removal_reason=removal_reason if evidence_removals else None,
                    removal_note=shared_note,
                )

        # on_commit so a rolled-back edit emits and steers nothing, matching every other reviewer
        # write path.
        transaction.on_commit(
            partial(
                _record_reviewer_edit,
                team=team,
                report_id=str(report_id),
                github_logins=[entry["github_login"] for entry in new_content if entry["github_login"]],
                user_uuids=[
                    entry["user_uuid"] for entry in new_content if entry["user_uuid"] and not entry["github_login"]
                ],
                correction=correction,
            )
        )

    return new_artefact


def _reviewer_entry_names(entry: dict, *, user_uuid: str, github_login: str | None) -> bool:
    """Whether a stored reviewer entry routes to this person.

    A login only stands in for an entry that carries no uuid of its own, the same rule the reviewer
    filter applies. GitHub reassigns logins, so matching one against an entry that names someone else
    by uuid would let the caller take that person off the report.
    """
    stored_uuid = str(entry.get("user_uuid") or "")
    if stored_uuid:
        return stored_uuid == user_uuid
    return bool(github_login) and str(entry.get("github_login") or "").strip().lower() == github_login


def _stored_reviewer_entry(entry: dict) -> dict:
    """A stored reviewer entry in the canonical shape, carried over field for field.

    A reviewer the caller did not touch keeps whatever their entry already holds. Re-resolving them
    would make an unrelated stale entry, for someone who has since left the organization, reject a
    write that is only about the caller.
    """
    commits = entry.get("relevant_commits")
    return {
        "github_login": entry.get("github_login"),
        "user_uuid": entry.get("user_uuid"),
        "github_name": entry.get("github_name") if isinstance(entry.get("github_name"), str) else None,
        "relevant_commits": commits if isinstance(commits, list) else [],
        "reason": bounded_reviewer_reason(entry.get("reason")) or None,
        "source_skill": entry.get("source_skill"),
        "is_skill_owner": bool(entry.get("is_skill_owner")),
        "is_default_owner": bool(entry.get("is_default_owner")),
    }


def _with_carried_default_owner(
    content: SuggestedReviewers, prior: Sequence[SuggestedReviewerEntry], *, team_id: int
) -> SuggestedReviewers:
    """`is_default_owner` taken from the stored entry rather than from the request.

    Only the fallback writes the flag, and it tells the removal paths that the entry is routing and
    not an ownership verdict. A caller that could set it on someone else's entry could suppress the
    correction their removal should record, so the write API carries the stored value the same way
    the add/remove endpoints do.

    Both identity fields are resolved to the org member they name first, the way the reviewer merge
    resolves them a step later. A login this organization cannot place, or one that places a
    different member, carries nothing: this endpoint stores the pair as given on an unprotected
    report, and a later edit matching that login would hand the mark to whoever ends up behind it.
    """
    stored_owners = {
        normalized
        for entry in prior
        if entry.is_default_owner and (normalized := _normalized_reviewer_user_uuid(entry.user_uuid))
    }
    logins_to_resolve = {entry.github_login for entry in content.root if entry.github_login} if stored_owners else set()
    login_to_org_user = resolve_org_github_login_to_users(team_id, logins_to_resolve) if logins_to_resolve else {}

    def carried(entry: SuggestedReviewerEntry) -> bool:
        user_uuid = _normalized_reviewer_user_uuid(entry.user_uuid)
        if not entry.github_login:
            return user_uuid in stored_owners
        member = login_to_org_user.get(entry.github_login.strip().lower())
        if member is None or (user_uuid and user_uuid != str(member.uuid)):
            return False
        return str(member.uuid) in stored_owners

    return SuggestedReviewers(
        root=[entry.model_copy(update={"is_default_owner": carried(entry)}) for entry in content.root]
    )


def _default_owner_labels(payloads: list[dict]) -> list[str]:
    return [
        label
        for payload in payloads
        if isinstance(payload, dict)
        and payload.get("is_default_owner")
        and (label := _reviewer_identity_label(payload))
    ]


def _default_owner_changes(labels: list[str]) -> list[Change]:
    """The activity-row change that marks which reviewers were only the default owner.

    The reviewer-corrections profile drops these labels, so a person who takes the default owner off
    a report does not read to the scouts as an ownership verdict.
    """
    if not labels:
        return []
    return [Change(type="SignalReport", action="changed", field="default_owner_reviewers", after=labels)]


def _removal_reason_changes(reason: str | None, reviewers: list[str]) -> list[Change]:
    """The activity-row changes that record why the editor removed these reviewers.

    The reviewer-corrections profile reads them, so research sees why people left and whom the
    reason covers. The note never goes here: activity-log readers need no report access, so the note
    reaches only the forwarded scout note, whose readers must be able to read reports.
    """
    if not reason or not reviewers:
        return []
    return [
        Change(type="SignalReport", action="changed", field="removal_reason", after=reason),
        Change(type="SignalReport", action="changed", field="removal_reason_reviewers", after=reviewers),
    ]


def _scout_readable_removal_note(
    *, team: Team, user: User, scoped_team_ids: tuple[int, ...] | None, note: str | None
) -> str | None:
    """The removal note to store, or None when its author may not steer scouts.

    The note lands in the reviewer-corrections profile, which every scout and research run reads
    verbatim. So it passes the gate a scout note passes: a reviewer edit must not carry text that its
    author could not leave as a note by hand. The reason code is a fixed choice and needs no gate.
    """
    if not note:
        return None
    canonical_team = team.parent_team or team
    if not principal_may_steer_scouts(user=user, scoped_team_ids=scoped_team_ids, canonical_team=canonical_team):
        return None
    return note


def remove_suggested_reviewer(
    *,
    team: Team,
    report_id: str,
    user: User,
    scoped_team_ids: tuple[int, ...] | None,
    was_impersonated: bool,
    removal_reason: str | None = None,
    removal_note: str | None = None,
    forward_note: bool = True,
) -> bool:
    """Take one person off a report's suggested reviewers and leave everyone else as they are.

    Returns whether the person was on the list. This is deliberately not routed through
    `append_suggested_reviewers`, which exists to add: it merges a caller-supplied list forward and
    re-resolves every entry, and it lets the write re-evaluate auto-start. A removal needs the
    opposite of all three.

    The read, the filter and the write sit in one transaction behind the report lock, so a reviewer
    added between them is not dropped, and not recorded as removed by the person stepping off.

    `reevaluate_autostart=False`: the new row is attributed to the caller, and auto-start runs an
    implementation task as the user a reviewers edit is attributed to. Stepping off a report must
    never start work, least of all under the credentials of the person who just declined it.
    """
    removal_note = _scout_readable_removal_note(
        team=team, user=user, scoped_team_ids=scoped_team_ids, note=removal_note
    )
    user_id = user.id
    if user_id is None:  # unreachable behind authentication, but keeps attribution honest
        raise serializers.ValidationError("Cannot attribute a reviewer edit to an anonymous user.")
    attribution = ArtefactAttribution.from_user(user_id)
    github_login = user.get_github_login()
    github_login = github_login.lower() if github_login else None

    with transaction.atomic():
        report = (
            SignalReport.objects.select_for_update()
            .filter(id=report_id, team_id=team.id)
            .exclude(status=SignalReport.Status.DELETED)
            .first()
        )
        if report is None:
            raise NotFound()

        current = (
            SignalReportArtefact.objects.filter(
                report_id=report_id,
                type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
            )
            .order_by("-created_at", "-id")
            .first()
        )
        try:
            prior_content = json.loads(current.content) if current else []
        except (json.JSONDecodeError, ValueError):
            prior_content = []
        if not isinstance(prior_content, list):
            return False

        prior = [entry for entry in prior_content if isinstance(entry, dict)]
        kept = [
            entry
            for entry in prior
            if not _reviewer_entry_names(entry, user_uuid=str(user.uuid), github_login=github_login)
        ]
        new_artefact = SignalReportArtefact.append_status(
            team_id=team.id,
            report_id=str(report_id),
            content=SuggestedReviewers(
                root=[SuggestedReviewerEntry(user_uuid=str(user.uuid), github_login=github_login)]
            ),
            attribution=attribution,
            reviewer_edit=ReviewerEdit(action="remove"),
            reevaluate_autostart=False,
        )
        if len(kept) == len(prior):
            return False
        new_content = SuggestedReviewers.model_validate_json(new_artefact.content).model_dump(mode="json")
        default_owner_labels = _default_owner_labels(prior)
        removed_default_owner = any(entry.get("is_default_owner") for entry in prior if entry not in kept)

        log_activity(
            organization_id=None,
            team_id=team.id,
            user=user,
            was_impersonated=was_impersonated,
            item_id=report_id,
            scope="SignalReport",
            activity="suggested_reviewers_changed",
            detail=Detail(
                name=report.title,
                changes=[
                    Change(
                        type="SignalReport",
                        action="changed",
                        field="suggested_reviewers",
                        before=list(dict.fromkeys(_reviewer_identity_label(entry) for entry in prior)),
                        after=list(dict.fromkeys(_reviewer_identity_label(entry) for entry in new_content)),
                    ),
                    *_removal_reason_changes(
                        None if removed_default_owner else removal_reason,
                        [] if removed_default_owner else [github_login or str(user.uuid)],
                    ),
                    *_default_owner_changes(default_owner_labels),
                ],
            ),
        )
        correction = (
            None
            if was_impersonated or removed_default_owner
            else ReviewerCorrection(
                report_id=str(report_id),
                added_reviewers=(),
                removed_reviewers=(github_login or str(user.uuid),),
                actor_user_id=user_id,
                scoped_team_ids=scoped_team_ids,
                removal_reason=removal_reason,
                removal_note=removal_note,
            )
        )
        # on_commit so a rolled-back edit steers nothing. No notification: a removal adds no
        # reviewer and assigns no pull request.
        transaction.on_commit(
            partial(
                _record_reviewer_edit,
                team=team,
                report_id=str(report_id),
                github_logins=[entry["github_login"] for entry in new_content if entry["github_login"]],
                user_uuids=[
                    entry["user_uuid"] for entry in new_content if entry["user_uuid"] and not entry["github_login"]
                ],
                correction=correction,
                forward_note=forward_note,
            )
        )
    return True


def _record_reviewer_edit(
    *,
    team: Team,
    report_id: str,
    github_logins: list[str],
    user_uuids: list[str],
    correction: ReviewerCorrection | None,
    forward_note: bool = True,
) -> None:
    """The post-commit tail of a reviewer edit: steer the scouts, then record what the edit did.

    Forwarding runs first so the analytics event can report what it achieved. `correction` is None
    for an agent write or an order-only rewrite, neither of which tells a scout anything.
    """
    forwarded = (
        forward_reviewer_correction_note(team=team, correction=correction) if correction and forward_note else None
    )
    capture_suggested_reviewers_resolved(
        team_id=team.id,
        report_id=report_id,
        github_logins=github_logins,
        user_uuids=user_uuids,
        source="user_edit",
        correction_notes_written=len(forwarded.note_ids) if forwarded else None,
        correction_note_targets=forwarded.targets_resolved if forwarded else None,
        removal_reason=correction.removal_reason if correction else None,
        has_removal_note=bool(correction.removal_note) if correction and correction.removed_reviewers else None,
    )


@extend_schema_view(
    list=extend_schema(
        summary="List a report's checks",
        description=(
            "List the forward-looking checks on a report. A check says what must stay true after "
            "the report was acted on, and the coordinator records each verdict as a `check_result` "
            "artefact on the report."
        ),
        parameters=[_REPORT_ID_PARAMETER],
        responses={200: SignalReportCheckSerializer(many=True)},
        operation_id="signals_report_checks_list",
    ),
    retrieve=extend_schema(
        summary="Get a single check",
        parameters=[_REPORT_ID_PARAMETER],
        responses={200: SignalReportCheckSerializer},
        operation_id="signals_report_checks_retrieve",
    ),
    destroy=extend_schema(
        summary="Cancel a check",
        description=(
            "Stop a check that is still open — active, or pending its report resolving. Its recorded "
            "results stay on the report."
        ),
        parameters=[_REPORT_ID_PARAMETER],
        responses={200: SignalReportCheckSerializer},
        operation_id="signals_report_checks_destroy",
    ),
)
class SignalReportCheckViewSet(
    TeamAndOrgViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Checks attached to a signal report: read, approve, replace metrics, and cancel.

    There is no create here. A check is authored by a scout run or by the research pipeline, both
    through `report_check_authoring.create_check`. An `agent` check puts its author's prose in front
    of a privileged scout run, and `task:write` does not authorize that, so no caller-facing
    endpoint accepts one. Anyone who can read the report can read its checks, and a person can
    still stop one.

    There is no in-place update: a check is a claim about the future, and editing its threshold
    after a result would make the recorded verdict unreadable. Replacing an open metric check
    cancels the old row and creates a new one in one transaction.
    """

    serializer_class = SignalReportCheckSerializer
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "task"
    queryset = SignalReportCheck.objects.unscoped().order_by(
        Case(
            When(status__in=SignalReportCheck.OPEN_STATUSES, then=Value(0)),
            default=Value(1),
            output_field=IntegerField(),
        ),
        "-created_at",
    )
    http_method_names = ["get", "post", "delete", "head", "options"]

    def _validated_report(self) -> SignalReport:
        report_id = self.parents_query_dict["report_id"]
        try:
            uuid.UUID(str(report_id))
        except (ValueError, TypeError):
            raise NotFound()
        report = (
            SignalReport.objects.filter(id=report_id, team=self.team)
            .exclude(status=SignalReport.Status.DELETED)
            .first()
        )
        if report is None:
            raise NotFound()
        return report

    def safely_get_queryset(self, queryset):
        return queryset.filter(report_id=self._validated_report().id, team=self.team).select_related("report")

    def destroy(self, request: Request, *args, **kwargs) -> Response:
        check = cast(SignalReportCheck, self.get_object())
        stopped = cancel_check(
            check, reason="stopped_by_person", attribution=resolve_request_attribution(request, self.team.id)
        )
        if not stopped:
            return Response(
                {"error": f"This check already finished as '{check.status}' and cannot be cancelled."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(self.get_serializer(check).data)

    @extend_schema(
        request=None,
        responses={200: SignalReportCheckSerializer},
        summary="Approve a follow-up check",
        description="Record a person's quality signal. Approval does not affect scheduling or execution.",
        operation_id="signals_report_checks_approve_create",
    )
    @action(detail=True, methods=["post"], url_path="approve", required_scopes=["task:write"])
    def approve(self, request: Request, *args, **kwargs) -> Response:
        attribution = resolve_request_attribution(request, self.team.id)
        if attribution.kind != "user" or not isinstance(request.successful_authenticator, SessionAuthentication):
            return Response({"error": "A person must approve this check."}, status=status.HTTP_403_FORBIDDEN)
        check = cast(SignalReportCheck, self.get_object())
        if check.kind == SignalReportCheck.Kind.METRIC_THRESHOLD and not ReportMetricAccessPolicy(
            request=request, team=self.team
        ).may_read_query(check.config):
            return Response(
                {"error": "The measurement query is not available to you."}, status=status.HTTP_403_FORBIDDEN
            )
        approved_at = timezone.now()
        SignalReportCheck.objects.for_team(self.team.id).filter(
            id=check.id, status__in=SignalReportCheck.OPEN_STATUSES, approved_at__isnull=True
        ).update(approved_at=approved_at, approved_by_id=attribution.user_id, updated_at=approved_at)
        check.refresh_from_db()
        if check.status not in SignalReportCheck.OPEN_STATUSES:
            return Response({"error": "Only open checks can be approved."}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(check).data)

    @validated_request(
        request_serializer=SignalReportCheckReplacementSerializer,
        responses={200: SignalReportCheckSerializer},
        summary="Replace a metric follow-up check",
        description="Atomically replace an open metric check. The old check stays live if the new one is invalid.",
        operation_id="signals_report_checks_replace_create",
    )
    @action(detail=True, methods=["post"], url_path="replace", required_scopes=["task:write", "query:read"])
    def replace(self, request: ValidatedRequest, *args, **kwargs) -> Response:
        check = cast(SignalReportCheck, self.get_object())
        data = request.validated_data
        try:
            replacement = replace_metric_check(
                check=check,
                title=data["title"],
                rationale=data.get("rationale", ""),
                config=data["config"],
                attribution=resolve_request_attribution(request, self.team.id),
                access_policy=ReportMetricAccessPolicy(request=request, team=self.team),
            )
        except CheckQueryAccessError as error:
            return Response({"error": str(error)}, status=status.HTTP_403_FORBIDDEN)
        except CheckCreationError as error:
            return Response({"error": str(error)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(replacement).data)


@extend_schema_view(
    list=extend_schema(
        summary="List a report's artefacts",
        description=(
            "List every artefact on a report — the full work log: signal findings (the evidence "
            "behind the report), status judgments (safety / actionability / priority, repo "
            "selection, suggested reviewers — the newest row of each status type is canonical), "
            "and log entries (code references, commits, task runs, notes). "
            "`suggested_reviewers` content is enriched with PostHog user info at read time. "
            "`ranking_score` content keeps only the head fields of each model's metadata; get the "
            "artefact by id for the full metadata."
        ),
        parameters=[_REPORT_ID_PARAMETER],
        responses={200: SignalReportArtefactSerializer(many=True)},
        operation_id="signals_report_artefacts_list",
    ),
    retrieve=extend_schema(
        summary="Get a single artefact",
        description=(
            "Get one artefact by id, content parsed (and reviewers enriched) the same way as the list. "
            "A `ranking_score` keeps its full model metadata."
        ),
        parameters=[_REPORT_ID_PARAMETER],
        responses={200: SignalReportArtefactSerializer},
        operation_id="signals_report_artefacts_retrieve",
    ),
    # The bespoke reviewers PUT stays app-only: agents append suggested_reviewers via POST instead.
    update=extend_schema(exclude=True),
)
class SignalReportArtefactViewSet(
    TeamAndOrgViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Artefacts attached to a signal report.

    Two write surfaces, both gated by the `task:write` scope (already held by the agent tokens):

    - PUT edits a report's suggested reviewers: it appends a new `suggested_reviewers` status
      artefact (latest-wins, so the new row becomes current) with bespoke reviewer enrichment,
      merging commits/names forward from the current reviewers. Other types return 400.
    - POST / PATCH / DELETE manage artefacts, except for the types the pipeline owns
      (`NON_WRITABLE_ARTEFACT_TYPES`) and, for DELETE, the append-only `task_run` log; all of
      those return 400 naming the type.
      Log entries accumulate; status types (judgments, repo selection, suggested reviewers, channel assignments)
      are latest-wins, so appending a new version supersedes the previous one as the report's
      canonical status. Content is validated against the type's schema. Team scoping is
      enforced by `safely_get_queryset`, so an artefact id from another team / a deleted
      report 404s.

    Writes are attributed: to the task named by the `X-PostHog-Task-Id` header (set automatically
    for sandbox agents) when present, else to the requesting user.
    """

    serializer_class = SignalReportArtefactSerializer
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "task"
    # select_related: the read serializer renders `created_by` inline.
    queryset = SignalReportArtefact.objects.select_related("created_by").order_by("-created_at", "-id")
    http_method_names = ["get", "post", "put", "patch", "delete", "head", "options"]

    def _validated_report_id(self) -> str:
        # `report_id` addresses a report's UUID primary key. Agents sometimes pass a signal id
        # (e.g. `sig_praise`) instead, which the ORM can't coerce to a UUID — left to reach the
        # query it surfaces as a 500. Reject it up front as a clean 404 the caller can recover from.
        report_id = self.parents_query_dict["report_id"]
        try:
            uuid.UUID(str(report_id))
        except (ValueError, TypeError):
            raise NotFound()
        return report_id

    def _validate_channel_assignment(self, assignment: ChannelAssignment, request: Request) -> None:
        if assignment.channel_id is not None and not tasks_facade.channel_exists(
            self.team.id, assignment.channel_id, request.user.id
        ):
            raise serializers.ValidationError({"content": {"channel_id": "Unknown or inaccessible channel."}})

    def safely_get_queryset(self, queryset):
        # Mirror SignalReportViewSet: a deleted parent report is unreachable, so
        # its artefacts must be too (otherwise a known UUID would bypass deletion).
        queryset = queryset.filter(
            report_id=self._validated_report_id(),
            team=self.team,
        ).exclude(report__status=SignalReport.Status.DELETED)
        if not organization_report_monitoring_enabled(self.organization.id):
            queryset = queryset.exclude(type=SignalReportArtefact.ArtefactType.CHECK_OBSERVATION)
        # Scoring rows are staff-only on every artefact route, not only in the log.
        if not self.request.user.is_staff:
            queryset = queryset.exclude(
                type__in=SignalReportArtefact.SYSTEM_SCORING_ARTEFACT_TYPES
                | SignalReportArtefact.INTERNAL_ARTEFACT_TYPES
            )
        return queryset

    def retrieve(self, request, *args, **kwargs):
        with trial_state_errors():
            store = trial_store_for_request(request, self.team_id)
            if store is not None:
                report_id = str(self._validated_report_id())
                for artefact in private_report_artefacts(store, report_id):
                    if str(artefact.id) == str(kwargs["pk"]):
                        return Response(self.get_serializer(artefact).data)
        return super().retrieve(request, *args, **kwargs)

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        # Surface legacy `SignalReportTask` associations as synthetic `task_run` artefacts so a
        # report's research / implementation runs appear in the log even before the backfill has
        # converted its gate rows. Merged into the materialized log (de-duplicated against the real
        # task_run artefacts) and re-sorted newest-first so each legacy row lands at its original
        # timestamp, then paginated as one list so `count` and ordering both account for them.
        real_artefacts = list(queryset)
        synthetic = SignalReport.synthetic_legacy_task_run_artefacts(
            report_id=self.parents_query_dict["report_id"],
            team_id=self.team.id,
            existing_artefacts=real_artefacts,
        )
        with trial_state_errors():
            store = trial_store_for_request(request, self.team_id)
            if store is not None:
                synthetic.extend(private_report_artefacts(store, str(self._validated_report_id())))
        log = (
            sorted([*real_artefacts, *synthetic], key=lambda a: (a.created_at, str(a.id)), reverse=True)
            if synthetic
            else real_artefacts
        )
        page = self.paginate_queryset(log)
        artefacts = list(page if page is not None else log)
        logins_union = normalized_github_logins_from_suggested_reviewer_artefacts(artefacts)
        login_map = resolve_org_github_login_to_users(self.team.id, logins_union) if logins_union else {}
        uuids_union = normalized_user_uuids_from_suggested_reviewer_artefacts(artefacts)
        uuid_map = resolve_org_users_by_uuid(self.team.id, uuids_union) if uuids_union else {}
        skills_union = source_skills_from_suggested_reviewer_artefacts(artefacts)
        scout_display_names = (
            dict(
                SignalScoutConfig.objects.for_team(self.team.id)
                .filter(skill_name__in=skills_union)
                .values_list("skill_name", "display_name")
            )
            if skills_union
            else {}
        )
        serializer = SignalReportArtefactSerializer(
            artefacts,
            many=True,
            context={
                **self.get_serializer_context(),
                "signals_github_login_to_user_map": login_map,
                "signals_reviewer_user_uuid_map": uuid_map,
                "signals_scout_display_names": scout_display_names,
                "signals_compact_ranking_scores": True,
                "signals_reviewer_history": [
                    artefact
                    for artefact in real_artefacts
                    if artefact.type == SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS
                ],
            },
        )
        response = (
            self.get_paginated_response(serializer.data)
            if page is not None
            else Response(
                {
                    "count": len(serializer.data),
                    "next": None,
                    "previous": None,
                    "results": serializer.data,
                }
            )
        )
        return response

    def update(self, request, *args, **kwargs):
        artefact = cast(SignalReportArtefact, self.get_object())

        # Generic endpoint, single-type allow-list: any other artefact type is
        # part of the agentic pipeline contract and must not be hand-edited.
        if artefact.type != SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS:
            return Response(
                {
                    "error": (
                        "Only suggested_reviewers artefacts may be modified via this endpoint. "
                        f"This artefact has type '{artefact.type}'."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        write_serializer = SignalReportArtefactWriteSerializer(data=request.data)
        write_serializer.is_valid(raise_exception=True)
        entries = write_serializer.validated_data.get("targets", write_serializer.validated_data["content"])

        try:
            new_artefact = append_suggested_reviewers(
                team=self.team,
                report_id=str(artefact.report_id),
                entries=entries,
                request=request,
                edit=ReviewerEdit(
                    action=write_serializer.validated_data["action"],
                    expected_state=write_serializer.validated_data.get("expected_reviewers"),
                ),
                removal_reason=write_serializer.validated_data.get("removal_reason"),
                removal_note=write_serializer.validated_data.get("removal_note"),
            )
        except StaleReviewerProposal as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
        except ReviewerWriteError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        # Return the read-shape (enriched) so the client sees the canonical result.
        read_serializer = SignalReportSuggestedReviewersArtefactSerializer(
            new_artefact, context=self.get_serializer_context()
        )
        return Response(read_serializer.data)

    @staticmethod
    def _write_response_data(artefact: SignalReportArtefact) -> dict:
        """Build the create/update response payload, parsing stored JSON content for the echo."""
        try:
            parsed_content: dict | list = json.loads(artefact.content)
        except (json.JSONDecodeError, ValueError):
            parsed_content = {}
        return SignalReportArtefactWriteResponseSerializer(
            {
                "id": artefact.id,
                "claim_id": artefact.claim_id,
                "report_id": artefact.report_id,
                "type": artefact.type,
                "content": parsed_content,
                "created_at": artefact.created_at,
                "updated_at": artefact.updated_at,
                "task_id": artefact.task_id,
            }
        ).data

    def _schedule_suggested_reviewer_telemetry(self, *, content: SuggestedReviewers, report_id: str) -> None:
        transaction.on_commit(
            partial(
                capture_suggested_reviewers_resolved,
                team_id=self.team.id,
                report_id=report_id,
                github_logins=[entry.github_login for entry in content.root if entry.github_login],
                user_uuids=[entry.user_uuid for entry in content.root if entry.user_uuid and not entry.github_login],
                source="api",
            )
        )

    @validated_request(
        request_serializer=SignalReportArtefactLogCreateSerializer,
        responses={
            201: OpenApiResponse(response=SignalReportArtefactWriteResponseSerializer, description="Artefact created."),
            400: OpenApiResponse(
                description="Unknown artefact type, content not matching the type's schema, "
                "or an invalid X-PostHog-Task-Id header."
            ),
            404: OpenApiResponse(description="Report not found for this project."),
        },
        parameters=[
            _REPORT_ID_PARAMETER,
            OpenApiParameter(
                name=TASK_ID_HEADER,
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.HEADER,
                required=False,
                description=(
                    "Task to attribute the artefact to (must belong to this project). Set automatically "
                    "for sandbox agents; when absent the artefact is attributed to the requesting user."
                ),
            ),
        ],
        summary="Append an artefact to a report",
        description=(
            "Append an artefact to a report (see artefact_type for the writable types). Everything "
            "is append-only: log entries (code reference, commit, task run, note) accumulate, while "
            "status types (safety / actionability / priority judgments, repo selection, suggested "
            "reviewers, channel assignments) are latest-wins — appending a new version supersedes the previous one as the "
            "report's canonical status. Content is validated against the type's schema."
        ),
        operation_id="signals_report_artefacts_create",
    )
    def create(self, request: ValidatedRequest, *args, **kwargs) -> Response:
        report_id = self._validated_report_id()
        # A deleted / foreign report is unreachable — don't let a known report_id attach
        # artefacts to it. Mirrors the team-scoped filter in `safely_get_queryset`.
        report_exists = (
            SignalReport.objects.filter(id=report_id, team=self.team)
            .exclude(status=SignalReport.Status.DELETED)
            .exists()
        )
        if not report_exists:
            raise NotFound()
        artefact_type = request.validated_data["artefact_type"]
        writable_types = sorted(set(SignalReportArtefact.ArtefactType.values) - NON_WRITABLE_ARTEFACT_TYPES)
        if artefact_type not in SignalReportArtefact.ArtefactType.values:
            return Response(
                {"error": f"Unknown artefact type '{artefact_type}'. Valid types: {', '.join(writable_types)}."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if artefact_type in NON_WRITABLE_ARTEFACT_TYPES:
            # Legacy permissive types (e.g. video_segment) have no real content validation, so the
            # write API refuses them — they stay readable for existing rows but can't be created.
            return Response(
                {"error": f"Artefact type '{artefact_type}' is read-only and cannot be created through the API."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        content = request.validated_data["content"]
        attribution = resolve_request_attribution(request, self.team.id)
        # The write boundary: parse the raw payload into the type's content model once; the
        # typed model is what flows into the append helpers.
        try:
            parsed_content = parse_artefact_content(artefact_type, content)
        except ArtefactContentValidationError as e:
            return Response(
                {"error": f"content does not match the '{artefact_type}' schema: {e}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if isinstance(parsed_content, ChannelAssignment):
            self._validate_channel_assignment(parsed_content, request)
        claim_id = request.validated_data.get("claim_id")
        if isinstance(parsed_content, SuggestedReviewers):
            try:
                expected = request.validated_data.get("expected_reviewers")
                reviewer_outcome = request.validated_data.get("reviewer_outcome", "selected")
                with transaction.atomic():
                    SignalReport.objects.select_for_update().get(team_id=self.team.id, id=report_id)
                    snapshot = ReviewerRules.read_for_report(team_id=self.team.id, report_id=report_id)
                    previous = snapshot.state.reviewers_id
                    parsed_content = _with_carried_default_owner(
                        parsed_content, snapshot.reviewers, team_id=self.team.id
                    )
                    artefact = SignalReportArtefact.append_status(
                        team_id=self.team.id,
                        report_id=report_id,
                        content=parsed_content,
                        attribution=attribution,
                        reviewer_proposal=ReviewerProposal(
                            expected_state=ReviewerState.model_validate(expected),
                            outcome=reviewer_outcome,
                            retry_reason=request.validated_data.get("reviewer_retry_reason"),
                        )
                        if expected is not None
                        else None,
                        reviewer_edit=ReviewerEdit(action="replace", expected_state=expected)
                        if attribution.kind == "user" and reviewer_outcome == "selected"
                        else None,
                        claim_id=str(claim_id) if claim_id else None,
                    )
                    if artefact.id != previous:
                        self._schedule_suggested_reviewer_telemetry(
                            content=SuggestedReviewers.model_validate_json(artefact.content),
                            report_id=report_id,
                        )
            except StaleReviewerProposal as e:
                return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
            except ValueError as e:
                return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
            return Response(self._write_response_data(artefact), status=status.HTTP_201_CREATED)
        with transaction.atomic():
            report = SignalReport.objects.select_for_update().get(team_id=self.team.id, id=report_id)
            import_report_pull_requests(report)
            if claim_id:
                assignment = get_active_claim(team_id=self.team.id, report_id=report_id)
                if (
                    assignment is None
                    or assignment.claim_id != claim_id
                    or not actor_works_under_claim(assignment, attribution)
                ):
                    return Response(
                        {"detail": "Claim is stale or belongs to another actor."}, status=status.HTTP_409_CONFLICT
                    )
            try:
                artefact = SignalReportArtefact.append(
                    team_id=self.team.id,
                    report_id=report_id,
                    content=parsed_content,
                    attribution=attribution,
                    claim_id=str(claim_id) if claim_id else None,
                )
            except ArtefactContentValidationError as e:
                return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self._write_response_data(artefact), status=status.HTTP_201_CREATED)

    def _capture_canonical_reviewer_state(self, report_id: str) -> None:
        """Re-emit reviewer telemetry from the latest surviving `suggested_reviewers` row.

        Deleting or editing a reviewers artefact changes the report's canonical reviewer set
        without going through an append path, so the "latest event per report" read would
        otherwise keep describing the removed row. An empty login list is a valid state (the
        deletion removed the only row).

        Fully best-effort: this runs in a non-robust on_commit callback after the mutation
        committed, so an exception here would turn an already-successful request into a 500."""
        try:
            latest = (
                SignalReportArtefact.objects.filter(
                    team_id=self.team.id,
                    report_id=report_id,
                    type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
                )
                .order_by("-created_at")
                .first()
            )
            logins: list[str] = []
            user_uuids: list[str] = []
            if latest is not None:
                try:
                    parsed = json.loads(latest.content)
                except (json.JSONDecodeError, TypeError, ValueError):
                    parsed = []
                if isinstance(parsed, list):
                    rows = [entry for entry in parsed if isinstance(entry, dict)]
                    logins = [str(entry["github_login"]) for entry in rows if entry.get("github_login")]
                    user_uuids = [
                        str(entry["user_uuid"])
                        for entry in rows
                        if entry.get("user_uuid") and not entry.get("github_login")
                    ]
            capture_suggested_reviewers_resolved(
                team_id=self.team.id,
                report_id=report_id,
                github_logins=logins,
                user_uuids=user_uuids,
                source="api",
            )
        except Exception:
            logger.exception("failed to re-emit canonical reviewer state", report_id=report_id)

    @validated_request(
        request_serializer=SignalReportArtefactLogUpdateSerializer,
        responses={
            200: OpenApiResponse(response=SignalReportArtefactWriteResponseSerializer, description="Artefact updated."),
            400: OpenApiResponse(description="Content does not match the artefact type's schema."),
            404: OpenApiResponse(description="Artefact not found for this report / project."),
        },
        summary="Replace an artefact's content",
        description=(
            "Replace the content of an existing artefact, addressed by id. The new content is "
            "validated against the artefact's type schema. Editing the latest row of a status type "
            "changes the report's canonical status (latest-wins); to re-assess while keeping history, "
            "append a new artefact instead. Attribution is creation-time only — edits don't reassign it."
        ),
        parameters=[_REPORT_ID_PARAMETER],
        operation_id="signals_report_artefacts_partial_update",
    )
    def partial_update(self, request: ValidatedRequest, *args, **kwargs) -> Response:
        artefact = cast(SignalReportArtefact, self.get_object())
        if artefact.type in NON_WRITABLE_ARTEFACT_TYPES:
            # Legacy read-only types (e.g. video_segment) can't be created via the API, so they
            # can't be edited through it either.
            return Response(
                {"error": f"Artefact type '{artefact.type}' is read-only and cannot be edited through the API."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            parsed_content = parse_artefact_content(artefact.type, request.validated_data["content"])
            if isinstance(parsed_content, ChannelAssignment):
                self._validate_channel_assignment(parsed_content, request)
            artefact.update_content(request.validated_data["content"])
        except ArtefactContentValidationError as e:
            return Response(
                {"error": f"content does not match the '{artefact.type}' schema: {e}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if artefact.type == SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS:
            # Editing a reviewers row can change the report's canonical reviewer set in place.
            transaction.on_commit(partial(self._capture_canonical_reviewer_state, str(artefact.report_id)))
        return Response(self._write_response_data(artefact))

    @extend_schema(
        responses={
            204: OpenApiResponse(description="Artefact deleted."),
            400: OpenApiResponse(description="Artefact type cannot be deleted through the API."),
            404: OpenApiResponse(description="Artefact not found for this report / project."),
        },
        summary="Delete an artefact",
        description=(
            "Delete an artefact, addressed by id. Deleting the latest row of a status type reverts "
            "the report's canonical status to the previous version (latest-wins over what remains). "
            "`task_run` artefacts are an append-only work log and cannot be deleted. Neither can the "
            "types this API cannot write, which the pipeline owns: "
            # Interpolated from the constant the guard tests, so the contract cannot drift from it.
            f"{', '.join(f'`{artefact_type}`' for artefact_type in sorted(NON_WRITABLE_ARTEFACT_TYPES))}."
        ),
        parameters=[_REPORT_ID_PARAMETER],
        operation_id="signals_report_artefacts_destroy",
    )
    def destroy(self, request, *args, **kwargs) -> Response:
        artefact = cast(SignalReportArtefact, self.get_object())
        if artefact.type in {
            SignalReportArtefact.ArtefactType.TASK_RUN,
            SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
            SignalReportArtefact.ArtefactType.IMPACT_MEASUREMENT_PLAN,
            SignalReportArtefact.ArtefactType.WORK_CLAIM,
            SignalReportArtefact.ArtefactType.WORK_RELEASE,
            SignalReportArtefact.ArtefactType.PULL_REQUEST,
        }:
            # The work log is also what the per-report task cap counts; a deletable log would let
            # a client at the cap free its own slots.
            return Response(
                {"error": f"{artefact.type} artefacts are an append-only work log and cannot be deleted."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if artefact.type in NON_WRITABLE_ARTEFACT_TYPES:
            # System-generated types can't be created or edited through the API, so they can't be
            # deleted through it either. Deleting the latest row of one reverts the report's canonical
            # status — e.g. resurfacing a superseded implementation_decision, which then reopens a PR.
            return Response(
                {"error": f"Artefact type '{artefact.type}' is read-only and cannot be deleted through the API."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        was_reviewers = artefact.type == SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS
        report_id = str(artefact.report_id)
        with transaction.atomic():
            SignalReport.objects.select_for_update().get(team_id=self.team.id, id=report_id)
            artefact.delete()
        if was_reviewers:
            # Deleting the latest reviewers row reverts the canonical set to the previous row (or
            # none) — re-emit so the latest event per report tracks the surviving state.
            transaction.on_commit(partial(self._capture_canonical_reviewer_state, report_id))
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        responses={
            200: OpenApiResponse(
                response=CommitDiffResponseSerializer,
                description="The pull request diff, or the branch diff when no pull request is linked.",
            ),
            400: OpenApiResponse(description="Artefact is not a commit, or is missing repository/branch."),
            404: OpenApiResponse(description="Artefact not found, or no GitHub integration can access the repository."),
            502: OpenApiResponse(description="GitHub could not produce the diff (branch not found, fetch failed)."),
        },
        summary="Fetch the diff for a commit artefact",
        description=(
            "Fetch the unified diff for a `commit` artefact via the team's GitHub integration. "
            "A commit linked to a report pull request uses GitHub's durable pull request diff. "
            "A commit without that link compares the branch's current tip with the default branch."
        ),
        parameters=[_REPORT_ID_PARAMETER],
        operation_id="signals_report_artefacts_diff",
    )
    @action(detail=True, methods=["get"], url_path="diff", required_scopes=["task:read"])
    def diff(self, request: Request, *args, **kwargs) -> Response:
        artefact = cast(SignalReportArtefact, self.get_object())
        if artefact.type != SignalReportArtefact.ArtefactType.COMMIT:
            return Response(
                {"error": f"Diffs are only available for commit artefacts, not '{artefact.type}'."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            content = json.loads(artefact.content)
        except (json.JSONDecodeError, ValueError):
            content = {}
        if not isinstance(content, dict):
            # Log artefacts store arbitrary JSON; a non-object payload has no repository/commit.
            content = {}
        repository = content.get("repository")
        branch = content.get("branch")
        if not repository or not branch:
            return Response(
                {"error": "Artefact is missing a repository or branch."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # The diff is deliberately bounded to repos the team's GitHub installation can access
        # (`first_for_team_repository` returns None otherwise) rather than to a single per-report
        # repository: a report's work legitimately spans multiple repos (cross-repo fixes, stacked
        # PRs). That connection boundary is the intended scope — any `task:write` holder can already
        # run agents against those same repos — and the repo/ref values are validated in `get_diff`.
        try:
            github = GitHubIntegration.first_for_team_repository(
                self.team.id, repository, source="signals_api", priority=Priority.CRITICAL
            )
        except GitHubRateLimitError as e:
            return github_rate_limited_response(e)
        if github is None:
            return Response(
                {"error": f"No GitHub integration can access '{repository}'."},
                status=status.HTTP_404_NOT_FOUND,
            )
        try:
            pull_request = _pull_request_ref_for_commit(artefact, str(repository), str(branch), github)
        except GitHubRateLimitError as e:
            return github_rate_limited_response(e)
        except Exception:  # noqa: BLE001 — the branch comparison below is the safe fallback
            logger.warning(
                "signals pull request lookup errored; falling back to branch",
                repository=repository,
                branch=branch,
            )
            pull_request = None
        if pull_request is not None:
            try:
                pr_result = github.get_pull_request_diff(str(repository), pull_request.number)
            except GitHubRateLimitError as e:
                return github_rate_limited_response(e)
            except Exception:  # noqa: BLE001 — the branch comparison below is the safe fallback
                logger.warning(
                    "signals pull request diff fetch errored; falling back to branch",
                    repository=repository,
                    pr_number=pull_request.number,
                )
            else:
                if pr_result.get("success"):
                    return Response(
                        CommitDiffResponseSerializer(
                            {
                                "diff": pr_result["diff"],
                                "truncated": pr_result.get("truncated", False),
                            }
                        ).data
                    )
        try:
            # Diff the commit's branch against the repo default branch, using each branch's current
            # tip (no SHA pinning) so the diff stays useful as the branch keeps moving after the
            # commit was recorded — e.g. after PR babysitting or customer tweaks.
            base_branch = github.get_default_branch(repository)
            result = github.get_diff(repository, target_branch=str(branch), base_branch=base_branch)
        except GitHubRateLimitError as e:
            return github_rate_limited_response(e)
        except Exception:  # noqa: BLE001 — never let an upstream GitHub failure 500 this endpoint
            logger.warning(
                "signals branch diff fetch errored",
                repository=repository,
                branch=branch,
            )
            return Response(
                {"error": "GitHub could not produce the diff for this branch."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        if not result.get("success"):
            # Surface a clean message rather than the raw GitHub error body. A 404 from the
            # compare API means the branch (or repo) isn't on the remote — most often a branch
            # that was merged-and-deleted or force-rewritten away.
            if result.get("status_code") == 404:
                return Response(
                    {
                        "error": f"Branch '{branch}' or repository '{repository}' was not found on GitHub — "
                        "the branch may have been deleted or merged away."
                    },
                    status=status.HTTP_404_NOT_FOUND,
                )
            logger.warning(
                "signals branch diff fetch failed",
                repository=repository,
                branch=branch,
                status_code=result.get("status_code"),
            )
            return Response(
                {"error": "GitHub could not produce the diff for this branch."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response(
            CommitDiffResponseSerializer(
                {
                    "diff": result["diff"],
                    "truncated": result.get("truncated", False),
                }
            ).data
        )


class SignalUserAutonomyConfigView(APIView):
    """Per-user signal autonomy config (singleton keyed by user).

    GET    /api/users/<id>/signal_autonomy/ → current config (or 404)
    POST   /api/users/<id>/signal_autonomy/ → create or update
    DELETE /api/users/<id>/signal_autonomy/ → remove (opt out)
    """

    serializer_class = SignalUserAutonomyConfigSerializer
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "user"
    required_scopes = ["user:write"]

    def _resolve_user(self, request, user_id):
        if str(user_id) == "@me":
            return request.user
        if not request.user.is_staff:
            raise exceptions.PermissionDenied("Only staff can access other users' autonomy config.")

        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            raise exceptions.NotFound()

    @extend_schema(responses={200: SignalUserAutonomyConfigSerializer})
    def get(self, request, user_id, **kwargs):
        user = self._resolve_user(request, user_id)
        config = SignalUserAutonomyConfig.objects.filter(user=user).first()
        if config is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(SignalUserAutonomyConfigSerializer(config).data)

    @extend_schema(
        request=SignalUserAutonomyConfigCreateSerializer, responses={200: SignalUserAutonomyConfigSerializer}
    )
    def post(self, request, user_id, **kwargs):
        user = self._resolve_user(request, user_id)
        serializer = SignalUserAutonomyConfigCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated = serializer.validated_data
        # Partial update: only touch fields the client explicitly sent. This lets the
        # auto-start setting and the Slack notification settings be edited
        # independently from separate UI surfaces without one wiping the other.
        defaults: dict = {}
        if "autostart_priority" in serializer.initial_data:
            defaults["autostart_priority"] = validated.get("autostart_priority")
        if "slack_notification_min_priority" in serializer.initial_data:
            defaults["slack_notification_min_priority"] = validated.get("slack_notification_min_priority")
        if "github_assign_on_pull_request" in serializer.initial_data:
            defaults["github_assign_on_pull_request"] = validated.get("github_assign_on_pull_request", False)
        if "github_open_pull_request_ready" in serializer.initial_data:
            defaults["github_open_pull_request_ready"] = validated.get("github_open_pull_request_ready")
        if "slack_notification_channel" in serializer.initial_data:
            defaults["slack_notification_channel"] = validated.get("slack_notification_channel") or None
        integration_in_request = "slack_notification_integration_id" in serializer.initial_data
        if integration_in_request:
            integration_id = validated.get("slack_notification_integration_id")
            integration = None
            if integration_id is not None:
                current_team_id = request.user.current_team_id
                if current_team_id is None or current_team_id not in UserPermissions(user).team_ids_visible_for_user:
                    raise serializers.ValidationError(
                        {"slack_notification_integration_id": "Unknown Slack integration for this user."}
                    )
                try:
                    integration = IntegrationManager.slack.oauth.get(current_team_id, integration_id)
                except IntegrationNotFound:
                    raise serializers.ValidationError(
                        {"slack_notification_integration_id": "Unknown Slack integration for this user."}
                    )
            defaults["slack_notification_integration"] = integration
        wants_direct_message = bool(validated.get("slack_notification_direct_message"))
        existing_config = SignalUserAutonomyConfig.objects.filter(user=user).first() if integration_in_request else None
        if (
            integration_in_request
            and "slack_notification_channel" not in serializer.initial_data
            and not wants_direct_message
            and existing_config is not None
            and existing_config.slack_notification_integration_id
            != getattr(defaults["slack_notification_integration"], "id", None)
        ):
            existing_target = existing_config.slack_notification_channel or ""
            if is_slack_member_target(existing_target) and defaults["slack_notification_integration"] is not None:
                defaults["slack_notification_channel"] = resolve_own_direct_message_target(
                    user, defaults["slack_notification_integration"]
                )
            else:
                defaults["slack_notification_channel"] = None

        target = defaults.get("slack_notification_channel")
        if wants_direct_message or (target and is_slack_member_target(target)):
            # Resolve against the workspace that would deliver it: this request's, or the saved one.
            workspace = (
                defaults["slack_notification_integration"]
                if integration_in_request
                else saved_notification_integration(user)
            )
            if wants_direct_message:
                defaults["slack_notification_channel"] = resolve_own_direct_message_target(user, workspace)
            elif target:
                validate_slack_notification_target(user, target, workspace)
        config, _created = SignalUserAutonomyConfig.objects.update_or_create(
            user=user,
            defaults=defaults,
        )
        return Response(SignalUserAutonomyConfigSerializer(config).data)

    @extend_schema(responses={204: None})
    def delete(self, request, user_id, **kwargs):
        user = self._resolve_user(request, user_id)
        SignalUserAutonomyConfig.objects.filter(user=user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class PauseUntilRequestSerializer(serializers.Serializer):
    timestamp = serializers.DateTimeField(help_text="Pause the grouping pipeline until this timestamp (ISO 8601).")


class PauseResponseSerializer(serializers.Serializer):
    status = serializers.CharField(help_text="Always 'paused'.")
    paused_until = serializers.DateTimeField(help_text="The timestamp the pipeline is paused until.")


class UnpauseResponseSerializer(serializers.Serializer):
    status = serializers.CharField(help_text="Always 'unpaused'.")
    was_paused = serializers.BooleanField(help_text="Whether the workflow was actually paused at the time of the call.")


class PauseStateResponseSerializer(serializers.Serializer):
    paused_until = serializers.DateTimeField(
        allow_null=True, help_text="The timestamp the pipeline is paused until, or null if not paused/not running."
    )


class SignalProcessingViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """View and control signal processing pipeline state for a team."""

    # Same scope family as other signals team APIs (SignalSourceConfigViewSet, etc.)
    scope_object = "task"
    scope_object_write_actions = [
        "create",
        "update",
        "partial_update",
        "patch",
        "destroy",
        "pause",
        "unpause",
    ]

    @extend_schema(request=None, responses={200: PauseStateResponseSerializer})
    def list(self, request: Request, *args, **kwargs) -> Response:
        """Return current processing state including pause status."""
        state = async_to_sync(TeamSignalGroupingV2Workflow.paused_state)(self.team.id)
        return Response({"paused_until": state.isoformat() if state else None})

    @extend_schema(request=PauseUntilRequestSerializer, responses={200: PauseResponseSerializer})
    @action(methods=["PUT", "DELETE"], detail=False, url_path="pause")
    def pause(self, request: Request, *args, **kwargs) -> Response:
        if request.method == "DELETE":
            was_paused = async_to_sync(TeamSignalGroupingV2Workflow.unpause)(self.team.id)
            return Response({"status": "unpaused", "was_paused": was_paused})

        serializer = PauseUntilRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        timestamp = serializer.validated_data["timestamp"]
        async_to_sync(TeamSignalGroupingV2Workflow.pause_until)(self.team.id, timestamp)
        return Response({"status": "paused", "paused_until": timestamp.isoformat()})
