import os
import re
import json
import asyncio
import logging
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import UUID

from django.conf import settings
from django.http import HttpResponse, JsonResponse

import requests as http_requests
import posthoganalytics
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from posthog.api.mixins import validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.streaming import sse_streaming_response
from posthog.api.utils import ServerTimingsGathered
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication
from posthog.permissions import APIScopePermission
from posthog.rate_limit import CodeInviteThrottle
from posthog.renderers import ServerSentEventRenderer

from products.tasks.backend.facade import (
    access as tasks_access,
    api as tasks_facade,
    cancellation as tasks_cancellation,
    contracts as tasks_contracts,
)
from products.tasks.backend.facade.access import cloud_usage_limit_response, code_access_required_response
from products.tasks.backend.facade.metrics import (
    StreamConnectionOutcome,
    observe_stream_connection_closed,
    observe_stream_connection_opened,
    observe_stream_length_on_connect,
    observe_stream_resume_gap,
)
from products.tasks.backend.facade.streams import (
    TASK_RUN_STREAM_WAIT_DELAY_INCREMENT_SECONDS,
    TASK_RUN_STREAM_WAIT_INITIAL_DELAY_SECONDS,
    TASK_RUN_STREAM_WAIT_MAX_DELAY_SECONDS,
    TASK_RUN_STREAM_WAIT_TIMEOUT_SECONDS,
    TaskRunRedisStream,
    TaskRunStreamError,
    get_task_run_stream_key,
    run_uses_dedicated_stream,
)
from products.tasks.backend.presentation.serializers import (
    CodeInviteRedeemRequestSerializer,
    ConnectionTokenResponseSerializer,
    RepositoryReadinessQuerySerializer,
    RepositoryReadinessResponseSerializer,
    SandboxCustomImageBuildSerializer,
    SandboxCustomImageSerializer,
    SandboxCustomImageWriteSerializer,
    SandboxEnvironmentListSerializer,
    SandboxEnvironmentSerializer,
    SandboxEnvironmentWriteSerializer,
    SlackThreadContextQuerySerializer,
    SlackThreadContextResponseSerializer,
    StreamReadTokenResponseSerializer,
    TaskAutomationSerializer,
    TaskAutomationWriteSerializer,
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
    TaskRunCancelRequestSerializer,
    TaskRunCommandRequestSerializer,
    TaskRunCommandResponseSerializer,
    TaskRunCreateRequestSchemaSerializer,
    TaskRunCreateRequestSerializer,
    TaskRunDetailSerializer,
    TaskRunErrorResponseSerializer,
    TaskRunLivingArtifactCreateRequestSerializer,
    TaskRunLivingArtifactEditRequestSerializer,
    TaskRunLivingArtifactOpenResponseSerializer,
    TaskRunLivingArtifactResponseSerializer,
    TaskRunLivingArtifactsResponseSerializer,
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
    TaskWriteSerializer,
    WarmTaskRequestSerializer,
    WarmTaskResponseSerializer,
    WizardCloudRunHandleSerializer,
)

from ee.hogai.utils.aio import async_to_sync

logger = logging.getLogger(__name__)

TASKS_PREWARM_SANDBOX_FLAG = "tasks-prewarm-sandbox"

TASK_RUN_STREAM_KEEPALIVE_INTERVAL_SECONDS = 20.0
TASK_RUN_STREAM_KEEPALIVE_EVENT_NAME = "keepalive"
TASK_RUN_STREAM_KEEPALIVE_PAYLOAD = {"type": "keepalive"}
# Long-lived SSE connections pin NGINX Unit processes during recycle-drain, so
# cap each one: emit `event: end` so clients can tell rotation from run
# completion, then close. Clients resume from their Last-Event-ID cursor.
TASK_RUN_STREAM_CONNECTION_MAX_SECONDS = 15 * 60
TASK_RUN_STREAM_END_EVENT_NAME = "end"
TASK_RUN_STREAM_ROTATED_PAYLOAD = {"type": "rotated"}
# Distinct from the rotation `end` event above: this fires once when the run itself
# completes, so clients stop reconnecting instead of resuming from Last-Event-ID.
TASK_RUN_STREAM_COMPLETE_EVENT_NAME = "stream-end"
TASK_RUN_ARTIFACT_UPLOAD_EXPIRATION_SECONDS = 60 * 60


TASK_RUN_ARTIFACT_UPLOAD_FORM_OVERHEAD_BYTES = 64 * 1024


SESSION_LOG_PAGE_MAX_BYTES = 2 * 1024 * 1024
SESSION_LOG_PAGE_ENVELOPE_BYTES = 2


def _is_internal_debug_team(team_id: int | None) -> bool:
    if settings.DEBUG and not settings.TEST:
        return team_id == 1
    return team_id == 2 and settings.CLOUD_DEPLOYMENT == "US"


def _can_bypass_visibility(request, team_id: int | None) -> bool:
    """Whether this request may READ tasks/runs it doesn't own (never write — control stays creator-scoped).

    - Staff users: unconditionally, on any team (support/debugging). No opt-in needed, so staff don't hit
      the per-creator 404 when opening a task by URL or streaming its run logs — the frontend can't reliably
      thread a query param through every read (the SSE stream doesn't carry one).
    - Internal-debug teams: keep the narrower, explicit ``?ph_debug=true`` opt-in (dev/debug workflow).
    """
    if bool(getattr(request.user, "is_staff", False)):
        return True
    return _is_internal_debug_team(team_id) and request.query_params.get("ph_debug") == "true"


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


