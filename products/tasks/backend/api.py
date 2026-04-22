import os
import json
import uuid
import logging
import builtins
import traceback
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any, cast

from django.conf import settings
from django.core.cache import cache
from django.db import models, transaction
from django.db.models import F
from django.http import HttpResponse, JsonResponse, StreamingHttpResponse
from django.utils import timezone

import requests as http_requests
import jsonschema
import posthoganalytics
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response

from posthog.api.mixins import validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import ServerTimingsGathered
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication
from posthog.event_usage import groups
from posthog.permissions import APIScopePermission
from posthog.rate_limit import CodeInviteThrottle
from posthog.renderers import ServerSentEventRenderer
from posthog.storage import object_storage

from ee.hogai.utils.aio import async_to_sync

from .automation_service import (
    delete_automation_schedule,
    run_task_automation,
    sync_automation_schedule,
    update_automation_run_result,
)
from .models import CodeInvite, CodeInviteRedemption, SandboxEnvironment, Task, TaskAutomation, TaskRun
from .repository_readiness import compute_repository_readiness
from .serializers import (
    CodeInviteRedeemRequestSerializer,
    ConnectionTokenResponseSerializer,
    ErrorResponseSerializer,
    RepositoryReadinessQuerySerializer,
    RepositoryReadinessResponseSerializer,
    SandboxEnvironmentListSerializer,
    SandboxEnvironmentSerializer,
    TaskAutomationSerializer,
    TaskListQuerySerializer,
    TaskRunAppendLogRequestSerializer,
    TaskRunArtifactPresignRequestSerializer,
    TaskRunArtifactPresignResponseSerializer,
    TaskRunArtifactsFinalizeUploadRequestSerializer,
    TaskRunArtifactsFinalizeUploadResponseSerializer,
    TaskRunArtifactsPrepareUploadRequestSerializer,
    TaskRunArtifactsPrepareUploadResponseSerializer,
    TaskRunArtifactsUploadRequestSerializer,
    TaskRunArtifactsUploadResponseSerializer,
    TaskRunCommandRequestSerializer,
    TaskRunCommandResponseSerializer,
    TaskRunCreateRequestSchemaSerializer,
    TaskRunCreateRequestSerializer,
    TaskRunDetailSerializer,
    TaskRunRelayMessageRequestSerializer,
    TaskRunRelayMessageResponseSerializer,
    TaskRunSessionLogsQuerySerializer,
    TaskRunSetOutputRequestSerializer,
    TaskRunUpdateSerializer,
    TaskSerializer,
    TaskStagedArtifactsFinalizeUploadRequestSerializer,
    TaskStagedArtifactsFinalizeUploadResponseSerializer,
    TaskStagedArtifactsPrepareUploadRequestSerializer,
    TaskStagedArtifactsPrepareUploadResponseSerializer,
    build_task_run_artifact_size_error,
    get_task_run_artifact_max_size_bytes,
)
from .services.connection_token import create_sandbox_connection_token
from .services.staged_artifacts import (
    RUN_ARTIFACT_TTL_DAYS,
    STAGED_ARTIFACT_TTL_DAYS,
    build_task_artifact_entry,
    build_task_run_artifact_storage_path,
    build_task_staged_artifact_cache_key,
    build_task_staged_artifact_storage_path,
    cache_task_staged_artifact,
    get_safe_artifact_name,
    get_task_run_artifacts_by_id,
    get_task_staged_artifacts,
    tag_task_artifact,
)
from .stream.redis_stream import TaskRunRedisStream, TaskRunStreamError, get_task_run_stream_key
from .temporal.client import execute_posthog_code_agent_relay_workflow, execute_task_processing_workflow
from .temporal.process_task.utils import (
    PrAuthorshipMode,
    cache_github_user_token,
    get_provider_for_runtime_adapter,
    get_reasoning_effort_error,
    parse_run_state,
)

logger = logging.getLogger(__name__)
TASK_RUN_STREAM_KEEPALIVE_INTERVAL_SECONDS = 20.0
TASK_RUN_STREAM_KEEPALIVE_EVENT_NAME = "keepalive"
TASK_RUN_STREAM_KEEPALIVE_PAYLOAD = {"type": "keepalive"}
TASK_RUN_ARTIFACT_UPLOAD_EXPIRATION_SECONDS = 60 * 60
TASK_RUN_ARTIFACT_UPLOAD_FORM_OVERHEAD_BYTES = 64 * 1024


