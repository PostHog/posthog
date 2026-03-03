import os
import json
import uuid
import logging
import traceback
from datetime import datetime
from typing import cast

from django.http import HttpResponse, JsonResponse
from django.utils import timezone

import requests as http_requests
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from posthog.api.mixins import validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import ServerTimingsGathered
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication
from posthog.permissions import APIScopePermission, PostHogFeatureFlagPermission
from posthog.storage import object_storage

from .models import Task, TaskRun
from .repository_readiness import compute_repository_readiness
from .serializers import (
    ConnectionTokenResponseSerializer,
    ErrorResponseSerializer,
    RepositoryReadinessQuerySerializer,
    RepositoryReadinessResponseSerializer,
    TaskListQuerySerializer,
    TaskRunAppendLogRequestSerializer,
    TaskRunArtifactPresignRequestSerializer,
    TaskRunArtifactPresignResponseSerializer,
    TaskRunArtifactsUploadRequestSerializer,
    TaskRunArtifactsUploadResponseSerializer,
    TaskRunCommandRequestSerializer,
    TaskRunCommandResponseSerializer,
    TaskRunCreateRequestSerializer,
    TaskRunDetailSerializer,
    TaskRunSessionLogsQuerySerializer,
    TaskRunUpdateSerializer,
    TaskSerializer,
)
from .services.connection_token import create_sandbox_connection_token
from .temporal.client import execute_task_processing_workflow

logger = logging.getLogger(__name__)


@extend_schema(tags=["tasks"])
class TaskViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """
    API for managing tasks within a project. Tasks represent units of work to be performed by an agent.
    """

    serializer_class = TaskSerializer
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission, PostHogFeatureFlagPermission]
    scope_object = "task"
    queryset = Task.objects.all()
    posthog_feature_flag = {
        "tasks": [
            "list",
            "retrieve",
            "create",
            "update",
            "partial_update",
            "destroy",
            "run",
            "repository_readiness",
        ]
    }

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

    @validated_request(
        query_serializer=RepositoryReadinessQuerySerializer,
        responses={
            200: OpenApiResponse(
                response=RepositoryReadinessResponseSerializer, description="Repository readiness status"
            ),
        },
        summary="Get repository readiness",
        description="Get autonomy readiness details for a specific repository in the current project.",
    )
    @action(detail=False, methods=["get"], url_path="repository_readiness", required_scopes=["task:read"])
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

    def safely_get_queryset(self, queryset):
        qs = queryset.filter(team=self.team, deleted=False).order_by("-created_at")

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

        # Prefetch runs to avoid N+1 queries when fetching latest_run
        qs = qs.prefetch_related("runs")

        return qs

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "team": self.team}

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
            )
            logger.info(f"Workflow trigger completed for task {task.id}, run {task_run.id}")
        except Exception as e:
            logger.exception(f"Failed to trigger task processing workflow for task {task.id}, run {task_run.id}: {e}")

            logger.exception(f"Workflow error traceback: {traceback.format_exc()}")

    def perform_update(self, serializer):
        task = cast(Task, serializer.instance)
        logger.info(f"perform_update called for task {task.id} with validated_data: {serializer.validated_data}")
        serializer.save()
        logger.info(f"Task {task.id} updated successfully")

        return Response(TaskSerializer(task).data)

    @validated_request(
        request_serializer=TaskRunCreateRequestSerializer,
        responses={
            200: OpenApiResponse(response=TaskSerializer, description="Task with updated latest run"),
            404: OpenApiResponse(description="Task not found"),
        },
        summary="Run task",
        description="Create a new task run and kick off the workflow.",
    )
    @action(detail=True, methods=["post"], url_path="run", required_scopes=["task:write"])
    def run(self, request, pk=None, **kwargs):
        task = cast(Task, self.get_object())
        mode = request.validated_data.get("mode", "background")

        logger.info(f"Creating task run for task {task.id} with mode={mode}")

        task_run = task.create_run(mode=mode)

        logger.info(f"Triggering workflow for task {task.id}, run {task_run.id}")

        self._trigger_workflow(task, task_run)

        task.refresh_from_db()

        return Response(TaskSerializer(task, context=self.get_serializer_context()).data)


