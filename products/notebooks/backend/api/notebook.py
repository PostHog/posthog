import math
import hashlib
from datetime import timedelta
from typing import Any, Optional

from django.db import transaction
from django.db.models import Q, QuerySet
from django.http import JsonResponse
from django.utils.timezone import now

import structlog
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, extend_schema, extend_schema_view
from loginas.utils import is_impersonated_session
from rest_framework import serializers, viewsets
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import action
from posthog.exceptions import Conflict
from posthog.models import User
from posthog.models.activity_logging.activity_log import Change, Detail, changes_between, load_activity, log_activity
from posthog.models.activity_logging.activity_page import activity_page_response
from posthog.models.utils import UUIDT
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin
from posthog.rbac.user_access_control import UserAccessControlSerializerMixin
from posthog.utils import relative_date_parse

from products.notebooks.backend.kernel_runtime import build_notebook_sandbox_config, get_kernel_runtime
from products.notebooks.backend.models import KernelRuntime, Notebook
from products.notebooks.backend.python_analysis import analyze_python_globals, annotate_python_nodes
from products.tasks.backend.services.sandbox import SandboxStatus
from products.tasks.backend.temporal.exceptions import SandboxProvisionError

logger = structlog.get_logger(__name__)


def depluralize(string: str | None) -> str | None:
    if not string:
        return None

    if string.endswith("ies"):
        return string[:-3] + "y"
    elif string.endswith("s"):
        return string[:-1]
    else:
        return string


def log_notebook_activity(
    activity: str,
    notebook: Notebook,
    organization_id: UUIDT,
    team_id: int,
    user: User,
    was_impersonated: bool,
    changes: Optional[list[Change]] = None,
) -> None:
    short_id = str(notebook.short_id)
    log_activity(
        organization_id=organization_id,
        team_id=team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=notebook.short_id,
        scope="Notebook",
        activity=activity,
        detail=Detail(changes=changes, short_id=short_id, name=notebook.title),
    )


class NotebookMinimalSerializer(serializers.ModelSerializer, UserAccessControlSerializerMixin):
    created_by = UserBasicSerializer(read_only=True)
    last_modified_by = UserBasicSerializer(read_only=True)
    _create_in_folder = serializers.CharField(required=False, allow_blank=True, write_only=True)

    class Meta:
        model = Notebook
        fields = [
            "id",
            "short_id",
            "title",
            "deleted",
            "created_at",
            "created_by",
            "last_modified_at",
            "last_modified_by",
            "user_access_level",
            "_create_in_folder",
        ]
        read_only_fields = fields


class NotebookSerializer(NotebookMinimalSerializer):
    class Meta:
        model = Notebook
        fields = [
            "id",
            "short_id",
            "title",
            "content",
            "text_content",
            "version",
            "deleted",
            "created_at",
            "created_by",
            "last_modified_at",
            "last_modified_by",
            "user_access_level",
            "_create_in_folder",
        ]
        read_only_fields = [
            "id",
            "short_id",
            "created_at",
            "created_by",
            "last_modified_at",
            "last_modified_by",
            "user_access_level",
        ]

    def create(self, validated_data: dict, *args, **kwargs) -> Notebook:
        request = self.context["request"]
        team = self.context["get_team"]()

        created_by = validated_data.pop("created_by", request.user)
        content = validated_data.get("content")
        if isinstance(content, dict):
            validated_data["content"] = annotate_python_nodes(content)
        notebook = Notebook.objects.create(
            team=team,
            created_by=created_by,
            last_modified_by=request.user,
            **validated_data,
        )

        log_notebook_activity(
            activity="created",
            notebook=notebook,
            organization_id=self.context["request"].user.current_organization_id,
            team_id=team.id,
            user=self.context["request"].user,
            was_impersonated=is_impersonated_session(request),
        )

        return notebook

    def update(self, instance: Notebook, validated_data: dict, **kwargs) -> Notebook:
        try:
            before_update = Notebook.objects.get(pk=instance.id)
        except Notebook.DoesNotExist:
            before_update = None

        with transaction.atomic():
            # select_for_update locks the database row so we ensure version updates are atomic
            locked_instance = Notebook.objects.select_for_update().get(pk=instance.pk)

            if validated_data.keys():
                locked_instance.last_modified_at = now()
                locked_instance.last_modified_by = self.context["request"].user

                if validated_data.get("content"):
                    if validated_data.get("version") != locked_instance.version:
                        raise Conflict("Someone else edited the Notebook")

                    validated_data["version"] = locked_instance.version + 1
                    content = validated_data.get("content")
                    if isinstance(content, dict):
                        validated_data["content"] = annotate_python_nodes(content)

                updated_notebook = super().update(locked_instance, validated_data)

        changes = changes_between("Notebook", previous=before_update, current=updated_notebook)

        activity = "updated"
        if changes:
            deleted_change = next((change for change in changes if change.field == "deleted"), None)
            if deleted_change:
                activity = "restored" if deleted_change.after is False else "deleted"

        log_notebook_activity(
            activity=activity,
            notebook=updated_notebook,
            organization_id=self.context["request"].user.current_organization_id,
            team_id=self.context["team_id"],
            user=self.context["request"].user,
            was_impersonated=is_impersonated_session(self.context["request"]),
            changes=changes,
        )

        return updated_notebook


