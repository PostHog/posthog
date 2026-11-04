from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from django.db.models import TextChoices

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, NotFound
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.pagination import FacadeLimitOffsetPagination, facade_page_response
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.exceptions_capture import capture_exception
from posthog.models import User
from posthog.permissions import (
    FEATURE_FLAG_REQUIRED_ERROR_CODE,
    PostHogFeatureFlagPermission,
    get_authenticator_client,
    posthog_feature_flag_enabled,
)

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


class WorkflowViewColumn(TextChoices):
    TYPE = "type"
    TRIGGER = "trigger"
    OWNER = "owner"
    CREATED_BY = "created_by"
    LAST_7_DAYS = "last_7_days"
    HEALTH = "health"


class WorkflowViewFilterSerializer(serializers.Serializer):
    facet = serializers.ChoiceField(choices=WorkflowViewFacet.choices, help_text="Supported workflow list facet.")
    value = serializers.CharField(
        max_length=256, trim_whitespace=False, help_text="Facet value; createdBy accepts me for the current viewer."
    )
    negated = serializers.BooleanField(default=False, help_text="Exclude workflows matching this facet value.")


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
        help_text="Visible optional workflow columns in display order.",
    )


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


class WorkflowViewsFeatureFlagPermission(PostHogFeatureFlagPermission):
    message = "Workflow saved views are unavailable."
    code = FEATURE_FLAG_REQUIRED_ERROR_CODE

    def has_permission(self, request: Request, view: APIView) -> bool:
        workflow_views = cast(WorkflowViewViewSet, view)
        user = cast(User, request.user)
        for flag in ("workflows-saved-views", "workflows-list-v2"):
            try:
                enabled = posthog_feature_flag_enabled(
                    flag,
                    str(user.distinct_id),
                    organization_id=workflow_views.team.organization_id,
                    team_id=workflow_views.team.id,
                    caller_properties=get_authenticator_client(request.successful_authenticator),
                )
            except Exception as error:
                capture_exception(error, {"flag": flag})
                return False
            if not enabled:
                return False
        return True


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

    def handle_exception(self, exc: Exception) -> Response:
        if isinstance(exc, WorkflowViewNotFound):
            return super().handle_exception(NotFound())
        if isinstance(exc, WorkflowViewConflict):
            return super().handle_exception(WorkflowViewConflictError())
        return super().handle_exception(exc)

    @validated_request(responses={200: WorkflowViewSerializer(many=True)})
    def list(self, request: ValidatedRequest, *args: object, **kwargs: object) -> Response:
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
