import io
import uuid
import hashlib
from typing import Any

from django.db.models import QuerySet
from django.utils import timezone

import structlog
from loginas.utils import is_impersonated_session
from rest_framework import serializers, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import action
from posthog.models.activity_logging.activity_log import Detail, changes_between, log_activity

from products.streamlit_apps.backend.models import StreamlitApp, StreamlitAppSandbox, StreamlitAppVersion
from products.streamlit_apps.backend.services.app_runtime import AppRuntimeService
from products.streamlit_apps.backend.services.zip_validator import validate_zip

logger = structlog.get_logger(__name__)


# -- Serializers --


class StreamlitAppVersionSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = StreamlitAppVersion
        fields = [
            "id",
            "version_number",
            "zip_file",
            "zip_hash",
            "has_requirements",
            "packages",
            "snapshot_id",
            "created_by",
            "created_at",
        ]
        read_only_fields = fields


class StreamlitAppSandboxSerializer(serializers.ModelSerializer):
    class Meta:
        model = StreamlitAppSandbox
        fields = [
            "status",
            "restart_count",
            "last_error",
            "started_at",
            "last_activity_at",
            "current_viewers",
            "max_viewers",
        ]
        read_only_fields = fields


class StreamlitAppMinimalSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    status = serializers.SerializerMethodField()
    current_viewers = serializers.SerializerMethodField()

    class Meta:
        model = StreamlitApp
        fields = [
            "id",
            "short_id",
            "name",
            "description",
            "cpu_cores",
            "memory_gb",
            "status",
            "current_viewers",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_status(self, obj: StreamlitApp) -> str:
        try:
            return obj.sandbox.status
        except StreamlitAppSandbox.DoesNotExist:
            return "stopped"

    def get_current_viewers(self, obj: StreamlitApp) -> int:
        try:
            return obj.sandbox.current_viewers
        except StreamlitAppSandbox.DoesNotExist:
            return 0


class StreamlitAppSerializer(StreamlitAppMinimalSerializer):
    active_version = StreamlitAppVersionSerializer(read_only=True)
    sandbox = StreamlitAppSandboxSerializer(read_only=True)

    class Meta:
        model = StreamlitApp
        fields = [
            "id",
            "short_id",
            "name",
            "description",
            "cpu_cores",
            "memory_gb",
            "active_version",
            "sandbox",
            "status",
            "current_viewers",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "short_id",
            "active_version",
            "sandbox",
            "status",
            "current_viewers",
            "created_by",
            "created_at",
            "updated_at",
        ]

    def create(self, validated_data: dict, *args: Any, **kwargs: Any) -> StreamlitApp:
        request = self.context["request"]
        team = self.context["get_team"]()

        app = StreamlitApp.objects.create(
            team=team,
            created_by=request.user,
            **validated_data,
        )

        log_activity(
            organization_id=request.user.current_organization_id,
            team_id=team.id,
            user=request.user,
            was_impersonated=is_impersonated_session(request),
            item_id=str(app.id),
            scope="StreamlitApp",
            activity="created",
            detail=Detail(name=app.name),
        )

        return app

    def update(self, instance: StreamlitApp, validated_data: dict, **kwargs: Any) -> StreamlitApp:
        before_update = StreamlitApp.objects.get(pk=instance.pk)
        updated_app = super().update(instance, validated_data)

        changes = changes_between("StreamlitApp", previous=before_update, current=updated_app)
        if changes:
            request = self.context["request"]
            log_activity(
                organization_id=request.user.current_organization_id,
                team_id=self.context["team_id"],
                user=request.user,
                was_impersonated=is_impersonated_session(request),
                item_id=str(instance.id),
                scope="StreamlitApp",
                activity="updated",
                detail=Detail(changes=changes, name=updated_app.name),
            )

        return updated_app


# -- ViewSet --


class StreamlitAppViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "streamlit_app"
    queryset = StreamlitApp.objects.all()
    lookup_field = "short_id"

    def get_serializer_class(self) -> type[BaseSerializer]:
        return StreamlitAppMinimalSerializer if self.action == "list" else StreamlitAppSerializer

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        queryset = queryset.filter(deleted=False)
        queryset = queryset.select_related("created_by", "active_version")

        if self.action == "list":
            queryset = queryset.order_by("-updated_at")

        return queryset

    def perform_destroy(self, instance: StreamlitApp) -> None:
        instance.deleted = True
        instance.deleted_at = timezone.now()
        instance.save(update_fields=["deleted", "deleted_at", "updated_at"])

        request = self.request
        log_activity(
            organization_id=request.user.current_organization_id,
            team_id=self.team_id,
            user=request.user,
            was_impersonated=is_impersonated_session(request),
            item_id=str(instance.id),
            scope="StreamlitApp",
            activity="deleted",
            detail=Detail(name=instance.name),
        )

    # -- Version management --

    @action(methods=["GET"], detail=True, url_path="versions")
    def versions(self, request: Request, **kwargs: Any) -> Response:
        app = self.get_object()
        versions = app.versions.order_by("-version_number")
        serializer = StreamlitAppVersionSerializer(versions, many=True)
        return Response({"results": serializer.data})

    @action(methods=["POST"], detail=True, url_path="upload_version")
    def upload_version(self, request: Request, **kwargs: Any) -> Response:
        app = self.get_object()
        zip_file = request.FILES.get("file")

        if not zip_file:
            return Response({"detail": "No file provided."}, status=status.HTTP_400_BAD_REQUEST)

        file_content = zip_file.read()
        validation = validate_zip(io.BytesIO(file_content))
        if not validation.valid:
            return Response(
                {"detail": "Invalid zip file.", "errors": validation.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        zip_hash = hashlib.sha256(file_content).hexdigest()

        latest_version = app.versions.order_by("-version_number").first()
        next_version_number = (latest_version.version_number + 1) if latest_version else 1

        # Store the zip file path (in production this would be S3)
        zip_path = f"streamlit_apps/{app.team_id}/{app.id}/v{next_version_number}.zip"

        version = StreamlitAppVersion.objects.create(
            id=uuid.uuid4(),
            app=app,
            version_number=next_version_number,
            zip_file=zip_path,
            zip_hash=zip_hash,
            has_requirements=validation.has_requirements,
            packages=validation.packages,
            created_by=request.user,
        )

        app.active_version = version
        app.save(update_fields=["active_version", "updated_at"])

        log_activity(
            organization_id=request.user.current_organization_id,
            team_id=self.team_id,
            user=request.user,
            was_impersonated=is_impersonated_session(request),
            item_id=str(app.id),
            scope="StreamlitApp",
            activity="uploaded_version",
            detail=Detail(name=f"{app.name} v{next_version_number}"),
        )

        serializer = StreamlitAppVersionSerializer(version)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(methods=["POST"], detail=True, url_path="activate_version")
    def activate_version(self, request: Request, **kwargs: Any) -> Response:
        app = self.get_object()
        version_number = request.data.get("version_number")

        if version_number is None:
            return Response({"detail": "version_number is required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            version = app.versions.get(version_number=version_number)
        except StreamlitAppVersion.DoesNotExist:
            return Response({"detail": "Version not found."}, status=status.HTTP_404_NOT_FOUND)

        app.active_version = version
        app.save(update_fields=["active_version", "updated_at"])

        log_activity(
            organization_id=request.user.current_organization_id,
            team_id=self.team_id,
            user=request.user,
            was_impersonated=is_impersonated_session(request),
            item_id=str(app.id),
            scope="StreamlitApp",
            activity="activated_version",
            detail=Detail(name=f"{app.name} v{version_number}"),
        )

        return Response(StreamlitAppSerializer(app, context=self.get_serializer_context()).data)

    # -- Sandbox control --

    @action(methods=["GET"], detail=True, url_path="status")
    def get_status(self, request: Request, **kwargs: Any) -> Response:
        app = self.get_object()
        try:
            sandbox = app.sandbox
            return Response(StreamlitAppSandboxSerializer(sandbox).data)
        except StreamlitAppSandbox.DoesNotExist:
            return Response(
                {
                    "status": "stopped",
                    "restart_count": 0,
                    "last_error": "",
                    "started_at": None,
                    "last_activity_at": None,
                    "current_viewers": 0,
                    "max_viewers": 20,
                }
            )

    @action(methods=["POST"], detail=True, url_path="start")
    def start(self, request: Request, **kwargs: Any) -> Response:
        app = self.get_object()
        if not app.active_version:
            return Response(
                {"detail": "No active version. Upload a zip file first."}, status=status.HTTP_400_BAD_REQUEST
            )

        try:
            runtime = AppRuntimeService()
            runtime.start_app(app)
        except Exception as e:
            logger.exception("streamlit_app_start_failed", app_id=str(app.id), error=str(e))
            return Response({"detail": "Failed to start app."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        return Response(StreamlitAppSerializer(app, context=self.get_serializer_context()).data)

    @action(methods=["POST"], detail=True, url_path="stop")
    def stop(self, request: Request, **kwargs: Any) -> Response:
        app = self.get_object()

        try:
            runtime = AppRuntimeService()
            runtime.stop_app(app)
        except Exception as e:
            logger.exception("streamlit_app_stop_failed", app_id=str(app.id), error=str(e))
            return Response({"detail": "Failed to stop app."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        return Response(StreamlitAppSerializer(app, context=self.get_serializer_context()).data)

    @action(methods=["POST"], detail=True, url_path="restart")
    def restart(self, request: Request, **kwargs: Any) -> Response:
        app = self.get_object()

        try:
            runtime = AppRuntimeService()
            runtime.restart_app(app)
        except Exception as e:
            logger.exception("streamlit_app_restart_failed", app_id=str(app.id), error=str(e))
            return Response({"detail": "Failed to restart app."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        return Response(StreamlitAppSerializer(app, context=self.get_serializer_context()).data)
