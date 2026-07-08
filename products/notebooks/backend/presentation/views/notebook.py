import math
import hashlib
from datetime import timedelta
from typing import Any, cast

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Q, QuerySet
from django.http import Http404, JsonResponse
from django.utils.timezone import now

import structlog
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiParameter,
    extend_schema,
    extend_schema_field,
    extend_schema_view,
)
from rest_framework import serializers, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer

from posthog.hogql.query import execute_hogql_query

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.streaming import sse_streaming_response
from posthog.api.utils import action
from posthog.exceptions import Conflict
from posthog.helpers.impersonation import is_impersonated
from posthog.models import User
from posthog.models.activity_logging.activity_log import Change, changes_between, load_activity
from posthog.models.activity_logging.activity_page import activity_page_response
from posthog.models.utils import UUIDT
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin
from posthog.rbac.user_access_control import UserAccessControlSerializerMixin
from posthog.renderers import SafeJSONRenderer, ServerSentEventRenderer
from posthog.settings import SERVER_GATEWAY_INTERFACE
from posthog.utils import relative_date_parse

from products.notebooks.backend import collab_stream, markdown_collab, presence
from products.notebooks.backend.activity_logging import log_notebook_activity
from products.notebooks.backend.collab import submit_steps
from products.notebooks.backend.facade.content import convert_notebook_content_to_markdown
from products.notebooks.backend.kernel_runtime import build_notebook_sandbox_config, get_kernel_runtime
from products.notebooks.backend.models import KernelRuntime, Notebook, NotebookNodeRun
from products.notebooks.backend.python_analysis import analyze_python_globals, annotate_python_nodes
from products.notebooks.backend.query_validation import InvalidNotebookQueryError, normalize_notebook_query_nodes
from products.notebooks.backend.sql_v2 import is_sql_v2_enabled
from products.notebooks.backend.sql_v2_serializers import NotebookSQLV2RunRequestSerializer
from products.notebooks.backend.temporal.client import start_sql_v2_run_workflow
from products.notebooks.backend.temporal.sql_v2 import SQLV2RunInput
from products.tasks.backend.facade.exceptions import SandboxProvisionError
from products.tasks.backend.facade.sandbox import SandboxStatus

from ee.hogai.utils.aio import async_to_sync
from ee.hogai.utils.asgi import SyncIterableToAsync

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


_NOTEBOOK_FIELD_HELP_TEXTS = {
    "id": {"help_text": "UUID of the notebook."},
    "short_id": {"help_text": "Short alphanumeric identifier used in URLs and API lookups."},
    "title": {"help_text": "Title of the notebook."},
    "deleted": {"help_text": "Whether the notebook has been soft-deleted."},
}

_PARENT_RESOURCE_SCHEMA = {
    "type": "object",
    "nullable": True,
    "description": (
        "Parent resource this notebook is attached to, if any. Used by the notebook scene "
        "to render context-aware breadcrumbs (e.g. account notebooks link back to the "
        "Customer analytics accounts list)."
    ),
    "properties": {
        "type": {"type": "string", "enum": ["account"]},
        "id": {"type": "string", "format": "uuid"},
    },
    "required": ["type", "id"],
}


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
        extra_kwargs = _NOTEBOOK_FIELD_HELP_TEXTS


