import os
import json
import uuid
import asyncio
import logging
import traceback
from collections.abc import AsyncGenerator
from typing import Any, cast

from django.http import HttpResponse, StreamingHttpResponse
from django.utils import timezone

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from posthog.api.mixins import validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication
from posthog.permissions import APIScopePermission, PostHogFeatureFlagPermission
from posthog.renderers import SafeJSONRenderer, ServerSentEventRenderer
from posthog.settings import SERVER_GATEWAY_INTERFACE
from posthog.storage import object_storage

from ee.hogai.utils.asgi import SyncIterableToAsync

from .kafka_consumer import consume_agent_events
from .kafka_producer import AgentLogEntry, create_agent_log_entry, produce_agent_log_entries
from .models import Task, TaskRun
from .queries import get_agent_logs, get_agent_logs_as_jsonl, get_max_sequence
from .serializers import (
    ErrorResponseSerializer,
    FileManifestSerializer,
    TaskListQuerySerializer,
    TaskRunAppendLogRequestSerializer,
    TaskRunArtifactPresignRequestSerializer,
    TaskRunArtifactPresignResponseSerializer,
    TaskRunArtifactsUploadRequestSerializer,
    TaskRunArtifactsUploadResponseSerializer,
    TaskRunDetailSerializer,
    TaskRunUpdateSerializer,
    TaskSerializer,
)
from .temporal.client import (
    execute_cloud_workflow,
    execute_task_processing_workflow,
    is_workflow_running,
    send_process_task_heartbeat,
)

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
        request_serializer=None,
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

        logger.info(f"Creating task run for task {task.id}")

        task_run = task.create_run()

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
    renderer_classes = [SafeJSONRenderer, ServerSentEventRenderer]
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
            "sync",
            "heartbeat",
            "file_manifest",
        ]
    }
    http_method_names = ["get", "post", "put", "patch", "head", "options"]
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
        old_environment = task_run.environment

        # Update fields from validated data
        for key, value in request.validated_data.items():
            setattr(task_run, key, value)

        # Auto-set completed_at if status is completed or failed
        if "status" in request.validated_data and request.validated_data["status"] in [
            TaskRun.Status.COMPLETED,
            TaskRun.Status.FAILED,
        ]:
            if not task_run.completed_at:
                task_run.completed_at = timezone.now()

        task_run.save()

        # Trigger cloud workflow when switching from local to cloud
        new_environment = request.validated_data.get("environment")
        if new_environment == "cloud" and old_environment != "cloud":
            task = task_run.task
            if task.repository:
                logger.info(f"Environment switched to cloud for run {task_run.id}, starting cloud workflow")
                workflow_id = execute_cloud_workflow(
                    task_id=str(task.id),
                    run_id=str(task_run.id),
                    team_id=task.team_id,
                )
                if workflow_id:
                    state = task_run.state or {}
                    task_run.state = {**state, "workflow_id": workflow_id}
                    task_run.save(update_fields=["state", "updated_at"])

        return Response(TaskRunDetailSerializer(task_run, context=self.get_serializer_context()).data)

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
        task_run = serializer.save(team=self.team, task=task)

        if task_run.environment == TaskRun.Environment.CLOUD:
            workflow_id = execute_cloud_workflow(
                task_id=str(task.id),
                run_id=str(task_run.id),
                team_id=task.team.id,
            )
            if workflow_id:
                task_run.state = {"workflow_id": workflow_id}
                task_run.save(update_fields=["state", "updated_at"])

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

        entries = request.validated_data["entries"]
        current_sequence = get_max_sequence(
            team_id=task_run.team_id,
            task_id=str(task_run.task_id),
            run_id=str(task_run.id),
        )

        kafka_entries: list[AgentLogEntry] = []
        for i, entry in enumerate(entries):
            entry_type = entry.get("type", "unknown")
            kafka_entries.append(
                create_agent_log_entry(
                    team_id=task_run.team_id,
                    task_id=str(task_run.task_id),
                    run_id=str(task_run.id),
                    sequence=current_sequence + i + 1,
                    entry_type=entry_type,
                    entry=entry,
                )
            )

        produce_agent_log_entries(kafka_entries)

        return Response(TaskRunDetailSerializer(task_run, context=self.get_serializer_context()).data)

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

    @validated_request(
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
        log_content = get_agent_logs_as_jsonl(
            team_id=task_run.team_id,
            task_id=str(task_run.task_id),
            run_id=str(task_run.id),
        )
        response = HttpResponse(log_content, content_type="application/jsonl")
        response["Cache-Control"] = "no-cache"
        return response

    @validated_request(
        TaskRunArtifactPresignRequestSerializer,
        responses={
            200: OpenApiResponse(description="Artifact content"),
            404: OpenApiResponse(description="Artifact not found"),
        },
        summary="Download artifact content",
        description="Download artifact content directly (proxied through API). Useful for Docker containers that can't access S3 directly.",
    )
    @action(detail=True, methods=["post"], url_path="artifacts/download", required_scopes=["task:read"])
    def artifacts_download(self, request, pk=None, **kwargs):
        task_run = cast(TaskRun, self.get_object())
        storage_path = request.validated_data["storage_path"]
        artifacts = task_run.artifacts or []

        if not any(artifact.get("storage_path") == storage_path for artifact in artifacts):
            return Response(
                ErrorResponseSerializer({"error": "Artifact not found on this run"}).data,
                status=status.HTTP_404_NOT_FOUND,
            )

        # Use read_bytes for binary files to avoid UTF-8 decoding corruption
        content = object_storage.read_bytes(storage_path, missing_ok=True)
        if content is None:
            return Response(
                ErrorResponseSerializer({"error": "Artifact content not found"}).data,
                status=status.HTTP_404_NOT_FOUND,
            )

        content_type = "application/octet-stream"
        if storage_path.endswith(".tar.gz"):
            content_type = "application/gzip"
        elif storage_path.endswith(".json"):
            content_type = "application/json"

        response = HttpResponse(content, content_type=content_type)
        response["Cache-Control"] = "no-cache"
        return response

    @extend_schema(
        tags=["task-runs"],
        responses={
            200: OpenApiResponse(description="SSE event stream from agent"),
            202: OpenApiResponse(description="Message accepted"),
            404: OpenApiResponse(description="Task run not found"),
        },
        summary="Sync with cloud agent",
        description="GET opens SSE stream to receive events. POST sends messages to agent.",
    )
    @action(detail=True, methods=["get", "post"], url_path="sync", required_scopes=["task:write"])
    def sync(self, request, pk=None, **kwargs):
        task_run = cast(TaskRun, self.get_object())

        if request.method == "GET":
            return self._sync_get(request, task_run)
        else:
            return self._sync_post(request, task_run)

    def _sync_get(self, request, task_run: TaskRun) -> StreamingHttpResponse:
        """Open SSE stream to receive events from the agent via Kafka."""
        run_id = str(task_run.id)
        task_id = str(task_run.task_id)
        last_event_id = request.headers.get("Last-Event-ID")

        logger.info(f"[SYNC_GET] Opening SSE stream for run {run_id}, Last-Event-ID: {last_event_id}")

        from_sequence = int(last_event_id) if last_event_id and last_event_id.isdigit() else None

        async def event_stream() -> AsyncGenerator[bytes, None]:
            event_id = 0

            if from_sequence is not None:
                logger.info(f"[SYNC_GET] Replaying from ClickHouse, sequence > {from_sequence}")
                async for event in self._replay_from_log(task_run, last_event_id):
                    event_id += 1
                    logger.debug(f"[SYNC_GET] Replayed event {event_id}: {event.get('method', 'unknown')}")
                    yield self._format_sse_event(event, event_id)

            logger.info(f"[SYNC_GET] Starting live Kafka subscription for run {run_id}")
            try:
                async for entry in consume_agent_events(
                    task_id=task_id,
                    run_id=run_id,
                    from_sequence=from_sequence,
                ):
                    # Handle keepalive (SSE comment to keep connection alive)
                    if entry.get("_keepalive"):
                        yield b": keepalive\n\n"
                        continue

                    event_id += 1
                    if entry.get("type") == "notification" and entry.get("notification"):
                        event = entry["notification"]
                    elif entry.get("type") == "agent_event":
                        event = entry.get("event", {})
                    else:
                        event = entry

                    logger.info(
                        f"[SYNC_GET] Received event {event_id} from Kafka: method={event.get('method', 'unknown')}"
                    )
                    yield self._format_sse_event(event, event_id)
            except asyncio.CancelledError:
                logger.info(f"[SYNC_GET] SSE stream cancelled for run {run_id}")
            except Exception as e:
                logger.exception(f"[SYNC_GET] SSE stream error for run {run_id}: {e}")
                yield self._format_sse_event({"error": str(e)}, event_id + 1)

        if SERVER_GATEWAY_INTERFACE == "ASGI":
            stream = event_stream()
        else:
            stream = SyncIterableToAsync(event_stream())

        response = StreamingHttpResponse(
            streaming_content=stream,
            content_type=ServerSentEventRenderer.media_type,
        )
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response

    def _sync_post(self, request, task_run: TaskRun) -> Response:
        """Receive messages from client and forward to agent via Kafka."""
        run_id = str(task_run.id)
        message = request.data

        logger.info(f"[SYNC_POST] Received message for run {run_id}: method={message.get('method', 'unknown')}")
        logger.debug(f"[SYNC_POST] Full message: {message}")

        if not isinstance(message, dict):
            logger.error(f"[SYNC_POST] Invalid message type: {type(message)}")
            return Response(
                {"error": "Message must be a JSON object"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        current_sequence = get_max_sequence(
            team_id=task_run.team_id,
            task_id=str(task_run.task_id),
            run_id=str(task_run.id),
        )
        entry = create_agent_log_entry(
            team_id=task_run.team_id,
            task_id=str(task_run.task_id),
            run_id=str(task_run.id),
            sequence=current_sequence + 1,
            entry_type="client_message",
            entry={"type": "client_message", "message": message},
        )
        produce_agent_log_entries([entry])
        logger.info(f"[SYNC_POST] Message sent to Kafka for run {run_id}")

        if task_run.environment == TaskRun.Environment.CLOUD:
            self._ensure_cloud_workflow_running(task_run)

        logger.info(f"[SYNC_POST] Returning 202 Accepted for run {run_id}")
        return Response(status=status.HTTP_202_ACCEPTED)

    def _ensure_cloud_workflow_running(self, task_run: TaskRun) -> bool:
        """Ensure a cloud workflow is running for this run, starting one if needed."""
        run_id = str(task_run.id)
        task_id = str(task_run.task_id)
        state = task_run.state or {}

        workflow_id = state.get("workflow_id")
        if workflow_id and is_workflow_running(workflow_id):
            if send_process_task_heartbeat(run_id, workflow_id):
                logger.debug(f"[ENSURE_WORKFLOW] Heartbeat sent to existing workflow {workflow_id}")
                return True

        logger.info(f"[ENSURE_WORKFLOW] No active workflow for run {run_id}, starting new cloud workflow")
        new_workflow_id = execute_cloud_workflow(
            task_id=task_id,
            run_id=run_id,
            team_id=task_run.team_id,
        )

        if new_workflow_id:
            task_run.state = {**state, "workflow_id": new_workflow_id}
            task_run.save(update_fields=["state", "updated_at"])
            logger.info(f"[ENSURE_WORKFLOW] Started new cloud workflow {new_workflow_id} for run {run_id}")
            return True

        logger.warning(f"[ENSURE_WORKFLOW] Failed to start cloud workflow for run {run_id}")
        return False

    @extend_schema(
        tags=["task-runs"],
        responses={
            200: OpenApiResponse(description="Heartbeat sent successfully"),
            404: OpenApiResponse(description="Task run not found"),
        },
        summary="Send heartbeat to keep cloud session alive",
    )
    @action(detail=True, methods=["post"], url_path="heartbeat", required_scopes=["task:write"])
    def heartbeat(self, request, pk=None, **kwargs):
        task_run = cast(TaskRun, self.get_object())
        run_id = str(task_run.id)
        state = task_run.state or {}

        workflow_id = state.get("workflow_id")
        if workflow_id:
            success = send_process_task_heartbeat(run_id, workflow_id)
            if success:
                return Response({"status": "ok"})

        return Response({"status": "no_session"})

    @extend_schema(
        tags=["task-runs"],
        responses={
            200: OpenApiResponse(response=FileManifestSerializer, description="File manifest for cloud/local sync"),
            204: OpenApiResponse(description="No manifest exists"),
            404: OpenApiResponse(description="Task run not found"),
        },
        summary="Get or update file manifest for cloud/local sync",
        description="GET retrieves the current file manifest. PUT stores a new manifest. Used for syncing file state between local and cloud environments.",
    )
    @action(detail=True, methods=["get", "put"], url_path="file_manifest", required_scopes=["task:write"])
    def file_manifest(self, request, pk=None, **kwargs):
        task_run = cast(TaskRun, self.get_object())

        if request.method == "GET":
            return self._file_manifest_get(task_run)
        else:
            return self._file_manifest_put(request, task_run)

    def _file_manifest_get(self, task_run: TaskRun) -> Response:
        """Retrieve file manifest from S3."""
        manifest_path = task_run.get_file_manifest_path()
        content = object_storage.read(manifest_path, missing_ok=True)

        if not content:
            return Response(status=status.HTTP_204_NO_CONTENT)

        try:
            manifest_data = json.loads(content)
            return Response(manifest_data)
        except json.JSONDecodeError:
            logger.exception(f"Invalid JSON in file manifest for run {task_run.id}")
            return Response(
                ErrorResponseSerializer({"error": "Invalid manifest data"}).data,
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def _file_manifest_put(self, request, task_run: TaskRun) -> Response:
        """Store file manifest to S3."""
        serializer = FileManifestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                ErrorResponseSerializer({"error": str(serializer.errors)}).data,
                status=status.HTTP_400_BAD_REQUEST,
            )

        manifest_path = task_run.get_file_manifest_path()
        content = json.dumps(serializer.validated_data, default=str)

        object_storage.write(manifest_path, content)

        try:
            object_storage.tag(
                manifest_path,
                {
                    "ttl_days": "30",
                    "team_id": str(task_run.team_id),
                },
            )
        except Exception as exc:
            logger.warning(
                "task_run.file_manifest_tag_failed",
                extra={
                    "task_run_id": str(task_run.id),
                    "manifest_path": manifest_path,
                    "error": str(exc),
                },
            )

        logger.info(
            "task_run.file_manifest_uploaded",
            extra={
                "task_run_id": str(task_run.id),
                "manifest_path": manifest_path,
                "file_count": len(serializer.validated_data.get("files", {})),
            },
        )

        return Response(serializer.validated_data)

    async def _replay_from_log(self, task_run: TaskRun, from_event_id: str) -> AsyncGenerator[dict[str, Any], None]:
        """Replay events from ClickHouse log starting after the given event ID."""
        from_sequence = int(from_event_id) if from_event_id.isdigit() else 0

        logs = get_agent_logs(
            team_id=task_run.team_id,
            task_id=str(task_run.task_id),
            run_id=str(task_run.id),
            after_sequence=from_sequence,
        )

        for log in logs:
            entry = log.get("entry")
            if not entry:
                continue
            # Handle ACP notification format (from @posthog/agent-server)
            if entry.get("type") == "notification" and entry.get("notification"):
                yield entry["notification"]
            # Handle legacy agent_event format
            elif entry.get("type") == "agent_event":
                yield entry.get("event", {})
            # Handle client messages (for agent reconnection replay)
            elif entry.get("type") == "client_message":
                yield entry

    def _format_sse_event(self, data: dict[str, Any], event_id: int) -> bytes:
        """Format data as an SSE event."""
        output = f"id: {event_id}\n"
        output += f"data: {json.dumps(data)}\n\n"
        return output.encode()
