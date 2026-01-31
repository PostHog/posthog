import os
import json
import uuid
import logging
import traceback
from typing import cast

from django.http import HttpResponse
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
from posthog.renderers import SafeJSONRenderer
from posthog.storage import object_storage

from .models import Task, TaskRun
from .serializers import (
    ErrorResponseSerializer,
    FileManifestSerializer,
    TaskListQuerySerializer,
    TaskRunArtifactPresignRequestSerializer,
    TaskRunArtifactPresignResponseSerializer,
    TaskRunArtifactsUploadRequestSerializer,
    TaskRunArtifactsUploadResponseSerializer,
    TaskRunDetailSerializer,
    TaskRunUpdateSerializer,
    TaskSerializer,
)
from .temporal.client import execute_cloud_workflow, execute_task_processing_workflow, send_process_task_heartbeat

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
    renderer_classes = [SafeJSONRenderer]
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
