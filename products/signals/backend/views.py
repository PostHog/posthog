import json
import uuid
from datetime import timedelta
from typing import cast

from django.conf import settings
from django.db import IntegrityError
from django.db.models import (
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
from django.db.models.functions import Cast, Coalesce

import structlog
from asgiref.sync import async_to_sync
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from temporalio.common import RetryPolicy, WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import InternalAPIAuthentication, OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication
from posthog.models import Team
from posthog.permissions import APIScopePermission
from posthog.temporal.ai.video_segment_clustering.constants import clustering_workflow_id
from posthog.temporal.ai.video_segment_clustering.models import ClusteringWorkflowInputs
from posthog.temporal.common.client import sync_connect

from products.data_warehouse.backend.data_load.service import trigger_external_data_workflow
from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema
from products.signals.backend.api import emit_signal
from products.signals.backend.models import (
    InvalidStatusTransition,
    SignalReport,
    SignalReportArtefact,
    SignalSourceConfig,
)
from products.signals.backend.report_generation.resolve_reviewers import (
    get_org_member_github_login_to_user_map,
    get_org_member_github_logins_by_user_uuid,
)
from products.signals.backend.serializers import (
    SignalReportArtefactSerializer,
    SignalReportSerializer,
    SignalSourceConfigSerializer,
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
)
from products.signals.backend.temporal.types import (
    SignalReportDeletionWorkflowInputs,
    SignalReportReingestionWorkflowInputs,
)

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
            self._trigger_initial_clustering(instance)

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

    def _trigger_initial_clustering(self, config: SignalSourceConfig) -> None:
        """Fire-and-forget the clustering workflow."""
        try:
            client = sync_connect()
            async_to_sync(client.start_workflow)(  # type: ignore
                "video-segment-clustering",  # type: ignore
                ClusteringWorkflowInputs(team_id=self.team_id),  # type: ignore
                id=clustering_workflow_id(self.team_id, config.id),
                id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
            logger.info(f"Started initial clustering workflow for team {self.team_id}")
        except Exception:
            logger.exception(f"Failed to start initial clustering workflow for team {self.team_id}")

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
                self._trigger_initial_clustering(instance)
            else:
                self._trigger_data_import_sync(instance)
        elif not instance.enabled and was_enabled:
            if instance.source_type == SignalSourceConfig.SourceType.SESSION_ANALYSIS_CLUSTER:
                self._cancel_clustering_workflow(instance)

    def _cancel_clustering_workflow(self, config: SignalSourceConfig) -> None:
        """Cancel the running clustering workflow for the team, if any."""
        workflow_id = clustering_workflow_id(self.team_id, config.id)
        try:
            client = sync_connect()
            handle = client.get_workflow_handle(workflow_id)
            async_to_sync(handle.cancel)()
            logger.info("Cancelled clustering workflow for team %s", self.team_id)
        except RPCError as e:
            if e.status == RPCStatusCode.NOT_FOUND:
                return
            logger.exception("Failed to cancel clustering workflow for team %s", self.team_id)
        except Exception:
            logger.exception("Failed to cancel clustering workflow for team %s", self.team_id)

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


@extend_schema_view(
    list=extend_schema(exclude=True),
    retrieve=extend_schema(exclude=True),
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
        qs = self._annotate_signal_report_status_rank(qs)
        qs = self._annotate_signal_report_priority(qs)
        qs = self._prefetch_signal_report_priority_artefacts(qs)
        qs = self._annotate_is_suggested_reviewer(qs)
        return qs

    def _scope_signal_report_queryset(self, queryset):
        return queryset.filter(team=self.team).annotate(artefact_count=Count("artefacts"))

    def _exclude_deleted_signal_reports(self, queryset):
        # Deleted reports are terminal -- exclude from all endpoints (detail, list, actions)
        return queryset.exclude(status=SignalReport.Status.DELETED)

    def _apply_signal_report_status_filter(self, queryset):
        status_filter = self.request.query_params.get("status")
        if status_filter:
            return queryset.filter(status__in=[s.strip() for s in status_filter.split(",") if s.strip()])
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
                SignalReportArtefact.objects.filter(
                    report_id=OuterRef("id"),
                    type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
                ).extra(
                    where=[reviewer_where],
                    params=reviewer_json_filters,
                )
            )
        )

    def _annotate_signal_report_status_rank(self, queryset):
        # `ordering=status` uses semantic stage rank (annotation), not lexicographic `status` column order.
        return queryset.annotate(
            pipeline_status_rank=Case(
                When(status=SignalReport.Status.READY, then=Value(0)),
                When(status=SignalReport.Status.PENDING_INPUT, then=Value(1)),
                When(status=SignalReport.Status.IN_PROGRESS, then=Value(2)),
                When(status=SignalReport.Status.CANDIDATE, then=Value(3)),
                When(status=SignalReport.Status.POTENTIAL, then=Value(4)),
                When(status=SignalReport.Status.FAILED, then=Value(5)),
                When(status=SignalReport.Status.SUPPRESSED, then=Value(6)),
                When(status=SignalReport.Status.DELETED, then=Value(7)),
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
        github_login = self._get_github_login(self.request.user)
        if not github_login:
            return queryset.annotate(is_suggested_reviewer=Value(False))

        # github_login comes from our own UserSocialAuth DB, not user input.
        return queryset.annotate(
            is_suggested_reviewer=Exists(
                # nosemgrep: python.django.security.audit.query-set-extra.avoid-query-set-extra (parameterized via params)
                SignalReportArtefact.objects.filter(
                    report_id=OuterRef("id"),
                    type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
                ).extra(
                    where=["content::jsonb @> %s::jsonb"],
                    params=[json.dumps([{"github_login": github_login}])],
                )
            )
        )

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
    @action(detail=True, methods=["get"], url_path="artefacts", required_scopes=["task:read"])
    def artefacts(self, request, pk=None, **kwargs):
        report = cast(SignalReport, self.get_object())
        artefacts = report.artefacts.all().order_by("-created_at")
        serializer = SignalReportArtefactSerializer(artefacts, many=True)
        return Response(
            {
                "results": serializer.data,
                "count": len(serializer.data),
            }
        )

    @extend_schema(exclude=True)
    @action(detail=True, methods=["get"], url_path="signals", required_scopes=["task:read"])
    def signals(self, request, pk=None, **kwargs):
        """Fetch all signals for a report from ClickHouse, including full metadata."""
        report = self.get_object()
        report_data = SignalReportSerializer(report).data
        signals_list = fetch_signals_for_report_sync(self.team, str(report.id))
        return Response({"report": report_data, "signals": signals_list})

    @extend_schema(exclude=True)
    @action(detail=True, methods=["post"], url_path="state", required_scopes=["task:write"])
    def state(self, request, pk=None, **kwargs):
        """
        Transition a report to a new state. The model validates allowed transitions.

        Body: { "state": "suppressed" | "potential", ...kwargs passed to transition_to }
        """
        report = cast(SignalReport, self.get_object())

        target = request.data.get("state")
        if target not in ("suppressed", "potential"):
            return Response(
                {"error": "state must be one of ['suppressed', 'potential']"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        transition_kwargs = {k: v for k, v in request.data.items() if k != "state"}
        try:
            updated_fields = report.transition_to(SignalReport.Status(target), **transition_kwargs)
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

        report.save(update_fields=updated_fields)

        return Response(SignalReportSerializer(report, context=self.get_serializer_context()).data)

    @extend_schema(exclude=True)
    @action(detail=True, methods=["post"], url_path="reingest", required_scopes=["task:write"])
    def reingest(self, request, pk=None, **kwargs):
        """Re-ingest a report's signals. Staff-only."""
        if not request.user.is_staff:
            return Response(
                {"error": "Only staff users can reingest reports."},
                status=status.HTTP_403_FORBIDDEN,
            )

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

    scope_object = "INTERNAL"

    @extend_schema(request=None, responses={200: PauseStateResponseSerializer})
    def list(self, request: Request, *args, **kwargs) -> Response:
        """Return current processing state including pause status."""
        state = async_to_sync(TeamSignalGroupingV2Workflow.paused_state)(self.team.id)
        return Response({"paused_until": state.isoformat() if state else None})

    @extend_schema(request=PauseUntilRequestSerializer, responses={200: PauseResponseSerializer})
    @action(methods=["PUT"], detail=False, url_path="pause")
    def pause(self, request: Request, *args, **kwargs) -> Response:
        serializer = PauseUntilRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        timestamp = serializer.validated_data["timestamp"]
        async_to_sync(TeamSignalGroupingV2Workflow.pause_until)(self.team.id, timestamp)
        return Response({"status": "paused", "paused_until": timestamp.isoformat()})

    @extend_schema(request=None, responses={200: UnpauseResponseSerializer})
    @action(methods=["POST"], detail=False, url_path="unpause")
    def unpause(self, request: Request, *args, **kwargs) -> Response:
        was_paused = async_to_sync(TeamSignalGroupingV2Workflow.unpause)(self.team.id)
        return Response({"status": "unpaused", "was_paused": was_paused})
