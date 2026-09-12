from typing import Any
from uuid import UUID

from drf_spectacular.openapi import AutoSchema
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication
from posthog.permissions import APIScopePermission

from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.presentation.serializers import (
    SpaceFileCreateSerializer,
    SpaceFileListSerializer,
    SpaceFileSerializer,
    SpaceFileUpdateSerializer,
    SpaceFileVersionConflictSerializer,
)


class _SpaceFileSchema(AutoSchema):
    def _get_request_for_media_type(self, serializer: Any, direction: str = "request") -> tuple[Any, bool]:
        if self.method == "PATCH" and isinstance(serializer, dict):
            return serializer, True
        return super()._get_request_for_media_type(serializer, direction)


SPACE_FILE_UPDATE_REQUEST_SCHEMA = {
    "application/json": {
        "type": "object",
        "required": ["content", "base_version"],
        "properties": {
            "content": {
                "type": "string",
                "maxLength": 100000,
                "description": "Complete replacement Markdown file content, up to 100000 UTF-8 bytes.",
            },
            "base_version": {
                "type": "integer",
                "minimum": 1,
                "description": "Version read before this update. A stale version returns 409.",
            },
        },
    }
}


class SpaceFileViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    authentication_classes = [
        SessionAuthentication,
        PersonalAPIKeyAuthentication,
        OAuthAccessTokenAuthentication,
    ]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "task"
    scope_object_read_actions = ["list", "retrieve"]
    scope_object_write_actions = ["create", "partial_update"]
    http_method_names = ["get", "post", "patch", "head", "options"]
    serializer_class = SpaceFileSerializer
    schema = _SpaceFileSchema()

    def _user_id(self) -> int | None:
        return getattr(self.request.user, "id", None)

    def _sandbox_channel_id(self, request: Request) -> UUID | None:
        authenticator = request.successful_authenticator
        if not isinstance(authenticator, OAuthAccessTokenAuthentication):
            return None
        task_id = authenticator.access_token.sandbox_task_id
        if task_id is None:
            return None
        channel_id = tasks_facade.task_channel_id(task_id, self.team_id)
        if channel_id is None:
            raise PermissionDenied("This task is not assigned to a space.")
        return channel_id

    @extend_schema(
        responses={200: OpenApiResponse(response=SpaceFileListSerializer(many=True), description="Space files")},
        summary="List space files",
        description="List Markdown files in spaces the requester can access. Content is omitted from this response.",
    )
    def list(self, request: Request, *args, **kwargs) -> Response:
        files = tasks_facade.list_space_files(
            self.team_id,
            self._user_id(),
            channel_id=self._sandbox_channel_id(request),
        )
        page = self.paginate_queryset(files)
        if page is not None:
            return self.get_paginated_response(SpaceFileListSerializer(page, many=True).data)
        return Response(SpaceFileListSerializer(files, many=True).data)

    @extend_schema(
        responses={200: SpaceFileSerializer},
        summary="Get a space file",
        description="Get one Markdown file, including its complete content and current version.",
    )
    def retrieve(self, request: Request, pk: str | None = None, **kwargs) -> Response:
        if pk is None:
            raise NotFound("Space file not found.")
        space_file = tasks_facade.get_space_file(
            pk,
            self.team_id,
            self._user_id(),
            channel_id=self._sandbox_channel_id(request),
        )
        if space_file is None:
            raise NotFound("Space file not found.")
        return Response(SpaceFileSerializer(space_file).data)

    @extend_schema(
        request=SpaceFileCreateSerializer,
        responses={201: SpaceFileSerializer},
        summary="Create a space file",
        description="Create a Markdown file in a space the requester can access.",
    )
    def create(self, request: Request, **kwargs) -> Response:
        serializer = SpaceFileCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sandbox_channel_id = self._sandbox_channel_id(request)
        if sandbox_channel_id is not None and serializer.validated_data["channel_id"] != sandbox_channel_id:
            raise PermissionDenied("This task can create files only in its assigned space.")
        try:
            space_file = tasks_facade.create_space_file(
                self.team_id,
                self._user_id(),
                channel_id=serializer.validated_data["channel_id"],
                name=serializer.validated_data["name"],
                content=serializer.validated_data["content"],
            )
        except tasks_facade.SpaceFileNameConflictError:
            return Response(
                {"detail": "A file with this name already exists in the space."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if space_file is None:
            raise NotFound("Space not found.")
        return Response(SpaceFileSerializer(space_file).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        request=SPACE_FILE_UPDATE_REQUEST_SCHEMA,
        responses={
            200: SpaceFileSerializer,
            409: OpenApiResponse(
                response=SpaceFileVersionConflictSerializer,
                description="The file changed since it was read.",
            ),
        },
        summary="Update a space file",
        description="Replace a Markdown file's complete content when its version matches base_version.",
    )
    def partial_update(self, request: Request, pk: str | None = None, **kwargs) -> Response:
        if pk is None:
            raise NotFound("Space file not found.")
        serializer = SpaceFileUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sandbox_channel_id = self._sandbox_channel_id(request)
        try:
            space_file = tasks_facade.update_space_file(
                pk,
                self.team_id,
                self._user_id(),
                content=serializer.validated_data["content"],
                base_version=serializer.validated_data["base_version"],
                channel_id=sandbox_channel_id,
            )
        except tasks_facade.SpaceFileVersionConflictError as error:
            return Response(
                {
                    "detail": "The file changed since you read it. Read the latest version and try again.",
                    "current_version": error.current_version,
                },
                status=status.HTTP_409_CONFLICT,
            )
        if space_file is None:
            raise NotFound("Space file not found.")
        return Response(SpaceFileSerializer(space_file).data)