class TasksAccessPermission(BasePermission):
    message = "You need a valid invite code to access this feature."

    def has_permission(self, request, view) -> bool:
        user = request.user
        if not user or not user.is_authenticated:
            return False

        # Check 1: feature flag (covers existing enrolled users, staff overrides)
        org_id = str(view.organization.id)
        flag_enabled = posthoganalytics.feature_enabled(
            "tasks",
            user.distinct_id,
            groups={"organization": org_id},
            group_properties={"organization": {"id": org_id}},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
        if flag_enabled:
            return True

        # Check 2: invite code redemption (covers new invited users)
        return CodeInviteRedemption.objects.filter(user=user).exists()


@extend_schema(tags=["tasks"])
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
    permission_classes = [IsAuthenticated, APIScopePermission, TasksAccessPermission]
    scope_object = "task"
    queryset = Task.objects.all()

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

        # Only filter by internal on list — retrieve should always work if you have the ID
        if self.action == "list":
            internal_param = getattr(self.request, "validated_query_data", {}).get("internal")
            if internal_param is True:
                qs = qs.filter(internal=True)
            else:
                qs = qs.filter(internal=False)

        # select_related to avoid N+1 on created_by (UserBasicSerializer) and team (slug property)
        qs = qs.select_related("created_by", "team").prefetch_related("runs")

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
            )
            logger.info(f"Workflow trigger completed for task {task.id}, run {task_run.id}")
        except Exception as e:
            logger.exception(f"Failed to trigger task processing workflow for task {task.id}, run {task_run.id}: {e}")

            logger.exception(f"Workflow error traceback: {traceback.format_exc()}")

    @validated_request(
        request_serializer=TaskStagedArtifactsPrepareUploadRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=TaskStagedArtifactsPrepareUploadResponseSerializer,
                description="Prepared staged uploads for the requested artifacts",
            ),
            400: OpenApiResponse(response=ErrorResponseSerializer, description="Invalid artifact payload"),
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
                    ErrorResponseSerializer({"error": "Unable to generate upload URL"}).data,
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
            400: OpenApiResponse(response=ErrorResponseSerializer, description="Invalid artifact payload"),
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
                    ErrorResponseSerializer({"error": "Artifact storage path is invalid for this task"}).data,
                    status=status.HTTP_400_BAD_REQUEST,
                )

            s3_object = object_storage.head_object(storage_path)
            if not s3_object:
                return Response(
                    ErrorResponseSerializer({"error": "Artifact upload not found in object storage"}).data,
                    status=status.HTTP_400_BAD_REQUEST,
                )

            content_length = s3_object.get("ContentLength")
            if not isinstance(content_length, int):
                return Response(
                    ErrorResponseSerializer({"error": "Artifact upload metadata is unavailable"}).data,
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
                    ErrorResponseSerializer(
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
            404: OpenApiResponse(description="Task not found"),
        },
        summary="Run task",
        description="Create a new task run and kick off the workflow.",
    )
    @action(detail=True, methods=["post"], url_path="run", required_scopes=["task:write"])
    def run(self, request, pk=None, **kwargs):
        task = cast(Task, self.get_object())
        mode = request.validated_data.get("mode", "background")
        branch = request.validated_data.get("branch")
        resume_from_run_id = request.validated_data.get("resume_from_run_id")
        pending_user_message = request.validated_data.get("pending_user_message")
        pending_user_artifact_ids = request.validated_data.get("pending_user_artifact_ids") or []
        sandbox_environment_id = request.validated_data.get("sandbox_environment_id")
        pr_authorship_mode = request.validated_data.get("pr_authorship_mode")
        run_source = request.validated_data.get("run_source")
        signal_report_id = request.validated_data.get("signal_report_id")
        runtime_adapter = request.validated_data.get("runtime_adapter")
        model = request.validated_data.get("model")
        reasoning_effort = request.validated_data.get("reasoning_effort")
        github_user_token = request.validated_data.get("github_user_token")
        initial_permission_mode = request.validated_data.get("initial_permission_mode")

        runtime_state_fields = {
            "pr_authorship_mode": pr_authorship_mode,
            "run_source": run_source,
            "signal_report_id": signal_report_id,
            "runtime_adapter": runtime_adapter,
            "model": model,
            "reasoning_effort": reasoning_effort,
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

        # Only require a user token when the task has a repo (no-repo cloud runs skip GitHub operations)
        if pr_authorship_mode == PrAuthorshipMode.USER and task.repository and not github_user_token:
            return Response({"detail": "github_user_token is required for user-authored cloud runs"}, status=400)

        if sandbox_environment_id is not None:
            sandbox_environment = SandboxEnvironment.objects.filter(id=sandbox_environment_id, team=task.team).first()
            if not sandbox_environment:
                return Response({"detail": "Invalid sandbox_environment_id"}, status=400)

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
                run_storage_path = build_task_run_artifact_storage_path(
                    task_run,
                    str(staged_artifact["id"]),
                    str(staged_artifact["name"]),
                )
                source_storage_path = str(staged_artifact["storage_path"])
                if source_storage_path != run_storage_path:
                    object_storage.copy(source_storage_path, run_storage_path)
                tag_task_artifact(run_storage_path, ttl_days=RUN_ARTIFACT_TTL_DAYS, team_id=task.team_id)
                run_artifacts.append(
                    {
                        **staged_artifact,
                        "storage_path": run_storage_path,
                    }
                )

            task_run.artifacts = run_artifacts
            task_run.save(update_fields=["artifacts", "updated_at"])

            for artifact_id in pending_user_artifact_ids:
                cache.delete(build_task_staged_artifact_cache_key(str(task.id), artifact_id))

        if github_user_token and pr_authorship_mode == PrAuthorshipMode.USER:
            cache_github_user_token(str(task_run.id), github_user_token)

        logger.info(f"Triggering workflow for task {task.id}, run {task_run.id}")

        self._trigger_workflow(task, task_run)

        task.refresh_from_db()

        return Response(TaskSerializer(task, context=self.get_serializer_context()).data)


@extend_schema(tags=["task-automations"])
class TaskAutomationViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    serializer_class = TaskAutomationSerializer
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission, TasksAccessPermission]
    scope_object = "task"
    queryset = TaskAutomation.objects.all()
    filter_rewrite_rules = {"team_id": "task__team_id"}

    def safely_get_queryset(self, queryset):
        return queryset.filter(task__team=self.team).order_by("task__title", "-created_at")

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