class NotebookKernelExecuteSerializer(serializers.Serializer):
    code = serializers.CharField(allow_blank=True)
    return_variables = serializers.BooleanField(default=True)
    timeout = serializers.FloatField(required=False, min_value=0.1, max_value=120)


class NotebookKernelDataframeSerializer(serializers.Serializer):
    variable_name = serializers.CharField()
    offset = serializers.IntegerField(default=0, min_value=0)
    limit = serializers.IntegerField(default=10, min_value=1, max_value=500)
    timeout = serializers.FloatField(required=False, min_value=0.1, max_value=120)

    def validate_variable_name(self, value: str) -> str:
        if not value.isidentifier():
            raise serializers.ValidationError("Variable name must be a valid identifier.")
        return value


ALLOWED_KERNEL_CPU_CORES = [0.125, 0.25, 0.5, 1, 2, 4, 6, 8, 16, 32, 64]
ALLOWED_KERNEL_MEMORY_GB = [0.25, 0.5, 1, 2, 4, 8, 16, 32, 64, 128, 256]
ALLOWED_KERNEL_IDLE_TIMEOUT_SECONDS = [600, 1800, 3600, 10800, 21600, 43200]


class NotebookKernelConfigSerializer(serializers.Serializer):
    cpu_cores = serializers.FloatField(required=False)
    memory_gb = serializers.FloatField(required=False)
    idle_timeout_seconds = serializers.IntegerField(required=False)

    def validate_cpu_cores(self, value: float) -> float:
        if not any(math.isclose(value, option, rel_tol=0, abs_tol=1e-6) for option in ALLOWED_KERNEL_CPU_CORES):
            raise serializers.ValidationError("CPU cores must be a supported option.")
        return value

    def validate_memory_gb(self, value: float) -> float:
        if not any(math.isclose(value, option, rel_tol=0, abs_tol=1e-6) for option in ALLOWED_KERNEL_MEMORY_GB):
            raise serializers.ValidationError("Memory must be a supported option.")
        return value

    def validate_idle_timeout_seconds(self, value: int) -> int:
        if value not in ALLOWED_KERNEL_IDLE_TIMEOUT_SECONDS:
            raise serializers.ValidationError("Idle timeout must be a supported option.")
        return value

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("Provide at least one kernel configuration option.")
        return attrs


