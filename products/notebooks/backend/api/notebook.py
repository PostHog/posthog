import re
import hashlib
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
from pydantic import (
    BaseModel,
    ValidationError as PydanticValidationError,
)
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import Throttled, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer

from posthog.schema import QueryRequest

from posthog.hogql.constants import LimitContext
from posthog.hogql.errors import ExposedHogQLError, ResolutionError

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.query import _process_query_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.services.query import process_query_model
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import action, is_insight_actors_options_query, is_insight_actors_query, is_insight_query
from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded
from posthog.clickhouse.query_tagging import get_query_tag_value, tag_queries
from posthog.errors import ExposedCHQueryError
from posthog.exceptions import Conflict
from posthog.exceptions_capture import capture_exception
from posthog.models import User
from posthog.models.activity_logging.activity_log import Change, Detail, changes_between, load_activity, log_activity
from posthog.models.activity_logging.activity_page import activity_page_response
from posthog.models.utils import UUIDT
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin
from posthog.rbac.user_access_control import UserAccessControlError, UserAccessControlSerializerMixin
from posthog.schema_migrations.upgrade import upgrade
from posthog.utils import relative_date_parse

from products.notebooks.backend.kernel import notebook_kernel_service
from products.notebooks.backend.models import Notebook
from products.notebooks.backend.query_variables import (
    NotebookQueryVariable,
    cache_notebook_query_variable,
    store_query_result_in_kernel,
)

from common.hogvm.python.utils import HogVMException

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


