import os
import re
import json
import uuid
import asyncio
import logging
import builtins
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

from django.conf import settings
from django.db import models, transaction
from django.db.models import F, OuterRef, Q, Subquery
from django.db.models.functions import JSONObject
from django.http import HttpResponse, JsonResponse, StreamingHttpResponse
from django.utils import timezone

import requests as http_requests
import jsonschema
import posthoganalytics
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from posthog.api.mixins import validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import ServerTimingsGathered
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication
from posthog.event_usage import groups
from posthog.models.integration import Integration
from posthog.models.user_push_token import UserPushToken
from posthog.permissions import APIScopePermission
from posthog.rate_limit import CodeInviteThrottle
from posthog.renderers import ServerSentEventRenderer
from posthog.storage import object_storage
from posthog.temporal.oauth import PosthogMcpScopes

from products.slack_app.backend.models import SlackThreadTaskMapping

from ee.hogai.utils.aio import async_to_sync

from .access import has_tasks_access
from .automation_service import (
    delete_automation_schedule,
    run_task_automation,
    sync_automation_schedule,
    update_automation_run_result,
)
from .constants import CODEX_SERVICE_TIER_CHOICES, SERVICE_TIER_CONFIG_ID
from .metrics import (
    StreamConnectionOutcome,
    observe_stream_connection_closed,
    observe_stream_connection_opened,
    observe_stream_length_on_connect,
    observe_stream_resume_gap,
    origin_product_label,
)
from .models import (
    TASK_PRESENCE_TTL_SECONDS,
    CodeInvite,
    CodeInviteRedemption,
    SandboxEnvironment,
    Task,
    TaskAutomation,
    TaskPresence,
    TaskRun,
)
from .redis import get_tasks_cache, run_uses_dedicated_stream
from .repository_readiness import compute_repository_readiness
from .serializers import (
    CodeInviteRedeemRequestSerializer,
    ConnectionTokenResponseSerializer,
    RepositoryReadinessQuerySerializer,
    RepositoryReadinessResponseSerializer,
    SandboxEnvironmentListSerializer,
    SandboxEnvironmentSerializer,
    SlackThreadContextQuerySerializer,
    SlackThreadContextResponseSerializer,
    TaskAutomationSerializer,
    TaskListQuerySerializer,
    TaskPresenceBeaconRequestSerializer,
    TaskRepositoriesResponseSerializer,
    TaskRunAppendLogRequestSerializer,
    TaskRunArtifactPresignRequestSerializer,
    TaskRunArtifactPresignResponseSerializer,
    TaskRunArtifactsFinalizeUploadRequestSerializer,
    TaskRunArtifactsFinalizeUploadResponseSerializer,
    TaskRunArtifactsPrepareUploadRequestSerializer,
    TaskRunArtifactsPrepareUploadResponseSerializer,
    TaskRunArtifactsUploadRequestSerializer,
    TaskRunArtifactsUploadResponseSerializer,
    TaskRunBootstrapCreateRequestSerializer,
    TaskRunCommandRequestSerializer,
    TaskRunCommandResponseSerializer,
    TaskRunCreateRequestSchemaSerializer,
    TaskRunCreateRequestSerializer,
    TaskRunDetailSerializer,
    TaskRunErrorResponseSerializer,
    TaskRunRelayMessageRequestSerializer,
    TaskRunRelayMessageResponseSerializer,
    TaskRunSessionLogsQuerySerializer,
    TaskRunSetOutputRequestSerializer,
    TaskRunStartRequestSerializer,
    TaskRunUpdateSerializer,
    TaskSerializer,
    TaskStagedArtifactsFinalizeUploadRequestSerializer,
    TaskStagedArtifactsFinalizeUploadResponseSerializer,
    TaskStagedArtifactsPrepareUploadRequestSerializer,
    TaskStagedArtifactsPrepareUploadResponseSerializer,
    TaskSummariesRequestSerializer,
    TaskSummarySerializer,
    build_task_run_artifact_size_error,
    get_task_run_artifact_max_size_bytes,
)
from .services.code_usage_gate import cloud_usage_limit_response
from .services.connection_token import create_sandbox_connection_token
from .services.staged_artifacts import (
    RUN_ARTIFACT_TTL_DAYS,
    STAGED_ARTIFACT_TTL_DAYS,
    build_task_artifact_entry,
    build_task_staged_artifact_cache_key,
    build_task_staged_artifact_storage_path,
    cache_task_staged_artifact,
    get_safe_artifact_name,
    get_task_run_artifacts_by_id,
    get_task_staged_artifacts,
    tag_task_artifact,
)
from .stream.redis_stream import (
    TASK_RUN_STREAM_WAIT_DELAY_INCREMENT_SECONDS,
    TASK_RUN_STREAM_WAIT_INITIAL_DELAY_SECONDS,
    TASK_RUN_STREAM_WAIT_MAX_DELAY_SECONDS,
    TASK_RUN_STREAM_WAIT_TIMEOUT_SECONDS,
    TaskRunRedisStream,
    TaskRunStreamError,
    get_task_run_stream_key,
)
from .temporal.client import (
    execute_posthog_code_agent_relay_workflow,
    execute_task_processing_workflow,
    resume_task_in_cloud_workflow,
    signal_task_followup_message,
)
from .temporal.process_task.utils import (
    GitHubCredentialSource,
    PrAuthorshipMode,
    RunSource,
    cache_github_user_token,
    get_pr_authorship_mode,
    get_provider_for_runtime_adapter,
    get_reasoning_effort_error,
    parse_run_state,
    resolve_user_github_integration_for_task,
    user_github_integration_is_usable,
)
from .visibility import task_run_visibility_q, task_visibility_q

logger = logging.getLogger(__name__)
TASK_RUN_STREAM_KEEPALIVE_INTERVAL_SECONDS = 20.0
TASK_RUN_STREAM_KEEPALIVE_EVENT_NAME = "keepalive"
TASK_RUN_STREAM_KEEPALIVE_PAYLOAD = {"type": "keepalive"}
TASK_RUN_ARTIFACT_UPLOAD_EXPIRATION_SECONDS = 60 * 60


def _ensure_task_team_github_integration(task: Task) -> bool:
    if task.github_integration_id is not None:
        return True

    github_integration = Integration.objects.filter(team_id=task.team_id, kind="github").first()
    if github_integration is None:
        return False

    task.github_integration = github_integration
    task.save(update_fields=["github_integration", "updated_at"])
    return True