@extend_schema(tags=["task-runs"])
class TaskRunViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """
    API for managing task runs. Each run represents an execution of a task.
    """

    serializer_class = TaskRunDetailSerializer
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission, PostHogFeatureFlagPermission]
    scope_object = "task"
    queryset = TaskRun.objects.select_related("task").all()
    posthog_feature_flag = {
        "tasks": [
            "list",
            "retrieve",
            "create",
            "update",
            "partial_update",
            "set_output",
            "append_log",
            "session_logs",
            "command",
        ]
    }
    http_method_names = ["get", "post", "patch", "head", "options"]
    filter_rewrite_rules = {"team_id": "team_id"}

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
        responses={
            201: OpenApiResponse(response=TaskRunDetailSerializer, description="Created task run"),
        },
        summary="Create task run",
        description="Create a new run for a specific task.",
    )
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @validated_request(
        request_serializer=TaskRunUpdateSerializer,
        responses={
            200: OpenApiResponse(response=TaskRunDetailSerializer, description="Updated task run"),
            400: OpenApiResponse(response=ErrorResponseSerializer, description="Invalid update data"),
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
            400: OpenApiResponse(response=ErrorResponseSerializer, description="Invalid update data"),
            404: OpenApiResponse(description="Task run not found"),
        },
        summary="Update task run",
        strict_request_validation=True,
    )
    def partial_update(self, request, *args, **kwargs):
        task_run = cast(TaskRun, self.get_object())
        old_status = task_run.status

        # Update fields from validated data
        for key, value in request.validated_data.items():
            setattr(task_run, key, value)

        new_status = request.validated_data.get("status")
        terminal_statuses = [TaskRun.Status.COMPLETED, TaskRun.Status.FAILED, TaskRun.Status.CANCELLED]

        # Auto-set completed_at if status is completed or failed
        if new_status in terminal_statuses:
            if not task_run.completed_at:
                task_run.completed_at = timezone.now()

            # Signal Temporal workflow if status changed to terminal state
            if old_status != new_status:
                self._signal_workflow_completion(
                    task_run,
                    new_status,
                    request.validated_data.get("error_message"),
                )

        task_run.save()

        return Response(TaskRunDetailSerializer(task_run, context=self.get_serializer_context()).data)

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

        # Verify task belongs to team
        if not Task.objects.filter(id=task_id, team=self.team).exists():
            raise NotFound("Task not found")

        return queryset.filter(team=self.team, task_id=task_id)

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "team": self.team}

    def perform_create(self, serializer):
        task_id = self.kwargs.get("parent_lookup_task_id")
        if not task_id:
            raise NotFound("Task ID is required")
        task = Task.objects.get(id=task_id, team=self.team)
        serializer.save(team=self.team, task=task)

    @validated_request(
        request_serializer=None,
        responses={
            200: OpenApiResponse(response=TaskRunDetailSerializer, description="Run with updated output"),
            404: OpenApiResponse(description="Run not found"),
        },
        summary="Set run output",
        description="Update the output field for a task run (e.g., PR URL, commit SHA, etc.)",
    )
    @action(detail=True, methods=["patch"], url_path="set_output", required_scopes=["task:write"])
    def set_output(self, request, pk=None, **kwargs):
        task_run = cast(TaskRun, self.get_object())

        output_data = request.data.get("output", {})
        if not isinstance(output_data, dict):
            return Response(
                ErrorResponseSerializer({"error": "output must be a dictionary"}).data,
                status=status.HTTP_400_BAD_REQUEST,
            )

        # TODO: Validate output data according to schema for the task type.
        task_run.output = output_data
        task_run.save(update_fields=["output", "updated_at"])

        return Response(TaskRunDetailSerializer(task_run, context=self.get_serializer_context()).data)

    @validated_request(
        request_serializer=TaskRunAppendLogRequestSerializer,
        responses={
            200: OpenApiResponse(response=TaskRunDetailSerializer, description="Run with updated log"),
            400: OpenApiResponse(response=ErrorResponseSerializer, description="Invalid log entries"),
            404: OpenApiResponse(description="Run not found"),
        },
        summary="Append log entries",
        description="Append one or more log entries to the task run log array",
        strict_request_validation=True,
    )
    @action(detail=True, methods=["post"], url_path="append_log", required_scopes=["task:write"])
    def append_log(self, request, pk=None, **kwargs):
        task_run = cast(TaskRun, self.get_object())
        timer = ServerTimingsGathered()

        entries = request.validated_data["entries"]
        with timer("s3_append"):
            task_run.append_log(entries)

        task_run.heartbeat_workflow()

        response = Response(TaskRunDetailSerializer(task_run, context=self.get_serializer_context()).data)
        response["Server-Timing"] = timer.to_header_string()
        return response

    @validated_request(
        request_serializer=TaskRunArtifactsUploadRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=TaskRunArtifactsUploadResponseSerializer,
                description="Run with updated artifact manifest",
            ),
            400: OpenApiResponse(response=ErrorResponseSerializer, description="Invalid artifact payload"),
            404: OpenApiResponse(description="Run not found"),
        },
        summary="Upload artifacts for a task run",
        description="Persist task artifacts to S3 and attach them to the run manifest.",
        strict_request_validation=True,
    )
    @action(detail=True, methods=["post"], url_path="artifacts", required_scopes=["task:write"])
    def artifacts(self, request, pk=None, **kwargs):
        task_run = cast(TaskRun, self.get_object())
        artifacts = request.validated_data["artifacts"]

        prefix = task_run.get_artifact_s3_prefix()
        manifest = list(task_run.artifacts or [])

        for artifact in artifacts:
            safe_name = os.path.basename(artifact["name"]).strip() or "artifact"
            suffix = uuid.uuid4().hex[:8]
            storage_path = f"{prefix}/{suffix}_{safe_name}"

            content_bytes = artifact["content"].encode("utf-8")
            extras: dict[str, str] = {}
            content_type = artifact.get("content_type")
            if content_type:
                extras["ContentType"] = content_type

            object_storage.write(storage_path, content_bytes, extras or None)
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

            uploaded_at = timezone.now().isoformat()

            manifest.append(
                {
                    "name": safe_name,
                    "type": artifact["type"],
                    "size": len(content_bytes),
                    "content_type": content_type or "",
                    "storage_path": storage_path,
                    "uploaded_at": uploaded_at,
                }
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

        task_run.artifacts = manifest
        task_run.save(update_fields=["artifacts", "updated_at"])

        serializer = TaskRunArtifactsUploadResponseSerializer(
            {"artifacts": manifest},
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
            400: OpenApiResponse(response=ErrorResponseSerializer, description="Invalid request"),
            404: OpenApiResponse(description="Artifact not found"),
        },
        summary="Generate presigned URL for an artifact",
        description="Returns a temporary, signed URL that can be used to download a specific artifact.",
        strict_request_validation=True,
    )
    @action(detail=True, methods=["post"], url_path="artifacts/presign", required_scopes=["task:read"])
    def artifacts_presign(self, request, pk=None, **kwargs):
        task_run = cast(TaskRun, self.get_object())
        storage_path = request.validated_data["storage_path"]
        artifacts = task_run.artifacts or []

        if not any(artifact.get("storage_path") == storage_path for artifact in artifacts):
            return Response(
                ErrorResponseSerializer({"error": "Artifact not found on this run"}).data,
                status=status.HTTP_404_NOT_FOUND,
            )

        url = object_storage.get_presigned_url(storage_path)
        if not url:
            return Response(
                ErrorResponseSerializer({"error": "Unable to generate download URL"}).data,
                status=status.HTTP_400_BAD_REQUEST,
            )

        expires_in = 3600
        serializer = TaskRunArtifactPresignResponseSerializer({"url": url, "expires_in": expires_in})
        return Response(serializer.data)

    @extend_schema(
        responses={
            200: OpenApiResponse(description="Log content in JSONL format"),
            404: OpenApiResponse(description="Task run not found"),
        },
        summary="Get task run logs",
        description="Fetch the logs for a task run. Returns JSONL formatted log entries.",
    )
    @action(detail=True, methods=["get"], url_path="logs", required_scopes=["task:read"])
    def logs(self, request, pk=None, **kwargs):
        task_run = cast(TaskRun, self.get_object())
        timer = ServerTimingsGathered()

        with timer("s3_read"):
            log_content = object_storage.read(task_run.log_url, missing_ok=True) or ""

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
    @action(detail=True, methods=["get"], url_path="connection_token", required_scopes=["task:read"])
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
            200: OpenApiResponse(response=TaskRunCommandResponseSerializer, description="Agent server response"),
            400: OpenApiResponse(response=ErrorResponseSerializer, description="Invalid command or no active sandbox"),
            404: OpenApiResponse(description="Task run not found"),
            502: OpenApiResponse(response=ErrorResponseSerializer, description="Agent server unreachable"),
        },
        summary="Send command to agent server",
        description="Forward a JSON-RPC command to the agent server running in the sandbox. "
        "Supports user_message, cancel, and close commands.",
        strict_request_validation=True,
    )
    @action(detail=True, methods=["post"], url_path="command", required_scopes=["task:write"])
    def command(self, request, pk=None, **kwargs):
        task_run = cast(TaskRun, self.get_object())
        state = task_run.state or {}

        sandbox_url = state.get("sandbox_url")
        if not sandbox_url:
            return Response(
                ErrorResponseSerializer({"error": "No active sandbox for this task run"}).data,
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not self._is_valid_sandbox_url(sandbox_url):
            logger.warning(f"Blocked request to disallowed sandbox URL for task run {task_run.id}")
            return Response(
                ErrorResponseSerializer({"error": "Invalid sandbox URL"}).data,
                status=status.HTTP_400_BAD_REQUEST,
            )

        connection_token = create_sandbox_connection_token(
            task_run=task_run,
            user_id=request.user.id,
            distinct_id=request.user.distinct_id,
        )

        sandbox_connect_token = state.get("sandbox_connect_token")

        command_payload: dict = {
            "jsonrpc": request.validated_data["jsonrpc"],
            "method": request.validated_data["method"],
        }
        if request.validated_data.get("params"):
            command_payload["params"] = request.validated_data["params"]
        if "id" in request.validated_data and request.validated_data["id"] is not None:
            command_payload["id"] = request.validated_data["id"]

        try:
            agent_response = self._proxy_command_to_agent_server(
                sandbox_url=sandbox_url,
                connection_token=connection_token,
                sandbox_connect_token=sandbox_connect_token,
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
                ErrorResponseSerializer({"error": error_msg}).data,
                status=status.HTTP_502_BAD_GATEWAY,
            )

        except http_requests.ConnectionError:
            logger.warning(f"Agent server unreachable for task run {task_run.id}")
            return Response(
                ErrorResponseSerializer({"error": "Agent server is not reachable"}).data,
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except http_requests.Timeout:
            logger.warning(f"Agent server request timed out for task run {task_run.id}")
            return Response(
                ErrorResponseSerializer({"error": "Agent server request timed out"}).data,
                status=status.HTTP_504_GATEWAY_TIMEOUT,
            )
        except Exception:
            logger.exception(f"Failed to proxy command to agent server for task run {task_run.id}")
            return Response(
                ErrorResponseSerializer({"error": "Failed to send command to agent server"}).data,
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
    @action(detail=True, methods=["get"], url_path="session_logs", required_scopes=["task:read"])
    def session_logs(self, request, pk=None, **kwargs):
        task_run = cast(TaskRun, self.get_object())
        timer = ServerTimingsGathered()

        with timer("s3_read"):
            log_content = object_storage.read(task_run.log_url, missing_ok=True) or ""

        if not log_content.strip():
            response = JsonResponse([], safe=False)
            response["X-Total-Count"] = "0"
            response["X-Filtered-Count"] = "0"
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

                if len(filtered) >= limit:
                    break

        response = JsonResponse(filtered, safe=False)
        response["X-Total-Count"] = str(total_count)
        response["X-Filtered-Count"] = str(len(filtered))
        response["Cache-Control"] = "no-cache"
        response["Server-Timing"] = timer.to_header_string()
        return response

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