@extend_schema(tags=["task-runs"])
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
    permission_classes = [IsAuthenticated, APIScopePermission, TasksAccessPermission]
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
            "relay_message",
            "session_logs",
            "command",
            "stream",
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
        has_output_merge = "output" in request.validated_data and isinstance(request.validated_data["output"], dict)
        has_state_merge = "state" in request.validated_data and isinstance(request.validated_data["state"], dict)
        state_remove_keys = request.validated_data.get("state_remove_keys") or []
        has_state_mutation = has_state_merge or bool(state_remove_keys)
        update_fields: set[str] = set()

        with transaction.atomic():
            # Re-fetch with row lock when merging output to prevent concurrent
            # PATCHes (e.g. branch sync + PR URL) from clobbering each other.
            if has_output_merge or has_state_mutation:
                task_run = TaskRun.objects.select_for_update().get(pk=task_run.pk)

            old_status = task_run.status
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

        # Verify task belongs to team
        if not Task.objects.filter(id=task_id, team=self.team).exists():
            raise NotFound("Task not found")

        return queryset.filter(team=self.team, task_id=task_id)

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "team": self.team, "team_id": self.team.id}

    def perform_create(self, serializer):
        task_id = self.kwargs.get("parent_lookup_task_id")
        if not task_id:
            raise NotFound("Task ID is required")
        task = Task.objects.get(id=task_id, team=self.team)
        serializer.save(team=self.team, task=task)

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
                    ErrorResponseSerializer({"error": f"Output validation error: {e.message}"}).data,
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
            400: OpenApiResponse(response=ErrorResponseSerializer, description="Invalid log entries"),
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

        task_run.heartbeat_workflow()

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
                ErrorResponseSerializer({"error": "Failed to queue Slack relay"}).data,
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
            400: OpenApiResponse(response=ErrorResponseSerializer, description="Invalid artifact payload"),
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
        manifest = list(task_run.artifacts or [])

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
            manifest.append(
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
            400: OpenApiResponse(response=ErrorResponseSerializer, description="Invalid artifact payload"),
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
                    ErrorResponseSerializer({"error": "Unable to generate upload URL"}).data,
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
            400: OpenApiResponse(response=ErrorResponseSerializer, description="Invalid artifact payload"),
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
                    ErrorResponseSerializer({"error": "Artifact storage path is invalid for this run"}).data,
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
                    ErrorResponseSerializer({"error": "Artifact upload not found in object storage"}).data,
                    status=status.HTTP_400_BAD_REQUEST,
                )

            safe_name = get_safe_artifact_name(artifact["name"])
            content_type = artifact.get("content_type") or s3_object.get("ContentType") or ""
            content_length = s3_object.get("ContentLength")
            if not isinstance(content_length, int):
                return Response(
                    ErrorResponseSerializer({"error": "Artifact upload metadata is unavailable"}).data,
                    status=status.HTTP_400_BAD_REQUEST,
                )

            max_size_bytes = get_task_run_artifact_max_size_bytes(
                safe_name,
                content_type,
                artifact.get("type"),
            )
            if content_length > max_size_bytes:
                return Response(
                    ErrorResponseSerializer(
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
            400: OpenApiResponse(response=ErrorResponseSerializer, description="Invalid request"),
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
        request_serializer=TaskRunArtifactPresignRequestSerializer,
        responses={
            200: OpenApiResponse(
                description="Artifact content",
            ),
            400: OpenApiResponse(response=ErrorResponseSerializer, description="Invalid request"),
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
        artifact = next(
            (entry for entry in task_run.artifacts or [] if entry.get("storage_path") == storage_path),
            None,
        )

        if artifact is None:
            return Response(
                ErrorResponseSerializer({"error": "Artifact not found on this run"}).data,
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
                ErrorResponseSerializer({"error": "Unable to read artifact"}).data,
                status=status.HTTP_400_BAD_REQUEST,
            )

        if content is None:
            return Response(
                ErrorResponseSerializer({"error": "Artifact content not found"}).data,
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
    @action(
        detail=True,
        methods=["get"],
        url_path="connection_token",
        required_scopes=["task:read"],
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
                response=ErrorResponseSerializer,
                description="Invalid command or no active sandbox",
            ),
            404: OpenApiResponse(description="Task run not found"),
            502: OpenApiResponse(response=ErrorResponseSerializer, description="Agent server unreachable"),
        },
        summary="Send command to agent server",
        description="Forward a JSON-RPC command to the agent server running in the sandbox. "
        "Supports user_message, cancel, close, permission_response, and set_config_option commands.",
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
        run_state = parse_run_state(task_run.state)

        if not run_state.sandbox_url:
            return Response(
                ErrorResponseSerializer({"error": "No active sandbox for this task run"}).data,
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not self._is_valid_sandbox_url(run_state.sandbox_url):
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

        command_payload: dict = {
            "jsonrpc": request.validated_data["jsonrpc"],
            "method": request.validated_data["method"],
        }
        params = request.validated_data.get("params")
        if params:
            command_params = dict(params)
            if request.validated_data["method"] == "user_message":
                artifact_ids = command_params.pop("artifact_ids", [])
                if artifact_ids:
                    resolved_artifacts, missing_artifact_ids = get_task_run_artifacts_by_id(task_run, artifact_ids)
                    if missing_artifact_ids:
                        return Response(
                            {
                                "error": "Some artifact_ids are invalid for this run",
                                "missing_artifact_ids": missing_artifact_ids,
                            },
                            status=status.HTTP_400_BAD_REQUEST,
                        )
                    command_params["artifacts"] = resolved_artifacts
            if command_params:
                command_payload["params"] = command_params
        if "id" in request.validated_data and request.validated_data["id"] is not None:
            command_payload["id"] = request.validated_data["id"]

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
        last_event_id = request.headers.get("Last-Event-ID")
        start_latest = request.GET.get("start") == "latest"
        format_sse_event = self._format_sse_event

        async def async_stream() -> AsyncGenerator[bytes, None]:
            redis_stream = TaskRunRedisStream(stream_key)
            if not await redis_stream.wait_for_stream():
                yield format_sse_event({"error": "Stream not available"}, event_name="error")
                return

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
            except TaskRunStreamError as e:
                logger.error("TaskRunRedisStream error for stream %s: %s", stream_key, e, exc_info=True)
                yield format_sse_event({"error": str(e)}, event_name="error")

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
                response=ErrorResponseSerializer,
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
                ErrorResponseSerializer({"error": "Invalid invite code"}).data,
                status=status.HTTP_400_BAD_REQUEST,
            )

        if CodeInviteRedemption.objects.filter(invite_code=invite_code, user=request.user).exists():
            return Response({"success": True})

        with transaction.atomic():
            invite_code = CodeInvite.objects.select_for_update().get(id=invite_code.id)

            if not invite_code.is_redeemable:
                return Response(
                    ErrorResponseSerializer({"error": "This invite code is no longer valid"}).data,
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
        user = request.user

        # Check feature flag if we can resolve an org
        org = getattr(user, "organization", None)
        if org is not None:
            org_id = str(org.id)
            flag_enabled = posthoganalytics.feature_enabled(
                "tasks",
                user.distinct_id,
                groups={"organization": org_id},
                group_properties={"organization": {"id": org_id}},
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
            if flag_enabled:
                return Response({"has_access": True})

        # Fallback: check invite code redemption
        has_redeemed = CodeInviteRedemption.objects.filter(user=user).exists()
        return Response({"has_access": has_redeemed})


@extend_schema(tags=["sandbox-environments"])
class SandboxEnvironmentViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """API for managing sandbox environments that control network access for task runs."""

    serializer_class = SandboxEnvironmentSerializer
    authentication_classes = [
        SessionAuthentication,
        PersonalAPIKeyAuthentication,
        OAuthAccessTokenAuthentication,
    ]
    permission_classes = [IsAuthenticated, APIScopePermission, TasksAccessPermission]
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