@extend_schema(tags=["tasks"])
class TaskViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """
    API for managing tasks within a project. Tasks represent units of work to be performed by an agent.
    """

    authentication_classes = [
        SessionAuthentication,
        PersonalAPIKeyAuthentication,
        OAuthAccessTokenAuthentication,
    ]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "task"
    pagination_class = TasksPagination
    # Fallback for drf-spectacular introspection only; every action declares its own
    # request/response schema via @validated_request / @extend_schema.
    serializer_class = TaskSerializer

    def _user_id(self) -> int | None:
        return getattr(self.request.user, "id", None)

    def _write_serializer(self, data, *, partial: bool = False) -> TaskWriteSerializer:
        serializer = TaskWriteSerializer(
            data=data,
            partial=partial,
            context={"team": self.team, "team_id": self.team.id, "request": self.request},
        )
        serializer.is_valid(raise_exception=True)
        return serializer

    @validated_request(
        query_serializer=TaskListQuerySerializer,
        responses={
            200: OpenApiResponse(response=TaskSerializer, description="List of tasks"),
        },
        summary="List tasks",
        description="Get a list of tasks for the current project, with optional filtering by origin product, stage, organization, repository, and created_by.",
    )
    def list(self, request, *args, **kwargs):
        filters = {key: request.query_params.get(key) for key in request.query_params}
        filters["internal"] = getattr(request, "validated_query_data", {}).get("internal")
        filters["archived"] = getattr(request, "validated_query_data", {}).get("archived")
        filters["channel"] = getattr(request, "validated_query_data", {}).get("channel")
        # Staff can opt into seeing every team task; re-check server-side so a client can't
        # forge the flag to bypass the per-user visibility gate.
        all_team_tasks = bool(getattr(request, "validated_query_data", {}).get("all_team_tasks"))
        bypass_visibility = all_team_tasks and _can_bypass_visibility(request, self.team_id)
        tasks = tasks_facade._list_tasks_queryset(
            self.team_id, self._user_id(), filters=filters, bypass_visibility=bypass_visibility
        )
        page = self.paginate_queryset(tasks)
        assert page is not None, "TaskViewSet list requires an active paginator"
        return self.get_paginated_response(
            TaskSerializer(tasks_facade._tasks_to_dtos(page, self.team_id), many=True).data
        )

    @extend_schema(
        responses={200: OpenApiResponse(response=TaskSerializer, description="Task")},
        summary="Get task",
        description="Retrieve a single task by ID.",
    )
    def retrieve(self, request, pk=None, **kwargs):
        bypass_visibility = _can_bypass_visibility(request, self.team_id)
        task = tasks_facade.get_task_detail(pk, self.team_id, self._user_id(), bypass_visibility=bypass_visibility)
        if task is None:
            raise NotFound()
        return Response(TaskSerializer(task).data)

    @extend_schema(request=TaskWriteSerializer, responses={201: TaskSerializer})
    def create(self, request, **kwargs):
        serializer = self._write_serializer(request.data)
        task = tasks_facade.create_task(self.team_id, self._user_id(), validated_data=dict(serializer.validated_data))
        return Response(TaskSerializer(task).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=TaskWriteSerializer, responses={200: TaskSerializer})
    def update(self, request, pk=None, **kwargs):
        return self.partial_update(request, pk=pk, **kwargs)

    @extend_schema(request=TaskWriteSerializer, responses={200: TaskSerializer})
    def partial_update(self, request, pk=None, **kwargs):
        serializer = self._write_serializer(request.data, partial=True)
        task = tasks_facade.update_task(
            pk, self.team_id, self._user_id(), validated_data=dict(serializer.validated_data)
        )
        if task is None:
            raise NotFound()
        return Response(TaskSerializer(task).data)

    @extend_schema(responses={204: None})
    def destroy(self, request, pk=None, **kwargs):
        if not tasks_facade.soft_delete_task(pk, self.team_id, self._user_id()):
            raise NotFound()
        return Response(status=status.HTTP_204_NO_CONTENT)

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
        repositories = tasks_facade.list_task_repositories(self.team_id, self._user_id())
        serializer = TaskRepositoriesResponseSerializer({"repositories": repositories})
        return Response(serializer.data)

    @extend_schema(
        responses={
            200: OpenApiResponse(
                response=WizardCloudRunHandleSerializer,
                description="The team's active onboarding wizard cloud run.",
            ),
            204: OpenApiResponse(description="No active onboarding wizard cloud run for this project."),
        },
        summary="Get the team's active onboarding wizard cloud run",
        description=(
            "Returns the most recent onboarding wizard cloud run for the current project when it is "
            "still running (or completed within the last day), so the setup-progress FAB can rehydrate "
            "after a drop-flow signup that started the run server-side. Returns 204 when there is none."
        ),
    )
    @action(
        detail=False,
        methods=["get"],
        url_path="active_wizard_run",
        required_scopes=["task:read"],
        pagination_class=None,
        filter_backends=[],
    )
    def active_wizard_run(self, request, **kwargs):
        handle = tasks_facade.get_active_wizard_cloud_run(self.team_id)
        if handle is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response(WizardCloudRunHandleSerializer(handle).data)

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
        summaries = tasks_facade.get_task_summaries(self.team_id, self._user_id(), ids=ids)
        page = self.paginate_queryset(summaries)
        if page is not None:
            return self.get_paginated_response(TaskSummarySerializer(page, many=True).data)
        return Response(TaskSummarySerializer(summaries, many=True).data)

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

        result = tasks_facade.compute_repository_readiness(
            self.team_id,
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
        url = request.validated_query_data["url"]
        parsed = _parse_slack_thread_url(url)
        if parsed is None:
            return Response(
                {"detail": "Could not parse channel/thread_ts from the provided Slack URL.", "url": url},
                status=status.HTTP_400_BAD_REQUEST,
            )
        channel, thread_ts = parsed
        result = tasks_facade.resolve_slack_thread_context(
            self.team_id, channel=channel, thread_ts=thread_ts, url=url, build_url=request.build_absolute_uri
        )
        if result.outcome == "no_mapping" and (thread := result.no_mapping_thread) is not None:
            return Response(
                {
                    "detail": "no_mapping",
                    "thread": {
                        "url": thread.url,
                        "channel": thread.channel,
                        "thread_ts": thread.thread_ts,
                        "slack_workspace_id": thread.slack_workspace_id,
                        "mentioning_slack_user_id": thread.mentioning_slack_user_id,
                    },
                },
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer = SlackThreadContextResponseSerializer(result.context)
        return Response(serializer.data)

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
        result = tasks_facade.prepare_task_staged_artifacts(
            pk,
            self.team_id,
            self._user_id(),
            artifacts=request.validated_data["artifacts"],
            upload_expiration_seconds=TASK_RUN_ARTIFACT_UPLOAD_EXPIRATION_SECONDS,
        )
        if result is None:
            raise NotFound()
        if result.error is not None:
            return Response(
                TaskRunErrorResponseSerializer({"error": result.error}).data,
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = TaskStagedArtifactsPrepareUploadResponseSerializer({"artifacts": result.artifacts})
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
        result = tasks_facade.finalize_task_staged_artifacts(
            pk, self.team_id, self._user_id(), artifacts=request.validated_data["artifacts"]
        )
        if result is None:
            raise NotFound()
        if result.error is not None:
            return Response(
                TaskRunErrorResponseSerializer({"error": result.error}).data,
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = TaskStagedArtifactsFinalizeUploadResponseSerializer({"artifacts": result.artifacts})
        return Response(serializer.data)

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
        include_serializer_context=True,
    )
    @action(detail=True, methods=["post"], url_path="run", required_scopes=["task:write"])
    def run(self, request, pk=None, **kwargs):
        # Original order: 404 if the task isn't visible, then gate (always cloud) before the run.
        if not tasks_facade.task_visible(pk, self.team_id, self._user_id(), for_control=True):
            raise NotFound()

        if (limit_response := cloud_usage_limit_response(request.user, self.team_id)) is not None:
            return limit_response

        result = tasks_facade.run_task(pk, self.team_id, self._user_id(), validated_data=dict(request.validated_data))
        if result is None:
            raise NotFound()
        if result.error is not None:
            return self._task_error_response(result.error)
        return Response(TaskSerializer(result.task).data)

    def _warm_enabled(self) -> bool:
        """Person + org level gate for the sandbox-warming feature. Fail-closed on any error."""
        user = self.request.user
        distinct_id = getattr(user, "distinct_id", None) or str(getattr(user, "uuid", ""))
        organization_id = str(getattr(self.team, "organization_id", "") or "")
        try:
            return bool(
                posthoganalytics.feature_enabled(
                    TASKS_PREWARM_SANDBOX_FLAG,
                    distinct_id,
                    groups={"organization": organization_id},
                    group_properties={"organization": {"id": organization_id}},
                    only_evaluate_locally=False,
                    send_feature_flag_events=False,
                )
            )
        except Exception:
            logger.exception("tasks-prewarm-sandbox flag check failed; treating as disabled")
            return False

    @validated_request(
        request_serializer=WarmTaskRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=WarmTaskResponseSerializer,
                description="Warm Run provisioned (`task_id`/`run_id` to activate on submit), or an empty body when the feature is off, capped, or the integration didn't resolve.",
            ),
        },
        summary="Warm a task sandbox",
        description=(
            "Warm a full idling Run for a Code-app cloud task while the user composes: boot a sandbox, "
            "clone the repo, check out the branch, and start the agent, then idle awaiting the first "
            "message. On submit the normal create+run path transparently reuses and activates this Run; "
            "abandoned warms are reaped by the Run's inactivity timeout. Best-effort: returns an empty "
            "body when the feature flag is off, the warm pool is full, or the GitHub integration doesn't "
            "belong to the team."
        ),
    )
    @action(detail=False, methods=["post"], url_path="warm", required_scopes=["task:write"])
    def warm(self, request, **kwargs):
        if not self._warm_enabled():
            return Response(status=status.HTTP_200_OK)

        if access_response := code_access_required_response(request.user):
            return access_response

        user_id = self._user_id()
        if user_id is None:
            return Response(status=status.HTTP_200_OK)

        github_integration_id = tasks_facade.resolve_team_github_integration_id(
            self.team_id, request.validated_data["github_integration"]
        )
        if github_integration_id is None:
            return Response(status=status.HTTP_200_OK)

        result = tasks_facade.warm_task_sandbox(
            self.team_id,
            user_id,
            repository=request.validated_data["repository"],
            github_integration_id=github_integration_id,
            branch=request.validated_data.get("branch"),
            runtime_adapter=request.validated_data.get("runtime_adapter"),
            model=request.validated_data.get("model"),
            reasoning_effort=request.validated_data.get("reasoning_effort"),
        )
        if result is None:
            return Response(status=status.HTTP_200_OK)
        return Response(WarmTaskResponseSerializer({"task_id": result.task_id, "run_id": result.run_id}).data)

    @staticmethod
    def _task_error_response(error: tasks_contracts.TaskValidationError) -> Response:
        if error.kind == "error":
            return Response(
                TaskRunErrorResponseSerializer({"error": error.detail}).data,
                status=status.HTTP_400_BAD_REQUEST,
            )
        if error.kind == "detail":
            body: dict[str, Any] = {"detail": error.detail}
            if error.missing_artifact_ids is not None:
                body["missing_artifact_ids"] = error.missing_artifact_ids
            return Response(body, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {"type": "validation_error", "code": error.code, "detail": error.detail, "attr": error.attr},
            status=status.HTTP_400_BAD_REQUEST,
        )

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
    def presence(self, request, pk=None, **kwargs):
        device_id = request.validated_data["device_id"]
        if request.method == "DELETE":
            outcome = tasks_facade.leave_task_presence(pk, self.team_id, self._user_id(), device_id=device_id)
        else:
            outcome = tasks_facade.beacon_task_presence(pk, self.team_id, self._user_id(), device_id=device_id)
        if outcome == "not_found":
            raise NotFound("device_id does not match a push token registered by the caller")
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(tags=["task-automations"])
class TaskAutomationViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """API for managing scheduled task automations."""

    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "task"
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def _write_serializer(self, data, *, partial: bool = False) -> TaskAutomationWriteSerializer:
        serializer = TaskAutomationWriteSerializer(
            data=data, partial=partial, context={"team": self.team, "team_id": self.team.id}
        )
        serializer.is_valid(raise_exception=True)
        return serializer

    @staticmethod
    def _facade_kwargs(validated_data: dict) -> dict:
        """Translate the resolved ``github_integration`` instance to its id for the facade."""
        kwargs = dict(validated_data)
        if "github_integration" in kwargs:
            integration = kwargs.pop("github_integration")
            kwargs["github_integration_id"] = integration.id if integration is not None else None
        return kwargs

    @extend_schema(responses={200: TaskAutomationSerializer(many=True)})
    def list(self, request, **kwargs):
        automations = tasks_facade.list_task_automations(self.team_id, getattr(request.user, "id", None))
        page = self.paginate_queryset(automations)
        if page is not None:
            return self.get_paginated_response(TaskAutomationSerializer(page, many=True).data)
        return Response(TaskAutomationSerializer(automations, many=True).data)

    @extend_schema(responses={200: TaskAutomationSerializer})
    def retrieve(self, request, pk=None, **kwargs):
        automation = tasks_facade.get_task_automation(pk, self.team_id, getattr(request.user, "id", None))
        if automation is None:
            raise NotFound()
        return Response(TaskAutomationSerializer(automation).data)

    @extend_schema(request=TaskAutomationWriteSerializer, responses={201: TaskAutomationSerializer})
    def create(self, request, **kwargs):
        if access_response := code_access_required_response(request.user):
            return access_response
        serializer = self._write_serializer(request.data)
        automation = tasks_facade.create_task_automation(
            self.team_id, getattr(request.user, "id", None), **self._facade_kwargs(serializer.validated_data)
        )
        return Response(TaskAutomationSerializer(automation).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=TaskAutomationWriteSerializer, responses={200: TaskAutomationSerializer})
    def partial_update(self, request, pk=None, **kwargs):
        serializer = self._write_serializer(request.data, partial=True)
        if serializer.validated_data.get("enabled") is True:
            if access_response := code_access_required_response(request.user):
                return access_response
        automation = tasks_facade.update_task_automation(
            pk, self.team_id, getattr(request.user, "id", None), **self._facade_kwargs(serializer.validated_data)
        )
        if automation is None:
            raise NotFound()
        return Response(TaskAutomationSerializer(automation).data)

    @extend_schema(responses={204: None})
    def destroy(self, request, pk=None, **kwargs):
        if not tasks_facade.delete_task_automation(pk, self.team_id, getattr(request.user, "id", None)):
            raise NotFound()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(request=None, responses={200: TaskAutomationSerializer})
    @action(detail=True, methods=["post"], url_path="run", required_scopes=["task:write"])
    def run(self, request, pk=None, **kwargs):
        if access_response := code_access_required_response(request.user):
            return access_response
        automation = tasks_facade.run_task_automation_now(pk, self.team_id, getattr(request.user, "id", None))
        if automation is None:
            raise NotFound()
        return Response(TaskAutomationSerializer(automation).data)


@extend_schema(tags=["task-runs", "tasks"])
class TaskRunViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """
    API for managing task runs. Each run represents an execution of a task.
    """

    authentication_classes = [
        SessionAuthentication,
        PersonalAPIKeyAuthentication,
        OAuthAccessTokenAuthentication,
    ]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "task"
    http_method_names = ["get", "post", "patch", "head", "options"]
    pagination_class = TasksPagination
    # Fallback for drf-spectacular introspection only; every action declares its own
    # request/response schema via @validated_request / @extend_schema.
    serializer_class = TaskRunDetailSerializer

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "team": self.team, "team_id": self.team.id}

    def _task_id(self) -> str:
        task_id = self.kwargs.get("parent_lookup_task_id")
        if not task_id:
            raise NotFound("Task ID is required")
        try:
            UUID(task_id)
        except (ValueError, TypeError):
            raise NotFound("Task not found")
        return task_id

    def _user_id(self) -> int | None:
        return getattr(self.request.user, "id", None)

    # Actions that only read run state. Everything else mutates or drives the
    # run, so it requires task control (not just visibility): public-channel
    # visibility lets teammates watch a run, never command it. connection_token
    # is a GET but mints a write-capable token, so it is deliberately absent.
    _READ_ONLY_ACTIONS = (
        "list",
        "retrieve",
        "logs",
        "session_logs",
        "stream",
        "stream_token",
        "artifacts_presign",
        "artifacts_download",
    )

    def _ensure_task_accessible(self) -> str:
        """Gate access to the parent task, mirroring the old ``safely_get_queryset``.

        Staff users (and internal-debug teams via ``?ph_debug=true``) may read another member's runs
        through the read-only actions; the bypass never applies to control actions.
        """
        task_id = self._task_id()
        is_read_only = self.action in self._READ_ONLY_ACTIONS
        bypass_visibility = is_read_only and _can_bypass_visibility(self.request, self.team_id)
        if not tasks_facade.task_accessible_for_run_view(
            task_id,
            self.team_id,
            self._user_id(),
            bypass_visibility=bypass_visibility,
            for_control=not is_read_only,
        ):
            raise NotFound("Task not found")
        return task_id

    def _get_run_or_404(self, pk) -> tasks_contracts.TaskRunDetailDTO:
        task_id = self._ensure_task_accessible()
        run = tasks_facade.get_task_run_detail(pk, task_id, self.team_id)
        if run is None:
            raise NotFound()
        return run

    @validated_request(
        responses={
            200: OpenApiResponse(response=TaskRunDetailSerializer, description="List of task runs"),
        },
        summary="List task runs",
        description="Get a list of runs for a specific task.",
    )
    def list(self, request, *args, **kwargs):
        task_id = self._ensure_task_accessible()
        runs = tasks_facade.list_task_runs(task_id, self.team_id)
        page = self.paginate_queryset(runs)
        if page is not None:
            return self.get_paginated_response(TaskRunDetailSerializer(page, many=True).data)
        return Response(TaskRunDetailSerializer(runs, many=True).data)

    @validated_request(
        responses={
            200: OpenApiResponse(response=TaskRunDetailSerializer, description="Task run"),
            404: OpenApiResponse(description="Task run not found"),
        },
        summary="Get task run",
        description="Retrieve a single run for a specific task.",
    )
    def retrieve(self, request, pk=None, **kwargs):
        return Response(TaskRunDetailSerializer(self._get_run_or_404(pk)).data)

    def _validation_error_response(self, error: tasks_contracts.TaskRunValidationError) -> Response:
        if error.kind == "detail":
            return Response({"detail": error.detail}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {"type": "validation_error", "code": error.code, "detail": error.detail, "attr": error.attr},
            status=status.HTTP_400_BAD_REQUEST,
        )

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
        include_serializer_context=True,
    )
    def create(self, request, *args, **kwargs):
        task_id = self._task_id()
        environment = request.validated_data.get("environment", tasks_facade.TaskRunEnvironment.LOCAL)

        # Gate cloud runs before the run row is created; local runs aren't limited.
        if environment == tasks_facade.TaskRunEnvironment.CLOUD:
            if (limit_response := cloud_usage_limit_response(request.user, self.team_id)) is not None:
                return limit_response

        result = tasks_facade.bootstrap_task_run(
            task_id, self.team_id, self._user_id(), validated_data=dict(request.validated_data)
        )
        if result is None:
            raise NotFound("Task not found")
        if result.error is not None:
            return self._validation_error_response(result.error)
        return Response(TaskRunDetailSerializer(result.run).data, status=status.HTTP_201_CREATED)

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
        task_id = self._ensure_task_accessible()

        startable = tasks_facade.check_task_run_startable(pk, task_id, self.team_id)
        if startable == "not_found":
            raise NotFound()
        if startable == "not_cloud":
            return Response(
                TaskRunErrorResponseSerializer({"error": "Only cloud runs can be started via this endpoint"}).data,
                status=status.HTTP_400_BAD_REQUEST,
            )
        if startable.startswith("bad_status:"):
            current_status = startable.split(":", 1)[1]
            return Response(
                TaskRunErrorResponseSerializer(
                    {
                        "error": f"Only queued or not_started cloud runs can be started (current status: {current_status})"
                    }
                ).data,
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Backstop: don't launch the cloud workflow for an over-limit team.
        if (limit_response := cloud_usage_limit_response(request.user, self.team_id)) is not None:
            return limit_response

        outcome, started_task_id = tasks_facade.start_task_run(
            pk, task_id, self.team_id, self._user_id(), validated_data=dict(request.validated_data)
        )
        if outcome == "not_found":
            raise NotFound()
        if outcome.startswith("missing_artifacts:"):
            missing = [m for m in outcome.split(":", 1)[1].split(",") if m]
            return Response(
                {
                    "detail": "Some pending_user_artifact_ids are invalid for this run",
                    "missing_artifact_ids": missing,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if started_task_id is None:
            raise NotFound()
        task_dto = tasks_facade.get_task_detail(started_task_id, self.team_id, self._user_id())
        if task_dto is None:
            raise NotFound()
        return Response(TaskSerializer(task_dto).data)

    @validated_request(
        request_serializer=TaskRunCancelRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=TaskRunDetailSerializer, description="Run already finished; returned unchanged"
            ),
            202: OpenApiResponse(response=TaskRunDetailSerializer, description="Cancellation accepted"),
            400: OpenApiResponse(response=TaskRunErrorResponseSerializer, description="Run is not a cloud run"),
            404: OpenApiResponse(description="Task run not found"),
            503: OpenApiResponse(
                response=TaskRunErrorResponseSerializer,
                description="Cancellation could not be delivered; safe to retry",
            ),
        },
        summary="Cancel task run",
        description="Stop an active cloud run. Interrupts the agent, snapshots interactive sessions for "
        "later resume, tears down the sandbox, and marks the run cancelled. Idempotent: cancelling a "
        "finished run returns it unchanged.",
        strict_request_validation=True,
    )
    @action(detail=True, methods=["post"], url_path="cancel", required_scopes=["task:write"])
    def cancel(self, request, pk=None, **kwargs):
        task_id = self._ensure_task_accessible()
        outcome, run = tasks_cancellation.cancel_task_run(
            pk,
            task_id,
            self.team_id,
            reason=request.validated_data.get("reason"),
            source="api",
            requested_by_user_id=request.user.id,
            requested_by_distinct_id=request.user.distinct_id,
        )
        if outcome == "not_found" or run is None:
            raise NotFound()
        if outcome == "already_terminal":
            return Response(TaskRunDetailSerializer(run).data)
        if outcome == "not_cloud":
            return Response(
                TaskRunErrorResponseSerializer({"error": "Only cloud runs can be cancelled via this endpoint"}).data,
                status=status.HTTP_400_BAD_REQUEST,
            )
        if outcome == "unavailable":
            return Response(
                TaskRunErrorResponseSerializer({"error": "Could not reach the run's workflow; try again"}).data,
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response(TaskRunDetailSerializer(run).data, status=status.HTTP_202_ACCEPTED)

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
        pk = kwargs.get("pk")
        if pk is None:
            raise NotFound()
        task_id = self._ensure_task_accessible()
        run = tasks_facade.update_task_run(pk, task_id, self.team_id, validated_data=dict(request.validated_data))
        if run is None:
            raise NotFound()
        return Response(TaskRunDetailSerializer(run).data)

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
        task_id = self._ensure_task_accessible()
        output_data = request.validated_data["output"]

        validation_error = tasks_facade.validate_set_output(pk, task_id, self.team_id, output=output_data)
        if validation_error is not None:
            return Response(
                TaskRunErrorResponseSerializer({"error": validation_error}).data,
                status=status.HTTP_400_BAD_REQUEST,
            )

        run = tasks_facade.set_task_run_output(pk, task_id, self.team_id, output=output_data)
        if run is None:
            raise NotFound()
        return Response(TaskRunDetailSerializer(run).data)

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
        task_id = self._ensure_task_accessible()
        timer = ServerTimingsGathered()

        entries = request.validated_data["entries"]
        with timer("s3_append"):
            run = tasks_facade.append_task_run_log(pk, task_id, self.team_id, entries=entries)
        if run is None:
            raise NotFound()

        response = Response(TaskRunDetailSerializer(run).data)
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
        task_id = self._ensure_task_accessible()
        relay_status, relay_id = tasks_facade.relay_task_run_message(
            pk,
            task_id,
            self.team_id,
            text=request.validated_data["text"],
            text_parts=request.validated_data.get("text_parts"),
        )
        if relay_status == "failed":
            return Response(
                TaskRunErrorResponseSerializer({"error": "Failed to queue Slack relay"}).data,
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        if relay_status == "accepted":
            return Response({"status": "accepted", "relay_id": relay_id})
        return Response({"status": "skipped"})

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
        task_id = self._ensure_task_accessible()
        result = tasks_facade.upload_task_run_artifacts(
            pk, task_id, self.team_id, artifacts=request.validated_data["artifacts"]
        )
        if result is None:
            raise NotFound()
        _uploaded, manifest = result
        serializer = TaskRunArtifactsUploadResponseSerializer({"artifacts": manifest})
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
        task_id = self._ensure_task_accessible()
        prepared, ok = tasks_facade.prepare_task_run_artifact_uploads(
            pk,
            task_id,
            self.team_id,
            artifacts=request.validated_data["artifacts"],
            upload_expiration_seconds=TASK_RUN_ARTIFACT_UPLOAD_EXPIRATION_SECONDS,
            form_overhead_bytes=TASK_RUN_ARTIFACT_UPLOAD_FORM_OVERHEAD_BYTES,
        )
        if prepared is None and ok:
            raise NotFound()
        if not ok:
            return Response(
                TaskRunErrorResponseSerializer({"error": "Unable to generate upload URL"}).data,
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = TaskRunArtifactsPrepareUploadResponseSerializer({"artifacts": prepared})
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
        task_id = self._ensure_task_accessible()
        finalized_entries, error = tasks_facade.finalize_task_run_artifact_uploads(
            pk, task_id, self.team_id, artifacts=request.validated_data["artifacts"]
        )
        if finalized_entries is None and error is None:
            raise NotFound()
        if error is not None:
            return Response(
                TaskRunErrorResponseSerializer({"error": error}).data,
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = TaskRunArtifactsFinalizeUploadResponseSerializer({"artifacts": finalized_entries})
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
        task_id = self._ensure_task_accessible()
        storage_path = request.validated_data["storage_path"]
        url, error = tasks_facade.presign_task_run_artifact(pk, task_id, self.team_id, storage_path=storage_path)
        if url is None and error is None:
            raise NotFound()
        if error == "not_found":
            return Response(
                TaskRunErrorResponseSerializer({"error": "Artifact not found on this run"}).data,
                status=status.HTTP_404_NOT_FOUND,
            )
        if error == "unavailable":
            return Response(
                TaskRunErrorResponseSerializer({"error": "Unable to generate download URL"}).data,
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = TaskRunArtifactPresignResponseSerializer({"url": url, "expires_in": 3600})
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
        task_id = self._ensure_task_accessible()
        storage_path = request.validated_data["storage_path"]

        # Walk the resume chain so cloud→cloud resume runs can fetch the git checkpoint
        # pack/index that lives on the prior run they were forked from.
        content, artifact, error = tasks_facade.read_task_run_artifact(
            pk, task_id, self.team_id, storage_path=storage_path
        )
        if content is None and artifact is None and error is None:
            raise NotFound()
        if error == "not_found":
            return Response(
                TaskRunErrorResponseSerializer({"error": "Artifact not found on this run"}).data,
                status=status.HTTP_404_NOT_FOUND,
            )
        if error == "read_failed":
            return Response(
                TaskRunErrorResponseSerializer({"error": "Unable to read artifact"}).data,
                status=status.HTTP_400_BAD_REQUEST,
            )
        if error == "content_missing":
            return Response(
                TaskRunErrorResponseSerializer({"error": "Artifact content not found"}).data,
                status=status.HTTP_404_NOT_FOUND,
            )
        if artifact is None:
            raise NotFound()

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
        task_id = self._ensure_task_accessible()
        timer = ServerTimingsGathered()
        with timer("s3_read"):
            log_content = tasks_facade.read_task_run_logs(pk, task_id, self.team_id)
        if log_content is None:
            raise NotFound()

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
        task_id = self._ensure_task_accessible()
        user = request.user
        token = tasks_facade.create_task_run_connection_token(
            pk, task_id, self.team_id, user_id=user.id, distinct_id=user.distinct_id
        )
        if token is None:
            raise NotFound()
        return Response(ConnectionTokenResponseSerializer({"token": token}).data)

    @validated_request(
        responses={
            200: OpenApiResponse(
                response=StreamReadTokenResponseSerializer,
                description="Run-scoped token for reading the live event stream via the agent-proxy",
            ),
            404: OpenApiResponse(description="Task run not found"),
        },
        summary="Get task run stream read token",
        description="Generate a run-scoped JWT that authorizes reading this task run's live event stream via the agent-proxy.",
    )
    @action(
        detail=True,
        methods=["get"],
        url_path="stream_token",
        required_scopes=["task:read"],
    )
    def stream_token(self, request, pk=None, **kwargs):
        task_id = self._ensure_task_accessible()
        token = tasks_facade.create_task_run_stream_read_token(pk, task_id, self.team_id)
        if token is None:
            raise NotFound()
        stream_base_url = tasks_facade.resolve_stream_base_url(
            distinct_id=request.user.distinct_id, organization_id=self.team.organization_id
        )
        return Response(StreamReadTokenResponseSerializer({"token": token, "stream_base_url": stream_base_url}).data)

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
        task_id = self._ensure_task_accessible()
        method = request.validated_data["method"]
        request_id = request.validated_data.get("id")
        params = request.validated_data.get("params")

        if method == "user_message":
            if access_response := code_access_required_response(request.user):
                return access_response
            command_params = dict(params or {})
            artifact_ids = command_params.pop("artifact_ids", [])
            if artifact_ids:
                missing_artifact_ids, found = tasks_facade.validate_task_run_artifact_ids(
                    pk, task_id, self.team_id, artifact_ids=artifact_ids
                )
                if not found:
                    raise NotFound()
                if missing_artifact_ids:
                    return Response(
                        {
                            "error": "Some artifact_ids are invalid for this run",
                            "missing_artifact_ids": missing_artifact_ids,
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

            signal_result = tasks_facade.signal_task_run_user_message(
                pk, task_id, self.team_id, content=command_params.get("content"), artifact_ids=artifact_ids
            )
            if signal_result is None:
                raise NotFound()
            if signal_result is False:
                return Response(
                    TaskRunErrorResponseSerializer({"error": "Failed to queue user message for task run"}).data,
                    status=status.HTTP_502_BAD_GATEWAY,
                )

            # A warm Run has now received a human message — drop the warm flag so the warm-pool cap
            # (see products/tasks/backend/logic/services/warm.py) stops counting it. No-op for Runs
            # that were never warm; best-effort, since a failure only over-counts the pool until terminal.
            try:
                tasks_facade.update_task_run_state(pk, remove_keys=["await_user_message"])
            except Exception:
                logger.warning("Failed to clear await_user_message for task run %s", pk)

            response_payload: dict[str, Any] = {
                "jsonrpc": request.validated_data["jsonrpc"],
                "result": {"queued": True},
            }
            if request_id is not None:
                response_payload["id"] = request_id
            return Response(TaskRunCommandResponseSerializer(response_payload).data)

        connection = tasks_facade.get_task_run_sandbox_connection(
            pk, task_id, self.team_id, user_id=request.user.id, distinct_id=request.user.distinct_id
        )
        if connection is None:
            raise NotFound()

        if not connection.sandbox_url:
            return Response(
                TaskRunErrorResponseSerializer({"error": "No active sandbox for this task run"}).data,
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not self._is_valid_sandbox_url(connection.sandbox_url):
            logger.warning(f"Blocked request to disallowed sandbox URL for task run {pk}")
            return Response(
                TaskRunErrorResponseSerializer({"error": "Invalid sandbox URL"}).data,
                status=status.HTTP_400_BAD_REQUEST,
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
                sandbox_url=connection.sandbox_url,
                connection_token=connection.connection_token,
                sandbox_connect_token=connection.sandbox_connect_token,
                payload=command_payload,
            )

            tasks_facade.capture_relay_command_telemetry(
                pk, task_id, self.team_id, method=method, params=params, success=agent_response.ok
            )
            if agent_response.ok:
                return Response(agent_response.json())

            try:
                error_body = agent_response.json()
            except Exception:
                error_body = {}

            if agent_response.status_code == 401:
                error_msg = error_body.get("error", "Agent server authentication failed")
                logger.warning(f"Agent server auth failed for task run {pk}: {error_msg}")
            elif agent_response.status_code == 400:
                error_msg = error_body.get("error", "Agent server rejected the command")
                logger.warning(f"Agent server rejected command for task run {pk}: {error_msg}")
            else:
                error_msg = error_body.get("error", f"Agent server returned {agent_response.status_code}")

            return Response(
                TaskRunErrorResponseSerializer({"error": error_msg}).data,
                status=status.HTTP_502_BAD_GATEWAY,
            )

        except http_requests.ConnectionError:
            logger.warning(f"Agent server unreachable for task run {pk}")
            tasks_facade.capture_relay_command_telemetry(
                pk, task_id, self.team_id, method=method, params=params, success=False
            )
            return Response(
                TaskRunErrorResponseSerializer({"error": "Agent server is not reachable"}).data,
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except http_requests.Timeout:
            logger.warning(f"Agent server request timed out for task run {pk}")
            tasks_facade.capture_relay_command_telemetry(
                pk, task_id, self.team_id, method=method, params=params, success=False
            )
            return Response(
                TaskRunErrorResponseSerializer({"error": "Agent server request timed out"}).data,
                status=status.HTTP_504_GATEWAY_TIMEOUT,
            )
        except Exception:
            logger.exception(f"Failed to proxy command to agent server for task run {pk}")
            tasks_facade.capture_relay_command_telemetry(
                pk, task_id, self.team_id, method=method, params=params, success=False
            )
            return Response(
                TaskRunErrorResponseSerializer({"error": "Failed to send command to agent server"}).data,
                status=status.HTTP_502_BAD_GATEWAY,
            )

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
        connection_token: str | None,
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
        task_id = self._ensure_task_accessible()
        timer = ServerTimingsGathered()

        with timer("s3_read"):
            log_content = tasks_facade.read_task_run_logs(pk, task_id, self.team_id)
        if log_content is None:
            raise NotFound()

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

        page: list = []
        page_bytes = SESSION_LOG_PAGE_ENVELOPE_BYTES
        for entry in filtered[offset : offset + limit]:
            entry_bytes = len(json.dumps(entry)) + SESSION_LOG_PAGE_ENVELOPE_BYTES
            if page and page_bytes + entry_bytes > SESSION_LOG_PAGE_MAX_BYTES:
                break
            page.append(entry)
            page_bytes += entry_bytes

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
        task_id = self._ensure_task_accessible()
        if tasks_facade.get_task_run_detail(pk, task_id, self.team_id) is None:
            raise NotFound()

        # Resume also runs in cloud: gate before handoff.
        if (limit_response := cloud_usage_limit_response(request.user, self.team_id)) is not None:
            return limit_response

        outcome, run, _ = tasks_facade.resume_task_run_in_cloud(pk, task_id, self.team_id, self._user_id())
        if outcome == "not_found":
            raise NotFound()
        if outcome == "already_active":
            return Response(
                TaskRunErrorResponseSerializer({"error": "Run is already active in cloud"}).data,
                status=status.HTTP_400_BAD_REQUEST,
            )
        if outcome.startswith("auth_error:"):
            detail = outcome.split(":", 1)[1]
            return Response(
                {
                    "type": "validation_error",
                    "code": "github_authorization_required",
                    "detail": detail,
                    "attr": "pr_authorship_mode",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        if outcome == "workflow_failed":
            return Response(
                TaskRunErrorResponseSerializer({"error": "Failed to start cloud workflow"}).data,
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(TaskRunDetailSerializer(run).data)

    @staticmethod
    def _format_sse_event(data: dict, *, event_id: str | None = None, event_name: str | None = None) -> bytes:
        parts: list[str] = []
        if event_name:
            parts.append(f"event: {event_name}")
        if event_id:
            parts.append(f"id: {event_id}")
        parts.append(f"data: {json.dumps(data)}")
        return ("\n".join(parts) + "\n\n").encode()

    @extend_schema(
        description=(
            "Server-Sent Events stream of task run events. Events carry an `id:` line "
            "(a Redis stream id) usable as a resume cursor.\n\n"
            f"The server caps each connection at {TASK_RUN_STREAM_CONNECTION_MAX_SECONDS} seconds: it emits "
            '`event: end` with `data: {"type": "rotated"}` and closes. This does NOT mean the run '
            "finished — reconnect with the `Last-Event-ID` header set to the last received event id to "
            "resume without gaps or duplicates. Only treat the stream as complete when the run itself "
            "reaches a terminal status.\n\n"
            "`?start=latest` consumers must also carry `Last-Event-ID` across reconnects: reconnecting "
            "without it re-resolves to the then-current latest event, silently skipping anything published "
            "while disconnected.\n\n"
            "**SDK consumers**: do not call the generated fetch wrapper for this path — it will buffer "
            "the entire stream. Use the URL builder (`getTasksRunsStreamRetrieveUrl`) with a streaming "
            "`fetch`/`EventSource`-style consumer and the `Last-Event-ID` header instead."
        ),
        parameters=[
            OpenApiParameter(
                name="start",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Set to `latest` to skip the event backlog and only receive events published after connecting.",
            ),
            OpenApiParameter(
                name="Last-Event-ID",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.HEADER,
                required=False,
                description="Resume cursor: the `id:` of the last event received on a previous connection. Events strictly after it are delivered.",
            ),
        ],
        responses={(200, "text/event-stream"): OpenApiTypes.STR},
    )
    @action(
        detail=True,
        methods=["get"],
        url_path="stream",
        required_scopes=["task:read"],
        renderer_classes=[ServerSentEventRenderer],
    )
    def stream(self, request, pk=None, **kwargs):
        task_id = self._ensure_task_accessible()
        stream_info = tasks_facade.get_task_run_stream_info(pk, task_id, self.team_id)
        if stream_info is None:
            raise NotFound()

        stream_key = get_task_run_stream_key(str(stream_info.id))
        use_dedicated_stream = run_uses_dedicated_stream(stream_info.state)
        last_event_id = request.headers.get("Last-Event-ID")
        start_latest = request.GET.get("start") == "latest"
        format_sse_event = self._format_sse_event
        origin_product = stream_info.origin_product

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
                        else:
                            event_id, event = stream_item
                            yield format_sse_event(event, event_id=event_id)
                        if (
                            asyncio.get_running_loop().time() - connection_started_at
                            >= TASK_RUN_STREAM_CONNECTION_MAX_SECONDS
                        ):
                            outcome = "rotated"
                            # Without this marker a rotation EOF would be
                            # indistinguishable from run completion for API
                            # consumers reading until EOF.
                            yield format_sse_event(
                                TASK_RUN_STREAM_ROTATED_PAYLOAD,
                                event_name=TASK_RUN_STREAM_END_EVENT_NAME,
                            )
                            return
                    outcome = "completed"
                    # read_stream_entries only returns on the completion sentinel; emit an
                    # explicit terminal event so the client stops reconnecting without
                    # consulting run status (a dropped connection never reaches here).
                    yield format_sse_event({"status": "complete"}, event_name=TASK_RUN_STREAM_COMPLETE_EVENT_NAME)
                except TaskRunStreamError as e:
                    outcome = "stream_error"
                    logger.error("TaskRunRedisStream error for stream %s: %s", stream_key, e, exc_info=True)
                    yield format_sse_event({"error": str(e)}, event_name="error")
            finally:
                if opened:
                    duration = asyncio.get_running_loop().time() - connection_started_at
                    observe_stream_connection_closed(origin_product, outcome, duration)

        # Releases the request-thread DB connection (auth, task lookup) before the
        # long-lived stream begins — see sse_streaming_response. The stream body is
        # Redis-only, so it never re-acquires one.
        return sse_streaming_response(
            async_stream() if settings.SERVER_GATEWAY_INTERFACE == "ASGI" else async_to_sync(lambda: async_stream()),
            endpoint="task_run_log",
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


class TaskRunLivingArtifactViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """
    API for a task run's living artifacts — stable, versioned deliverable handles
    (Slack canvases/messages/files, connected documents) that agents create and edit.
    """

    authentication_classes = [
        SessionAuthentication,
        PersonalAPIKeyAuthentication,
        OAuthAccessTokenAuthentication,
    ]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "task"
    http_method_names = ["get", "post", "head", "options"]
    # The artifact registry is small and bounded per task; the response is a plain list.
    pagination_class = None
    # Fallback for drf-spectacular introspection only; every action declares its own
    # request/response schema via @validated_request.
    serializer_class = TaskRunLivingArtifactResponseSerializer

    def _task_id(self) -> str:
        task_id = self.kwargs.get("parent_lookup_task_id")
        if not task_id:
            raise NotFound("Task ID is required")
        try:
            UUID(task_id)
        except (ValueError, TypeError):
            raise NotFound("Task not found")
        return task_id

    def _run_id(self) -> str:
        run_id = self.kwargs.get("parent_lookup_run_id")
        if not run_id:
            raise NotFound("Run ID is required")
        return run_id

    def _ensure_task_accessible(self) -> str:
        """Gate access to the parent task, mirroring ``TaskRunViewSet._ensure_task_accessible``."""
        task_id = self._task_id()
        is_read = self.action in ("list", "retrieve")
        bypass_visibility = is_read and _can_bypass_visibility(self.request, self.team_id)
        if not tasks_facade.task_accessible_for_run_view(
            task_id, self.team_id, getattr(self.request.user, "id", None), bypass_visibility=bypass_visibility
        ):
            raise NotFound("Task not found")
        return task_id

    @validated_request(
        responses={
            200: OpenApiResponse(
                response=TaskRunLivingArtifactsResponseSerializer,
                description="Living artifacts registered for this task run",
            ),
            404: OpenApiResponse(description="Run not found"),
        },
        summary="List living artifacts for a task run",
        description="Returns stable, versioned artifact handles created by the run's task.",
        strict_request_validation=True,
        operation_id="tasks_runs_living_artifacts_list",
    )
    def list(self, request, *args, **kwargs):
        task_id = self._ensure_task_accessible()
        artifacts = tasks_facade.list_task_run_living_artifacts(self._run_id(), task_id, self.team_id)
        if artifacts is None:
            raise NotFound()
        serializer = TaskRunLivingArtifactsResponseSerializer({"artifacts": artifacts})
        return Response(serializer.data)

    @validated_request(
        request_serializer=TaskRunLivingArtifactCreateRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=TaskRunLivingArtifactResponseSerializer,
                description="Created living artifact",
            ),
            400: OpenApiResponse(response=TaskRunErrorResponseSerializer, description="Invalid artifact payload"),
            404: OpenApiResponse(description="Run not found"),
        },
        summary="Create a living artifact for a task run",
        description=(
            "Create a stable, editable artifact handle from direct markdown/text content or an existing run artifact. "
            "Slack adapters deliver into the mapped Slack thread; document artifacts use external connector storage "
            "when available."
        ),
        strict_request_validation=True,
        operation_id="tasks_runs_living_artifacts_create",
    )
    def create(self, request, *args, **kwargs):
        task_id = self._ensure_task_accessible()
        artifact, error = tasks_facade.create_task_run_living_artifact(
            self._run_id(), task_id, self.team_id, artifact=request.validated_data
        )
        if artifact is None and error is None:
            raise NotFound()
        if error is not None:
            return Response(TaskRunErrorResponseSerializer({"error": error}).data, status=status.HTTP_400_BAD_REQUEST)
        serializer = TaskRunLivingArtifactResponseSerializer(artifact)
        return Response(serializer.data)

    @validated_request(
        responses={
            200: OpenApiResponse(
                response=TaskRunLivingArtifactOpenResponseSerializer,
                description="Living artifact with current readable content",
            ),
            404: OpenApiResponse(description="Living artifact not found"),
        },
        summary="Open a living artifact for a task run",
        description="Return a stable living artifact handle and the current content when the adapter supports reads.",
        strict_request_validation=True,
        operation_id="tasks_runs_living_artifacts_open",
    )
    def retrieve(self, request, pk=None, **kwargs):
        task_id = self._ensure_task_accessible()
        artifact = tasks_facade.get_task_run_living_artifact(self._run_id(), task_id, self.team_id, artifact_id=pk)
        if artifact is None:
            raise NotFound()
        serializer = TaskRunLivingArtifactOpenResponseSerializer(artifact)
        return Response(serializer.data)

    @validated_request(
        request_serializer=TaskRunLivingArtifactEditRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=TaskRunLivingArtifactResponseSerializer,
                description="Updated living artifact",
            ),
            400: OpenApiResponse(response=TaskRunErrorResponseSerializer, description="Invalid artifact update"),
            404: OpenApiResponse(description="Living artifact not found"),
        },
        summary="Edit a living artifact for a task run",
        description="Commit a new version to an existing living artifact handle.",
        strict_request_validation=True,
        operation_id="tasks_runs_living_artifacts_edit",
    )
    @action(detail=True, methods=["post"], url_path="edit", required_scopes=["task:write"])
    def edit(self, request, pk=None, **kwargs):
        task_id = self._ensure_task_accessible()
        artifact, error = tasks_facade.edit_task_run_living_artifact(
            self._run_id(),
            task_id,
            self.team_id,
            artifact_id=pk,
            content=request.validated_data.get("content"),
            content_bytes=request.validated_data.get("content_bytes"),
            content_type=request.validated_data.get("content_type"),
            source_artifact_id=request.validated_data.get("source_artifact_id"),
            source_storage_path=request.validated_data.get("source_storage_path"),
            name=request.validated_data.get("name"),
            metadata=request.validated_data.get("metadata"),
        )
        if artifact is None and error is None:
            raise NotFound()
        if error == "not_found":
            raise NotFound()
        if error is not None:
            return Response(TaskRunErrorResponseSerializer({"error": error}).data, status=status.HTTP_400_BAD_REQUEST)
        serializer = TaskRunLivingArtifactResponseSerializer(artifact)
        return Response(serializer.data)


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
        result = tasks_facade.redeem_code_invite(request.validated_data["code"], request.user.id)

        if result.outcome == tasks_facade.CODE_INVITE_INVALID_CODE:
            return Response(
                TaskRunErrorResponseSerializer({"error": "Invalid invite code"}).data,
                status=status.HTTP_400_BAD_REQUEST,
            )
        if result.outcome == tasks_facade.CODE_INVITE_NOT_REDEEMABLE:
            return Response(
                TaskRunErrorResponseSerializer({"error": "This invite code is no longer valid"}).data,
                status=status.HTTP_400_BAD_REQUEST,
            )

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
        return Response({"has_access": tasks_access.has_tasks_access(request.user)})


@extend_schema(tags=["sandbox-environments"])
class SandboxEnvironmentViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """API for managing sandbox environments that control network access for task runs."""

    authentication_classes = [
        SessionAuthentication,
        PersonalAPIKeyAuthentication,
        OAuthAccessTokenAuthentication,
    ]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "task"
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    @extend_schema(responses={200: SandboxEnvironmentListSerializer(many=True)})
    def list(self, request, **kwargs):
        envs = tasks_facade.list_sandbox_environments(self.team_id, request.user.id)
        page = self.paginate_queryset(envs)
        if page is not None:
            return self.get_paginated_response(SandboxEnvironmentListSerializer(page, many=True).data)
        return Response(SandboxEnvironmentListSerializer(envs, many=True).data)

    @extend_schema(responses={200: SandboxEnvironmentSerializer})
    def retrieve(self, request, pk=None, **kwargs):
        env = tasks_facade.get_sandbox_environment(pk, self.team_id, request.user.id)
        if env is None:
            raise NotFound()
        return Response(SandboxEnvironmentSerializer(env).data)

    @extend_schema(request=SandboxEnvironmentWriteSerializer, responses={201: SandboxEnvironmentSerializer})
    def create(self, request, **kwargs):
        serializer = SandboxEnvironmentWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            env = tasks_facade.create_sandbox_environment(self.team_id, request.user.id, **serializer.validated_data)
        except ValueError as e:
            raise ValidationError(str(e))
        return Response(SandboxEnvironmentSerializer(env).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=SandboxEnvironmentWriteSerializer, responses={200: SandboxEnvironmentSerializer})
    def partial_update(self, request, pk=None, **kwargs):
        serializer = SandboxEnvironmentWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            env = tasks_facade.update_sandbox_environment(
                pk, self.team_id, request.user.id, **serializer.validated_data
            )
        except ValueError as e:
            raise ValidationError(str(e))
        if env is None:
            raise NotFound()
        return Response(SandboxEnvironmentSerializer(env).data)

    @extend_schema(responses={204: None})
    def destroy(self, request, pk=None, **kwargs):
        if not tasks_facade.delete_sandbox_environment(pk, self.team_id, request.user.id):
            raise NotFound()
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(tags=["sandbox-custom-images"])
class SandboxCustomImageViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """API for custom sandbox base images, built on top of the VM sandbox base via an image-builder agent.

    Custom images only run on the Modal VM runtime, so every action is gated on the
    `tasks-modal-vm-sandbox` flag (org-enabled with `user_created` in its origin_products payload).
    """

    authentication_classes = [
        SessionAuthentication,
        PersonalAPIKeyAuthentication,
        OAuthAccessTokenAuthentication,
    ]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "task"
    http_method_names = ["get", "post", "delete", "head", "options"]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if request.method == "OPTIONS":
            return
        if not tasks_facade.sandbox_custom_images_enabled(self.team_id, request.user.id):
            raise PermissionDenied("Custom sandbox images require the Modal VM runtime, which is not enabled")

    @extend_schema(responses={200: SandboxCustomImageSerializer(many=True)})
    def list(self, request, **kwargs):
        images = tasks_facade.list_sandbox_custom_images(self.team_id, request.user.id)
        page = self.paginate_queryset(images)
        if page is not None:
            return self.get_paginated_response(SandboxCustomImageSerializer(page, many=True).data)
        return Response(SandboxCustomImageSerializer(images, many=True).data)

    @extend_schema(responses={200: SandboxCustomImageSerializer})
    def retrieve(self, request, pk=None, **kwargs):
        image = tasks_facade.get_sandbox_custom_image(pk, self.team_id, request.user.id)
        if image is None:
            raise NotFound()
        return Response(SandboxCustomImageSerializer(image).data)

    @extend_schema(
        request=SandboxCustomImageWriteSerializer,
        responses={201: SandboxCustomImageSerializer},
        description="Create a draft custom image and start its interactive image-builder agent task. "
        "The returned builder_task_id points at the conversation.",
    )
    def create(self, request, **kwargs):
        serializer = SandboxCustomImageWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            image = tasks_facade.create_sandbox_custom_image(self.team_id, request.user.id, **serializer.validated_data)
        except ValueError as e:
            raise ValidationError(str(e))
        return Response(SandboxCustomImageSerializer(image).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        request=None,
        responses={200: SandboxCustomImageSerializer},
        description="Revive (or reuse) the image's builder agent session. When the previous session has "
        "ended, a fresh one is started seeded with the stored spec — use this to update an existing image.",
    )
    @action(detail=True, methods=["post"], url_path="builder_task", required_scopes=["task:write"])
    def builder_task(self, request, pk=None, **kwargs):
        try:
            image = tasks_facade.ensure_sandbox_custom_image_builder_task(pk, self.team_id, request.user.id)
        except ValueError as e:
            raise ValidationError(str(e))
        if image is None:
            raise NotFound()
        return Response(SandboxCustomImageSerializer(image).data)

    @extend_schema(
        request=SandboxCustomImageBuildSerializer,
        responses={200: SandboxCustomImageSerializer},
        description="Persist the image spec (from the request body or the builder agent's sandbox), "
        "run the security scan, and on pass build and publish the image.",
    )
    @action(detail=True, methods=["post"], required_scopes=["task:write"])
    def build(self, request, pk=None, **kwargs):
        serializer = SandboxCustomImageBuildSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            image = tasks_facade.build_sandbox_custom_image(
                pk, self.team_id, request.user.id, spec_yaml=serializer.validated_data.get("spec_yaml")
            )
        except ValueError as e:
            raise ValidationError(str(e))
        if image is None:
            raise NotFound()
        return Response(SandboxCustomImageSerializer(image).data)

    @extend_schema(responses={204: None})
    def destroy(self, request, pk=None, **kwargs):
        if not tasks_facade.delete_sandbox_custom_image(pk, self.team_id, request.user.id):
            raise NotFound()
        return Response(status=status.HTTP_204_NO_CONTENT)
