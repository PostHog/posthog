from __future__ import annotations

from functools import cached_property
from typing import Any, cast
from uuid import UUID

from django.db.models import TextChoices

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, NotFound
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.api.file_system.file_system import MAX_PATH_LENGTH
from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.pagination import FacadeLimitOffsetPagination, facade_page_response
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.exceptions_capture import capture_exception
from posthog.models import User
from posthog.models.file_system.constants import workflows_list_v2_enabled
from posthog.permissions import FEATURE_FLAG_REQUIRED_ERROR_CODE

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.workflows.backend.facade.contracts import WorkflowViewConflict, WorkflowViewNotFound, WorkflowViewState
from products.workflows.backend.facade.workflow_views import (
    create_workflow_view,
    delete_workflow_view,
    get_workflow_view,
    initialize_workflow_views,
    list_workflow_views,
    restore_default_workflow_view,
    update_workflow_view,
)


class WorkflowViewFacet(TextChoices):
    STATUS = "status"
    KIND = "kind"
    TRIGGER = "trigger"
    OWNER = "owner"
    HEALTH = "health"
    CREATED_BY = "createdBy"
    TAG = "tag"
    IN = "in"


class WorkflowViewColumn(TextChoices):
    TYPE = "type"
    TRIGGER = "trigger"
    OWNER = "owner"
    CREATED_BY = "created_by"
    LAST_7_DAYS = "last_7_days"
    HEALTH = "health"


FACET_VALUE_MAX_LENGTH = 256


class WorkflowViewFilterSerializer(serializers.Serializer):
    facet = serializers.ChoiceField(
        choices=WorkflowViewFacet.choices,
        help_text="Supported workflow list facet. The in facet takes a folder path and must be negated.",
    )
    value = serializers.CharField(
        max_length=MAX_PATH_LENGTH,
        trim_whitespace=False,
        help_text=(
            f"Facet value, up to {FACET_VALUE_MAX_LENGTH} characters; createdBy accepts me for the current viewer. "
            f"An in value is a folder path and can be up to {MAX_PATH_LENGTH} characters, like any folder path."
        ),
    )
    negated = serializers.BooleanField(default=False, help_text="Exclude workflows matching this facet value.")

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        opens_a_folder = attrs["facet"] == WorkflowViewFacet.IN and not attrs.get("negated", False)
        if opens_a_folder:
            raise serializers.ValidationError("A view can hide a folder with -in:, but it can't open one.")
        if attrs["facet"] != WorkflowViewFacet.IN and len(attrs["value"]) > FACET_VALUE_MAX_LENGTH:
            raise serializers.ValidationError(
                {"value": f"Ensure this field has no more than {FACET_VALUE_MAX_LENGTH} characters."}
            )
        return attrs


class WorkflowViewStateSerializer(serializers.Serializer):
    filters = serializers.ListField(
        child=WorkflowViewFilterSerializer(), max_length=100, help_text="Saved workflow facet filters."
    )
    text = serializers.CharField(
        allow_blank=True, max_length=1000, trim_whitespace=False, help_text="Saved workflow list free-text search."
    )
    columns = serializers.ListField(
        child=serializers.ChoiceField(choices=WorkflowViewColumn.choices),
        max_length=6,
        help_text="Visible optional workflow columns. The list always shows them in the same fixed order.",
    )

    def validate_columns(self, columns: list[str]) -> list[str]:
        if len(set(columns)) != len(columns):
            raise serializers.ValidationError("Each column can appear only once.")
        return columns


class WorkflowViewSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True, help_text="Identifier of the shared workflow view.")
    name = serializers.CharField(max_length=128, help_text="Shared workflow view name.")
    state = WorkflowViewStateSerializer(help_text="Saved filters, text search, and visible columns.")
    version = serializers.IntegerField(read_only=True, help_text="Current version required for updates and deletion.")
    default_key = serializers.CharField(read_only=True, allow_null=True, help_text="Shipped view identifier, or null.")
    deleted = serializers.BooleanField(
        read_only=True, help_text="Whether the shipped view was deleted and can be restored."
    )
    created_at = serializers.DateTimeField(read_only=True, help_text="When the shared view was created.")
    updated_at = serializers.DateTimeField(read_only=True, help_text="When the shared view was last changed.")
    user_access_level = serializers.SerializerMethodField(help_text="Your workflow access in the owning project.")

    def get_user_access_level(self, _view: object) -> str:
        access = self.context["view"].user_access_control.access_level_for_resource("hog_flow")
        return access.access_level if access else "none"


class WorkflowViewCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=128, help_text="Shared workflow view name.")
    state = WorkflowViewStateSerializer(help_text="Saved filters, text search, and visible columns.")


class RequiredFieldsOnPatchSerializer(serializers.Serializer):
    @property
    def partial(self) -> bool:
        return False

    @partial.setter
    def partial(self, _value: bool) -> None:
        pass


