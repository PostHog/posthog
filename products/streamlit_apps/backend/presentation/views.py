from typing import Any, cast

from django.core.cache import cache

import structlog
from drf_spectacular.utils import extend_schema
from loginas.utils import is_impersonated_session
from rest_framework import status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import TypedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.models.user import User
from posthog.rate_limit import ClickHouseBurstRateThrottle

from products.streamlit_apps.backend.facade import api
from products.streamlit_apps.backend.facade.contracts import CreateAppInput, UpdateAppInput
from products.streamlit_apps.backend.presentation.serializers import (
    ActivateVersionRequestSerializer,
    ActivateVersionResponseSerializer,
    CreateAppInputSerializer,
    StreamlitAppMinimalSerializer,
    StreamlitAppsAccessPermission,
    StreamlitAppSandboxSerializer,
    StreamlitAppSerializer,
    StreamlitAppStatusSerializer,
    StreamlitAppVersionListSerializer,
    StreamlitAppVersionSerializer,
    StreamlitConnectInfoSerializer,
    UpdateAppInputSerializer,
    UploadVersionRequestSerializer,
)

logger = structlog.get_logger(__name__)

_STATUS_CACHE_TTL_SECONDS = 2


class StreamlitAppViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "streamlit_app"
    permission_classes = [StreamlitAppsAccessPermission]
    lookup_field = "short_id"

    @extend_schema(summary="List streamlit apps", responses={200: StreamlitAppMinimalSerializer(many=True)})
    def list(self, request: Request, **kwargs: Any) -> Response:
        apps = api.list_apps(self.team_id)
        page = self.paginate_queryset(apps)
        if page is not None:
            return self.get_paginated_response(StreamlitAppMinimalSerializer(page, many=True).data)
        return Response(StreamlitAppMinimalSerializer(apps, many=True).data)

    @validated_request(
        request_serializer=CreateAppInputSerializer,
        summary="Create a streamlit app",
        responses={201: StreamlitAppSerializer},
    )
    def create(self, request: TypedRequest[CreateAppInput], **kwargs: Any) -> Response:
        try:
            app = api.create_app(
                team_id=self.team_id,
                user=cast(User, request.user),
                data=request.validated_data,
                was_impersonated=is_impersonated_session(request),
            )
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(StreamlitAppSerializer(app).data, status=status.HTTP_201_CREATED)

    @extend_schema(summary="Retrieve a streamlit app", responses={200: StreamlitAppSerializer})
    def retrieve(self, request: Request, short_id: str, **kwargs: Any) -> Response:
        try:
            app = api.get_app(self.team_id, short_id)
        except api.AppNotFoundError:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(StreamlitAppSerializer(app).data)

    def _update(self, request: TypedRequest[UpdateAppInput], short_id: str) -> Response:
        try:
            app = api.update_app(
                team_id=self.team_id,
                short_id=short_id,
                user=cast(User, request.user),
                data=request.validated_data,
                was_impersonated=is_impersonated_session(request),
            )
        except api.AppNotFoundError:
            return Response(status=status.HTTP_404_NOT_FOUND)
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(StreamlitAppSerializer(app).data)

    @validated_request(
        request_serializer=UpdateAppInputSerializer,
        summary="Update a streamlit app",
        responses={200: StreamlitAppSerializer},
    )
    def update(self, request: TypedRequest[UpdateAppInput], short_id: str, **kwargs: Any) -> Response:
        return self._update(request, short_id)

    @validated_request(
        request_serializer=UpdateAppInputSerializer,
        summary="Partially update a streamlit app",
        responses={200: StreamlitAppSerializer},
    )
    def partial_update(self, request: TypedRequest[UpdateAppInput], short_id: str, **kwargs: Any) -> Response:
        return self._update(request, short_id)

    @extend_schema(summary="Delete a streamlit app", request=None, responses={204: None})
    def destroy(self, request: Request, short_id: str, **kwargs: Any) -> Response:
        try:
            api.delete_app(
                team_id=self.team_id,
                short_id=short_id,
                user=cast(User, request.user),
                was_impersonated=is_impersonated_session(request),
            )
        except api.AppNotFoundError:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        summary="List app versions",
        responses={200: StreamlitAppVersionListSerializer},
    )
    @action(methods=["GET"], detail=True, url_path="versions")
    def versions(self, request: Request, short_id: str, **kwargs: Any) -> Response:
        try:
            versions = api.list_versions(self.team_id, short_id)
        except api.AppNotFoundError:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response({"results": StreamlitAppVersionSerializer(versions, many=True).data})

    @extend_schema(
        summary="Upload a new app version",
        request=UploadVersionRequestSerializer,
        responses={201: StreamlitAppVersionSerializer},
    )
    @action(methods=["POST"], detail=True, url_path="upload_version")
    def upload_version(self, request: Request, short_id: str, **kwargs: Any) -> Response:
        zip_file = request.FILES.get("file")
        if not zip_file:
            return Response({"detail": "No file provided."}, status=status.HTTP_400_BAD_REQUEST)

        # Reject oversized uploads by their declared size before reading the body
        # into memory, so a large multipart POST can't force a full allocation.
        try:
            api.check_zip_size(zip_file.size)
        except api.ZipTooLargeError as e:
            return Response({"detail": str(e)}, status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)

        file_content = zip_file.read()

        try:
            version = api.upload_version(
                team_id=self.team_id,
                short_id=short_id,
                user=cast(User, request.user),
                file_content=file_content,
                declared_size=zip_file.size,
                was_impersonated=is_impersonated_session(request),
            )
        except api.AppNotFoundError:
            return Response(status=status.HTTP_404_NOT_FOUND)
        except api.ZipTooLargeError as e:
            return Response({"detail": str(e)}, status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        except api.InvalidZipError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except api.ConcurrentUploadError as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)

        return Response(StreamlitAppVersionSerializer(version).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Activate an existing app version",
        request=ActivateVersionRequestSerializer,
        responses={200: ActivateVersionResponseSerializer},
    )
    @action(methods=["POST"], detail=True, url_path="activate_version")
    def activate_version(self, request: Request, short_id: str, **kwargs: Any) -> Response:
        version_number = request.data.get("version_number")

        if version_number is None:
            return Response({"detail": "version_number is required."}, status=status.HTTP_400_BAD_REQUEST)

        # Guard the type before the facade call: a non-integer (e.g. "abc" or 1.5)
        # would otherwise raise ValueError deep in the ORM and surface as a 500.
        if not isinstance(version_number, int) or isinstance(version_number, bool):
            return Response({"detail": "version_number must be an integer."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            version = api.activate_version(
                team_id=self.team_id,
                short_id=short_id,
                user=cast(User, request.user),
                version_number=version_number,
                was_impersonated=is_impersonated_session(request),
            )
        except api.AppNotFoundError:
            return Response(status=status.HTTP_404_NOT_FOUND)
        except api.VersionNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)

        return Response({"active_version": StreamlitAppVersionSerializer(version).data})

    @extend_schema(
        summary="Get app sandbox status",
        responses={200: StreamlitAppStatusSerializer},
    )
    @action(methods=["GET"], detail=True, url_path="status")
    def get_status(self, request: Request, short_id: str, **kwargs: Any) -> Response:
        cache_key = f"streamlit_sandbox_status:{self.team_id}:{short_id}"
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)

        try:
            sandbox = api.get_status(self.team_id, short_id)
        except api.AppNotFoundError:
            return Response(status=status.HTTP_404_NOT_FOUND)

        payload = StreamlitAppSandboxSerializer(sandbox).data
        cache.set(cache_key, payload, _STATUS_CACHE_TTL_SECONDS)
        return Response(payload)

    @extend_schema(
        summary="Start the app sandbox",
        request=None,
        responses={200: StreamlitAppSerializer, 202: StreamlitAppSerializer},
    )
    @action(methods=["POST"], detail=True, url_path="start", throttle_classes=[ClickHouseBurstRateThrottle])
    def start(self, request: Request, short_id: str, **kwargs: Any) -> Response:
        try:
            app, already_running = api.start_app(self.team_id, short_id)
        except api.AppNotFoundError:
            return Response(status=status.HTTP_404_NOT_FOUND)
        except api.NoActiveVersionError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        if already_running:
            return Response(StreamlitAppSerializer(app).data)
        return Response(StreamlitAppSerializer(app).data, status=status.HTTP_202_ACCEPTED)

    @extend_schema(
        summary="Stop the app sandbox",
        request=None,
        responses={200: StreamlitAppSerializer},
    )
    @action(methods=["POST"], detail=True, url_path="stop")
    def stop(self, request: Request, short_id: str, **kwargs: Any) -> Response:
        try:
            app = api.stop_app(self.team_id, short_id)
        except api.AppNotFoundError:
            return Response(status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.exception("streamlit_app_stop_failed", short_id=short_id, error=str(e))
            return Response({"detail": "Failed to stop app."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        return Response(StreamlitAppSerializer(app).data)

    @extend_schema(
        summary="Get iframe connection info for a running app",
        responses={200: StreamlitConnectInfoSerializer},
    )
    @action(methods=["GET"], detail=True, url_path="connect_info", throttle_classes=[ClickHouseBurstRateThrottle])
    def connect_info(self, request: Request, short_id: str, **kwargs: Any) -> Response:
        try:
            connect_info = api.get_connect_info(self.team_id, short_id, cast(User, request.user))
        except api.AppNotFoundError:
            return Response(status=status.HTTP_404_NOT_FOUND)
        except api.AppNotRunningError as e:
            return Response({"detail": str(e)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except api.ConnectUnavailableError as e:
            return Response({"detail": str(e)}, status=status.HTTP_502_BAD_GATEWAY)

        return Response(StreamlitConnectInfoSerializer(connect_info).data)

    @extend_schema(
        summary="Restart the app sandbox",
        request=None,
        responses={202: StreamlitAppSerializer},
    )
    @action(methods=["POST"], detail=True, url_path="restart", throttle_classes=[ClickHouseBurstRateThrottle])
    def restart(self, request: Request, short_id: str, **kwargs: Any) -> Response:
        try:
            app, _transitioning = api.restart_app(self.team_id, short_id)
        except api.AppNotFoundError:
            return Response(status=status.HTTP_404_NOT_FOUND)

        return Response(StreamlitAppSerializer(app).data, status=status.HTTP_202_ACCEPTED)