class NotebookKernelQuerySerializer(serializers.Serializer):
    store_as = serializers.CharField(required=False, allow_blank=True, allow_null=True)


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

    def get_serializer_class(self) -> type[BaseSerializer]:
        return NotebookMinimalSerializer if self.action == "list" else NotebookSerializer

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

    @action(methods=["POST"], url_path="kernel/query", detail=True)
    def kernel_query(self, request: Request, **kwargs):
        serializer = NotebookKernelQuerySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        store_as = self._clean_variable_name(serializer.validated_data.get("store_as"))
        notebook = self._get_notebook_for_kernel()

        request_payload = request.data.copy()
        request_payload.pop("store_as", None)

        try:
            upgraded_query = upgrade(request_payload)
            request_model = QueryRequest.model_validate(upgraded_query)
            query, client_query_id, execution_mode = _process_query_request(
                request_model, self.team, request_model.client_query_id, request.user
            )
            if client_query_id:
                tag_queries(client_query_id=client_query_id)
            query_dict = query.model_dump()

            result = process_query_model(
                self.team,
                query,
                execution_mode=execution_mode,
                query_id=client_query_id,
                user=request.user,
                is_query_service=(get_query_tag_value("access_method") == "personal_api_key"),
                limit_context=(
                    LimitContext.QUERY_ASYNC
                    if (
                        is_insight_query(query_dict)
                        or is_insight_actors_query(query_dict)
                        or is_insight_actors_options_query(query_dict)
                    )
                    and get_query_tag_value("access_method") != "personal_api_key"
                    else None
                ),
            )

            if isinstance(result, BaseModel):
                result = result.model_dump(by_alias=True)

            response_status = (
                status.HTTP_202_ACCEPTED
                if result.get("query_status") and result["query_status"].get("complete") is False
                else status.HTTP_200_OK
            )

            self._maybe_store_query_result(notebook, store_as, result, client_query_id)
            return Response(result, status=response_status)
        except PydanticValidationError as err:
            raise ValidationError(err.errors())
        except (ExposedHogQLError, ExposedCHQueryError, HogVMException) as err:
            raise ValidationError(str(err), getattr(err, "code_name", None))
        except UserAccessControlError as err:
            raise ValidationError(str(err))
        except ResolutionError as err:
            raise ValidationError(str(err))
        except ConcurrencyLimitExceeded as err:
            raise Throttled(detail=str(err))
        except Exception as err:
            self._handle_column_ch_error(err)
            capture_exception(err)
            raise

    @action(methods=["POST"], url_path="kernel/start", detail=True)
    def kernel_start(self, request: Request, **kwargs):
        notebook = self._get_notebook_for_kernel()
        kernel_status = notebook_kernel_service.ensure_kernel(notebook)
        return Response(kernel_status.as_dict())

    @action(methods=["POST"], url_path="kernel/stop", detail=True)
    def kernel_stop(self, request: Request, **kwargs):
        notebook = self._get_notebook_for_kernel()
        stopped = notebook_kernel_service.shutdown_kernel(notebook)
        return Response({"stopped": stopped})

    @action(methods=["POST"], url_path="kernel/restart", detail=True)
    def kernel_restart(self, request: Request, **kwargs):
        notebook = self._get_notebook_for_kernel()
        kernel_status = notebook_kernel_service.restart_kernel(notebook)
        return Response(kernel_status.as_dict())

    @action(methods=["POST"], url_path="kernel/execute", detail=True)
    def kernel_execute(self, request: Request, **kwargs):
        serializer = NotebookKernelExecuteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        notebook = self._get_notebook_for_kernel()

        try:
            execution = notebook_kernel_service.execute(
                notebook,
                serializer.validated_data["code"],
                capture_variables=serializer.validated_data.get("return_variables", True),
                timeout=serializer.validated_data.get("timeout"),
            )
        except RuntimeError as err:
            logger.exception("notebook_kernel_execute_failed", notebook_short_id=notebook.short_id)
            return Response({"detail": str(err)}, status=503)

        return Response(execution.as_dict())

    def _maybe_store_query_result(
        self,
        notebook: Notebook,
        store_as: str | None,
        result: dict[str, Any],
        client_query_id: str | None,
    ) -> None:
        if not store_as:
            return

        if self._store_result_in_kernel(notebook, store_as, result):
            return

        query_status = result.get("query_status") if isinstance(result, dict) else None
        query_id = None
        if isinstance(query_status, dict) and not query_status.get("complete"):
            query_id = query_status.get("id") or client_query_id

        if not query_id:
            return

        cache_notebook_query_variable(query_id, self._build_query_variable(notebook, store_as))

    def _store_result_in_kernel(self, notebook: Notebook, variable_name: str, result: dict[str, Any]) -> bool:
        query_status = result.get("query_status") if isinstance(result, dict) else None
        if isinstance(query_status, dict):
            if not query_status.get("complete"):
                return False

            final_result = query_status.get("results")
        else:
            final_result = result

        if final_result is None:
            return False

        return store_query_result_in_kernel(
            self.team,
            self._current_user(),
            self._build_query_variable(notebook, variable_name),
            final_result,
        )

    def _build_query_variable(self, notebook: Notebook, variable_name: str) -> NotebookQueryVariable:
        return NotebookQueryVariable(
            team_id=self.team_id,
            notebook_short_id=notebook.short_id,
            user_id=self._current_user_id(),
            variable_name=variable_name,
        )

    def _current_user(self) -> User | None:
        return self.request.user if isinstance(self.request.user, User) else None

    def _current_user_id(self) -> int | None:
        return self.request.user.id if isinstance(self.request.user, User) else None

    def _clean_variable_name(self, variable_name: str | None) -> str | None:
        if variable_name is None:
            return None

        trimmed_name = variable_name.strip()
        if not trimmed_name:
            return None

        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", trimmed_name):
            raise ValidationError({"store_as": "Variable name must be a valid Python identifier."})

        return trimmed_name

    def _handle_column_ch_error(self, error: Exception) -> None:
        if getattr(error, "message", None):
            match = re.search(r"There's no column.*in table", error.message)
            if match:
                raise ValidationError(
                    match.group(0) + ". Note: While in beta, not all column types may be fully supported"
                )