class NotebookSerializer(NotebookMinimalSerializer):
    parent_resource = serializers.SerializerMethodField(
        help_text=(
            "Parent resource this notebook is attached to, or `null`. Returns "
            "`{type: 'account', id: <uuid>}` for account-linked notebooks; used by the "
            "frontend to route breadcrumbs back to the resource's list."
        ),
    )

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
            "parent_resource",
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
            "parent_resource",
        ]
        extra_kwargs = {
            **_NOTEBOOK_FIELD_HELP_TEXTS,
            "content": {"help_text": "Notebook content as a ProseMirror JSON document structure."},
            "text_content": {"help_text": "Plain text representation of the notebook content for search."},
            "version": {
                "help_text": "Version number for optimistic concurrency control. Must match the current version when updating content."
            },
        }

    @extend_schema_field(_PARENT_RESOURCE_SCHEMA)
    def get_parent_resource(self, obj: Notebook) -> dict | None:
        # Group parents are skipped: ResourceNotebook stores group PK but personhog has no get-by-pk RPC.
        link = obj.resources.filter(account_id__isnull=False).only("account_id").first()
        if link is None:
            return None
        return {"type": "account", "id": str(link.account_id)}

    def create(self, validated_data: dict, *args, **kwargs) -> Notebook:
        request = self.context["request"]
        team = self.context["get_team"]()

        # short_id is read-only in the serializer but can be provided on create
        short_id = request.data.get("short_id")
        if short_id:
            if not isinstance(short_id, str) or not short_id.isalnum() or len(short_id) > 12:
                raise serializers.ValidationError(
                    {"short_id": "short_id must be an alphanumeric string up to 12 characters."}
                )
            validated_data["short_id"] = short_id

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
            was_impersonated=is_impersonated(request),
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
            should_publish_update = False

            if validated_data.keys():
                locked_instance.last_modified_at = now()
                locked_instance.last_modified_by = self.context["request"].user

                update_diff: markdown_collab.MarkdownDiff | None = None
                if "content" in validated_data:
                    if validated_data.get("version") != locked_instance.version:
                        raise Conflict("Someone else edited the Notebook")

                    validated_data["version"] = locked_instance.version + 1
                    content = validated_data.get("content")
                    if isinstance(content, dict):
                        validated_data["content"] = annotate_python_nodes(content)
                    update_diff = markdown_collab.build_markdown_update_diff(
                        locked_instance.content, validated_data.get("content")
                    )
                    should_publish_update = True

                updated_notebook = super().update(locked_instance, validated_data)
                if should_publish_update:
                    notify_team_id = updated_notebook.team_id
                    notify_notebook_id = str(updated_notebook.short_id)
                    notify_version = updated_notebook.version
                    transaction.on_commit(
                        lambda: markdown_collab.publish_notebook_update(
                            notify_team_id, notify_notebook_id, notify_version, diff=update_diff
                        )
                    )

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
            was_impersonated=is_impersonated(self.context["request"]),
            changes=changes,
        )

        return updated_notebook

    def validate_content(self, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        try:
            return normalize_notebook_query_nodes(value)
        except InvalidNotebookQueryError as err:
            raise serializers.ValidationError(str(err))


class NotebookMarkdownSerializer(serializers.Serializer):
    markdown = serializers.CharField(
        allow_blank=True,
        read_only=True,
        help_text="The notebook content rendered as markdown. Markdown notebooks return their stored markdown "
        "source; legacy rich-text notebooks are converted from their ProseMirror document.",
    )


class NotebookKernelExecuteSerializer(serializers.Serializer):
    code = serializers.CharField(allow_blank=True)
    return_variables = serializers.BooleanField(default=True)
    timeout = serializers.FloatField(required=False, min_value=0.1, max_value=120)


class NotebookHogQLExecuteSerializer(serializers.Serializer):
    query = serializers.CharField(allow_blank=True)


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


class NotebookCollabSaveSerializer(serializers.Serializer):
    client_id = serializers.CharField(help_text="Unique identifier for the client session.")
    version = serializers.IntegerField(help_text="The collab version the client's steps are based on.")
    steps = serializers.ListField(
        child=serializers.JSONField(),
        help_text="List of ProseMirror step JSON objects to apply.",
    )
    content = serializers.JSONField(help_text="The resulting ProseMirror document after applying the steps locally.")
    text_content = serializers.CharField(
        required=False, allow_blank=True, default="", help_text="Plain text for search indexing."
    )
    # No default: omitted title should preserve the existing notebook title, while "" clears it.
    title = serializers.CharField(required=False, allow_blank=True, help_text="Updated notebook title.")
    cursor_head = serializers.IntegerField(
        required=False, allow_null=True, help_text="ProseMirror cursor head position after applying steps."
    )

    def validate_content(self, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        try:
            return normalize_notebook_query_nodes(value)
        except InvalidNotebookQueryError as err:
            raise serializers.ValidationError(str(err))


class NotebookCollabCursorSerializer(serializers.Serializer):
    head = serializers.IntegerField(
        required=False,
        min_value=0,
        help_text="ProseMirror selection head position (rich v1 notebooks).",
    )
    node_index = serializers.IntegerField(
        required=False,
        min_value=0,
        help_text="Index of the caret's block node in the markdown notebook document (markdown notebooks).",
    )
    offset = serializers.IntegerField(
        required=False,
        min_value=0,
        help_text="Caret offset in the plain text of the focused editable element, in UTF-16 code units.",
    )
    list_item_index = serializers.IntegerField(
        required=False,
        min_value=0,
        help_text="Index of the focused list item when the caret is inside a list block.",
    )


class NotebookMarkdownSaveSerializer(serializers.Serializer):
    client_id = serializers.CharField(
        help_text="Unique identifier for the client session, used to skip self-echo on the update stream."
    )
    version = serializers.IntegerField(
        help_text="The notebook version the submitted content is based on (optimistic concurrency baseline)."
    )
    content = serializers.JSONField(
        help_text="The full markdown notebook document: a ProseMirror doc wrapping a single markdown node."
    )
    text_content = serializers.CharField(
        required=False, allow_blank=True, default="", help_text="Plain text for search indexing."
    )
    # No default: omitted title should preserve the existing notebook title, while "" clears it.
    title = serializers.CharField(required=False, allow_blank=True, help_text="Updated notebook title.")
    cursor = NotebookCollabCursorSerializer(
        required=False,
        help_text="The author's caret in the saved markdown, broadcast with the update so other "
        "clients can move the author's remote caret together with the text change.",
    )

    def validate_content(self, value: Any) -> Any:
        if markdown_collab.get_markdown_notebook_markdown(value) is None:
            raise serializers.ValidationError("Content must be a markdown notebook document.")
        return value


class NotebookCollabPresenceSerializer(serializers.Serializer):
    client_id = serializers.CharField(
        max_length=200,
        help_text="Unique identifier for the client session, used to skip self-echo on the update stream.",
    )
    version = serializers.IntegerField(
        min_value=0,
        help_text="The notebook version the cursor position is relative to.",
    )
    cursor = NotebookCollabCursorSerializer(
        help_text="The caller's caret position, broadcast to other clients on this notebook's collab stream."
    )


def _collab_user_name(user: User) -> str:
    return user.get_full_name() or "Wandering Hog"


def _format_hogql_response_payload(response: Any) -> dict[str, Any]:
    if hasattr(response, "model_dump"):
        response_payload = response.model_dump(exclude_none=True)
    else:
        response_payload = response.dict(exclude_none=True)
    for key in ("clickhouse", "hogql", "timings", "modifiers"):
        response_payload.pop(key, None)
    return response_payload


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
            notebook = Notebook(
                short_id="scratchpad",
                team=self.team,
                created_by=self.request.user,
                last_modified_by=self.request.user,
                visibility=Notebook.Visibility.INTERNAL,
            )
            self.check_object_permissions(self.request, notebook)
            return notebook

        return self.get_object()

    def _require_query_access(self) -> None:
        # SQLV2 runs arbitrary HogQL and returns analytics rows, so notebook access alone is not
        # enough — a notebook editor whose query access is denied must not read data through it.
        # Mirrors ee/api/subscription.py: the query:read scope gates tokens, this gates sessions
        # (which carry no scopes) and enforces real RBAC for tokens too.
        if not self.user_access_control.check_access_level_for_resource("query", "viewer"):
            raise PermissionDenied("You need query access to run SQL in a notebook.")

    def _current_user(self) -> User | None:
        return self.request.user if isinstance(self.request.user, User) else None

    @extend_schema(
        description="Return the notebook's content rendered as markdown. Markdown notebooks return their stored "
        "markdown source; legacy rich-text notebooks are converted from their ProseMirror document. Useful for "
        "exporting a notebook into docs or feeding it to an AI agent.",
        responses={200: NotebookMarkdownSerializer},
    )
    @action(methods=["GET"], url_path="markdown", detail=True, required_scopes=["notebook:read"])
    def markdown(self, request: Request, **kwargs) -> Response:
        notebook = self.get_object()
        serializer = NotebookMarkdownSerializer({"markdown": convert_notebook_content_to_markdown(notebook.content)})
        return Response(serializer.data)

    def safely_get_queryset(self, queryset) -> QuerySet:
        if not self.action.endswith("update"):
            # Soft-deleted notebooks can be brought back with a PATCH request
            queryset = queryset.filter(deleted=False)

        queryset = queryset.select_related("created_by", "last_modified_by", "team")
        if self.action == "list":
            queryset = queryset.filter(deleted=False, visibility=Notebook.Visibility.DEFAULT)
            queryset = self._filter_list_request(self.request, queryset)
            # The list serializer omits content/text_content, but both are large columns
            # (ProseMirror JSON + full plaintext) that we'd otherwise load and JSON-decode per row.
            # search/contains filters run as WHERE-clause predicates, so they don't need the columns in Python.
            queryset = queryset.defer("content", "text_content")

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
            elif key == "search" and value:
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
                    match_value: str | int | None = splat[1] if len(splat) > 1 else None

                    if target:
                        # the JSONB query requires a specific structure
                        basic_structure = list[dict[str, Any]]
                        nested_structure = basic_structure | list[dict[str, basic_structure]]

                        presence_match_structure: basic_structure | nested_structure = [{"type": f"ph-{target}"}]

                        try:
                            # We try to parse the match as a number, as query params are always strings,
                            # but an id could be an integer and wouldn't match
                            if isinstance(match_value, str):  # because mypy
                                match_value = int(match_value)
                        except (ValueError, TypeError):
                            pass

                        id_match_structure: basic_structure | nested_structure = [{"attrs": {"id": match_value}}]
                        if target == "replay-timestamp":
                            # replay timestamps are not at the top level, they're one-level down in a content array
                            presence_match_structure = [{"content": [{"type": f"ph-{target}"}]}]
                            id_match_structure = [{"content": [{"attrs": {"sessionRecordingId": match_value}}]}]
                        elif target == "query":
                            id_match_structure = [
                                {
                                    "attrs": {
                                        "query": {
                                            "kind": "SavedInsightNode",
                                            "shortId": match_value,
                                        }
                                    }
                                }
                            ]

                        if match_value == "true" or match_value is None:
                            queryset = queryset.filter(content__content__contains=presence_match_structure)
                        elif match_value == "false":
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

    @action(methods=["POST"], url_path="hogql/execute", detail=True)
    def hogql_execute(self, request: Request, **kwargs):
        serializer = NotebookHogQLExecuteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        notebook = self._get_notebook_for_kernel()

        try:
            response = execute_hogql_query(
                query=serializer.validated_data["query"], team=self.team, user=self._current_user()
            )
        except Exception as err:
            logger.exception("notebook_hogql_execute_failed", notebook_short_id=notebook.short_id)
            return Response({"error": str(err)}, status=400)

        return Response(_format_hogql_response_payload(response))

    @action(
        methods=["POST"],
        url_path="kernel/execute/stream",
        detail=True,
        renderer_classes=[ServerSentEventRenderer],
    )
    def kernel_execute_stream(self, request: Request, **kwargs):
        serializer = NotebookKernelExecuteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        notebook = self._get_notebook_for_kernel()

        analysis = analyze_python_globals(serializer.validated_data["code"])
        variable_names = [entry["name"] for entry in analysis.exported_with_types]
        renderer = SafeJSONRenderer()

        def stream():
            try:
                for event in get_kernel_runtime(notebook, self._current_user()).execute_stream(
                    serializer.validated_data["code"],
                    capture_variables=serializer.validated_data.get("return_variables", True),
                    variable_names=variable_names,
                    timeout=serializer.validated_data.get("timeout"),
                ):
                    if event["type"] == "result":
                        payload = event["data"]
                    else:
                        payload = {"text": event.get("text", "")}
                    payload_json = renderer.render(payload).decode()
                    yield f"event: {event['type']}\ndata: {payload_json}\n\n".encode()
            except SandboxProvisionError:
                logger.exception("notebook_kernel_execute_failed", notebook_short_id=notebook.short_id)
                payload = {"error": "Failed to execute notebook code."}
                payload_json = renderer.render(payload).decode()
                yield f"event: error\ndata: {payload_json}\n\n".encode()
            except RuntimeError:
                logger.exception("notebook_kernel_execute_failed", notebook_short_id=notebook.short_id)
                payload = {"error": "Failed to execute notebook code."}
                payload_json = renderer.render(payload).decode()
                yield f"event: error\ndata: {payload_json}\n\n".encode()

        streaming_content = SyncIterableToAsync(stream()) if SERVER_GATEWAY_INTERFACE == "ASGI" else stream()
        return sse_streaming_response(streaming_content, endpoint="notebook_stream")

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

    # Experimental, flag-gated slice — kept out of the public OpenAPI schema (no generated FE/MCP types yet).
    @extend_schema(exclude=True)
    @action(methods=["POST"], url_path="sql_v2/run", detail=True, required_scopes=["notebook:write", "query:read"])
    def sql_v2_run(self, request: Request, **kwargs):
        user = self._current_user()
        # Server-side gate is permissive in local dev (frontend still gates the UI); prod is flag-gated.
        if not (settings.DEBUG or is_sql_v2_enabled(user)):
            raise Http404()

        serializer = NotebookSQLV2RunRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        notebook = self._get_notebook_for_kernel()
        self._require_query_access()

        run = NotebookNodeRun.objects.create(
            team_id=self.team_id,
            notebook=notebook,
            node_id=serializer.validated_data["node_id"],
            status=NotebookNodeRun.Status.RUNNING,
        )

        try:
            start_sql_v2_run_workflow(
                SQLV2RunInput(
                    run_id=str(run.id),
                    notebook_short_id=notebook.short_id,
                    team_id=self.team_id,
                    user_id=user.id if isinstance(user, User) else None,
                    code=serializer.validated_data["code"],
                )
            )
        except Exception:
            logger.exception("notebook_sql_v2_run_start_failed", notebook_short_id=notebook.short_id)
            run.status = NotebookNodeRun.Status.FAILED
            run.error = "Failed to start run."
            run.save(update_fields=["status", "error", "updated_at"])
            return Response({"detail": "Failed to start run."}, status=503)

        return Response({"run_id": str(run.id)})

    @extend_schema(exclude=True)
    @action(
        methods=["GET"],
        url_path="sql_v2/runs/(?P<run_id>[^/.]+)",
        detail=True,
        required_scopes=["notebook:read", "query:read"],
    )
    def sql_v2_run_result(self, request: Request, run_id: str | None = None, **kwargs):
        # The node short-polls this durable read to learn when its run finishes. One indexed
        # query, no held connection — resilient to reloads/remounts (see sql_v2_result_delivery.md).
        user = self._current_user()
        if not (settings.DEBUG or is_sql_v2_enabled(user)) or run_id is None:
            raise Http404()

        # Scope to the notebook (via get_object → per-notebook access control), not just the
        # team: a team-only lookup lets a user read a run from a notebook they can't access.
        notebook = self._get_notebook_for_kernel()
        # The result envelope is analytics rows, so gate reads on query access too — a
        # notebook-reader whose query access is denied must not read the rows back.
        self._require_query_access()
        try:
            run = NotebookNodeRun.objects.for_team(self.team_id).filter(id=run_id, notebook=notebook).first()
        except DjangoValidationError:  # malformed run_id (not a UUID)
            raise Http404()
        if run is None:
            raise Http404()

        return Response(
            {
                "status": run.status,
                "result": run.envelope if run.status == NotebookNodeRun.Status.DONE else None,
                "error": run.error or None,
            }
        )

    @extend_schema(request=NotebookCollabSaveSerializer)
    @action(methods=["POST"], url_path="collab/save", detail=True, required_scopes=["notebook:write"])
    def collab_save(self, request: Request, **kwargs):
        serializer = NotebookCollabSaveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        notebook = self.get_object()

        user = cast(User, request.user)
        user_name = _collab_user_name(user)

        result = submit_steps(
            team_id=notebook.team_id,
            notebook_id=str(notebook.short_id),
            client_id=data["client_id"],
            steps_json=data["steps"],
            last_seen_version=data["version"],
            last_saved_version=notebook.version,
            user_id=user.pk,
            user_name=user_name,
            cursor_head=data.get("cursor_head"),
        )

        content = data["content"]

        if result.status == "accepted":
            notebook_before = Notebook.objects.get(pk=notebook.pk)
            Notebook.objects.filter(pk=notebook.pk).update(
                content=annotate_python_nodes(content) if isinstance(content, dict) else content,
                text_content=data.get("text_content", ""),
                title=data.get("title", notebook.title),
                version=result.version,
                last_modified_at=now(),
                last_modified_by=request.user,
            )
            notebook.refresh_from_db()

            # Snapshot diffs into the activity logs for history
            changes = changes_between("Notebook", previous=notebook_before, current=notebook)
            log_notebook_activity(
                activity="updated",
                notebook=notebook,
                organization_id=cast(UUIDT, user.current_organization_id),
                team_id=notebook.team_id,
                user=user,
                was_impersonated=is_impersonated(request),
                changes=changes,
            )

            return Response(NotebookSerializer(notebook, context=self.get_serializer_context()).data)

        # Snapshot the rejected save attempt so user has a recovery path
        log_notebook_activity(
            activity=f"save_rejected_{result.status}",  # save_rejected_conflict | save_rejected_stale
            notebook=notebook,
            organization_id=cast(UUIDT, user.current_organization_id),
            team_id=notebook.team_id,
            user=user,
            was_impersonated=is_impersonated(request),
            changes=[
                Change(
                    type="Notebook",
                    field="content",
                    action="changed",
                    before=notebook.content,
                    after=content,
                ),
            ],
        )

        if result.status == "stale":
            # Stream was trimmed (MAXLEN/TTL).
            return Response({"code": "conflict_stale"}, status=410)

        # Carries the missed steps so the client can reconcile without depending on SSE
        assert result.steps_since is not None  # status == "conflict" guarantees this
        return Response(
            {
                "code": "conflict",
                "steps": [e.step for e in result.steps_since],
                "client_ids": [e.client_id for e in result.steps_since],
                "version": result.version,
            },
            status=409,
        )

    @extend_schema(request=NotebookMarkdownSaveSerializer)
    @action(methods=["POST"], url_path="collab/markdown_save", detail=True, required_scopes=["notebook:write"])
    def collab_markdown_save(self, request: Request, **kwargs):
        """Versioned save for markdown notebooks: persists the full document and streams a diff to other clients."""
        serializer = NotebookMarkdownSaveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        notebook = self.get_object()
        user = cast(User, request.user)
        submitted_content = data["content"]

        notebook_before: Notebook | None = None
        with transaction.atomic():
            # The row lock serializes the Postgres version check with the Redis stream append, so
            # stream entry N is always the transition from the persisted version N-1.
            locked_notebook = Notebook.objects.select_for_update().get(pk=notebook.pk)

            if locked_notebook.version != data["version"]:
                result = markdown_collab.fetch_missed_markdown_updates(
                    locked_notebook.team_id,
                    str(locked_notebook.short_id),
                    last_seen_version=data["version"],
                    current_version=locked_notebook.version,
                )
            else:
                annotated_content = annotate_python_nodes(submitted_content)
                diff = markdown_collab.build_markdown_update_diff(locked_notebook.content, annotated_content)
                result = markdown_collab.submit_markdown_update(
                    locked_notebook.team_id,
                    str(locked_notebook.short_id),
                    client_id=data["client_id"],
                    diff=diff,
                    last_seen_version=locked_notebook.version,
                    last_saved_version=locked_notebook.version,
                    user_id=user.pk,
                    user_name=_collab_user_name(user),
                    cursor=data.get("cursor"),
                )
                if result.status == "accepted":
                    notebook_before = Notebook.objects.get(pk=notebook.pk)
                    locked_notebook.content = annotated_content
                    locked_notebook.text_content = data.get("text_content", "")
                    if "title" in data:
                        locked_notebook.title = data["title"]
                    locked_notebook.version = result.version
                    locked_notebook.last_modified_at = now()
                    locked_notebook.last_modified_by = user
                    locked_notebook.save(
                        update_fields=[
                            "content",
                            "text_content",
                            "title",
                            "version",
                            "last_modified_at",
                            "last_modified_by",
                        ]
                    )

        if result.status == "accepted":
            changes = changes_between("Notebook", previous=notebook_before, current=locked_notebook)
            log_notebook_activity(
                activity="updated",
                notebook=locked_notebook,
                organization_id=cast(UUIDT, user.current_organization_id),
                team_id=locked_notebook.team_id,
                user=user,
                was_impersonated=is_impersonated(request),
                changes=changes,
            )
            return Response(NotebookSerializer(locked_notebook, context=self.get_serializer_context()).data)

        # Snapshot the rejected save attempt so user has a recovery path
        log_notebook_activity(
            activity=f"save_rejected_{result.status}",  # save_rejected_conflict | save_rejected_stale
            notebook=locked_notebook,
            organization_id=cast(UUIDT, user.current_organization_id),
            team_id=locked_notebook.team_id,
            user=user,
            was_impersonated=is_impersonated(request),
            changes=[
                Change(
                    type="Notebook",
                    field="content",
                    action="changed",
                    before=locked_notebook.content,
                    after=submitted_content,
                ),
            ],
        )

        if result.status == "stale":
            return Response({"code": "conflict_stale"}, status=410)

        assert result.updates is not None  # status == "conflict" guarantees this
        return Response(
            {
                "code": "conflict",
                "updates": [
                    {
                        "version": entry.version,
                        "diff": entry.diff,
                        "base_crc": entry.base_crc,
                        "client_id": entry.client_id,
                    }
                    for entry in result.updates
                ],
                "version": result.version,
            },
            status=409,
        )

    @extend_schema(request=NotebookCollabPresenceSerializer, responses={204: None})
    @action(methods=["POST"], url_path="collab/presence", detail=True, required_scopes=["notebook:write"])
    def collab_presence(self, request: Request, **kwargs):
        """Broadcast the caller's caret position to other clients on this notebook's collab stream."""
        serializer = NotebookCollabPresenceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        notebook = self.get_object()
        user = cast(User, request.user)

        presence.publish_presence(
            notebook.team_id,
            str(notebook.short_id),
            client_id=data["client_id"],
            user_id=user.pk,
            user_name=_collab_user_name(user),
            version=data["version"],
            cursor=data["cursor"],
        )
        return Response(status=204)

    @action(
        methods=["GET"],
        url_path="collab/stream",
        detail=True,
        renderer_classes=[ServerSentEventRenderer],
        required_scopes=["notebook:read"],
    )
    def collab_stream(self, request: Request, **kwargs):
        """SSE stream of accepted prosemirror-collab steps for this notebook."""
        notebook = self.get_object()
        team_id = notebook.team_id
        notebook_id = str(notebook.short_id)
        last_event_id = request.headers.get("Last-Event-ID")

        # On ASGI (Granian in prod) the async generator runs as one cheap task per connection.
        # On WSGI (tests, fallback) async_to_sync bridges it via a worker thread + queue.
        return sse_streaming_response(
            collab_stream.stream_collab_sse(team_id, notebook_id, last_event_id=last_event_id)
            if SERVER_GATEWAY_INTERFACE == "ASGI"
            else async_to_sync(
                lambda: collab_stream.stream_collab_sse(team_id, notebook_id, last_event_id=last_event_id)
            ),
            endpoint="notebook_collab",
        )

    @action(methods=["GET"], detail=False)
    def recording_comments(self, request: Request, **kwargs):
        recording_id = request.GET.get("recording_id")
        if not recording_id:
            return Response({"detail": "recording_id is required"}, status=400)

        queryset = self.get_queryset()
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

    @extend_schema(operation_id="notebooks_all_activity_retrieve")
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
