import json
import uuid
from datetime import timedelta
from typing import cast

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import (
    BooleanField,
    Case,
    CharField,
    Count,
    Exists,
    F,
    Func,
    IntegerField,
    JSONField,
    OuterRef,
    Prefetch,
    Q,
    Subquery,
    Value,
    When,
)
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast, Coalesce

import structlog
from asgiref.sync import async_to_sync
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import exceptions, mixins, serializers, status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from temporalio.common import RetryPolicy, WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import InternalAPIAuthentication, OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication
from posthog.models import Team, User
from posthog.models.integration import GitHubIntegration, Integration
from posthog.models.team.extensions import get_or_create_team_extension
from posthog.permissions import APIScopePermission
from posthog.temporal.common.client import sync_connect
from posthog.user_permissions import UserPermissions

from products.data_warehouse.backend.data_load.service import trigger_external_data_workflow
from products.signals.backend.artefact_schemas import (
    ArtefactContentValidationError,
    Dismissal,
    SuggestedReviewers,
    parse_artefact_content,
)
from products.signals.backend.facade.api import emit_signal
from products.signals.backend.implementation_pr import fetch_implementation_pr_urls_for_reports
from products.signals.backend.models import (
    ArtefactAttribution,
    AutonomyPriority,
    InvalidStatusTransition,
    SignalReport,
    SignalReportArtefact,
    SignalSourceConfig,
    SignalTeamConfig,
    SignalUserAutonomyConfig,
)
from products.signals.backend.report_generation.resolve_reviewers import (
    get_org_member_github_login_to_user_map,
    get_org_member_github_logins_by_user_uuid,
    normalized_github_logins_from_suggested_reviewer_artefacts,
    resolve_org_github_login_to_users,
)
from products.signals.backend.serializers import (
    CommitDiffResponseSerializer,
    SignalReportArtefactLogCreateSerializer,
    SignalReportArtefactLogUpdateSerializer,
    SignalReportArtefactSerializer,
    SignalReportArtefactWriteResponseSerializer,
    SignalReportArtefactWriteSerializer,
    SignalReportSerializer,
    SignalSourceConfigSerializer,
    SignalTeamConfigSerializer,
    SignalUserAutonomyConfigCreateSerializer,
    SignalUserAutonomyConfigSerializer,
)
from products.signals.backend.task_attribution import (
    TASK_ID_HEADER,
    resolve_request_attribution,
    resolve_task_id_from_header,
)
from products.signals.backend.temporal.backfill_error_tracking import (
    BackfillErrorTrackingInput,
    BackfillErrorTrackingWorkflow,
)
from products.signals.backend.temporal.deletion import SignalReportDeletionWorkflow
from products.signals.backend.temporal.grouping_v2 import TeamSignalGroupingV2Workflow
from products.signals.backend.temporal.reingestion import SignalReportReingestionWorkflow
from products.signals.backend.temporal.signal_queries import (
    fetch_report_ids_for_source_products,
    fetch_signals_for_report_sync,
    fetch_source_products_for_reports,
)
from products.signals.backend.temporal.types import (
    SignalReportDeletionWorkflowInputs,
    SignalReportReingestionWorkflowInputs,
)
from products.tasks.backend.models import Task, TaskRun
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema

logger = structlog.get_logger(__name__)


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

    def perform_create(self, serializer):
        try:
            instance = serializer.save(team_id=self.team_id, created_by=self.request.user)
        except IntegrityError:
            raise serializers.ValidationError(
                {"source_product": "A configuration for this source product and type already exists for this team."}
            )

        if instance.source_type == SignalSourceConfig.SourceType.SESSION_ANALYSIS_CLUSTER and instance.enabled:
            self._trigger_session_analysis_setup()

        if (
            instance.source_product == SignalSourceConfig.SourceProduct.ERROR_TRACKING
            and instance.source_type == SignalSourceConfig.SourceType.ISSUE_CREATED
            and instance.enabled
        ):
            self._trigger_error_tracking_backfill()

    def _trigger_session_analysis_setup(self) -> None:
        """Upsert the per-team summarization schedule now instead of waiting for the
        reconciler's next tick. Reconciler remains the safety net."""
        from posthog.temporal.session_replay.summarization_sweep.schedule import a_upsert_team_schedule

        try:
            async_to_sync(a_upsert_team_schedule)(self.team_id)
            logger.info(f"Upserted session analysis schedule for team {self.team_id}")
        except Exception:
            logger.exception(f"Failed to upsert session analysis schedule for team {self.team_id}")

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

    def perform_update(self, serializer):
        instance = cast(SignalSourceConfig, serializer.instance)
        was_enabled = instance.enabled
        try:
            instance = serializer.save()
        except IntegrityError:
            raise serializers.ValidationError(
                {"source_product": "A configuration for this source product and type already exists for this team."}
            )

        if instance.enabled and not was_enabled:
            if instance.source_type == SignalSourceConfig.SourceType.SESSION_ANALYSIS_CLUSTER:
                self._trigger_session_analysis_setup()
            else:
                self._trigger_data_import_sync(instance)

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


class SignalTeamConfigViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Team-level signal autonomy config (singleton per team).

    GET  /signals/config/  → retrieve
    POST /signals/config/  → update
    """

    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission]
    serializer_class = SignalTeamConfigSerializer
    queryset = SignalTeamConfig.objects.all()
    scope_object = "task"

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

    @extend_schema(exclude=True)
    def list(self, request: Request, *args, **kwargs) -> Response:
        return Response(SignalTeamConfigSerializer(self._get_config()).data)

    @extend_schema(exclude=True)
    def create(self, request: Request, *args, **kwargs) -> Response:
        config = self._get_config()
        serializer = SignalTeamConfigSerializer(config, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


SIGNAL_REPORT_DISMISSAL_NOTE_MAX_LENGTH = 4000
# Upper bound on how far a snooze can push out re-promotion. Generous enough for any
# realistic snooze, but bounded so a caller can't effectively block a report forever.
SIGNAL_REPORT_MAX_SNOOZE_FOR = 100_000


class SignalReportStateRequestSerializer(serializers.Serializer):
    state = serializers.ChoiceField(
        choices=[("suppressed", "suppressed"), ("potential", "potential")],
        help_text=(
            "Target state for the report. Use 'suppressed' to dismiss the report from the inbox, "
            "or 'potential' to snooze/reopen it for later review."
        ),
    )
    dismissal_reason = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text=(
            "Optional short reason code for the dismissal (e.g. 'not_a_bug', 'wont_fix', 'duplicate'). "
            "The set of reason codes is owned by the caller and is not validated server-side."
        ),
    )
    dismissal_note = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=SIGNAL_REPORT_DISMISSAL_NOTE_MAX_LENGTH,
        help_text="Optional free-form note explaining the dismissal. Capped at 4000 characters.",
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


@extend_schema_view(
    destroy=extend_schema(exclude=True),
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
    # Shared Q for "ready but not actionable" — used in status ranking and suggested-reviewer suppression.
    # Requires `latest_actionability_value` annotation to be applied first.
    _Q_READY_NOT_ACTIONABLE = Q(status=SignalReport.Status.READY) & Q(latest_actionability_value="not_actionable")
    _DEFAULT_SIGNAL_REPORT_ORDERING = "-is_suggested_reviewer,status,-updated_at"
    _SIGNAL_REPORT_ORDERING_FIELDS: dict[str, str] = {
        "status": "pipeline_status_rank",
        "is_suggested_reviewer": "is_suggested_reviewer",
        "signal_count": "signal_count",
        "total_weight": "total_weight",
        "priority": "priority_rank",
        "created_at": "created_at",
        "updated_at": "updated_at",
        "id": "id",
    }

    def safely_get_queryset(self, queryset):
        qs = queryset
        qs = self._scope_signal_report_queryset(qs)
        qs = self._exclude_deleted_signal_reports(qs)
        qs = self._apply_signal_report_status_filter(qs)
        qs = self._apply_signal_report_search_filter(qs)
        qs = self._apply_signal_report_source_product_filter(qs)
        qs = self._apply_signal_report_suggested_reviewer_filter(qs)
        qs = self._apply_signal_report_task_filter(qs)
        qs = self._annotate_latest_actionability_value(qs)
        qs = self._annotate_signal_report_status_rank(qs)
        qs = self._annotate_signal_report_priority(qs)
        qs = self._apply_signal_report_priority_filter(qs)
        qs = self._prefetch_signal_report_priority_artefacts(qs)
        qs = self._annotate_is_suggested_reviewer(qs)
        if self.action != "list":
            qs = self._annotate_implementation_pr_url(qs)
        return qs

    def _scope_signal_report_queryset(self, queryset):
        # Count via a correlated subquery instead of `Count("artefacts")`,
        # so the main query doesn't LEFT JOIN + GROUP BY the full artefact table
        artefact_count_subquery = Subquery(
            SignalReportArtefact.objects.filter(report_id=OuterRef("id"))
            .values("report_id")
            .annotate(count=Count("*"))
            .values("count"),
            output_field=IntegerField(),
        )
        return queryset.filter(team=self.team).annotate(
            artefact_count=Coalesce(artefact_count_subquery, Value(0), output_field=IntegerField()),
        )

    def _exclude_deleted_signal_reports(self, queryset):
        # Deleted reports are terminal -- exclude from all endpoints (detail, list, actions)
        return queryset.exclude(status=SignalReport.Status.DELETED)

    def _apply_signal_report_status_filter(self, queryset):
        status_filter = self.request.query_params.get("status")
        if status_filter:
            return queryset.filter(status__in=[s.strip() for s in status_filter.split(",") if s.strip()])
        # The `state` action reopens dismissed reports, so it must be able to reach a suppressed
        # report by ID — otherwise transitioning one back to "potential" would 404. Everywhere
        # else suppressed reports stay hidden unless an explicit `status` filter asks for them.
        if self.action == "state":
            return queryset
        return queryset.exclude(status=SignalReport.Status.SUPPRESSED)

    def _apply_signal_report_search_filter(self, queryset):
        search = self.request.query_params.get("search")
        if not search:
            return queryset
        return queryset.filter(Q(title__icontains=search) | Q(summary__icontains=search))

    def _apply_signal_report_source_product_filter(self, queryset):
        source_product_filter = self.request.query_params.get("source_product")
        if not source_product_filter:
            return queryset

        source_products = [s.strip() for s in source_product_filter.split(",") if s.strip()]
        if not source_products:
            return queryset

        report_ids_with_source = fetch_report_ids_for_source_products(self.team, source_products)
        return queryset.filter(id__in=report_ids_with_source)

    def _latest_suggested_reviewers_qs(self):
        """`suggested_reviewers` rows that are the *current* (latest) version for the correlated
        outer report (`OuterRef("id")`).

        suggested_reviewers is append-only, so only the newest row is the live reviewer set —
        older versions remain as history and must not match. A row is current iff no newer row of
        the same type exists for its report.
        """
        has_newer = Exists(
            SignalReportArtefact.objects.filter(
                report_id=OuterRef("report_id"),
                type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
                created_at__gt=OuterRef("created_at"),
            )
        )
        return SignalReportArtefact.objects.filter(
            report_id=OuterRef("id"),
            type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
        ).filter(~has_newer)

    def _apply_signal_report_suggested_reviewer_filter(self, queryset):
        suggested_reviewer_filter = self.request.query_params.get("suggested_reviewers")
        if not suggested_reviewer_filter:
            return queryset

        reviewer_user_uuids = [s.strip() for s in suggested_reviewer_filter.split(",") if s.strip()]
        try:
            reviewer_user_uuids = [str(uuid.UUID(user_uuid)) for user_uuid in reviewer_user_uuids]
        except (ValueError, AttributeError) as e:
            raise serializers.ValidationError({"suggested_reviewers": f"Invalid user UUID: {e}"})

        reviewer_github_logins = list(
            get_org_member_github_logins_by_user_uuid(self.team.id, reviewer_user_uuids).values()
        )
        if not reviewer_github_logins:
            return queryset.none()

        reviewer_json_filters = [
            json.dumps([{"github_login": github_login}]) for github_login in reviewer_github_logins
        ]
        reviewer_where = " OR ".join(["content::jsonb @> %s::jsonb"] * len(reviewer_json_filters))
        return queryset.filter(
            Exists(
                # nosemgrep: python.django.security.audit.query-set-extra.avoid-query-set-extra (parameterized via params)
                self._latest_suggested_reviewers_qs().extra(
                    where=[reviewer_where],
                    params=reviewer_json_filters,
                )
            )
        )

    def _apply_signal_report_task_filter(self, queryset):
        # Reports a given task is associated with — used by running agents ("which reports am I
        # working against?") and by the agent harness to fan commit artefacts out to them.
        # Association is derived from `task_run` artefacts (their `task` attribution FK is always
        # the task they record) — artefacts are the sole source of task↔report association.
        task_filter = self.request.query_params.get("task_id")
        if not task_filter:
            return queryset
        try:
            task_uuid = uuid.UUID(task_filter.strip())
        except (ValueError, AttributeError) as e:
            raise serializers.ValidationError({"task_id": f"Invalid task UUID: {e}"})
        return queryset.filter(
            id__in=SignalReportArtefact.objects.filter(
                team=self.team,
                type=SignalReportArtefact.ArtefactType.TASK_RUN,
                task_id=task_uuid,
            ).values("report_id")
        )

    def _apply_signal_report_priority_filter(self, queryset):
        # Filters on the `priority_rank` annotation, which must be applied first.
        # Reports without a priority artefact (coalesced to "~") are excluded when this filter is set.
        priority_filter = self.request.query_params.get("priority")
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

        return queryset.filter(priority_rank__in=values)

    def _annotate_signal_report_status_rank(self, queryset):
        # `ordering=status` uses semantic stage rank (annotation), not lexicographic `status` column order.
        # `status=ready` splits into two virtual stages (requires `latest_actionability_value`):
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
                When(status=SignalReport.Status.RESOLVED, then=Value(7)),
                When(status=SignalReport.Status.SUPPRESSED, then=Value(8)),
                When(status=SignalReport.Status.DELETED, then=Value(9)),
                default=Value(50),
                output_field=IntegerField(),
            )
        )

    def _annotate_signal_report_priority(self, queryset):
        # `ordering=priority` sorts by the priority value ("P0"–"P4") from the latest priority_judgment
        # artefact. These sort lexicographically, so we extract via jsonb and coalesce NULL to "~"
        # (sorts after "P4") for reports without a priority. The startswith guard skips non-object content.
        latest_priority = Subquery(
            SignalReportArtefact.objects.filter(
                report_id=OuterRef("id"),
                type=SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT,
                content__startswith="{",
            )
            .order_by("-created_at")
            .annotate(
                _priority_val=Func(
                    Cast(F("content"), output_field=JSONField()),
                    Value("priority"),
                    function="jsonb_extract_path_text",
                    output_field=CharField(),
                ),
            )
            .values("_priority_val")[:1],
            output_field=CharField(),
        )
        return queryset.annotate(
            priority_rank=Coalesce(latest_priority, Value("~"), output_field=CharField()),
        )

    def _annotate_latest_actionability_value(self, queryset):
        # Extract the "actionability" value from the latest actionability_judgment artefact.
        latest_actionability = Subquery(
            SignalReportArtefact.objects.filter(
                report_id=OuterRef("id"),
                type=SignalReportArtefact.ArtefactType.ACTIONABILITY_JUDGMENT,
                content__startswith="{",
            )
            .order_by("-created_at")
            .annotate(
                _actionability_val=Func(
                    Cast(F("content"), output_field=JSONField()),
                    Value("actionability"),
                    function="jsonb_extract_path_text",
                    output_field=CharField(),
                ),
            )
            .values("_actionability_val")[:1],
            output_field=CharField(),
        )
        return queryset.annotate(latest_actionability_value=latest_actionability)

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
        )

    def _annotate_is_suggested_reviewer(self, queryset):
        # Annotate is_suggested_reviewer by resolving the current user's GitHub login
        # and checking jsonb containment on the artefact content list. This stays fresh
        # even when a user connects their GitHub account after the report was generated.
        # Never true for ready + not_actionable — there is nothing actionable to review.
        # Failed reports are excluded too — pipelines that errored should not bubble as "needs your review".
        github_login = self._get_github_login(self.request.user)
        if not github_login:
            return queryset.annotate(is_suggested_reviewer=Value(False))

        # github_login comes from our own UserSocialAuth DB, not user input.
        suggested_exists = Exists(
            # nosemgrep: python.django.security.audit.query-set-extra.avoid-query-set-extra (parameterized via params)
            self._latest_suggested_reviewers_qs().extra(
                where=["content::jsonb @> %s::jsonb"],
                params=[json.dumps([{"github_login": github_login}])],
            )
        )
        return queryset.annotate(
            is_suggested_reviewer=Case(
                When(self._Q_READY_NOT_ACTIONABLE, then=Value(False)),
                When(status=SignalReport.Status.FAILED, then=Value(False)),
                default=suggested_exists,
                output_field=BooleanField(),
            ),
        )

    def _annotate_implementation_pr_url(self, queryset):
        # Find the latest TaskRun output->pr_url across the tasks associated with each report.
        # Association is derived from `task_run` artefacts — "the newest PR produced by any task
        # working on this report". Path: task_run artefact -> task -> TaskRun(latest with a
        # pr_url) -> output->'pr_url'. The artefact queryset is nested one level deeper than the
        # TaskRun subquery, hence the double OuterRef back to the report.
        latest_impl_pr_url = Subquery(
            TaskRun.objects.filter(
                task_id__in=SignalReportArtefact.objects.filter(
                    report_id=OuterRef(OuterRef("id")),
                    type=SignalReportArtefact.ArtefactType.TASK_RUN,
                    task_id__isnull=False,
                ).values("task_id"),
                output__pr_url__isnull=False,
            )
            .exclude(output__pr_url="")
            .order_by("-created_at")
            .annotate(output_pr_url_text=KeyTextTransform("pr_url", "output"))
            .values("output_pr_url_text")[:1],
            output_field=CharField(),
        )
        return queryset.annotate(implementation_pr_url=latest_impl_pr_url)

    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)
        return self._apply_signal_report_ordering(queryset)

    def _parse_ordering_string(self, raw: str) -> list[str]:
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        clauses: list[str] = []
        for part in parts:
            descending = part.startswith("-")
            name = part[1:] if descending else part
            db_field = self._SIGNAL_REPORT_ORDERING_FIELDS.get(name)
            if db_field is None:
                return self._default_signal_report_ordering_clauses
            clause = f"-{db_field}" if descending else db_field
            clauses.append(clause)
        return clauses

    @property
    def _default_signal_report_ordering_clauses(self) -> list[str]:
        return self._parse_ordering_string(self._DEFAULT_SIGNAL_REPORT_ORDERING)

    def _parse_signal_report_ordering(self) -> list[str]:
        raw = self.request.query_params.get("ordering", self._DEFAULT_SIGNAL_REPORT_ORDERING)
        if not raw or not str(raw).strip():
            return self._default_signal_report_ordering_clauses
        clauses = self._parse_ordering_string(str(raw).strip())
        return clauses if clauses else self._default_signal_report_ordering_clauses

    def _apply_signal_report_ordering(self, queryset):
        clauses = self._parse_signal_report_ordering()
        has_id = any((c[1:] if c.startswith("-") else c) == "id" for c in clauses)
        if not has_id:
            clauses = [*clauses, "id"]
        return queryset.order_by(*clauses)

    @staticmethod
    def _get_github_login(user) -> str | None:
        login = user.get_github_login()
        return login.lower() if login else None

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "team": self.team}

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="status",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description=(
                    "Comma-separated list of statuses to include. "
                    "Valid values: potential, candidate, in_progress, pending_input, ready, failed, suppressed. "
                    "Defaults to all statuses except suppressed."
                ),
            ),
            OpenApiParameter(
                name="search",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Case-insensitive substring match against report title and summary.",
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
                name="suggested_reviewers",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description=(
                    "Comma-separated list of PostHog user UUIDs. Reports are kept if their suggested reviewers "
                    "include any of the given users."
                ),
            ),
            OpenApiParameter(
                name="priority",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description=(
                    "Comma-separated list of priorities to include. Valid values: P0, P1, P2, P3, P4. "
                    "Reports without a priority assignment are excluded when this filter is set."
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
                    "priority, created_at, updated_at, id. Defaults to '-is_suggested_reviewer,status,-updated_at'."
                ),
            ),
            OpenApiParameter(
                name="task_id",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Only reports associated with this task (via the report's task associations).",
            ),
        ],
    )
    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        reports = list(page if page is not None else queryset)

        report_ids = [str(r.id) for r in reports]
        source_products_map = fetch_source_products_for_reports(self.team, report_ids) if report_ids else {}
        implementation_pr_url_map = fetch_implementation_pr_urls_for_reports(report_ids)

        context = {
            **self.get_serializer_context(),
            "source_products_map": source_products_map,
            "implementation_pr_url_map": implementation_pr_url_map,
        }
        serializer = self.get_serializer(reports, many=True, context=context)

        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    @extend_schema(exclude=True)
    @action(detail=False, methods=["get"], url_path="available_reviewers", required_scopes=["task:read"])
    def available_reviewers(self, request, **kwargs):
        login_to_user = get_org_member_github_login_to_user_map(self.team.id) or {}
        query = (request.query_params.get("query") or "").strip().lower()

        users_by_uuid = {str(user.uuid): user for user in login_to_user.values()}

        filtered_users = [
            (user_uuid, user)
            for user_uuid, user in users_by_uuid.items()
            if not query
            or query in f"{user.first_name} {user.last_name}".strip().lower()
            or query in (user.email or "").lower()
        ]

        reviewers = {
            user_uuid: {
                "name": f"{user.first_name} {user.last_name}".strip(),
                "email": user.email or "",
            }
            for user_uuid, user in sorted(
                filtered_users,
                key=lambda item: (
                    (item[1].first_name or "").lower(),
                    (item[1].last_name or "").lower(),
                    (item[1].email or "").lower(),
                    item[0],
                ),
            )[:100]
        }

        return Response(reviewers)

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
        report.save(update_fields=updated_fields)

        return Response({"status": "deletion_started", "report_id": report_id}, status=status.HTTP_202_ACCEPTED)

    @extend_schema(exclude=True)
    @action(detail=True, methods=["get"], url_path="signals", required_scopes=["task:read"])
    def signals(self, request, pk=None, **kwargs):
        """Fetch all signals for a report from ClickHouse, including full metadata."""
        report = self.get_object()
        report_data = SignalReportSerializer(report).data
        signals_list = fetch_signals_for_report_sync(self.team, str(report.id))
        return Response({"report": report_data, "signals": signals_list})

    @extend_schema(
        request=SignalReportStateRequestSerializer,
        responses={200: SignalReportSerializer},
    )
    @action(detail=True, methods=["post"], url_path="state", required_scopes=["task:write"])
    def state(self, request, pk=None, **kwargs):
        """
        Transition a report to a new state. The model validates allowed transitions.

        The request body is validated by SignalReportStateRequestSerializer — only the
        fields it declares (state, dismissal_reason, dismissal_note, snooze_for) are read,
        and only snooze_for is ever forwarded to transition_to. Any other key is ignored,
        so internal transition_to kwargs (reset_weight, error, ...) can't be injected.

        Body: {
            "state": "suppressed" | "potential",
            # Optional dismissal feedback (honored when state == "suppressed" or "potential"):
            "dismissal_reason": "<any string code, owned by the caller>",
            "dismissal_note": "free-form text",
            # Optional, only honored for state == "potential":
            "snooze_for": <number of additional signals before re-promotion>,
        }
        """
        report = cast(SignalReport, self.get_object())

        serializer = SignalReportStateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        target = data["state"]
        dismissal_reason = data.get("dismissal_reason")
        dismissal_note = data.get("dismissal_note")

        # Only `snooze_for` (on a snooze back to "potential") is caller-controllable. Every other
        # `transition_to` kwarg (signals_at_run_increment, reset_weight, title, summary, error) is an
        # internal pipeline concern and must never be reachable from this public API surface, so it is
        # passed explicitly rather than splatting caller-supplied kwargs.
        snooze_for = data.get("snooze_for") if target == "potential" else None

        try:
            updated_fields = report.transition_to(SignalReport.Status(target), snooze_for=snooze_for)
        except InvalidStatusTransition as e:
            logger.warning("Invalid status transition for SignalReport %s: %s", report.id, e, exc_info=True)
            return Response(
                {"error": "Invalid state transition for this report."},
                status=status.HTTP_409_CONFLICT,
            )
        except (ValueError, TypeError) as e:
            logger.warning("Invalid data when transitioning SignalReport %s: %s", report.id, e, exc_info=True)
            return Response(
                {"error": "Invalid data for state transition."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            report.save(update_fields=updated_fields)

            # Persist the dismissal feedback as its own artefact so it survives status changes
            # and so multiple dismissals (with different rationales) can stack over time.
            # Captured for both suppress and snooze (transition to potential) flows.
            if target in ("suppressed", "potential") and (dismissal_reason or dismissal_note):
                user = request.user
                SignalReportArtefact.append_dismissal(
                    team_id=self.team.id,
                    report_id=str(report.id),
                    content=Dismissal(
                        reason=dismissal_reason,
                        note=dismissal_note,
                        user_id=getattr(user, "id", None) if getattr(user, "is_authenticated", False) else None,
                        user_uuid=str(user.uuid)
                        if getattr(user, "is_authenticated", False) and getattr(user, "uuid", None)
                        else None,
                    ),
                    attribution=resolve_request_attribution(request, self.team.id),
                )

        return Response(SignalReportSerializer(report, context=self.get_serializer_context()).data)

    @extend_schema(exclude=True)
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


@extend_schema_view(
    list=extend_schema(
        summary="List a report's artefacts",
        description=(
            "List every artefact on a report — the full work log: signal findings (the evidence "
            "behind the report), status judgments (safety / actionability / priority, repo "
            "selection, suggested reviewers — the newest row of each status type is canonical), "
            "and log entries (code references, commits, task runs, notes). "
            "`suggested_reviewers` content is enriched with PostHog user info at read time."
        ),
        responses={200: SignalReportArtefactSerializer(many=True)},
        operation_id="signals_report_artefacts_list",
    ),
    retrieve=extend_schema(
        summary="Get a single artefact",
        description="Get one artefact by id, content parsed (and reviewers enriched) the same way as the list.",
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
    - POST / PATCH / DELETE manage artefacts of *any* type — no type is writer-restricted.
      Log entries accumulate; status types (judgments, repo selection, suggested reviewers)
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
    queryset = SignalReportArtefact.objects.select_related("created_by").order_by("-created_at")
    http_method_names = ["get", "post", "put", "patch", "delete", "head", "options"]

    def safely_get_queryset(self, queryset):
        # Mirror SignalReportViewSet: a deleted parent report is unreachable, so
        # its artefacts must be too (otherwise a known UUID would bypass deletion).
        return queryset.filter(
            report_id=self.parents_query_dict["report_id"],
            team=self.team,
        ).exclude(report__status=SignalReport.Status.DELETED)

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        artefacts = list(page if page is not None else queryset)
        logins_union = normalized_github_logins_from_suggested_reviewer_artefacts(artefacts)
        login_map = resolve_org_github_login_to_users(self.team.id, logins_union) if logins_union else {}
        serializer = SignalReportArtefactSerializer(
            artefacts,
            many=True,
            context={
                **self.get_serializer_context(),
                "signals_github_login_to_user_map": login_map,
            },
        )
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

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
        entries = write_serializer.validated_data["content"]

        # Resolved before the locked transaction below — header validation must not hold the lock.
        attribution = resolve_request_attribution(request, self.team.id)

        # Resolve any user_uuid → canonical github_login via team org membership.
        uuids_to_resolve = [str(e["user_uuid"]) for e in entries if e.get("user_uuid")]
        uuid_to_login: dict[str, str] = (
            get_org_member_github_logins_by_user_uuid(self.team.id, uuids_to_resolve) if uuids_to_resolve else {}
        )

        # Resolve canonical login per entry. Fail loudly if a user_uuid does not
        # map to an org member with a GitHub identity on this team.
        # The third tuple element distinguishes "github_name explicitly supplied
        # (incl. empty string to clear)" from "field absent" — the merge step below
        # only falls back to the prior name when the field is absent.
        resolved_entries: list[tuple[str, str | None, bool]] = []
        for idx, entry in enumerate(entries):
            user_uuid = entry.get("user_uuid")
            if user_uuid is not None:
                resolved_login = uuid_to_login.get(str(user_uuid))
                if not resolved_login:
                    return Response(
                        {
                            "error": (
                                f"content[{idx}]: user_uuid '{user_uuid}' is not an org member of this team "
                                "with a linked GitHub identity."
                            )
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                login_lc = resolved_login.lower()
            else:
                raw_login = entry.get("github_login") or ""
                login_lc = raw_login.strip().lower()
                if not login_lc:
                    return Response(
                        {"error": f"content[{idx}]: github_login resolved to empty after normalization."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

            explicit_name = "github_name" in entry
            github_name = entry.get("github_name") if explicit_name else None
            resolved_entries.append((login_lc, github_name, explicit_name))

        # Lock the report for the read-merge-append so concurrent reviewer edits serialize — each
        # PUT reads the current (latest) reviewers and appends a new row, so without the lock two
        # simultaneous edits would both read the same row and one would be silently lost.
        seen: set[str] = set()
        with transaction.atomic():
            SignalReport.objects.select_for_update().filter(id=artefact.report_id, team_id=self.team_id).first()

            # Merge commits/names forward from the *current* reviewers (the latest status row), not
            # necessarily the addressed one — `suggested_reviewers` is append-only and latest-wins.
            current = (
                SignalReportArtefact.objects.filter(
                    report_id=artefact.report_id,
                    type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
                )
                .order_by("-created_at")
                .first()
            )
            try:
                prior_content = json.loads((current or artefact).content)
            except (json.JSONDecodeError, ValueError):
                prior_content = []
            prior_commits_by_login: dict[str, list] = {}
            prior_name_by_login: dict[str, str | None] = {}
            if isinstance(prior_content, list):
                for prior in prior_content:
                    if not isinstance(prior, dict):
                        continue
                    login = (prior.get("github_login") or "").strip().lower()
                    if not login:
                        continue
                    commits = prior.get("relevant_commits")
                    if isinstance(commits, list):
                        prior_commits_by_login[login] = commits
                    prior_name = prior.get("github_name")
                    if isinstance(prior_name, str):
                        prior_name_by_login[login] = prior_name

            # Dedupe by canonical login, preserve first-seen order.
            new_content: list[dict] = []
            for login_lc, github_name, explicit_name in resolved_entries:
                if login_lc in seen:
                    continue
                seen.add(login_lc)
                # If the client supplied github_name (incl. ""), honour it. Otherwise
                # carry over the prior one so kept reviewers don't lose their name.
                effective_name = github_name if explicit_name else prior_name_by_login.get(login_lc)
                new_content.append(
                    {
                        "github_login": login_lc,
                        "github_name": effective_name,
                        "relevant_commits": prior_commits_by_login.get(login_lc, []),
                    }
                )

            # Append a new status row rather than mutating in place: a human reviewer edit becomes a
            # point-in-time entry in the work log, and latest-wins keeps it current. Appending a
            # reviewers status also re-evaluates auto-start (handled in `append_status`, on commit).
            new_artefact = SignalReportArtefact.append_status(
                team_id=self.team.id,
                report_id=str(artefact.report_id),
                content=SuggestedReviewers.model_validate(new_content),
                attribution=attribution,
            )

        # Return the read-shape (enriched) so the client sees the canonical result.
        login_map = resolve_org_github_login_to_users(self.team.id, list(seen)) if seen else {}
        read_serializer = SignalReportArtefactSerializer(
            new_artefact,
            context={
                **self.get_serializer_context(),
                "signals_github_login_to_user_map": login_map,
            },
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
                "report_id": artefact.report_id,
                "type": artefact.type,
                "content": parsed_content,
                "created_at": artefact.created_at,
                "updated_at": artefact.updated_at,
                "task_id": artefact.task_id,
            }
        ).data

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
            "Append an artefact of any type to a report. Everything is append-only: log entries "
            "(code reference, line reference, commit, task run, note) accumulate, while "
            "status types (safety / actionability / priority judgments, repo selection, suggested "
            "reviewers) are latest-wins — appending a new version supersedes the previous one as the "
            "report's canonical status. Content is validated against the type's schema."
        ),
        operation_id="signals_report_artefacts_create",
    )
    def create(self, request: ValidatedRequest, *args, **kwargs) -> Response:
        report_id = self.parents_query_dict["report_id"]
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
        if artefact_type not in SignalReportArtefact.ArtefactType.values:
            return Response(
                {
                    "error": (
                        f"Unknown artefact type '{artefact_type}'. "
                        f"Valid types: {', '.join(sorted(SignalReportArtefact.ArtefactType.values))}."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        content = request.validated_data["content"]
        attribution = resolve_request_attribution(request, self.team.id)
        if artefact_type == SignalReportArtefact.ArtefactType.TASK_RUN:
            # task_run artefacts are the task↔report association itself, so they get
            # associate-me ergonomics: content.task_id defaults to the calling agent's task
            # (the header), product/type default to a generic agent-run label, the named task
            # must belong to this project, attribution is always the recorded task, and
            # re-associating an already-linked task is idempotent (returns the existing entry).
            if not isinstance(content, dict):
                return Response(
                    {"error": "task_run content must be a JSON object."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            task_id = content.get("task_id") or resolve_task_id_from_header(request, self.team.id)
            if not task_id:
                return Response(
                    {"error": "Provide content.task_id, or call with an X-PostHog-Task-Id header."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if not Task.objects.filter(id=task_id, team=self.team).exists():
                return Response(
                    {"error": "Unknown task for this project."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            content = {**content, "task_id": str(task_id)}
            content.setdefault("product", "tasks")
            content.setdefault("type", "agent_run")
            existing = (
                SignalReportArtefact.objects.filter(
                    team=self.team,
                    report_id=report_id,
                    type=SignalReportArtefact.ArtefactType.TASK_RUN,
                    task_id=task_id,
                )
                .order_by("created_at")
                .first()
            )
            if existing is not None:
                return Response(self._write_response_data(existing), status=status.HTTP_200_OK)
            attribution = ArtefactAttribution.from_task(str(task_id))
        # The write boundary: parse the raw payload into the type's content model once; the
        # typed model is what flows into the append helpers.
        try:
            parsed_content = parse_artefact_content(artefact_type, content)
        except ArtefactContentValidationError as e:
            return Response(
                {"error": f"content does not match the '{artefact_type}' schema: {e}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        artefact = SignalReportArtefact.append(
            team_id=self.team.id,
            report_id=report_id,
            content=parsed_content,
            attribution=attribution,
        )
        return Response(self._write_response_data(artefact), status=status.HTTP_201_CREATED)

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
        operation_id="signals_report_artefacts_partial_update",
    )
    def partial_update(self, request: ValidatedRequest, *args, **kwargs) -> Response:
        artefact = cast(SignalReportArtefact, self.get_object())
        try:
            artefact.update_content(request.validated_data["content"])
        except ArtefactContentValidationError as e:
            return Response(
                {"error": f"content does not match the '{artefact.type}' schema: {e}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(self._write_response_data(artefact))

    @extend_schema(
        responses={
            204: OpenApiResponse(description="Artefact deleted."),
            404: OpenApiResponse(description="Artefact not found for this report / project."),
        },
        summary="Delete an artefact",
        description=(
            "Delete an artefact, addressed by id. Deleting the latest row of a status type reverts "
            "the report's canonical status to the previous version (latest-wins over what remains)."
        ),
        operation_id="signals_report_artefacts_destroy",
    )
    def destroy(self, request, *args, **kwargs) -> Response:
        artefact = cast(SignalReportArtefact, self.get_object())
        artefact.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        responses={
            200: OpenApiResponse(
                response=CommitDiffResponseSerializer,
                description="The branch's unified diff against the repository default branch.",
            ),
            400: OpenApiResponse(description="Artefact is not a commit, or is missing repository/branch."),
            404: OpenApiResponse(description="Artefact not found, or no GitHub integration can access the repository."),
            502: OpenApiResponse(description="GitHub could not produce the diff (branch not found, fetch failed)."),
        },
        summary="Fetch the diff for a commit artefact",
        description=(
            "Fetch the unified diff of a `commit` artefact's branch against the repository default "
            "branch via the team's GitHub integration — using the branch's current tip so the diff "
            "reflects the latest state of the work, not just the single recorded commit."
        ),
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
        github = GitHubIntegration.first_for_team_repository(self.team.id, repository)
        if github is None:
            return Response(
                {"error": f"No GitHub integration can access '{repository}'."},
                status=status.HTTP_404_NOT_FOUND,
            )
        try:
            # Diff the commit's branch against the repo default branch, using each branch's current
            # tip (no SHA pinning) so the diff stays useful as the branch keeps moving after the
            # commit was recorded — e.g. after PR babysitting or customer tweaks.
            base_branch = github.get_default_branch(repository)
            result = github.get_diff(repository, target_branch=str(branch), base_branch=base_branch)
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
            {
                "diff": result["diff"],
                "truncated": result.get("truncated", False),
            }
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

    @extend_schema(responses={200: SignalUserAutonomyConfigSerializer})
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
        if "slack_notification_channel" in serializer.initial_data:
            defaults["slack_notification_channel"] = validated.get("slack_notification_channel") or None
        if "slack_notification_integration_id" in serializer.initial_data:
            integration_id = validated.get("slack_notification_integration_id")
            integration = None
            if integration_id is not None:
                current_team_id = request.user.current_team_id
                if current_team_id is None or current_team_id not in UserPermissions(user).team_ids_visible_for_user:
                    raise serializers.ValidationError(
                        {"slack_notification_integration_id": "Unknown Slack integration for this user."}
                    )
                candidate = Integration.objects.filter(
                    pk=integration_id,
                    kind="slack",
                    team_id=current_team_id,
                ).first()
                if candidate is None:
                    raise serializers.ValidationError(
                        {"slack_notification_integration_id": "Unknown Slack integration for this user."}
                    )
                integration = candidate
            defaults["slack_notification_integration"] = integration
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