def _resolve_cloud_pr_authorship_mode(
    task: Task,
    *,
    pr_authorship_mode: PrAuthorshipMode | str | None,
    request_user_id: int | None,
    github_user_token: str | None,
) -> tuple[PrAuthorshipMode | str | None, Response | None]:
    if pr_authorship_mode != PrAuthorshipMode.USER or github_user_token:
        return pr_authorship_mode, None

    if task.created_by_id != request_user_id:
        return None, Response(
            {
                "type": "validation_error",
                "code": "github_authorization_required",
                "detail": "User-authored runs must be started by the task creator, or provide github_user_token.",
                "attr": "pr_authorship_mode",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    user_github_integration = resolve_user_github_integration_for_task(task, allow_refresh=False)
    if user_github_integration is not None and user_github_integration_is_usable(user_github_integration):
        if task.github_user_integration_id != user_github_integration.integration.id:
            task.github_user_integration = user_github_integration.integration
            task.save(update_fields=["github_user_integration", "updated_at"])
        return PrAuthorshipMode.USER, None

    if _ensure_task_team_github_integration(task):
        return PrAuthorshipMode.BOT, None

    return None, Response(
        {
            "type": "validation_error",
            "code": "github_authorization_required",
            "detail": ("Link a GitHub account with repo access before running user-authored cloud tasks."),
            "attr": "pr_authorship_mode",
        },
        status=status.HTTP_400_BAD_REQUEST,
    )


def _github_credential_source_extra_state(
    pr_authorship_mode: PrAuthorshipMode | str | None, github_user_token: str | None
) -> dict[str, str]:
    """Durable marker of which GitHub identity a run is pinned to, decided once at creation.

    A caller-supplied token is owned by the caller and un-refreshable by us, so the refresh
    loop must never swap it for the task creator's server integration. Persisting the source
    in run state keeps that decision durable (the per-run token cache only lives ~6h).
    """
    if pr_authorship_mode != PrAuthorshipMode.USER:
        return {}
    source = GitHubCredentialSource.CALLER_TOKEN if github_user_token else GitHubCredentialSource.SERVER_INTEGRATION
    return {"github_credential_source": source.value}


# Run-state keys that are server-owned and must never be mutable through the PATCH endpoint:
#   - github_credential_source / pr_authorship_mode fix the run's GitHub identity at creation;
#     a caller could otherwise flip a caller-token run to ``server_integration`` and have the
#     task creator's server-side token injected into their sandbox.
#   - sandbox_id is the credential-propagation target; a caller could otherwise repoint a visible
#     run at a sandbox they control and capture the run owner's token on the next rotation.
# All three are written only server-side (run creation + the temporal workflow), never via PATCH.
_PROTECTED_RUN_STATE_KEYS = frozenset({"github_credential_source", "pr_authorship_mode", "sandbox_id"})


TASK_RUN_ARTIFACT_UPLOAD_FORM_OVERHEAD_BYTES = 64 * 1024


def _is_internal_debug_team(team_id: int | None) -> bool:
    if settings.DEBUG and not settings.TEST:
        return team_id == 1
    return team_id == 2 and settings.CLOUD_DEPLOYMENT == "US"


class _SchemaAwareLimitOffsetPagination(LimitOffsetPagination):
    """LimitOffsetPagination subclass that surfaces `default_limit`/`max_limit` in the OpenAPI schema."""

    def get_schema_operation_parameters(self, view):
        parameters = super().get_schema_operation_parameters(view)
        for parameter in parameters:
            if parameter.get("name") == self.limit_query_param:
                parameter["schema"]["default"] = self.default_limit
                if self.max_limit is not None:
                    parameter["schema"]["maximum"] = self.max_limit
                parameter["schema"]["minimum"] = 1
            elif parameter.get("name") == self.offset_query_param:
                parameter["schema"]["default"] = 0
                parameter["schema"]["minimum"] = 0
        return parameters


class TasksPagination(_SchemaAwareLimitOffsetPagination):
    default_limit = 50
    max_limit = 100


def _parse_slack_thread_url(url: str) -> tuple[str, str] | None:
    """Parse a Slack permalink into `(channel, thread_ts)`"""
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    match = re.search(r"/archives/(?P<channel>[A-Z0-9]+)/p(?P<ts>\d+)", parsed.path)
    if not match:
        return None
    channel = match.group("channel")
    # Reply permalinks put the parent thread_ts in the query string; that wins over the in-path ts.
    thread_ts_from_query = parse_qs(parsed.query).get("thread_ts", [None])[0]
    if thread_ts_from_query:
        return channel, thread_ts_from_query
    raw_ts = match.group("ts")
    if len(raw_ts) < 7:
        return None
    return channel, f"{raw_ts[:-6]}.{raw_ts[-6:]}"


def _temporal_workflow_url(workflow_id: str | None) -> str | None:
    if not workflow_id:
        return None
    base = getattr(settings, "TEMPORAL_UI_HOST", None)
    namespace = getattr(settings, "TEMPORAL_NAMESPACE", None)
    if not base or not namespace:
        return None
    return f"{base.rstrip('/')}/namespaces/{namespace}/workflows/{workflow_id}"


def _slack_repo_research_payload(
    request, team_id: int, state: dict[str, Any], repo_research_runs_by_id: dict[str, TaskRun]
) -> dict[str, Any] | None:
    """Build the repo-research block for a run, or None when the mention wasn't ambiguous."""
    research_task_id = state.get("repo_research_task_id")
    research_run_id = state.get("repo_research_run_id")
    if not research_task_id or not research_run_id:
        return None
    research_run = repo_research_runs_by_id.get(research_run_id)
    sandbox_url = None
    log_url = None
    run_status = None
    if research_run is not None:
        sandbox_url = (research_run.state if isinstance(research_run.state, dict) else {}).get("sandbox_url")
        run_status = research_run.status
        try:
            log_url = object_storage.get_presigned_url(research_run.log_url, expiration=3600)
        except Exception:
            logger.exception("slack_thread_context_research_log_presign_failed", extra={"run_id": research_run_id})
            log_url = None
    workflow_id = TaskRun.get_workflow_id(research_task_id, research_run_id)
    return {
        "task_id": research_task_id,
        "run_id": research_run_id,
        "status": run_status,
        "task_processing_workflow_id": workflow_id,
        "task_processing_workflow_url": _temporal_workflow_url(workflow_id),
        "sandbox_url": sandbox_url,
        "task_view_url": request.build_absolute_uri(
            f"/project/{team_id}/tasks/{research_task_id}?runId={research_run_id}&ph_debug=true"
        ),
        "log_url": log_url,
    }


_FULL_MCP_RUN_SOURCES: frozenset[RunSource | None] = frozenset({None, RunSource.MANUAL})


def _resolve_posthog_mcp_scopes(task_run: TaskRun) -> PosthogMcpScopes:
    run_source = parse_run_state(task_run.state).run_source
    return "full" if run_source in _FULL_MCP_RUN_SOURCES else "read_only"


class TaskViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """
    API for managing tasks within a project. Tasks represent units of work to be performed by an agent.
    """

    serializer_class = TaskSerializer
    authentication_classes = [
        SessionAuthentication,
        PersonalAPIKeyAuthentication,
        OAuthAccessTokenAuthentication,
    ]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "task"
    queryset = Task.objects.all()
    pagination_class = TasksPagination

    @validated_request(
        query_serializer=TaskListQuerySerializer,
        responses={
            200: OpenApiResponse(response=TaskSerializer, description="List of tasks"),
        },
        summary="List tasks",
        description="Get a list of tasks for the current project, with optional filtering by origin product, stage, organization, repository, and created_by.",
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(
        responses={
            200: OpenApiResponse(
                response=TaskRepositoriesResponseSerializer,
                description="Distinct repositories used by tasks in the current project.",
            ),
        },
        summary="List distinct task repositories",
        description="Return the set of repositories referenced by non-deleted, non-internal tasks in the current project. Used to populate repository filter pickers without being constrained by task list pagination.",
    )
    @action(
        detail=False,
        methods=["get"],
        url_path="repositories",
        required_scopes=["task:read"],
        pagination_class=None,
        filter_backends=[],
    )
    def repositories(self, request, **kwargs):
        repositories = (
            Task.objects.filter(team=self.team, deleted=False, internal=False)
            .filter(task_visibility_q(getattr(self.request.user, "id", None)))
            .exclude(repository__isnull=True)
            .exclude(repository__exact="")
            .values_list("repository", flat=True)
            .distinct()
            .order_by("repository")
        )
        serializer = TaskRepositoriesResponseSerializer({"repositories": list(repositories)})
        return Response(serializer.data)

    @validated_request(
        request_serializer=TaskSummariesRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=TaskSummarySerializer(many=True),
                description="Summary fields for the requested tasks",
            ),
        },
        summary="Fetch task summaries by ID",
        description=(
            "Returns summary for the requested tasks: `id`, `title`, `repository`, `created_at`, "
            "`updated_at`, and the latest run's `status` and `environment`."
        ),
        parameters=[
            OpenApiParameter(
                name="limit",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Page size for the paginated response.",
            ),
            OpenApiParameter(
                name="offset",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Offset into the result set for pagination.",
            ),
        ],
    )
    @action(
        detail=False,
        methods=["post"],
        url_path="summaries",
        required_scopes=["task:read"],
        filter_backends=[],
    )
    def summaries(self, request, **kwargs):
        ids = request.validated_data["ids"]
        latest_run = (
            TaskRun.objects.filter(task=OuterRef("pk"))
            .order_by("-created_at", "-id")
            .annotate(_data=JSONObject(status="status", environment="environment"))
        )
        tasks = (
            Task.objects.filter(team=self.team, deleted=False, id__in=ids)
            .filter(task_visibility_q(getattr(self.request.user, "id", None)))
            .annotate(_latest_run=Subquery(latest_run.values("_data")[:1]))
            .order_by("-created_at", "id")
        )
        page = self.paginate_queryset(tasks)
        if page is not None:
            serializer = TaskSummarySerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = TaskSummarySerializer(tasks, many=True)
        return Response(serializer.data)

    @validated_request(
        query_serializer=RepositoryReadinessQuerySerializer,
        responses={
            200: OpenApiResponse(
                response=RepositoryReadinessResponseSerializer,
                description="Repository readiness status",
            ),
        },
        summary="Get repository readiness",
        description="Get autonomy readiness details for a specific repository in the current project.",
    )
    @action(
        detail=False,
        methods=["get"],
        url_path="repository_readiness",
        required_scopes=["task:read"],
    )
    def repository_readiness(self, request, **kwargs):
        repository = request.validated_query_data["repository"]
        window_days = request.validated_query_data["window_days"]
        refresh = request.validated_query_data["refresh"]

        result = compute_repository_readiness(
            team=self.team,
            repository=repository,
            window_days=window_days,
            refresh=refresh,
        )
        return Response(result)

    @validated_request(
        query_serializer=SlackThreadContextQuerySerializer,
        responses={
            200: OpenApiResponse(
                response=SlackThreadContextResponseSerializer,
                description="Task, runs, and Temporal workflow handles for the Slack thread.",
            ),
            400: OpenApiResponse(description="Malformed Slack URL or unparseable thread identifiers."),
            403: OpenApiResponse(description="Endpoint is gated to PostHog-internal debugging."),
            404: OpenApiResponse(description="No SlackThreadTaskMapping exists for the parsed (channel, thread_ts)."),
        },
        summary="Resolve a Slack thread to its task, runs, and Temporal workflows",
        description=(
            "PostHog-internal debug tool. Resolves a Slack permalink to the linked task, its runs, "
            "the task-processing and mention-dispatch Temporal workflow ids/URLs, and presigned log URLs."
        ),
    )
    @action(
        detail=False,
        methods=["get"],
        url_path="slack_thread_context",
        required_scopes=["task:read"],
        pagination_class=None,
        filter_backends=[],
    )
    def slack_thread_context(self, request, **kwargs):
        if not _is_internal_debug_team(self.team_id):
            return Response(
                {"detail": "slack-thread-context is restricted to PostHog-internal debugging."},
                status=status.HTTP_403_FORBIDDEN,
            )
        # 1. Get Slack URL from the request URL
        url = request.validated_query_data["url"]
        parsed = _parse_slack_thread_url(url)
        if parsed is None:
            return Response(
                {"detail": "Could not parse channel/thread_ts from the provided Slack URL.", "url": url},
                status=status.HTTP_400_BAD_REQUEST,
            )
        channel, thread_ts = parsed
        # 2. Find related tasks
        mapping = (
            SlackThreadTaskMapping.objects.select_related("task", "task__created_by")
            .filter(channel=channel, thread_ts=thread_ts)
            .first()
        )
        if mapping is None:
            return Response(
                {
                    "detail": "no_mapping",
                    "thread": {
                        "url": url,
                        "channel": channel,
                        "thread_ts": thread_ts,
                        "slack_workspace_id": None,
                        "mentioning_slack_user_id": None,
                    },
                },
                status=status.HTTP_404_NOT_FOUND,
            )
        task = mapping.task
        # 3. Find runs for the task
        runs = list(TaskRun.objects.filter(task=task).order_by("created_at", "id"))
        # Include repo discovery runs, if present
        repo_research_run_ids = [
            rid
            for run in runs
            if (rid := (run.state if isinstance(run.state, dict) else {}).get("repo_research_run_id"))
        ]
        repo_research_runs_by_id: dict[str, TaskRun] = (
            {str(r.id): r for r in TaskRun.objects.filter(team=task.team, id__in=repo_research_run_ids)}
            if repo_research_run_ids
            else {}
        )
        # `?ph_debug=true` allows to check tasks of all team members through /tasks/<id>
        task_url = request.build_absolute_uri(f"/project/{task.team_id}/tasks/{task.id}?ph_debug=true")
        run_payloads: list[dict[str, Any]] = []
        # 4. Find workflows for the runs
        for run in runs:
            state = run.state if isinstance(run.state, dict) else {}
            output = run.output if isinstance(run.output, dict) else {}
            task_processing_workflow_id = TaskRun.get_workflow_id(task.id, run.id)
            mention_workflow_id = state.get("slack_mention_workflow_id")
            try:
                presigned_log_url = object_storage.get_presigned_url(run.log_url, expiration=3600)
            except Exception:
                logger.exception("slack_thread_context_log_presign_failed", extra={"run_id": str(run.id)})
                presigned_log_url = None
            run_payloads.append(
                {
                    "id": str(run.id),
                    "status": run.status,
                    "created_at": run.created_at,
                    "completed_at": run.completed_at,
                    "sandbox_url": state.get("sandbox_url"),
                    "pr_url": output.get("pr_url"),
                    "error_message": run.error_message,
                    "task_processing_workflow_id": task_processing_workflow_id,
                    "task_processing_workflow_url": _temporal_workflow_url(task_processing_workflow_id),
                    "mention_workflow_id": mention_workflow_id,
                    "mention_workflow_url": _temporal_workflow_url(mention_workflow_id),
                    "task_view_url": request.build_absolute_uri(
                        f"/project/{task.team_id}/tasks/{task.id}?runId={run.id}&ph_debug=true"
                    ),
                    "log_url": presigned_log_url,
                    "repo_research": _slack_repo_research_payload(
                        request, task.team_id, state, repo_research_runs_by_id
                    ),
                }
            )
        payload = {
            "thread": {
                "url": url,
                "channel": channel,
                "thread_ts": thread_ts,
                "slack_workspace_id": mapping.slack_workspace_id,
                "mentioning_slack_user_id": mapping.mentioning_slack_user_id,
            },
            "task": {
                "id": str(task.id),
                "team_id": task.team_id,
                "title": task.title,
                "repository": task.repository,
                "origin_product": task.origin_product,
                "created_at": task.created_at,
                "url": task_url,
            },
            "runs": run_payloads,
        }
        serializer = SlackThreadContextResponseSerializer(payload)
        return Response(serializer.data)

    def safely_get_queryset(self, queryset):
        qs = queryset.filter(team=self.team, deleted=False)
        # `?ph_debug=true` allows to check tasks of all team members through /tasks/<id>
        if not (
            _is_internal_debug_team(self.team_id)
            and self.action == "retrieve"
            and self.request.query_params.get("ph_debug") == "true"
        ):
            qs = qs.filter(task_visibility_q(getattr(self.request.user, "id", None)))
        qs = qs.order_by("-created_at")

        params = self.request.query_params if hasattr(self, "request") else {}

        # Filter by origin product
        origin_product = params.get("origin_product")
        if origin_product:
            qs = qs.filter(origin_product=origin_product)

        stage = params.get("stage")
        if stage:
            qs = qs.filter(runs__stage=stage)

        # Filter by repository or organization using the repository field
        organization = params.get("organization")
        repository = params.get("repository")
        created_by = params.get("created_by")
        search = params.get("search")
        status_filter = params.get("status")

        if repository:
            repo_str = repository.strip().lower()
            if "/" in repo_str:
                qs = qs.filter(repository__iexact=repo_str)
            else:
                qs = qs.filter(repository__iendswith=f"/{repo_str}")

        if organization:
            org_str = organization.strip().lower()
            qs = qs.filter(repository__istartswith=f"{org_str}/")

        if created_by:
            qs = qs.filter(created_by_id=created_by)

        # Only apply list-oriented filters on list — retrieve/update should always work if
        # you have the ID. Without this guard, a client passing a query param while fetching
        # a single task by ID would see an unexpected 404 when the task does not match.
        if self.action == "list":
            if search:
                search_term = search.strip()
                if search_term:
                    search_q = Q(title__icontains=search_term) | Q(description__icontains=search_term)
                    # Slugs look like "<team-prefix>-<task_number>". If the search term is a bare
                    # number, or looks like "<prefix>-<number>", also match by task_number so users
                    # can find tasks by slug.
                    number_part = search_term.split("-")[-1].strip()
                    if number_part.isdigit():
                        search_q |= Q(task_number=int(number_part))
                    qs = qs.filter(search_q)

            if status_filter:
                # `-id` is a deterministic tiebreaker when two runs share a `created_at`
                # timestamp (e.g. both seeded with `timezone.now()` in the same tick).
                latest_run_status = (
                    TaskRun.objects.filter(task=OuterRef("pk")).order_by("-created_at", "-id").values("status")[:1]
                )
                qs = qs.annotate(_latest_run_status=Subquery(latest_run_status)).filter(
                    _latest_run_status=status_filter
                )

            internal_param = getattr(self.request, "validated_query_data", {}).get("internal")
            if internal_param is True and (settings.DEBUG or self.request.user.is_staff):
                qs = qs.filter(internal=True)
            else:
                qs = qs.filter(internal=False)

            archived_param = getattr(self.request, "validated_query_data", {}).get("archived")
            if archived_param == "true":
                qs = qs.filter(archived=True)
            elif archived_param == "all":
                pass
            else:
                qs = qs.filter(archived=False)

        # select_related to avoid N+1 on created_by (UserBasicSerializer), team (slug property),
        # and GitHub integrations returned on task rows.
        qs = qs.select_related("created_by", "team", "github_integration", "github_user_integration").prefetch_related(
            "runs"
        )

        # `stage` joins through `runs` and can produce duplicate task rows. If any other
        # JOIN-producing filter is added above, broaden this guard (or move `.distinct()`
        # to run unconditionally).
        if stage:
            qs = qs.distinct()

        return qs

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "team": self.team, "team_id": self.team.id}

    def perform_create(self, serializer):
        logger.info(f"Creating task with data: {serializer.validated_data}")
        serializer.save(team=self.team)

    def perform_destroy(self, instance):
        task = cast(Task, instance)
        logger.info(f"Soft deleting task {task.id}")
        task.soft_delete()

    def _trigger_workflow(self, task: Task, task_run: TaskRun) -> None:
        try:
            logger.info(f"Attempting to trigger task processing workflow for task {task.id}, run {task_run.id}")
            execute_task_processing_workflow(
                task_id=str(task.id),
                run_id=str(task_run.id),
                team_id=task.team.id,
                user_id=getattr(self.request.user, "id", None),
                posthog_mcp_scopes=_resolve_posthog_mcp_scopes(task_run),
            )
            logger.info(f"Workflow trigger completed for task {task.id}, run {task_run.id}")
        except Exception as e:
            logger.exception(f"Failed to trigger task processing workflow for task {task.id}, run {task_run.id}: {e}")

    @validated_request(
        request_serializer=TaskStagedArtifactsPrepareUploadRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=TaskStagedArtifactsPrepareUploadResponseSerializer,
                description="Prepared staged uploads for the requested artifacts",
            ),
            400: OpenApiResponse(response=TaskRunErrorResponseSerializer, description="Invalid artifact payload"),
            404: OpenApiResponse(description="Task not found"),
        },
        summary="Prepare staged direct uploads for task attachments",
        description="Reserve S3 object keys for task attachments before creating a new run and return presigned POST forms for direct uploads.",
        strict_request_validation=True,
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="staged_artifacts/prepare_upload",
        required_scopes=["task:write"],
    )
    def staged_artifacts_prepare_upload(self, request, pk=None, **kwargs):
        task = cast(Task, self.get_object())
        artifacts = request.validated_data["artifacts"]

        prepared_artifacts: list[dict] = []
        for artifact in artifacts:
            artifact_id = uuid.uuid4().hex
            safe_name = get_safe_artifact_name(artifact["name"])
            storage_path = build_task_staged_artifact_storage_path(task, artifact_id, safe_name)
            presigned_post = object_storage.get_presigned_post(
                storage_path,
                conditions=[
                    ["content-length-range", 0, artifact["size"] + TASK_RUN_ARTIFACT_UPLOAD_FORM_OVERHEAD_BYTES]
                ],
                expiration=TASK_RUN_ARTIFACT_UPLOAD_EXPIRATION_SECONDS,
            )
            if not presigned_post:
                return Response(
                    TaskRunErrorResponseSerializer({"error": "Unable to generate upload URL"}).data,
                    status=status.HTTP_400_BAD_REQUEST,
                )

            prepared_artifacts.append(
                {
                    "id": artifact_id,
                    "name": safe_name,
                    "type": artifact["type"],
                    "source": artifact.get("source") or "",
                    "size": artifact["size"],
                    "content_type": artifact.get("content_type") or "",
                    "storage_path": storage_path,
                    "expires_in": TASK_RUN_ARTIFACT_UPLOAD_EXPIRATION_SECONDS,
                    "presigned_post": presigned_post,
                }
            )

        serializer = TaskStagedArtifactsPrepareUploadResponseSerializer(
            {"artifacts": prepared_artifacts},
            context=self.get_serializer_context(),
        )
        return Response(serializer.data)

    @validated_request(
        request_serializer=TaskStagedArtifactsFinalizeUploadRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=TaskStagedArtifactsFinalizeUploadResponseSerializer,
                description="Finalized staged artifacts available for the next task run",
            ),
            400: OpenApiResponse(response=TaskRunErrorResponseSerializer, description="Invalid artifact payload"),
            404: OpenApiResponse(description="Task not found"),
        },
        summary="Finalize staged direct uploads for task attachments",
        description="Verify staged S3 uploads and cache their metadata so they can be attached to the next run created for this task.",
        strict_request_validation=True,
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="staged_artifacts/finalize_upload",
        required_scopes=["task:write"],
    )
    def staged_artifacts_finalize_upload(self, request, pk=None, **kwargs):
        task = cast(Task, self.get_object())
        artifacts = request.validated_data["artifacts"]
        artifact_prefix = f"{settings.OBJECT_STORAGE_TASKS_FOLDER}/artifacts/team_{task.team_id}/task_{task.id}/staged/"
        finalized_artifacts: list[dict] = []

        for artifact in artifacts:
            artifact_id = artifact["id"]
            storage_path = artifact["storage_path"]
            if not storage_path.startswith(artifact_prefix) or f"/{artifact_id}/" not in storage_path:
                return Response(
                    TaskRunErrorResponseSerializer({"error": "Artifact storage path is invalid for this task"}).data,
                    status=status.HTTP_400_BAD_REQUEST,
                )

            s3_object = object_storage.head_object(storage_path)
            if not s3_object:
                return Response(
                    TaskRunErrorResponseSerializer({"error": "Artifact upload not found in object storage"}).data,
                    status=status.HTTP_400_BAD_REQUEST,
                )

            content_length = s3_object.get("ContentLength")
            if not isinstance(content_length, int):
                return Response(
                    TaskRunErrorResponseSerializer({"error": "Artifact upload metadata is unavailable"}).data,
                    status=status.HTTP_400_BAD_REQUEST,
                )

            safe_name = get_safe_artifact_name(artifact["name"])
            content_type = artifact.get("content_type") or s3_object.get("ContentType") or ""
            max_size_bytes = get_task_run_artifact_max_size_bytes(
                safe_name,
                content_type,
                artifact.get("type"),
            )
            if content_length > max_size_bytes:
                return Response(
                    TaskRunErrorResponseSerializer(
                        {"error": build_task_run_artifact_size_error(safe_name, max_size_bytes)}
                    ).data,
                    status=status.HTTP_400_BAD_REQUEST,
                )
            finalized_artifact = build_task_artifact_entry(
                artifact_id=artifact_id,
                name=safe_name,
                artifact_type=artifact["type"],
                source=artifact.get("source") or "",
                size=content_length,
                content_type=content_type,
                storage_path=storage_path,
            )
            finalized_artifacts.append(finalized_artifact)

        for finalized_artifact in finalized_artifacts:
            cache_task_staged_artifact(task, finalized_artifact)
            tag_task_artifact(
                finalized_artifact["storage_path"],
                ttl_days=STAGED_ARTIFACT_TTL_DAYS,
                team_id=task.team_id,
            )

        serializer = TaskStagedArtifactsFinalizeUploadResponseSerializer(
            {"artifacts": finalized_artifacts},
            context=self.get_serializer_context(),
        )
        return Response(serializer.data)

    def perform_update(self, serializer):
        task = cast(Task, serializer.instance)
        logger.info(f"perform_update called for task {task.id} with validated_data: {serializer.validated_data}")
        serializer.save()
        logger.info(f"Task {task.id} updated successfully")

        return Response(TaskSerializer(task).data)

    @extend_schema(request=TaskRunCreateRequestSchemaSerializer)
    @validated_request(
        request_serializer=TaskRunCreateRequestSerializer,
        responses={
            200: OpenApiResponse(response=TaskSerializer, description="Task with updated latest run"),
            400: OpenApiResponse(response=TaskRunErrorResponseSerializer, description="Invalid task run payload"),
            404: OpenApiResponse(description="Task not found"),
            429: OpenApiResponse(
                response=TaskRunErrorResponseSerializer, description="Team is over its posthog_code usage limit"
            ),
        },
        summary="Run task",
        description="Create a new task run and kick off the workflow.",
    )
    @action(detail=True, methods=["post"], url_path="run", required_scopes=["task:write"])
    def run(self, request, pk=None, **kwargs):
        task = cast(Task, self.get_object())

        # Always cloud: gate before creating the run.
        if (limit_response := cloud_usage_limit_response(request.user, self.team_id)) is not None:
            return limit_response

        mode = request.validated_data.get("mode", "background")
        branch = request.validated_data.get("branch")
        resume_from_run_id = request.validated_data.get("resume_from_run_id")
        pending_user_message = request.validated_data.get("pending_user_message")
        pending_user_artifact_ids = request.validated_data.get("pending_user_artifact_ids") or []
        sandbox_environment_id = request.validated_data.get("sandbox_environment_id")
        sandbox_environment_id_supplied_by_user = sandbox_environment_id is not None
        pr_authorship_mode = request.validated_data.get("pr_authorship_mode")
        run_source = request.validated_data.get("run_source")
        signal_report_id = request.validated_data.get("signal_report_id")
        runtime_adapter = request.validated_data.get("runtime_adapter")
        model = request.validated_data.get("model")
        reasoning_effort = request.validated_data.get("reasoning_effort")
        service_tier = request.validated_data.get("service_tier")
        github_user_token = request.validated_data.get("github_user_token")
        initial_permission_mode = request.validated_data.get("initial_permission_mode")
        if run_source == RunSource.SIGNAL_REPORT:
            pr_authorship_mode = PrAuthorshipMode.BOT

        runtime_state_fields = {
            "pr_authorship_mode": pr_authorship_mode,
            "run_source": run_source,
            "signal_report_id": signal_report_id,
            "runtime_adapter": runtime_adapter,
            "model": model,
            "reasoning_effort": reasoning_effort,
            "service_tier": service_tier,
        }

        extra_state = None
        if pending_user_message is not None:
            extra_state = {"pending_user_message": pending_user_message}
        if pending_user_artifact_ids:
            extra_state = extra_state or {}
            extra_state["pending_user_artifact_ids"] = pending_user_artifact_ids
        if initial_permission_mode is not None:
            extra_state = extra_state or {}
            extra_state["initial_permission_mode"] = initial_permission_mode

        if resume_from_run_id:
            # prevent cross-task resume
            previous_run = task.runs.filter(id=resume_from_run_id).first()
            if not previous_run:
                return Response({"detail": "Invalid resume_from_run_id"}, status=400)

            # Derive snapshot_external_id from the validated previous run
            prev_state = parse_run_state(previous_run.state)
            extra_state = extra_state or {}
            extra_state["resume_from_run_id"] = str(resume_from_run_id)
            if prev_state.snapshot_external_id:
                extra_state["snapshot_external_id"] = prev_state.snapshot_external_id

            if prev_state.sandbox_environment_id and sandbox_environment_id is None:
                sandbox_environment_id = prev_state.sandbox_environment_id

            for field_name in runtime_state_fields:
                if runtime_state_fields[field_name] is None:
                    runtime_state_fields[field_name] = getattr(prev_state, field_name)

            pr_authorship_mode = runtime_state_fields["pr_authorship_mode"]
            run_source = runtime_state_fields["run_source"]
            signal_report_id = runtime_state_fields["signal_report_id"]
            runtime_adapter = runtime_state_fields["runtime_adapter"]
            model = runtime_state_fields["model"]
            reasoning_effort = runtime_state_fields["reasoning_effort"]
            service_tier = runtime_state_fields["service_tier"]
            if branch is None and prev_state.pr_base_branch is not None:
                branch = prev_state.pr_base_branch

        provider = get_provider_for_runtime_adapter(runtime_adapter)

        for key, value in {
            "pr_base_branch": branch,
            "pr_authorship_mode": pr_authorship_mode,
            "run_source": run_source,
            "signal_report_id": signal_report_id,
            "runtime_adapter": runtime_adapter,
            "provider": provider,
            "model": model,
            "reasoning_effort": reasoning_effort,
            "service_tier": service_tier,
        }.items():
            if value is not None:
                extra_state = extra_state or {}
                extra_state[key] = value.value if hasattr(value, "value") else value

        reasoning_effort_error = get_reasoning_effort_error(
            runtime_adapter=runtime_adapter,
            model=model,
            reasoning_effort=reasoning_effort,
        )
        if reasoning_effort_error is not None:
            return Response(
                {
                    "type": "validation_error",
                    "code": "invalid_input",
                    "detail": reasoning_effort_error,
                    "attr": "reasoning_effort",
                },
                status=400,
            )

        pr_authorship_mode, validation_response = _resolve_cloud_pr_authorship_mode(
            task,
            pr_authorship_mode=pr_authorship_mode,
            request_user_id=getattr(request.user, "id", None),
            github_user_token=github_user_token,
        )
        if validation_response is not None:
            return validation_response
        if pr_authorship_mode is not None:
            extra_state = extra_state or {}
            extra_state["pr_authorship_mode"] = (
                pr_authorship_mode.value if hasattr(pr_authorship_mode, "value") else pr_authorship_mode
            )

        if credential_source := _github_credential_source_extra_state(pr_authorship_mode, github_user_token):
            extra_state = extra_state or {}
            extra_state.update(credential_source)

        if sandbox_environment_id is not None:
            sandbox_environment = SandboxEnvironment.get_accessible_for_task(
                environment_id=sandbox_environment_id,
                team_id=task.team_id,
                task_created_by_id=task.created_by_id,
            )
            if sandbox_environment is None:
                if sandbox_environment_id_supplied_by_user:
                    return Response({"detail": "Invalid sandbox_environment_id"}, status=400)
            else:
                extra_state = extra_state or {}
                extra_state["sandbox_environment_id"] = str(sandbox_environment.id)

                logger.info(
                    "Applying sandbox environment to task run",
                    extra={
                        "task_id": str(task.id),
                        "sandbox_environment_id": str(sandbox_environment.id),
                        "sandbox_environment_name": sandbox_environment.name,
                        "network_access_level": sandbox_environment.network_access_level,
                    },
                )

        staged_artifacts: list[dict[str, Any]] = []
        if pending_user_artifact_ids:
            staged_artifacts, missing_artifact_ids = get_task_staged_artifacts(task, pending_user_artifact_ids)
            if missing_artifact_ids:
                return Response(
                    {
                        "detail": "Some pending_user_artifact_ids are invalid or expired",
                        "missing_artifact_ids": missing_artifact_ids,
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        logger.info(f"Creating task run for task {task.id} with mode={mode}, branch={branch}")

        task_run = task.create_run(mode=mode, branch=branch, extra_state=extra_state)

        if pending_user_artifact_ids:
            run_artifacts: list[dict] = []
            for staged_artifact in staged_artifacts:
                storage_path = str(staged_artifact["storage_path"])
                tag_task_artifact(storage_path, ttl_days=RUN_ARTIFACT_TTL_DAYS, team_id=task.team_id)
                run_artifacts.append(dict(staged_artifact))

            task_run.artifacts = run_artifacts
            task_run.save(update_fields=["artifacts", "updated_at"])

            for artifact_id in pending_user_artifact_ids:
                get_tasks_cache().delete(build_task_staged_artifact_cache_key(str(task.id), artifact_id))

        if github_user_token and pr_authorship_mode == PrAuthorshipMode.USER:
            cache_github_user_token(str(task_run.id), github_user_token)

        logger.info(f"Triggering workflow for task {task.id}, run {task_run.id}")

        self._trigger_workflow(task, task_run)

        task.refresh_from_db()

        return Response(TaskSerializer(task, context=self.get_serializer_context()).data)

    @validated_request(
        request_serializer=TaskPresenceBeaconRequestSerializer,
        responses={
            204: OpenApiResponse(description="Presence recorded for this device."),
            404: OpenApiResponse(description="`device_id` does not match a push token registered by the caller."),
        },
        summary="Beacon presence for a device watching this task",
        description=(
            "Idempotent upsert: marks the calling user + `device_id` as actively watching this task "
            "for the next ~60 seconds. While at least one device for the user has a non-expired "
            "presence row for this task, the push fanout will skip ALL of that user's other "
            "registered devices for task notifications — the contract is 'if any device is "
            "demonstrably watching, suppress the others'. Clients call this every ~30s while the "
            "task screen is foregrounded. `device_id` is the UUID of the caller's UserPushToken row."
        ),
    )
    @action(
        detail=True,
        methods=["post", "delete"],
        url_path="presence",
        required_scopes=["task:write"],
    )
    def presence(self, request, **kwargs):
        if request.method == "DELETE":
            return self._presence_leave(request)
        return self._presence_beacon(request)

    def _presence_beacon(self, request) -> Response:
        task = cast(Task, self.get_object())
        device_id = request.validated_data["device_id"]
        push_token = UserPushToken.objects.filter(user=request.user, id=device_id).first()
        if push_token is None:
            raise NotFound("device_id does not match a push token registered by the caller")

        # Lookup mirrors the unique constraint exactly so a stray row with a
        # mismatched team/user (e.g. from a bug elsewhere) gets corrected on
        # upsert instead of crashing into the constraint a second time.
        # nosemgrep: idor-lookup-without-team — team scope is enforced by
        # TaskScopedManager (DRF view sets the ContextVar) and via `task` FK
        # whose row is fetched through self.get_object() above.
        now = timezone.now()
        TaskPresence.objects.update_or_create(
            task=task,
            push_token=push_token,
            defaults={
                "team": task.team,
                "user": request.user,
                "expires_at": now + timedelta(seconds=TASK_PRESENCE_TTL_SECONDS),
            },
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _presence_leave(self, request) -> Response:
        task = cast(Task, self.get_object())
        device_id = request.validated_data["device_id"]
        # No 404 on missing rows — the beacon-leave path runs from blur/background
        # handlers that should be safe to call unconditionally without the client
        # having to track whether a beacon was ever sent.
        TaskPresence.objects.filter(task=task, push_token_id=device_id, user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(tags=["task-automations"])
class TaskAutomationViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    serializer_class = TaskAutomationSerializer
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "task"
    queryset = TaskAutomation.objects.all()
    filter_rewrite_rules = {"team_id": "task__team_id"}

    def safely_get_queryset(self, queryset):
        return (
            queryset.filter(task__team=self.team)
            .filter(task_run_visibility_q(getattr(self.request.user, "id", None)))
            .order_by("task__title", "-created_at")
        )

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "team": self.team, "team_id": self.team.id}

    def perform_create(self, serializer):
        automation = serializer.save()
        sync_automation_schedule(automation)

    def perform_update(self, serializer):
        automation = serializer.save()
        sync_automation_schedule(automation)

    def perform_destroy(self, instance):
        automation = cast(TaskAutomation, instance)
        delete_automation_schedule(automation)
        automation.delete()

    @action(detail=True, methods=["post"], url_path="run", required_scopes=["task:write"])
    def run(self, request, pk=None, **kwargs):
        automation = cast(TaskAutomation, self.get_object())
        run_task_automation(str(automation.id))
        automation.refresh_from_db()
        return Response(TaskAutomationSerializer(automation, context=self.get_serializer_context()).data)


@extend_schema(tags=["task-runs", "tasks"])
class TaskRunViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """
    API for managing task runs. Each run represents an execution of a task.
    """

    serializer_class = TaskRunDetailSerializer
    authentication_classes = [
        SessionAuthentication,
        PersonalAPIKeyAuthentication,
        OAuthAccessTokenAuthentication,
    ]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "task"
    queryset = TaskRun.objects.select_related(
        "task", "task__created_by", "task__github_integration", "task__github_user_integration"
    ).all()
    http_method_names = ["get", "post", "patch", "head", "options"]
    filter_rewrite_rules = {"team_id": "team_id"}
    pagination_class = TasksPagination

    @validated_request(
        responses={
            200: OpenApiResponse(response=TaskRunDetailSerializer, description="List of task runs"),
        },
        summary="List task runs",
        description="Get a list of runs for a specific task.",
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @validated_request(
        request_serializer=TaskRunBootstrapCreateRequestSerializer,
        responses={
            201: OpenApiResponse(response=TaskRunDetailSerializer, description="Created task run"),
            400: OpenApiResponse(response=TaskRunErrorResponseSerializer, description="Invalid task run payload"),
            429: OpenApiResponse(
                response=TaskRunErrorResponseSerializer, description="Team is over its posthog_code usage limit"
            ),
        },
        summary="Create task run",
        description="Create a new run for a specific task without starting execution.",
    )
    def create(self, request, *args, **kwargs):
        task_id = self.kwargs.get("parent_lookup_task_id")
        if not task_id:
            raise NotFound("Task ID is required")

        task = (
            Task.objects.filter(id=task_id, team=self.team)
            .filter(task_visibility_q(getattr(request.user, "id", None)))
            .first()
        )
        if task is None:
            raise NotFound("Task not found")
        environment = request.validated_data.get("environment", TaskRun.Environment.LOCAL)

        # Gate cloud runs before the run row is created; local runs aren't limited.
        if environment == TaskRun.Environment.CLOUD:
            if (limit_response := cloud_usage_limit_response(request.user, self.team_id)) is not None:
                return limit_response

        mode = request.validated_data.get("mode", "background")
        branch = request.validated_data.get("branch")
        sandbox_environment_id = request.validated_data.get("sandbox_environment_id")
        pr_authorship_mode = request.validated_data.get("pr_authorship_mode")
        run_source = request.validated_data.get("run_source")
        signal_report_id = request.validated_data.get("signal_report_id")
        runtime_adapter = request.validated_data.get("runtime_adapter")
        model = request.validated_data.get("model")
        reasoning_effort = request.validated_data.get("reasoning_effort")
        service_tier = request.validated_data.get("service_tier")
        github_user_token = request.validated_data.get("github_user_token")
        initial_permission_mode = request.validated_data.get("initial_permission_mode")
        if run_source == RunSource.SIGNAL_REPORT:
            pr_authorship_mode = PrAuthorshipMode.BOT

        extra_state: dict[str, Any] | None = None
        if initial_permission_mode is not None:
            extra_state = {"initial_permission_mode": initial_permission_mode}

        provider = get_provider_for_runtime_adapter(runtime_adapter)
        for key, value in {
            "pr_base_branch": branch,
            "pr_authorship_mode": pr_authorship_mode,
            "run_source": run_source,
            "signal_report_id": signal_report_id,
            "runtime_adapter": runtime_adapter,
            "provider": provider,
            "model": model,
            "reasoning_effort": reasoning_effort,
            "service_tier": service_tier,
        }.items():
            if value is not None:
                extra_state = extra_state or {}
                extra_state[key] = value.value if hasattr(value, "value") else value

        reasoning_effort_error = get_reasoning_effort_error(
            runtime_adapter=runtime_adapter,
            model=model,
            reasoning_effort=reasoning_effort,
        )
        if reasoning_effort_error is not None:
            return Response(
                {
                    "type": "validation_error",
                    "code": "invalid_input",
                    "detail": reasoning_effort_error,
                    "attr": "reasoning_effort",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        pr_authorship_mode, validation_response = _resolve_cloud_pr_authorship_mode(
            task,
            pr_authorship_mode=pr_authorship_mode,
            request_user_id=getattr(request.user, "id", None),
            github_user_token=github_user_token,
        )
        if validation_response is not None:
            return validation_response
        if pr_authorship_mode is not None:
            extra_state = extra_state or {}
            extra_state["pr_authorship_mode"] = (
                pr_authorship_mode.value if hasattr(pr_authorship_mode, "value") else pr_authorship_mode
            )

        if credential_source := _github_credential_source_extra_state(pr_authorship_mode, github_user_token):
            extra_state = extra_state or {}
            extra_state.update(credential_source)

        if sandbox_environment_id is not None:
            sandbox_environment = SandboxEnvironment.get_accessible_for_task(
                environment_id=sandbox_environment_id,
                team_id=task.team_id,
                task_created_by_id=task.created_by_id,
            )
            if sandbox_environment is None:
                return Response({"detail": "Invalid sandbox_environment_id"}, status=status.HTTP_400_BAD_REQUEST)

            extra_state = extra_state or {}
            extra_state["sandbox_environment_id"] = str(sandbox_environment.id)

            logger.info(
                "Applying sandbox environment to task run",
                extra={
                    "task_id": str(task.id),
                    "sandbox_environment_id": str(sandbox_environment.id),
                    "sandbox_environment_name": sandbox_environment.name,
                    "network_access_level": sandbox_environment.network_access_level,
                },
            )

        logger.info(
            "Creating task run for task %s with mode=%s, branch=%s, environment=%s",
            task.id,
            mode,
            branch,
            environment,
        )
        task_run = task.create_run(
            environment=environment,
            mode=mode,
            branch=branch,
            extra_state=extra_state,
        )

        if github_user_token and pr_authorship_mode == PrAuthorshipMode.USER:
            cache_github_user_token(str(task_run.id), github_user_token)

        serializer = TaskRunDetailSerializer(task_run, context=self.get_serializer_context())
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @validated_request(
        request_serializer=TaskRunStartRequestSerializer,
        responses={
            200: OpenApiResponse(response=TaskSerializer, description="Task with updated latest run"),
            400: OpenApiResponse(response=TaskRunErrorResponseSerializer, description="Invalid start payload"),
            404: OpenApiResponse(description="Task run not found"),
            429: OpenApiResponse(
                response=TaskRunErrorResponseSerializer, description="Team is over its posthog_code usage limit"
            ),
        },
        summary="Start task run",
        description="Start an existing cloud run after any initial run-scoped attachments have been uploaded.",
    )
    @action(detail=True, methods=["post"], url_path="start", required_scopes=["task:write"])
    def start(self, request, pk=None, **kwargs):
        task_run = cast(TaskRun, self.get_object())
        task = task_run.task
        pending_user_message = request.validated_data.get("pending_user_message")
        pending_user_artifact_ids = request.validated_data.get("pending_user_artifact_ids") or []
        startable_statuses = {TaskRun.Status.NOT_STARTED, TaskRun.Status.QUEUED}

        if task_run.environment != TaskRun.Environment.CLOUD:
            return Response(
                TaskRunErrorResponseSerializer({"error": "Only cloud runs can be started via this endpoint"}).data,
                status=status.HTTP_400_BAD_REQUEST,
            )
        if task_run.status not in startable_statuses:
            return Response(
                TaskRunErrorResponseSerializer(
                    {
                        "error": f"Only queued or not_started cloud runs can be started (current status: {task_run.status})"
                    }
                ).data,
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Backstop: don't launch the cloud workflow for an over-limit team.
        if (limit_response := cloud_usage_limit_response(request.user, self.team_id)) is not None:
            return limit_response

        if pending_user_artifact_ids:
            _, missing_artifact_ids = get_task_run_artifacts_by_id(task_run, pending_user_artifact_ids)
            if missing_artifact_ids:
                return Response(
                    {
                        "detail": "Some pending_user_artifact_ids are invalid for this run",
                        "missing_artifact_ids": missing_artifact_ids,
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        state_updates: dict[str, Any] = {}
        if pending_user_message is not None:
            state_updates["pending_user_message"] = pending_user_message
        if pending_user_artifact_ids:
            state_updates["pending_user_artifact_ids"] = pending_user_artifact_ids

        previous_state = dict(task_run.state or {})
        try:
            if state_updates:
                TaskRun.update_state_atomic(task_run.id, updates=state_updates)
                task_run.refresh_from_db()

            logger.info("Triggering workflow for task %s, existing run %s", task.id, task_run.id)
            self._trigger_workflow(task, task_run, raise_on_error=True)
        except Exception:
            if state_updates:
                rollback_updates = {
                    key: previous_state[key] for key in state_updates.keys() if key in previous_state
                } or None
                rollback_remove_keys = [key for key in state_updates.keys() if key not in previous_state] or None
                TaskRun.update_state_atomic(
                    task_run.id,
                    updates=rollback_updates,
                    remove_keys=rollback_remove_keys,
                )
            raise

        task.refresh_from_db()
        return Response(TaskSerializer(task, context=self.get_serializer_context()).data)

    @validated_request(
        request_serializer=TaskRunUpdateSerializer,
        responses={
            200: OpenApiResponse(response=TaskRunDetailSerializer, description="Updated task run"),
            400: OpenApiResponse(response=TaskRunErrorResponseSerializer, description="Invalid update data"),
            404: OpenApiResponse(description="Task run not found"),
        },
        summary="Update task run",
        description="Update a task run with status, stage, branch, output, and state information.",
        strict_request_validation=True,
    )
    def update(self, request, *args, **kwargs):
        return self.partial_update(request, *args, **kwargs)

    @validated_request(
        request_serializer=TaskRunUpdateSerializer,
        responses={
            200: OpenApiResponse(response=TaskRunDetailSerializer, description="Updated task run"),
            400: OpenApiResponse(response=TaskRunErrorResponseSerializer, description="Invalid update data"),
            404: OpenApiResponse(description="Task run not found"),
        },
        summary="Update task run",
        strict_request_validation=True,
    )
    def partial_update(self, request, *args, **kwargs):
        task_run = cast(TaskRun, self.get_object())
        has_output_merge = "output" in request.validated_data and isinstance(request.validated_data["output"], dict)
        has_state_merge = "state" in request.validated_data and isinstance(request.validated_data["state"], dict)
        # Protected keys fix the run's GitHub identity at creation — callers cannot change or remove them.
        if has_state_merge:
            request.validated_data["state"] = {
                k: v for k, v in request.validated_data["state"].items() if k not in _PROTECTED_RUN_STATE_KEYS
            }
        state_remove_keys = [
            k for k in (request.validated_data.get("state_remove_keys") or []) if k not in _PROTECTED_RUN_STATE_KEYS
        ]
        has_state_mutation = has_state_merge or bool(state_remove_keys)
        update_fields: set[str] = set()

        with transaction.atomic():
            # Re-fetch with row lock when merging output to prevent concurrent
            # PATCHes (e.g. branch sync + PR URL) from clobbering each other.
            if has_output_merge or has_state_mutation:
                task_run = TaskRun.objects.select_for_update().get(pk=task_run.pk)

            old_status = task_run.status
            old_environment = task_run.environment
            old_pr_url = (task_run.output or {}).get("pr_url") if isinstance(task_run.output, dict) else None

            # Update fields from validated data
            for key, value in request.validated_data.items():
                if key == "output" and isinstance(value, dict):
                    existing_output = task_run.output if isinstance(task_run.output, dict) else {}
                    setattr(task_run, key, {**existing_output, **value})
                    update_fields.add(key)
                    continue
                if key == "state_remove_keys":
                    continue
                if key == "state" and has_state_merge:
                    existing_state = task_run.state if isinstance(task_run.state, dict) else {}
                    next_state = dict(existing_state)
                    for remove_key in state_remove_keys:
                        next_state.pop(remove_key, None)
                    next_state.update(value)
                    setattr(task_run, key, next_state)
                    update_fields.add(key)
                    continue
                setattr(task_run, key, value)
                update_fields.add(key)

            if state_remove_keys and not has_state_merge:
                existing_state = task_run.state if isinstance(task_run.state, dict) else {}
                next_state = dict(existing_state)
                for remove_key in state_remove_keys:
                    next_state.pop(remove_key, None)
                task_run.state = next_state
                update_fields.add("state")

            new_status = request.validated_data.get("status")
            terminal_statuses = [
                TaskRun.Status.COMPLETED,
                TaskRun.Status.FAILED,
                TaskRun.Status.CANCELLED,
            ]

            # Auto-set completed_at if status is completed or failed
            if new_status in terminal_statuses:
                if not task_run.completed_at:
                    task_run.completed_at = timezone.now()
                    update_fields.add("completed_at")

            update_fields.add("updated_at")
            task_run.save(update_fields=list(update_fields))
            task_run.publish_stream_state_event()

        update_automation_run_result(task_run)

        # Signal Temporal and post Slack updates after commit to avoid
        # holding the row lock during external calls.
        if new_status in terminal_statuses and old_status != new_status:
            self._signal_workflow_completion(
                task_run,
                new_status,
                request.validated_data.get("error_message"),
            )
            # mark_completed / mark_failed fire pushes from the model. Cancellation
            # transitions only flow through this PATCH path, so dispatch here.
            if new_status == TaskRun.Status.CANCELLED:
                from products.tasks.backend.push_dispatcher import notify_task_run_cancelled

                notify_task_run_cancelled(task_run)
        new_environment = request.validated_data.get("environment")
        if new_environment == "local" and old_environment == TaskRun.Environment.CLOUD:
            self._signal_workflow_completion(task_run, "cancelled", "handoff")

        new_pr_url = (task_run.output or {}).get("pr_url") if isinstance(task_run.output, dict) else None
        if new_pr_url and new_pr_url != old_pr_url:
            self._post_slack_update_for_pr(task_run)

        return Response(TaskRunDetailSerializer(task_run, context=self.get_serializer_context()).data)

    def _post_slack_update_for_pr(self, task_run: TaskRun) -> None:
        pr_url = (task_run.output or {}).get("pr_url") if isinstance(task_run.output, dict) else None
        if not pr_url:
            return

        try:
            from products.slack_app.backend.models import SlackThreadTaskMapping
            from products.tasks.backend.temporal.process_task.activities.post_slack_update import (
                PostSlackUpdateInput,
                post_slack_update,
            )

            mapping = (
                SlackThreadTaskMapping.objects.filter(task_run=task_run)
                .order_by("-updated_at")
                .values(
                    "integration_id",
                    "channel",
                    "thread_ts",
                    "mentioning_slack_user_id",
                )
                .first()
            )

            if not mapping:
                return

            post_slack_update(
                PostSlackUpdateInput(
                    run_id=str(task_run.id),
                    slack_thread_context={
                        "integration_id": mapping["integration_id"],
                        "channel": mapping["channel"],
                        "thread_ts": mapping["thread_ts"],
                        "mentioning_slack_user_id": mapping["mentioning_slack_user_id"],
                    },
                )
            )
        except Exception:
            logger.exception("task_run_slack_update_for_pr_failed for run %s", task_run.id)

    def _signal_workflow_completion(self, task_run: TaskRun, status: str, error_message: str | None) -> None:
        """Send completion signal to Temporal workflow."""
        from posthog.temporal.common.client import sync_connect

        from products.tasks.backend.temporal.process_task.workflow import ProcessTaskWorkflow

        try:
            client = sync_connect()
            handle = client.get_workflow_handle(task_run.workflow_id)

            import asyncio

            asyncio.run(handle.signal(ProcessTaskWorkflow.complete_task, args=[status, error_message]))
            logger.info(f"Signaled workflow completion for task run {task_run.id} with status {status}")
        except Exception as e:
            logger.warning(f"Failed to signal workflow completion for task run {task_run.id}: {e}")

    def safely_get_queryset(self, queryset):
        # Task runs are always scoped to a specific task
        task_id = self.kwargs.get("parent_lookup_task_id")
        if not task_id:
            raise NotFound("Task ID is required")

        task_filter = Task.objects.filter(id=task_id, team=self.team)
        # `?ph_debug=true` allows to check tasks of all team members through /tasks/<id>.
        # Allowlist read-only actions only — connection_token is a GET but mints a write-capable token.
        is_internal_debug_read = (
            _is_internal_debug_team(self.team_id)
            and self.action in ("list", "retrieve", "logs", "session_logs", "stream")
            and self.request.query_params.get("ph_debug") == "true"
        )
        if not is_internal_debug_read:
            task_filter = task_filter.filter(task_visibility_q(getattr(self.request.user, "id", None)))
        if not task_filter.exists():
            raise NotFound("Task not found")

        return queryset.filter(team=self.team, task_id=task_id)

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "team": self.team, "team_id": self.team.id}

    def perform_create(self, serializer):
        task_id = self.kwargs.get("parent_lookup_task_id")
        if not task_id:
            raise NotFound("Task ID is required")
        task = (
            Task.objects.filter(id=task_id, team=self.team)
            .filter(task_visibility_q(getattr(self.request.user, "id", None)))
            .first()
        )
        if task is None:
            raise NotFound("Task not found")
        serializer.save(team=self.team, task=task)

    def _trigger_workflow(self, task: Task, task_run: TaskRun, *, raise_on_error: bool = False) -> None:
        try:
            logger.info("Attempting to trigger task processing workflow for task %s, run %s", task.id, task_run.id)
            execute_task_processing_workflow(
                task_id=str(task.id),
                run_id=str(task_run.id),
                team_id=task.team.id,
                user_id=getattr(self.request.user, "id", None),
                posthog_mcp_scopes=_resolve_posthog_mcp_scopes(task_run),
            )
            logger.info("Workflow trigger completed for task %s, run %s", task.id, task_run.id)
        except Exception as e:
            logger.exception(
                "Failed to trigger task processing workflow for task %s, run %s: %s", task.id, task_run.id, e
            )
            if raise_on_error:
                raise

    def _build_artifact_storage_path(self, task_run: TaskRun, artifact_id: str, name: str) -> tuple[str, str]:
        safe_name = get_safe_artifact_name(name)
        prefix = task_run.get_artifact_s3_prefix()
        return safe_name, f"{prefix}/{artifact_id[:8]}_{safe_name}"

    @staticmethod
    def _tag_artifact_object(task_run: TaskRun, storage_path: str) -> None:
        try:
            object_storage.tag(
                storage_path,
                {
                    "ttl_days": "30",
                    "team_id": str(task_run.team_id),
                },
            )
        except Exception as exc:
            logger.warning(
                "task_run.artifact_tag_failed",
                extra={
                    "task_run_id": str(task_run.id),
                    "storage_path": storage_path,
                    "error": str(exc),
                },
            )

    @staticmethod
    def _build_artifact_manifest_entry(
        *,
        artifact_id: str,
        name: str,
        artifact_type: str,
        source: str,
        size: int,
        content_type: str,
        storage_path: str,
        uploaded_at: str,
    ) -> dict[str, str | int]:
        return {
            "id": artifact_id,
            "name": name,
            "type": artifact_type,
            "source": source,
            "size": size,
            "content_type": content_type,
            "storage_path": storage_path,
            "uploaded_at": uploaded_at,
        }

    @staticmethod
    def _find_artifact_manifest_entry(
        manifest: builtins.list[dict[str, Any]], artifact_id: str, storage_path: str
    ) -> dict[str, Any] | None:
        return next(
            (
                entry
                for entry in manifest
                if entry.get("id") == artifact_id or entry.get("storage_path") == storage_path
            ),
            None,
        )

    @staticmethod
    def _save_artifact_manifest(task_run: TaskRun, manifest: builtins.list[dict[str, Any]]) -> None:
        task_run.artifacts = manifest
        task_run.save(update_fields=["artifacts", "updated_at"])

    @validated_request(
        request_serializer=TaskRunSetOutputRequestSerializer,
        responses={
            200: OpenApiResponse(response=TaskRunDetailSerializer, description="Run with updated output"),
            404: OpenApiResponse(description="Run not found"),
        },
        summary="Set run output",
        description="Update the output field for a task run (e.g., PR URL, commit SHA, etc.)",
    )
    @action(
        detail=True,
        methods=["patch"],
        url_path="set_output",
        required_scopes=["task:write"],
    )
    def set_output(self, request, pk=None, **kwargs):
        task_run = cast(TaskRun, self.get_object())
        task = cast(Task, task_run.task)
        output_data = request.validated_data["output"]

        if task.json_schema:
            try:
                jsonschema.validate(instance=output_data, schema=task.json_schema)
            except jsonschema.ValidationError as e:
                return Response(
                    TaskRunErrorResponseSerializer({"error": f"Output validation error: {e.message}"}).data,
                    status=status.HTTP_400_BAD_REQUEST,
                )
        task_run.output = output_data
        task_run.save(update_fields=["output", "updated_at"])
        # We only really want to complete the task run if it's a structured output task.
        if task.json_schema:
            self._signal_workflow_completion(task_run, TaskRun.Status.COMPLETED, None)
        task_run.publish_stream_state_event()
        self._post_slack_update_for_pr(task_run)

        return Response(TaskRunDetailSerializer(task_run, context=self.get_serializer_context()).data)

    @validated_request(
        request_serializer=TaskRunAppendLogRequestSerializer,
        responses={
            200: OpenApiResponse(response=TaskRunDetailSerializer, description="Run with updated log"),
            400: OpenApiResponse(response=TaskRunErrorResponseSerializer, description="Invalid log entries"),
            404: OpenApiResponse(description="Run not found"),
        },
        summary="Append log entries",
        description="Append one or more log entries to the task run log array",
        strict_request_validation=True,
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="append_log",
        required_scopes=["task:write"],
    )
    def append_log(self, request, pk=None, **kwargs):
        task_run = cast(TaskRun, self.get_object())
        timer = ServerTimingsGathered()

        entries = request.validated_data["entries"]
        with timer("s3_append"):
            task_run.append_log(entries)

        task_run.heartbeat_workflow(agent_active=True)

        response = Response(TaskRunDetailSerializer(task_run, context=self.get_serializer_context()).data)
        response["Server-Timing"] = timer.to_header_string()
        return response

    @validated_request(
        request_serializer=TaskRunRelayMessageRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=TaskRunRelayMessageResponseSerializer,
                description="Relay accepted",
            ),
            404: OpenApiResponse(description="Run not found"),
        },
        summary="Relay run message to Slack",
        description="Queue a Slack relay workflow to post a run message into the mapped Slack thread.",
        strict_request_validation=True,
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="relay_message",
        required_scopes=["task:write"],
    )
    def relay_message(self, request, pk=None, **kwargs):
        task_run = cast(TaskRun, self.get_object())
        if task_run.is_terminal:
            return Response({"status": "skipped"})

        # Skip relay for non-Slack tasks — no thread to post to
        from products.slack_app.backend.models import SlackThreadTaskMapping

        if not SlackThreadTaskMapping.objects.filter(task_run=task_run).exists():
            return Response({"status": "skipped"})

        text = request.validated_data["text"].strip()
        if not text:
            return Response({"status": "skipped"})

        try:
            relay_id = execute_posthog_code_agent_relay_workflow(
                run_id=str(task_run.id),
                text=text,
                delete_progress=True,
            )
        except Exception:
            logger.exception(
                "task_run_relay_message_enqueue_failed",
                extra={"run_id": str(task_run.id)},
            )
            return Response(
                TaskRunErrorResponseSerializer({"error": "Failed to queue Slack relay"}).data,
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response({"status": "accepted", "relay_id": relay_id})

    @validated_request(
        request_serializer=TaskRunArtifactsUploadRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=TaskRunArtifactsUploadResponseSerializer,
                description="Run with updated artifact manifest",
            ),
            400: OpenApiResponse(response=TaskRunErrorResponseSerializer, description="Invalid artifact payload"),
            404: OpenApiResponse(description="Run not found"),
        },
        summary="Upload artifacts for a task run",
        description="Persist task artifacts to S3 and attach them to the run manifest.",
        strict_request_validation=True,
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="artifacts",
        required_scopes=["task:write"],
    )
    def artifacts(self, request, pk=None, **kwargs):
        task_run = cast(TaskRun, self.get_object())
        artifacts = request.validated_data["artifacts"]
        uploaded: list[dict] = []

        for artifact in artifacts:
            artifact_id = uuid.uuid4().hex
            safe_name, storage_path = self._build_artifact_storage_path(task_run, artifact_id, artifact["name"])

            content_bytes = artifact["content_bytes"]
            extras: dict[str, str] = {}
            content_type = artifact.get("content_type")
            if content_type:
                extras["ContentType"] = content_type

            object_storage.write(storage_path, content_bytes, extras or None)
            self._tag_artifact_object(task_run, storage_path)

            uploaded_at = timezone.now().isoformat()
            uploaded.append(
                self._build_artifact_manifest_entry(
                    artifact_id=artifact_id,
                    name=safe_name,
                    artifact_type=artifact["type"],
                    source=artifact.get("source") or "",
                    size=len(content_bytes),
                    content_type=content_type or "",
                    storage_path=storage_path,
                    uploaded_at=uploaded_at,
                )
            )

            logger.info(
                "task_run.artifact_uploaded",
                extra={
                    "task_run_id": str(task_run.id),
                    "storage_path": storage_path,
                    "artifact_type": artifact["type"],
                    "size": len(content_bytes),
                },
            )

        with transaction.atomic():
            task_run = TaskRun.objects.select_for_update().get(pk=task_run.pk)
            manifest = list(task_run.artifacts or [])
            manifest.extend(uploaded)
            self._save_artifact_manifest(task_run, manifest)

        serializer = TaskRunArtifactsUploadResponseSerializer(
            {"artifacts": manifest},
            context=self.get_serializer_context(),
        )
        return Response(serializer.data)

    @validated_request(
        request_serializer=TaskRunArtifactsPrepareUploadRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=TaskRunArtifactsPrepareUploadResponseSerializer,
                description="Prepared uploads for the requested artifacts",
            ),
            400: OpenApiResponse(response=TaskRunErrorResponseSerializer, description="Invalid artifact payload"),
            404: OpenApiResponse(description="Run not found"),
        },
        summary="Prepare direct uploads for task run artifacts",
        description="Reserve S3 object keys for task artifacts and return presigned POST forms for direct uploads.",
        strict_request_validation=True,
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="artifacts/prepare_upload",
        required_scopes=["task:write"],
    )
    def artifacts_prepare_upload(self, request, pk=None, **kwargs):
        task_run = cast(TaskRun, self.get_object())
        artifacts = request.validated_data["artifacts"]

        prepared_artifacts: list[dict] = []

        for artifact in artifacts:
            artifact_id = uuid.uuid4().hex
            safe_name, storage_path = self._build_artifact_storage_path(task_run, artifact_id, artifact["name"])
            content_type = artifact.get("content_type") or ""
            conditions: list[list[str | int]] = [
                ["content-length-range", 0, artifact["size"] + TASK_RUN_ARTIFACT_UPLOAD_FORM_OVERHEAD_BYTES]
            ]

            presigned_post = object_storage.get_presigned_post(
                storage_path,
                conditions=conditions,
                expiration=TASK_RUN_ARTIFACT_UPLOAD_EXPIRATION_SECONDS,
            )
            if not presigned_post:
                return Response(
                    TaskRunErrorResponseSerializer({"error": "Unable to generate upload URL"}).data,
                    status=status.HTTP_400_BAD_REQUEST,
                )

            prepared_artifacts.append(
                {
                    "id": artifact_id,
                    "name": safe_name,
                    "type": artifact["type"],
                    "source": artifact.get("source") or "",
                    "size": artifact["size"],
                    "content_type": content_type,
                    "storage_path": storage_path,
                    "expires_in": TASK_RUN_ARTIFACT_UPLOAD_EXPIRATION_SECONDS,
                    "presigned_post": presigned_post,
                }
            )

        serializer = TaskRunArtifactsPrepareUploadResponseSerializer(
            {"artifacts": prepared_artifacts},
            context=self.get_serializer_context(),
        )
        return Response(serializer.data)

    @validated_request(
        request_serializer=TaskRunArtifactsFinalizeUploadRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=TaskRunArtifactsFinalizeUploadResponseSerializer,
                description="Run with updated artifact manifest",
            ),
            400: OpenApiResponse(response=TaskRunErrorResponseSerializer, description="Invalid artifact payload"),
            404: OpenApiResponse(description="Run not found"),
        },
        summary="Finalize direct uploads for task run artifacts",
        description="Verify directly uploaded S3 objects and attach them to the run artifact manifest.",
        strict_request_validation=True,
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="artifacts/finalize_upload",
        required_scopes=["task:write"],
    )
    def artifacts_finalize_upload(self, request, pk=None, **kwargs):
        task_run = cast(TaskRun, self.get_object())
        artifacts = request.validated_data["artifacts"]
        manifest = list(task_run.artifacts or [])
        artifact_prefix = f"{task_run.get_artifact_s3_prefix()}/"
        finalized_entries: list[dict] = []
        new_storage_paths: list[str] = []

        for artifact in artifacts:
            artifact_id = artifact["id"]
            storage_path = artifact["storage_path"]

            if not storage_path.startswith(artifact_prefix) or f"/{artifact_id[:8]}_" not in storage_path:
                return Response(
                    TaskRunErrorResponseSerializer({"error": "Artifact storage path is invalid for this run"}).data,
                    status=status.HTTP_400_BAD_REQUEST,
                )

            existing_entry = self._find_artifact_manifest_entry(manifest, artifact_id, storage_path)
            if existing_entry is not None:
                # Callers rely on the response to return artifacts uploaded in
                # this request so they can pass those IDs back with subsequent
                # user_message commands. Echo the already-finalized entry
                # instead of the entire cumulative manifest — otherwise prior
                # turns' artifacts would be re-sent alongside the current ones.
                finalized_entries.append(existing_entry)
                continue

            s3_object = object_storage.head_object(storage_path)
            if not s3_object:
                return Response(
                    TaskRunErrorResponseSerializer({"error": "Artifact upload not found in object storage"}).data,
                    status=status.HTTP_400_BAD_REQUEST,
                )

            safe_name = get_safe_artifact_name(artifact["name"])
            content_type = artifact.get("content_type") or s3_object.get("ContentType") or ""
            content_length = s3_object.get("ContentLength")
            if not isinstance(content_length, int):
                return Response(
                    TaskRunErrorResponseSerializer({"error": "Artifact upload metadata is unavailable"}).data,
                    status=status.HTTP_400_BAD_REQUEST,
                )

            max_size_bytes = get_task_run_artifact_max_size_bytes(
                safe_name,
                content_type,
                artifact.get("type"),
            )
            if content_length > max_size_bytes:
                return Response(
                    TaskRunErrorResponseSerializer(
                        {"error": build_task_run_artifact_size_error(safe_name, max_size_bytes)}
                    ).data,
                    status=status.HTTP_400_BAD_REQUEST,
                )

            entry = self._build_artifact_manifest_entry(
                artifact_id=artifact_id,
                name=safe_name,
                artifact_type=artifact["type"],
                source=artifact.get("source") or "",
                size=content_length,
                content_type=content_type,
                storage_path=storage_path,
                uploaded_at=timezone.now().isoformat(),
            )
            manifest.append(entry)
            finalized_entries.append(entry)
            new_storage_paths.append(storage_path)

        self._save_artifact_manifest(task_run, manifest)

        for storage_path in new_storage_paths:
            self._tag_artifact_object(task_run, storage_path)

        serializer = TaskRunArtifactsFinalizeUploadResponseSerializer(
            {"artifacts": finalized_entries},
            context=self.get_serializer_context(),
        )
        return Response(serializer.data)

    @validated_request(
        request_serializer=TaskRunArtifactPresignRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=TaskRunArtifactPresignResponseSerializer,
                description="Presigned URL for the requested artifact",
            ),
            400: OpenApiResponse(response=TaskRunErrorResponseSerializer, description="Invalid request"),
            404: OpenApiResponse(description="Artifact not found"),
        },
        summary="Generate presigned URL for an artifact",
        description="Returns a temporary, signed URL that can be used to download a specific artifact.",
        strict_request_validation=True,
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="artifacts/presign",
        required_scopes=["task:read"],
    )
    def artifacts_presign(self, request, pk=None, **kwargs):
        task_run = cast(TaskRun, self.get_object())
        storage_path = request.validated_data["storage_path"]
        artifacts = task_run.artifacts or []

        if not any(artifact.get("storage_path") == storage_path for artifact in artifacts):
            return Response(
                TaskRunErrorResponseSerializer({"error": "Artifact not found on this run"}).data,
                status=status.HTTP_404_NOT_FOUND,
            )

        url = object_storage.get_presigned_url(storage_path)
        if not url:
            return Response(
                TaskRunErrorResponseSerializer({"error": "Unable to generate download URL"}).data,
                status=status.HTTP_400_BAD_REQUEST,
            )

        expires_in = 3600
        serializer = TaskRunArtifactPresignResponseSerializer({"url": url, "expires_in": expires_in})
        return Response(serializer.data)

    @validated_request(
        request_serializer=TaskRunArtifactPresignRequestSerializer,
        responses={
            200: OpenApiResponse(
                description="Artifact content",
            ),
            400: OpenApiResponse(response=TaskRunErrorResponseSerializer, description="Invalid request"),
            404: OpenApiResponse(description="Artifact not found"),
        },
        summary="Download an artifact through the backend",
        description="Streams artifact content for a task run artifact after validating that it belongs to the run.",
        strict_request_validation=True,
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="artifacts/download",
        required_scopes=["task:read"],
    )
    def artifacts_download(self, request, pk=None, **kwargs):
        task_run = cast(TaskRun, self.get_object())
        storage_path = request.validated_data["storage_path"]

        # Walk the resume chain so cloud→cloud resume runs can fetch the
        # git checkpoint pack/index that lives on the prior run they were
        # forked from.
        artifact = task_run.find_artifact_in_resume_chain(storage_path)

        if artifact is None:
            return Response(
                TaskRunErrorResponseSerializer({"error": "Artifact not found on this run"}).data,
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            content = object_storage.read_bytes(storage_path, missing_ok=True)
        except Exception:
            logger.exception(
                "task_run.artifact_download_failed",
                extra={
                    "task_run_id": str(task_run.id),
                    "storage_path": storage_path,
                },
            )
            return Response(
                TaskRunErrorResponseSerializer({"error": "Unable to read artifact"}).data,
                status=status.HTTP_400_BAD_REQUEST,
            )

        if content is None:
            return Response(
                TaskRunErrorResponseSerializer({"error": "Artifact content not found"}).data,
                status=status.HTTP_404_NOT_FOUND,
            )

        response = HttpResponse(
            content,
            content_type=str(artifact.get("content_type") or "application/octet-stream"),
        )
        response["Cache-Control"] = "no-cache"
        response["Content-Disposition"] = (
            f'attachment; filename="{os.path.basename(str(artifact.get("name") or "artifact"))}"'
        )
        return response

    @extend_schema(
        extensions={"x-product": "logs"},
        responses={
            200: OpenApiResponse(description="Log content in JSONL format"),
            404: OpenApiResponse(description="Task run not found"),
        },
        summary="Get task run logs",
        description=(
            "Fetch the logs for a task run as JSONL. If the run resumes from "
            "another (state.resume_from_run_id), each ancestor's log is "
            "concatenated first (oldest ancestor → ... → this run) so resume "
            "consumers see a single continuous history and can find the most "
            "recent git_checkpoint event regardless of which run emitted it."
        ),
    )
    @action(detail=True, methods=["get"], url_path="logs", required_scopes=["task:read"])
    def logs(self, request, pk=None, **kwargs):
        task_run = cast(TaskRun, self.get_object())
        timer = ServerTimingsGathered()

        chain = task_run.get_resume_chain()
        with timer("s3_read"):
            parts: list[str] = []
            for run in chain:
                chunk = object_storage.read(run.log_url, missing_ok=True) or ""
                if chunk:
                    if not chunk.endswith("\n"):
                        chunk = chunk + "\n"
                    parts.append(chunk)
            log_content = "".join(parts)

        response = HttpResponse(log_content, content_type="application/jsonl")
        response["Cache-Control"] = "no-cache"
        response["Server-Timing"] = timer.to_header_string()
        return response

    @validated_request(
        responses={
            200: OpenApiResponse(
                response=ConnectionTokenResponseSerializer,
                description="Connection token for direct sandbox connection",
            ),
            404: OpenApiResponse(description="Task run not found"),
        },
        summary="Get sandbox connection token",
        description="Generate a JWT token for direct connection to the sandbox. Valid for 24 hours.",
    )
    @action(
        detail=True,
        methods=["get"],
        url_path="connection_token",
        required_scopes=["task:write"],
    )
    def connection_token(self, request, pk=None, **kwargs):
        task_run = cast(TaskRun, self.get_object())
        user = request.user

        token = create_sandbox_connection_token(
            task_run=task_run,
            user_id=user.id,
            distinct_id=user.distinct_id,
        )

        return Response(ConnectionTokenResponseSerializer({"token": token}).data)

    @validated_request(
        request_serializer=TaskRunCommandRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=TaskRunCommandResponseSerializer,
                description="Agent server response",
            ),
            400: OpenApiResponse(
                response=TaskRunErrorResponseSerializer,
                description="Invalid command or no active sandbox",
            ),
            404: OpenApiResponse(description="Task run not found"),
            502: OpenApiResponse(response=TaskRunErrorResponseSerializer, description="Agent server unreachable"),
        },
        summary="Send command to task run",
        description="Queue user_message JSON-RPC commands through the task workflow and forward sandbox control "
        "commands to the agent server. Supports user_message, cancel, close, permission_response, "
        "and set_config_option commands.",
        strict_request_validation=True,
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="command",
        required_scopes=["task:write"],
    )
    def command(self, request, pk=None, **kwargs):
        task_run = cast(TaskRun, self.get_object())
        method = request.validated_data["method"]
        request_id = request.validated_data.get("id")
        params = request.validated_data.get("params")

        if method == "set_config_option":
            if self._persist_config_option_state(task_run, params):
                response_payload: dict[str, Any] = {
                    "jsonrpc": request.validated_data["jsonrpc"],
                    "result": {"updated": True},
                }
                if request_id is not None:
                    response_payload["id"] = request_id
                return Response(TaskRunCommandResponseSerializer(response_payload).data)

        if method == "user_message":
            command_params = dict(params or {})
            artifact_ids = command_params.pop("artifact_ids", [])
            if artifact_ids:
                _, missing_artifact_ids = get_task_run_artifacts_by_id(task_run, artifact_ids)
                if missing_artifact_ids:
                    return Response(
                        {
                            "error": "Some artifact_ids are invalid for this run",
                            "missing_artifact_ids": missing_artifact_ids,
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

            try:
                signal_task_followup_message(
                    task_run.workflow_id,
                    command_params.get("content"),
                    artifact_ids,
                )
            except Exception:
                logger.exception("Failed to signal follow-up message for task run %s", task_run.id)
                return Response(
                    TaskRunErrorResponseSerializer({"error": "Failed to queue user message for task run"}).data,
                    status=status.HTTP_502_BAD_GATEWAY,
                )

            response_payload: dict[str, Any] = {
                "jsonrpc": request.validated_data["jsonrpc"],
                "result": {"queued": True},
            }
            if request_id is not None:
                response_payload["id"] = request_id
            return Response(TaskRunCommandResponseSerializer(response_payload).data)

        run_state = parse_run_state(task_run.state)

        if not run_state.sandbox_url:
            return Response(
                TaskRunErrorResponseSerializer({"error": "No active sandbox for this task run"}).data,
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not self._is_valid_sandbox_url(run_state.sandbox_url):
            logger.warning(f"Blocked request to disallowed sandbox URL for task run {task_run.id}")
            return Response(
                TaskRunErrorResponseSerializer({"error": "Invalid sandbox URL"}).data,
                status=status.HTTP_400_BAD_REQUEST,
            )

        connection_token = create_sandbox_connection_token(
            task_run=task_run,
            user_id=request.user.id,
            distinct_id=request.user.distinct_id,
        )

        command_payload: dict = {
            "jsonrpc": request.validated_data["jsonrpc"],
            "method": method,
        }
        if params:
            command_params = dict(params)
            if command_params:
                command_payload["params"] = command_params
        if request_id is not None:
            command_payload["id"] = request_id

        try:
            agent_response = self._proxy_command_to_agent_server(
                sandbox_url=run_state.sandbox_url,
                connection_token=connection_token,
                sandbox_connect_token=run_state.sandbox_connect_token,
                payload=command_payload,
            )

            if agent_response.ok:
                return Response(agent_response.json())

            try:
                error_body = agent_response.json()
            except Exception:
                error_body = {}

            if agent_response.status_code == 401:
                error_msg = error_body.get("error", "Agent server authentication failed")
                logger.warning(f"Agent server auth failed for task run {task_run.id}: {error_msg}")
            elif agent_response.status_code == 400:
                error_msg = error_body.get("error", "Agent server rejected the command")
                logger.warning(f"Agent server rejected command for task run {task_run.id}: {error_msg}")
            else:
                error_msg = error_body.get("error", f"Agent server returned {agent_response.status_code}")

            return Response(
                TaskRunErrorResponseSerializer({"error": error_msg}).data,
                status=status.HTTP_502_BAD_GATEWAY,
            )

        except http_requests.ConnectionError:
            logger.warning(f"Agent server unreachable for task run {task_run.id}")
            return Response(
                TaskRunErrorResponseSerializer({"error": "Agent server is not reachable"}).data,
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except http_requests.Timeout:
            logger.warning(f"Agent server request timed out for task run {task_run.id}")
            return Response(
                TaskRunErrorResponseSerializer({"error": "Agent server request timed out"}).data,
                status=status.HTTP_504_GATEWAY_TIMEOUT,
            )
        except Exception:
            logger.exception(f"Failed to proxy command to agent server for task run {task_run.id}")
            return Response(
                TaskRunErrorResponseSerializer({"error": "Failed to send command to agent server"}).data,
                status=status.HTTP_502_BAD_GATEWAY,
            )

    @staticmethod
    def _persist_config_option_state(task_run: TaskRun, params: dict[str, Any] | None) -> bool:
        if not params:
            return False

        config_id = params.get("configId")
        value = params.get("value")
        if config_id != SERVICE_TIER_CONFIG_ID or value not in CODEX_SERVICE_TIER_CHOICES:
            return False

        TaskRun.update_state_atomic(task_run.id, updates={"service_tier": value})
        return True

    @staticmethod
    def _is_valid_sandbox_url(url: str) -> bool:
        """Validate sandbox URL against allowlist to prevent SSRF.

        Only allows:
        - http://localhost:{port} (Docker sandboxes)
        - http://127.0.0.1:{port} (Docker sandboxes)
        - https://*.modal.run (Modal sandboxes)
        - https://*.modal.host (Modal connect token sandboxes)
        """
        from urllib.parse import urlparse

        try:
            parsed = urlparse(url)
        except Exception:
            return False

        if parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1"):
            return True

        if (
            parsed.scheme == "https"
            and parsed.hostname
            and (parsed.hostname.endswith(".modal.run") or parsed.hostname.endswith(".modal.host"))
        ):
            return True

        return False

    @staticmethod
    def _proxy_command_to_agent_server(
        sandbox_url: str,
        connection_token: str,
        sandbox_connect_token: str | None,
        payload: dict,
    ) -> http_requests.Response:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {connection_token}",
        }

        command_url = f"{sandbox_url.rstrip('/')}/command"

        # Modal connect tokens use Authorization: Bearer for tunnel auth,
        # which conflicts with the JWT auth the agent server expects.
        # Pass the Modal token as a query parameter instead so both
        # auth mechanisms can coexist.
        params = {}
        if sandbox_connect_token:
            params["_modal_connect_token"] = sandbox_connect_token

        return http_requests.post(
            command_url,
            json=payload,
            headers=headers,
            params=params,
            timeout=600,
        )

    @validated_request(
        query_serializer=TaskRunSessionLogsQuerySerializer,
        responses={
            200: OpenApiResponse(description="Filtered log events as JSON array"),
            404: OpenApiResponse(description="Task run not found"),
        },
        summary="Get filtered task run session logs",
        description="Fetch session log entries for a task run with optional filtering by timestamp, event type, and limit.",
    )
    @action(
        detail=True,
        methods=["get"],
        url_path="session_logs",
        required_scopes=["task:read"],
    )
    def session_logs(self, request, pk=None, **kwargs):
        task_run = cast(TaskRun, self.get_object())
        timer = ServerTimingsGathered()

        with timer("s3_read"):
            log_content = object_storage.read(task_run.log_url, missing_ok=True) or ""

        if not log_content.strip():
            response = JsonResponse([], safe=False)
            response["X-Total-Count"] = "0"
            response["X-Filtered-Count"] = "0"
            response["X-Matching-Count"] = "0"
            response["X-Has-More"] = "false"
            response["Cache-Control"] = "no-cache"
            response["Server-Timing"] = timer.to_header_string()
            return response

        # Parse all JSONL entries
        all_entries = []
        for line in log_content.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                all_entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue

        total_count = len(all_entries)

        # Apply filters from validated query params
        params = request.validated_query_data
        after = params.get("after")
        event_types_str = params.get("event_types")
        exclude_types_str = params.get("exclude_types")
        limit = params.get("limit", 1000)
        offset = params.get("offset", 0)

        event_types = {t.strip() for t in event_types_str.split(",") if t.strip()} if event_types_str else None
        exclude_types = {t.strip() for t in exclude_types_str.split(",") if t.strip()} if exclude_types_str else None

        with timer("filter"):
            filtered = []
            for entry in all_entries:
                # Filter by timestamp (parse to avoid Z vs +00:00 and fractional second mismatches)
                if after:
                    entry_ts = entry.get("timestamp", "")
                    if not entry_ts:
                        continue  # Skip entries without timestamps
                    try:
                        entry_dt = datetime.fromisoformat(entry_ts.replace("Z", "+00:00"))
                        if entry_dt <= after:
                            continue
                    except (ValueError, TypeError):
                        continue  # Skip entries with unparseable timestamps

                # Determine the event type for filtering
                event_type = self._get_event_type(entry)

                if event_types and event_type not in event_types:
                    continue
                if exclude_types and event_type in exclude_types:
                    continue

                filtered.append(entry)

        matching_count = len(filtered)
        page = filtered[offset : offset + limit]
        has_more = offset + len(page) < matching_count

        response = JsonResponse(page, safe=False)
        response["X-Total-Count"] = str(total_count)
        response["X-Filtered-Count"] = str(matching_count)
        response["X-Matching-Count"] = str(matching_count)
        response["X-Has-More"] = "true" if has_more else "false"
        response["Cache-Control"] = "no-cache"
        response["Server-Timing"] = timer.to_header_string()
        return response

    @validated_request(
        responses={
            200: OpenApiResponse(response=TaskRunDetailSerializer, description="Run resumed in cloud"),
            400: OpenApiResponse(
                response=TaskRunErrorResponseSerializer, description="Run already active or workflow failed"
            ),
            429: OpenApiResponse(
                response=TaskRunErrorResponseSerializer, description="Team is over its posthog_code usage limit"
            ),
        },
        summary="Resume task run in cloud",
        description="Resume an existing task run in a cloud sandbox. Terminates any existing workflow and starts a new one.",
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="resume_in_cloud",
        required_scopes=["task:write"],
    )
    def resume_in_cloud(self, request, pk=None, **kwargs):
        task_run = cast(TaskRun, self.get_object())

        # Resume also runs in cloud: gate before handoff.
        if (limit_response := cloud_usage_limit_response(request.user, self.team_id)) is not None:
            return limit_response

        logger.info(
            "resume_in_cloud_called",
            extra={
                "task_run_id": str(task_run.id),
                "task_id": str(task_run.task_id),
                "prior_status": task_run.status,
                "prior_environment": task_run.environment,
                "prior_state_keys": sorted((task_run.state or {}).keys()),
                "prior_snapshot_external_id": (task_run.state or {}).get("snapshot_external_id"),
                "use_modal_resume_snapshots": settings.TASKS_USE_MODAL_RESUME_SNAPSHOTS,
            },
        )

        with transaction.atomic():
            task_run = (
                TaskRun.objects.select_for_update(of=("self",))
                .select_related("task", "task__created_by", "task__github_integration", "task__github_user_integration")
                .get(pk=task_run.pk)
            )

            is_cloud_active = task_run.environment == TaskRun.Environment.CLOUD and task_run.status in (
                TaskRun.Status.QUEUED,
                TaskRun.Status.IN_PROGRESS,
            )
            if is_cloud_active:
                return Response(
                    TaskRunErrorResponseSerializer({"error": "Run is already active in cloud"}).data,
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if get_pr_authorship_mode(task_run.task, task_run.state) == PrAuthorshipMode.USER:
                pr_authorship_mode, validation_response = _resolve_cloud_pr_authorship_mode(
                    task_run.task,
                    pr_authorship_mode=PrAuthorshipMode.USER,
                    request_user_id=getattr(request.user, "id", None),
                    github_user_token=None,
                )
                if validation_response is not None:
                    return validation_response
                if pr_authorship_mode is not None:
                    task_run.state = {
                        **(task_run.state or {}),
                        "pr_authorship_mode": (
                            pr_authorship_mode.value if hasattr(pr_authorship_mode, "value") else pr_authorship_mode
                        ),
                    }

            prior_status = task_run.status
            prior_environment = task_run.environment
            prior_completed_at = task_run.completed_at
            prior_state = dict(task_run.state or {})
            task_run.prepare_for_cloud_handoff()

        # Any prior workflow under this ID gets terminated atomically by
        # TERMINATE_IF_RUNNING inside resume_task_in_cloud_workflow. We
        # intentionally don't send a separate cancel signal here: it races
        # with start, and signals are routed by workflow_id so a late signal
        # could land on the new execution.

        logger.info(
            "Resuming task run in cloud",
            extra={
                "task_run_id": str(task_run.id),
                "task_id": str(task_run.task_id),
            },
        )

        try:
            resume_task_in_cloud_workflow(str(task_run.id), task_run.workflow_id)
        except Exception as e:
            logger.exception(
                "Failed to trigger handoff workflow",
                extra={"task_run_id": str(task_run.id), "error": str(e)},
            )
            with transaction.atomic():
                task_run = TaskRun.objects.select_for_update().get(pk=task_run.pk)
                task_run.status = prior_status
                task_run.environment = prior_environment
                task_run.completed_at = prior_completed_at
                task_run.state = prior_state
                task_run.error_message = "Failed to start cloud workflow"
                task_run.save(
                    update_fields=[
                        "status",
                        "environment",
                        "completed_at",
                        "state",
                        "error_message",
                        "updated_at",
                    ]
                )
            task_run.publish_stream_state_event()
            return Response(
                TaskRunErrorResponseSerializer({"error": "Failed to start cloud workflow"}).data,
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(TaskRunDetailSerializer(task_run, context=self.get_serializer_context()).data)

    @staticmethod
    def _format_sse_event(data: dict, *, event_id: str | None = None, event_name: str | None = None) -> bytes:
        parts: list[str] = []
        if event_name:
            parts.append(f"event: {event_name}")
        if event_id:
            parts.append(f"id: {event_id}")
        parts.append(f"data: {json.dumps(data)}")
        return ("\n".join(parts) + "\n\n").encode()

    @action(
        detail=True,
        methods=["get"],
        url_path="stream",
        required_scopes=["task:read"],
        renderer_classes=[ServerSentEventRenderer],
    )
    def stream(self, request, pk=None, **kwargs):
        task_run = cast(TaskRun, self.get_object())
        stream_key = get_task_run_stream_key(str(task_run.id))
        use_dedicated_stream = run_uses_dedicated_stream(task_run.state)
        last_event_id = request.headers.get("Last-Event-ID")
        start_latest = request.GET.get("start") == "latest"
        format_sse_event = self._format_sse_event
        origin_product = origin_product_label(task_run)

        async def async_stream() -> AsyncGenerator[bytes]:
            redis_stream = TaskRunRedisStream(stream_key, use_dedicated_stream)
            connection_started_at = asyncio.get_running_loop().time()
            # Default to client_disconnect: any exit that isn't an explicit
            # completion/error/unavailable is the client (or proxy) going away.
            outcome: StreamConnectionOutcome = "client_disconnect"
            # Record opened inside the try so the closed counter only fires when
            # the open succeeded — keeps opened/closed balanced for the
            # active-connections gauge regardless of which increment fails.
            opened = False
            try:
                observe_stream_connection_opened(origin_product)
                opened = True
                delay = TASK_RUN_STREAM_WAIT_INITIAL_DELAY_SECONDS
                wait_started_at = asyncio.get_running_loop().time()
                last_keepalive_at = wait_started_at

                while not await redis_stream.exists():
                    now = asyncio.get_running_loop().time()
                    if now - wait_started_at >= TASK_RUN_STREAM_WAIT_TIMEOUT_SECONDS:
                        outcome = "unavailable"
                        yield format_sse_event({"error": "Stream not available"}, event_name="error")
                        return

                    if now - last_keepalive_at >= TASK_RUN_STREAM_KEEPALIVE_INTERVAL_SECONDS:
                        last_keepalive_at = now
                        yield format_sse_event(
                            TASK_RUN_STREAM_KEEPALIVE_PAYLOAD,
                            event_name=TASK_RUN_STREAM_KEEPALIVE_EVENT_NAME,
                        )

                    await asyncio.sleep(delay)
                    delay = min(
                        delay + TASK_RUN_STREAM_WAIT_DELAY_INCREMENT_SECONDS,
                        TASK_RUN_STREAM_WAIT_MAX_DELAY_SECONDS,
                    )

                # Only reconnects (Last-Event-ID set) can suffer a trimmed resume
                # point, and that's the only case where stream depth vs the trim
                # cap is interesting — so skip the extra Redis reads on fresh
                # connects. Best-effort: never break the stream.
                if last_event_id:
                    try:
                        observe_stream_length_on_connect(await redis_stream.get_length())
                        if await redis_stream.resume_point_trimmed(last_event_id):
                            observe_stream_resume_gap(origin_product)
                            logger.warning(
                                "task_run_stream_resume_gap",
                                extra={"stream_key": stream_key, "last_event_id": last_event_id},
                            )
                    except Exception:
                        logger.warning(
                            "task_run_stream_attach_observe_failed",
                            extra={"stream_key": stream_key},
                            exc_info=True,
                        )

                start_id = last_event_id or "0"
                if not last_event_id and start_latest:
                    start_id = await redis_stream.get_latest_stream_id() or "0"
                try:
                    async for stream_item in redis_stream.read_stream_entries(
                        start_id=start_id,
                        keepalive_interval_seconds=TASK_RUN_STREAM_KEEPALIVE_INTERVAL_SECONDS,
                    ):
                        if stream_item is None:
                            yield format_sse_event(
                                TASK_RUN_STREAM_KEEPALIVE_PAYLOAD,
                                event_name=TASK_RUN_STREAM_KEEPALIVE_EVENT_NAME,
                            )
                            continue
                        event_id, event = stream_item
                        yield format_sse_event(event, event_id=event_id)
                    outcome = "completed"
                except TaskRunStreamError as e:
                    outcome = "stream_error"
                    logger.error("TaskRunRedisStream error for stream %s: %s", stream_key, e, exc_info=True)
                    yield format_sse_event({"error": str(e)}, event_name="error")
            finally:
                if opened:
                    duration = asyncio.get_running_loop().time() - connection_started_at
                    observe_stream_connection_closed(origin_product, outcome, duration)

        return StreamingHttpResponse(
            async_stream() if settings.SERVER_GATEWAY_INTERFACE == "ASGI" else async_to_sync(lambda: async_stream()),
            content_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @staticmethod
    def _get_event_type(entry: dict) -> str:
        """Extract the event type from a log entry for filtering purposes.

        For _posthog/* events, returns the notification method (e.g., '_posthog/console').
        For session/update events, returns the sessionUpdate value (e.g., 'agent_message_chunk').
        """
        notification = entry.get("notification", {})
        if not isinstance(notification, dict):
            return ""
        method = notification.get("method", "")

        if method == "session/update":
            params = notification.get("params", {})
            update = params.get("update", {}) if isinstance(params, dict) else {}
            return str(update.get("sessionUpdate", method)) if isinstance(update, dict) else method

        return method


def _activate_code_for_user(user, organization=None) -> None:
    """Capture an analytics event when a user redeems a Code invite."""
    posthoganalytics.capture(
        distinct_id=str(user.distinct_id),
        event="code_invite_redeemed",
        groups=groups(organization=organization),
    )


@extend_schema(tags=["code-invites"])
class CodeInviteViewSet(viewsets.ViewSet):
    """API for redeeming PostHog Code invite codes."""

    authentication_classes = [
        SessionAuthentication,
        PersonalAPIKeyAuthentication,
        OAuthAccessTokenAuthentication,
    ]
    permission_classes = [IsAuthenticated, APIScopePermission]

    scope_object = "task"

    http_method_names = ["get", "post", "head", "options"]
    throttle_classes = [CodeInviteThrottle]

    def get_permissions(self):
        # Both endpoints are user-account-level operations (not project data).
        if self.action in ("check_access", "redeem"):
            return [IsAuthenticated()]
        return super().get_permissions()

    @validated_request(
        request_serializer=CodeInviteRedeemRequestSerializer,
        responses={
            200: OpenApiResponse(description="Invite code redeemed successfully"),
            400: OpenApiResponse(
                response=TaskRunErrorResponseSerializer,
                description="Invalid or expired invite code",
            ),
        },
        summary="Redeem invite code",
        description="Redeem a PostHog Code invite code to enable access.",
    )
    @action(detail=False, methods=["post"], url_path="redeem")
    def redeem(self, request, **kwargs):
        code_str = request.validated_data["code"].strip()

        try:
            invite_code = CodeInvite.objects.get(code__iexact=code_str)
        except CodeInvite.DoesNotExist:
            return Response(
                TaskRunErrorResponseSerializer({"error": "Invalid invite code"}).data,
                status=status.HTTP_400_BAD_REQUEST,
            )

        if CodeInviteRedemption.objects.filter(invite_code=invite_code, user=request.user).exists():
            return Response({"success": True})

        with transaction.atomic():
            invite_code = CodeInvite.objects.select_for_update().get(id=invite_code.id)

            if not invite_code.is_redeemable:
                return Response(
                    TaskRunErrorResponseSerializer({"error": "This invite code is no longer valid"}).data,
                    status=status.HTTP_400_BAD_REQUEST,
                )

            organization = request.user.organization if hasattr(request.user, "organization") else None

            CodeInviteRedemption.objects.create(
                invite_code=invite_code,
                user=request.user,
                organization=organization,
            )

            CodeInvite.objects.filter(id=invite_code.id).update(redemption_count=F("redemption_count") + 1)

            _activate_code_for_user(request.user, organization=organization)

        return Response({"success": True})

    @extend_schema(
        responses={
            200: OpenApiResponse(description="Access check result"),
        },
        summary="Check access",
        description="Check whether the authenticated user has access to PostHog Code.",
    )
    @action(detail=False, methods=["get"], url_path="check-access")
    def check_access(self, request, **kwargs):
        return Response({"has_access": has_tasks_access(request.user)})


@extend_schema(tags=["sandbox-environments"])
class SandboxEnvironmentViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """API for managing sandbox environments that control network access for task runs."""

    serializer_class = SandboxEnvironmentSerializer
    authentication_classes = [
        SessionAuthentication,
        PersonalAPIKeyAuthentication,
        OAuthAccessTokenAuthentication,
    ]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "task"
    queryset = SandboxEnvironment.objects.all()
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    filter_rewrite_rules = {"team_id": "team_id"}

    def get_serializer_class(self):
        if self.action == "list":
            return SandboxEnvironmentListSerializer
        return SandboxEnvironmentSerializer

    def safely_get_queryset(self, queryset):
        user = self.request.user
        qs = queryset.filter(models.Q(private=False) | models.Q(created_by=user))
        # Exclude internal environments from list views by default
        if self.action == "list":
            qs = qs.filter(internal=False)
        return qs

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["team"] = self.team
        return context