@extend_schema(
    description="The API for interacting with Notebooks. This feature is in early access and the API can have "
    "breaking changes without announcement.",
)
@extend_schema_view(
    list=extend_schema(
        parameters=[
            OpenApiParameter("short_id", exclude=True),
            OpenApiParameter(
                "created_by",
                OpenApiTypes.UUID,
                description="The UUID of the Notebook's creator",
                required=False,
            ),
            OpenApiParameter(
                "user",
                description="If any value is provided for this parameter, return notebooks created by the logged in user.",
                required=False,
            ),
            OpenApiParameter(
                "date_from",
                OpenApiTypes.DATETIME,
                description="Filter for notebooks created after this date & time",
                required=False,
            ),
            OpenApiParameter(
                "date_to",
                OpenApiTypes.DATETIME,
                description="Filter for notebooks created before this date & time",
                required=False,
            ),
            OpenApiParameter(
                "contains",
                description="""Filter for notebooks that match a provided filter.
                Each match pair is separated by a colon,
                multiple match pairs can be sent separated by a space or a comma""",
                examples=[
                    OpenApiExample(
                        "Filter for notebooks that have any recording",
                        value="recording:true",
                    ),
                    OpenApiExample(
                        "Filter for notebooks that do not have any recording",
                        value="recording:false",
                    ),
                    OpenApiExample(
                        "Filter for notebooks that have a specific recording",
                        value="recording:the-session-recording-id",
                    ),
                ],
                required=False,
            ),
        ],
    )
)
class NotebookViewSet(TeamAndOrgViewSetMixin, AccessControlViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    scope_object = "notebook"
    queryset = Notebook.objects.all()
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["short_id"]
    lookup_field = "short_id"

    def get_serializer_class(self) -> type[BaseSerializer]:
        return NotebookMinimalSerializer if self.action == "list" else NotebookSerializer

    def _get_notebook_for_kernel(self) -> Notebook:
        if self.kwargs.get(self.lookup_field) == "scratchpad":
            return Notebook(
                short_id="scratchpad",
                team=self.team,
                created_by=self.request.user,
                last_modified_by=self.request.user,
                visibility=Notebook.Visibility.INTERNAL,
            )

        return self.get_object()

    def _current_user(self) -> User | None:
        return self.request.user if isinstance(self.request.user, User) else None

    def safely_get_queryset(self, queryset) -> QuerySet:
        if not self.action.endswith("update"):
            # Soft-deleted notebooks can be brought back with a PATCH request
            queryset = queryset.filter(deleted=False)

        queryset = queryset.select_related("created_by", "last_modified_by", "team")
        if self.action == "list":
            queryset = queryset.filter(deleted=False, visibility=Notebook.Visibility.DEFAULT)
            queryset = self._filter_list_request(self.request, queryset)

        order = self.request.GET.get("order", None)
        if order:
            queryset = queryset.order_by(order)
        else:
            queryset = queryset.order_by("-last_modified_at")

        return queryset

    def _filter_list_request(self, request: Request, queryset: QuerySet, filters: dict | None = None) -> QuerySet:
        filters = filters or request.GET.dict()

        for key in filters:
            value = filters.get(key, None)
            if key == "user":
                queryset = queryset.filter(created_by=request.user)
            elif key == "created_by":
                queryset = queryset.filter(created_by__uuid=value)
            elif key == "last_modified_by":
                queryset = queryset.filter(last_modified_by__uuid=value)
            elif key == "date_from" and isinstance(value, str):
                queryset = queryset.filter(last_modified_at__gt=relative_date_parse(value, self.team.timezone_info))
            elif key == "date_to" and isinstance(value, str):
                queryset = queryset.filter(last_modified_at__lt=relative_date_parse(value, self.team.timezone_info))
            elif key == "search":
                queryset = queryset.filter(
                    # some notebooks have no text_content until next saved, so we need to check the title too
                    # TODO this can be removed once all/most notebooks have text_content
                    Q(title__search=value) | Q(text_content__search=value)
                )
            elif key == "contains" and isinstance(value, str):
                contains = value
                match_pairs = contains.replace(",", " ").split(" ")
                # content is a JSONB field that has an array of objects under the key "content"
                # each of those (should) have a "type" field
                # and for recordings that type is "ph-recording"
                # each of those objects can have attrs which is a dict with id for the recording
                for match_pair in match_pairs:
                    splat = match_pair.split(":")
                    target = depluralize(splat[0])
                    match = splat[1] if len(splat) > 1 else None

                    if target:
                        # the JSONB query requires a specific structure
                        basic_structure = list[dict[str, Any]]
                        nested_structure = basic_structure | list[dict[str, basic_structure]]

                        presence_match_structure: basic_structure | nested_structure = [{"type": f"ph-{target}"}]

                        try:
                            # We try to parse the match as a number, as query params are always strings,
                            # but an id could be an integer and wouldn't match
                            if isinstance(match, str):  # because mypy
                                match = int(match)
                        except (ValueError, TypeError):
                            pass

                        id_match_structure: basic_structure | nested_structure = [{"attrs": {"id": match}}]
                        if target == "replay-timestamp":
                            # replay timestamps are not at the top level, they're one-level down in a content array
                            presence_match_structure = [{"content": [{"type": f"ph-{target}"}]}]
                            id_match_structure = [{"content": [{"attrs": {"sessionRecordingId": match}}]}]
                        elif target == "query":
                            id_match_structure = [
                                {
                                    "attrs": {
                                        "query": {
                                            "kind": "SavedInsightNode",
                                            "shortId": match,
                                        }
                                    }
                                }
                            ]

                        if match == "true" or match is None:
                            queryset = queryset.filter(content__content__contains=presence_match_structure)
                        elif match == "false":
                            queryset = queryset.exclude(content__content__contains=presence_match_structure)
                        else:
                            queryset = queryset.filter(content__content__contains=presence_match_structure)
                            queryset = queryset.filter(content__content__contains=id_match_structure)

        return queryset

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        serializer = self.get_serializer(instance)

        if str(request.headers.get("If-None-Match")) == str(instance.version):
            return Response(None, 304)

        return Response(serializer.data)

    @action(methods=["POST"], url_path="kernel/start", detail=True)
    def kernel_start(self, request: Request, **kwargs):
        notebook = self._get_notebook_for_kernel()
        try:
            kernel_runtime = get_kernel_runtime(notebook, self._current_user()).ensure()
        except SandboxProvisionError:
            logger.exception("notebook_kernel_start_failed", notebook_short_id=notebook.short_id)
            return Response({"detail": "Failed to start notebook kernel."}, status=503)
        except RuntimeError:
            logger.exception("notebook_kernel_start_failed", notebook_short_id=notebook.short_id)
            return Response({"detail": "Failed to start notebook kernel."}, status=503)
        return Response({"id": str(kernel_runtime.id), "status": kernel_runtime.status})

    @action(methods=["POST"], url_path="kernel/stop", detail=True)
    def kernel_stop(self, request: Request, **kwargs):
        notebook = self._get_notebook_for_kernel()
        try:
            stopped = get_kernel_runtime(notebook, self._current_user()).shutdown()
        except RuntimeError:
            logger.exception("notebook_kernel_stop_failed", notebook_short_id=notebook.short_id)
            return Response({"detail": "Failed to stop notebook kernel."}, status=503)
        return Response({"stopped": stopped})

    @action(methods=["POST"], url_path="kernel/restart", detail=True)
    def kernel_restart(self, request: Request, **kwargs):
        notebook = self._get_notebook_for_kernel()
        try:
            kernel_runtime = get_kernel_runtime(notebook, self._current_user()).restart()
        except SandboxProvisionError:
            logger.exception("notebook_kernel_restart_failed", notebook_short_id=notebook.short_id)
            return Response({"detail": "Failed to restart notebook kernel."}, status=503)
        except RuntimeError:
            logger.exception("notebook_kernel_restart_failed", notebook_short_id=notebook.short_id)
            return Response({"detail": "Failed to restart notebook kernel."}, status=503)
        return Response({"id": str(kernel_runtime.id), "status": kernel_runtime.status})

    @action(methods=["GET"], url_path="kernel/status", detail=True)
    def kernel_status(self, request: Request, **kwargs):
        notebook = self._get_notebook_for_kernel()
        user = self._current_user()
        runtime = (
            KernelRuntime.objects.filter(
                team_id=self.team_id,
                notebook_short_id=notebook.short_id,
                user=user if isinstance(user, User) else None,
            )
            .order_by("-last_used_at")
            .first()
        )
        service = get_kernel_runtime(notebook, user).service
        backend = runtime.backend if runtime else service._get_backend()
        sandbox_config = build_notebook_sandbox_config(notebook)
        cpu_cores = sandbox_config.cpu_cores

        status = runtime.status if runtime else KernelRuntime.Status.STOPPED
        if (
            runtime
            and runtime.sandbox_id
            and runtime.backend
            in (
                KernelRuntime.Backend.MODAL,
                KernelRuntime.Backend.DOCKER,
            )
        ):
            try:
                sandbox_class = service._get_sandbox_class(runtime.backend)
                sandbox = sandbox_class.get_by_id(runtime.sandbox_id)
                if sandbox.get_status() != SandboxStatus.RUNNING:
                    status = KernelRuntime.Status.STOPPED
            except Exception:
                status = KernelRuntime.Status.STOPPED

        if runtime and status == KernelRuntime.Status.STOPPED:
            if (
                runtime.backend == KernelRuntime.Backend.MODAL
                and runtime.status in (KernelRuntime.Status.RUNNING, KernelRuntime.Status.STARTING)
                and runtime.last_used_at
                and sandbox_config.ttl_seconds
                and now() >= runtime.last_used_at + timedelta(seconds=sandbox_config.ttl_seconds)
            ):
                status = KernelRuntime.Status.TIMED_OUT

            if runtime.status != status:
                runtime.status = status
                runtime.save(update_fields=["status"])

        return Response(
            {
                "backend": backend,
                "status": status,
                "last_used_at": runtime.last_used_at.isoformat() if runtime else None,
                "last_error": runtime.last_error if runtime else None,
                "runtime_id": str(runtime.id) if runtime else None,
                "kernel_id": runtime.kernel_id if runtime else None,
                "kernel_pid": runtime.kernel_pid if runtime else None,
                "sandbox_id": runtime.sandbox_id if runtime else None,
                "cpu_cores": cpu_cores,
                "memory_gb": sandbox_config.memory_gb,
                "disk_size_gb": sandbox_config.disk_size_gb,
                "idle_timeout_seconds": sandbox_config.ttl_seconds,
            }
        )

    @action(methods=["POST"], url_path="kernel/config", detail=True)
    def kernel_config(self, request: Request, **kwargs):
        serializer = NotebookKernelConfigSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        notebook = self._get_notebook_for_kernel()
        update_fields = []

        if "cpu_cores" in serializer.validated_data:
            notebook.kernel_cpu_cores = serializer.validated_data["cpu_cores"]
            update_fields.append("kernel_cpu_cores")
        if "memory_gb" in serializer.validated_data:
            notebook.kernel_memory_gb = serializer.validated_data["memory_gb"]
            update_fields.append("kernel_memory_gb")
        if "idle_timeout_seconds" in serializer.validated_data:
            notebook.kernel_idle_timeout_seconds = serializer.validated_data["idle_timeout_seconds"]
            update_fields.append("kernel_idle_timeout_seconds")

        if notebook.pk:
            notebook.save(update_fields=update_fields)

        return Response(
            {
                "cpu_cores": notebook.kernel_cpu_cores,
                "memory_gb": notebook.kernel_memory_gb,
                "idle_timeout_seconds": notebook.kernel_idle_timeout_seconds,
            }
        )

    @action(methods=["POST"], url_path="kernel/execute", detail=True)
    def kernel_execute(self, request: Request, **kwargs):
        serializer = NotebookKernelExecuteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        notebook = self._get_notebook_for_kernel()

        try:
            analysis = analyze_python_globals(serializer.validated_data["code"])
            variable_names = [entry["name"] for entry in analysis.exported_with_types]
            execution = get_kernel_runtime(notebook, self._current_user()).execute(
                serializer.validated_data["code"],
                capture_variables=serializer.validated_data.get("return_variables", True),
                variable_names=variable_names,
                timeout=serializer.validated_data.get("timeout"),
            )
        except SandboxProvisionError:
            logger.exception("notebook_kernel_execute_failed", notebook_short_id=notebook.short_id)
            return Response({"detail": "Failed to execute notebook code."}, status=503)
        except RuntimeError:
            logger.exception("notebook_kernel_execute_failed", notebook_short_id=notebook.short_id)
            return Response({"detail": "Failed to execute notebook code."}, status=503)

        return Response(execution.as_dict())

    @action(methods=["GET"], url_path="kernel/dataframe", detail=True)
    def kernel_dataframe(self, request: Request, **kwargs):
        serializer = NotebookKernelDataframeSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        notebook = self._get_notebook_for_kernel()

        try:
            data = get_kernel_runtime(notebook, self._current_user()).dataframe_page(
                serializer.validated_data["variable_name"],
                offset=serializer.validated_data["offset"],
                limit=serializer.validated_data["limit"],
                timeout=serializer.validated_data.get("timeout"),
            )
        except ValueError:
            logger.exception(
                "notebook_kernel_dataframe_invalid_request",
                notebook_short_id=notebook.short_id,
            )
            return Response({"detail": "Invalid dataframe request."}, status=400)
        except SandboxProvisionError:
            logger.exception("notebook_kernel_dataframe_failed", notebook_short_id=notebook.short_id)
            return Response({"detail": "Failed to fetch dataframe data."}, status=503)
        except RuntimeError:
            logger.exception("notebook_kernel_dataframe_failed", notebook_short_id=notebook.short_id)
            return Response({"detail": "Failed to fetch dataframe data."}, status=503)

        return Response(data)

    @action(methods=["GET"], detail=False)
    def recording_comments(self, request: Request, **kwargs):
        recording_id = request.GET.get("recording_id")
        if not recording_id:
            return Response({"detail": "recording_id is required"}, status=400)

        queryset = self.safely_get_queryset(self.queryset)
        queryset = self._filter_list_request(request, queryset, {"contains": f"recording:{recording_id}"})
        notebooks = queryset.all()
        comments = []
        for notebook in notebooks:
            content_nodes = notebook.content.get("content", {})
            for node in content_nodes:
                if node.get("type", None) == "paragraph" and len(node.get("content", [])) == 2:
                    attrs = node.get("content", [])[0].get("attrs", {})
                    content_node_recording_id = attrs.get("sessionRecordingId", None)
                    playback_time = attrs.get("playbackTime", None)
                    if content_node_recording_id == recording_id and playback_time is not None:
                        text = node.get("content", [])[1].get("text", None)
                        comments.append(
                            {
                                "timeInRecording": playback_time,
                                "comment": text,
                                "notebookShortId": notebook.short_id,
                                "notebookTitle": notebook.title,
                                # the individual comments don't have an id, so we'll generate one
                                # to save the frontend having to do it
                                "id": hashlib.sha256(
                                    f"{notebook.short_id}-{notebook.title}-{text}-{playback_time}".encode()
                                ).hexdigest(),
                            }
                        )
        return JsonResponse({"results": comments})

    @action(methods=["GET"], url_path="activity", detail=False)
    def all_activity(self, request: Request, **kwargs):
        limit = int(request.query_params.get("limit", "10"))
        page = int(request.query_params.get("page", "1"))

        activity_page = load_activity(scope="Notebook", team_id=self.team_id, limit=limit, page=page)
        return activity_page_response(activity_page, limit, page, request)

    @action(methods=["GET"], url_path="activity", detail=True, required_scopes=["activity_log:read"])
    def activity(self, request: Request, **kwargs):
        notebook = self.get_object()
        limit = int(request.query_params.get("limit", "10"))
        page = int(request.query_params.get("page", "1"))

        activity_page = load_activity(
            scope="Notebook",
            team_id=self.team_id,
            item_ids=[notebook.id, notebook.short_id],
            limit=limit,
            page=page,
        )
        return activity_page_response(activity_page, limit, page, request)