class WorkflowViewUpdateSerializer(RequiredFieldsOnPatchSerializer):
    version = serializers.IntegerField(min_value=1, help_text="Version last read; stale edits are rejected with 409.")
    name = serializers.CharField(max_length=128, required=False, help_text="Replacement shared workflow view name.")
    state = WorkflowViewStateSerializer(
        required=False, help_text="Replacement filters, text search, and visible columns."
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if "name" not in attrs and "state" not in attrs:
            raise serializers.ValidationError("Send a name or a state to change.")
        return attrs


class WorkflowViewDeleteSerializer(serializers.Serializer):
    version = serializers.IntegerField(
        min_value=1, help_text="Version last read; stale deletions are rejected with 409."
    )


class WorkflowViewConflictSerializer(serializers.Serializer):
    type = serializers.CharField(help_text="Error category.")
    code = serializers.CharField(help_text="Machine-readable conflict code.")
    detail = serializers.CharField(help_text="Reason the view could not be changed.")
    attr = serializers.CharField(allow_null=True, help_text="Field associated with this error, if any.")


class WorkflowViewConflictError(APIException):
    status_code = 409
    default_detail = "This view changed. Reload it before saving or deleting."
    default_code = "workflow_view_conflict"


class WorkflowViewPagination(FacadeLimitOffsetPagination):
    default_limit = 100
    max_limit = 100


class WorkflowViewsFeatureFlagPermission(BasePermission):
    message = "Workflow saved views are unavailable."
    code = FEATURE_FLAG_REQUIRED_ERROR_CODE

    def has_permission(self, request: Request, view: APIView) -> bool:
        workflow_views = cast(WorkflowViewViewSet, view)
        try:
            return workflows_list_v2_enabled(workflow_views.team, cast(User, request.user))
        except Exception as error:
            capture_exception(error, {"flag": "workflows-list-v2"})
            return False


class WorkflowViewViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "hog_flow"
    scope_object_read_actions = ["list", "retrieve", "initialize"]
    scope_object_write_actions = ["create", "partial_update", "destroy", "restore_default"]
    serializer_class = WorkflowViewSerializer
    permission_classes = [WorkflowViewsFeatureFlagPermission]
    requires_resource_level_access = True
    path_parameters = {"id": UUID}
    pagination_class = WorkflowViewPagination
    lookup_field = "id"
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    @cached_property
    def user_access_control(self) -> UserAccessControl:
        # Saved views are stored on the project's main environment, so a child environment's URL reads and
        # writes the parent's views. Check the parent's workflow access rules, because the child's own
        # rules can be looser. The URL environment's membership check still runs on the child.
        owner = self.team.parent_team
        if owner is None:
            return super().user_access_control
        return UserAccessControl(user=cast(User, self.request.user), team=owner, organization_id=self.organization_id)

    def handle_exception(self, exc: Exception) -> Response:
        if isinstance(exc, WorkflowViewNotFound):
            return super().handle_exception(NotFound())
        if isinstance(exc, WorkflowViewConflict):
            return super().handle_exception(WorkflowViewConflictError())
        return super().handle_exception(exc)

    @extend_schema(responses={200: WorkflowViewSerializer(many=True)})
    def list(self, request: Request, *args: object, **kwargs: object) -> Response:
        return facade_page_response(self, lambda page: list_workflow_views(self.team_id, page))

    @validated_request(responses={200: WorkflowViewSerializer})
    def retrieve(self, request: ValidatedRequest, *args: object, **kwargs: object) -> Response:
        view = get_workflow_view(self.team_id, self.kwargs["id"])
        return Response(self.get_serializer(view).data)

    @validated_request(WorkflowViewCreateSerializer, responses={201: WorkflowViewSerializer})
    def create(self, request: ValidatedRequest, *args: object, **kwargs: object) -> Response:
        view = create_workflow_view(
            self.team_id,
            name=request.validated_data["name"],
            state=cast(WorkflowViewState, request.validated_data["state"]),
        )
        return Response(self.get_serializer(view).data, status=201)

    @validated_request(
        WorkflowViewUpdateSerializer,
        responses={200: WorkflowViewSerializer, 409: OpenApiResponse(response=WorkflowViewConflictSerializer)},
    )
    def partial_update(self, request: ValidatedRequest, *args: object, **kwargs: object) -> Response:
        updated = update_workflow_view(
            self.team_id,
            self.kwargs["id"],
            request.validated_data["version"],
            name=request.validated_data.get("name"),
            state=cast(WorkflowViewState | None, request.validated_data.get("state")),
        )
        return Response(self.get_serializer(updated).data)

    @validated_request(
        query_serializer=WorkflowViewDeleteSerializer,
        responses={204: None, 409: OpenApiResponse(response=WorkflowViewConflictSerializer)},
    )
    def destroy(self, request: ValidatedRequest, *args: object, **kwargs: object) -> Response:
        delete_workflow_view(self.team_id, self.kwargs["id"], request.validated_query_data["version"])
        return Response(status=204)

    @extend_schema(request=None, responses={200: WorkflowViewSerializer})
    @action(detail=False, methods=["POST"])
    def initialize(self, request: Request, *args: object, **kwargs: object) -> Response:
        view = initialize_workflow_views(self.team_id)
        return Response(self.get_serializer(view).data)

    @extend_schema(request=None, responses={200: WorkflowViewSerializer})
    @action(detail=False, methods=["POST"])
    def restore_default(self, request: Request, *args: object, **kwargs: object) -> Response:
        view = restore_default_workflow_view(self.team_id)
        return Response(self.get_serializer(view).data)
