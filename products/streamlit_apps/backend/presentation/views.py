import io
import uuid
import hashlib
from typing import Any

from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from django.utils import timezone

import structlog
from loginas.utils import is_impersonated_session
from rest_framework import status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.models.activity_logging.activity_log import Detail, log_activity
from posthog.rate_limit import ClickHouseBurstRateThrottle

from products.streamlit_apps.backend.logic.app_runtime import AppRuntimeService
from products.streamlit_apps.backend.logic.zip_validator import validate_zip
from products.streamlit_apps.backend.models import StreamlitApp, StreamlitAppSandbox, StreamlitAppVersion
from products.streamlit_apps.backend.presentation.serializers import (
    StreamlitAppMinimalSerializer,
    StreamlitAppsAccessPermission,
    StreamlitAppSandboxSerializer,
    StreamlitAppSerializer,
    StreamlitAppVersionSerializer,
)

logger = structlog.get_logger(__name__)

_STATUS_CACHE_TTL_SECONDS = 2
_LAST_ACTIVITY_DEBOUNCE_SECONDS = 30


class StreamlitAppViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "streamlit_app"
    permission_classes = [StreamlitAppsAccessPermission]
    # all_teams: the fail-closed `objects` manager raises at import time (no team
    # context yet); TeamAndOrgViewSetMixin filters this queryset by team per request.
    queryset = StreamlitApp.all_teams.all()
    lookup_field = "short_id"

    def get_serializer_class(self) -> type[BaseSerializer]:
        return StreamlitAppMinimalSerializer if self.action == "list" else StreamlitAppSerializer

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        queryset = queryset.filter(deleted=False)
        queryset = queryset.select_related("created_by", "active_version", "sandbox")

        if self.action == "list":
            queryset = queryset.order_by("-updated_at")

        return queryset

    @staticmethod
    def _get_sandbox_or_none(app: StreamlitApp) -> StreamlitAppSandbox | None:
        try:
            return app.sandbox
        except StreamlitAppSandbox.DoesNotExist:
            return None

    @classmethod
    def _stop_active_sandbox_after_version_change(cls, app: StreamlitApp) -> None:
        """Stop a running/starting sandbox so the next viewer request boots the
        newly-activated version. Best-effort: failures are logged but don't fail
        the version change."""
        sandbox = cls._get_sandbox_or_none(app)
        if sandbox is None:
            return
        if sandbox.status not in (StreamlitAppSandbox.Status.RUNNING, StreamlitAppSandbox.Status.STARTING):
            return
        try:
            AppRuntimeService().stop_app(app)
        except Exception:
            logger.warning("streamlit_app_stop_on_version_change_failed", app_id=str(app.id), exc_info=True)

    def perform_destroy(self, instance: StreamlitApp) -> None:
        try:
            runtime = AppRuntimeService()
            runtime.stop_app(instance)
        except Exception:
            logger.warning("streamlit_app_stop_on_delete_failed", app_id=str(instance.id))

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

    @action(methods=["GET"], detail=True, url_path="versions")
    def versions(self, request: Request, **kwargs: Any) -> Response:
        app = self.get_object()
        versions = app.versions.select_related("created_by").order_by("-version_number")[:50]
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
                {"detail": "Invalid zip file: " + "; ".join(validation.errors)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        zip_hash = hashlib.sha256(file_content).hexdigest()

        from posthog.storage import object_storage

        version_id = uuid.uuid4()
        zip_path = f"streamlit_apps/{app.team_id}/{app.id}/{version_id}.zip"
        object_storage.write(zip_path, file_content)

        def _cleanup_orphan() -> None:
            try:
                object_storage.delete(zip_path)
            except Exception:
                logger.warning("streamlit_upload_orphan_cleanup_failed", zip_path=zip_path, exc_info=True)

        try:
            with transaction.atomic():
                latest_version = app.versions.select_for_update().order_by("-version_number").first()
                next_version_number = (latest_version.version_number + 1) if latest_version else 1

                version = StreamlitAppVersion.objects.create(
                    id=version_id,
                    app=app,
                    version_number=next_version_number,
                    zip_file=zip_path,
                    zip_hash=zip_hash,
                    created_by=request.user,
                )

                app.active_version = version
                app.save(update_fields=["active_version", "updated_at"])
        except IntegrityError:
            _cleanup_orphan()
            return Response(
                {"detail": "Concurrent upload detected. Please try again."},
                status=status.HTTP_409_CONFLICT,
            )
        except Exception:
            _cleanup_orphan()
            raise

        self._stop_active_sandbox_after_version_change(app)

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

        self._stop_active_sandbox_after_version_change(app)

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

        return Response({"active_version": StreamlitAppVersionSerializer(version).data})

    @action(methods=["GET"], detail=True, url_path="status")
    def get_status(self, request: Request, **kwargs: Any) -> Response:
        app = self.get_object()
        sandbox = self._get_sandbox_or_none(app)
        if sandbox is None:
            return Response(
                {
                    "status": "stopped",
                    "restart_count": app.restart_count,
                    "last_error": "",
                    "started_at": None,
                    "last_activity_at": None,
                }
            )

        from products.streamlit_apps.backend.logic.app_runtime import _sync_sandbox_status

        cache_key = f"streamlit_sandbox_status:{sandbox.id}"
        cached = cache.get(cache_key)
        if cached is None:
            sandbox = _sync_sandbox_status(sandbox)
            payload = StreamlitAppSandboxSerializer(sandbox).data
            cache.set(cache_key, payload, _STATUS_CACHE_TTL_SECONDS)
            return Response(payload)
        return Response(cached)

    @action(methods=["POST"], detail=True, url_path="start", throttle_classes=[ClickHouseBurstRateThrottle])
    def start(self, request: Request, **kwargs: Any) -> Response:
        app = self.get_object()
        if not app.active_version:
            return Response(
                {"detail": "No active version. Upload a zip file first."}, status=status.HTTP_400_BAD_REQUEST
            )

        sandbox = self._get_sandbox_or_none(app)
        if sandbox and sandbox.status in (
            StreamlitAppSandbox.Status.RUNNING,
            StreamlitAppSandbox.Status.STARTING,
        ):
            return Response(StreamlitAppSerializer(app, context=self.get_serializer_context()).data)

        from products.streamlit_apps.backend.tasks import run_streamlit_app_lifecycle

        run_streamlit_app_lifecycle.delay(str(app.id), "start", team_id=app.team_id)

        return Response(
            StreamlitAppSerializer(app, context=self.get_serializer_context()).data,
            status=status.HTTP_202_ACCEPTED,
        )

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

    @action(methods=["GET"], detail=True, url_path="connect_info", throttle_classes=[ClickHouseBurstRateThrottle])
    def connect_info(self, request: Request, **kwargs: Any) -> Response:
        app = self.get_object()
        sandbox_record = StreamlitAppSandbox.objects.filter(app=app).first()
        if not sandbox_record or sandbox_record.status != StreamlitAppSandbox.Status.RUNNING:
            return Response({"detail": "App is not running."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        runtime = AppRuntimeService()
        connect_data = runtime.get_connect_url(app, user_id=request.user.id, team_id=self.team_id)
        if not connect_data:
            return Response({"detail": "Unable to connect to app."}, status=status.HTTP_502_BAD_GATEWAY)

        now = timezone.now()
        if (
            sandbox_record.last_activity_at is None
            or (now - sandbox_record.last_activity_at).total_seconds() > _LAST_ACTIVITY_DEBOUNCE_SECONDS
        ):
            sandbox_record.last_activity_at = now
            sandbox_record.save(update_fields=["last_activity_at"])

        from products.streamlit_apps.backend.logic.oauth import (
            create_streamlit_access_token,
            find_reusable_streamlit_access_token,
        )

        access_token = find_reusable_streamlit_access_token(user=request.user, team_id=self.team_id)
        if access_token is None:
            access_token = create_streamlit_access_token(user=request.user, team_id=self.team_id)

        sandbox_url = connect_data["url"].rstrip("/")
        # Docker sandboxes have no Modal connect token; only Modal tunnels need it.
        modal_token = connect_data["token"]
        iframe_url = f"{sandbox_url}/?_posthog_token={access_token.token}"
        if modal_token:
            iframe_url += f"&_modal_connect_token={modal_token}&_posthog_modal_token={modal_token}"

        expires_in = max(0, int((access_token.expires - timezone.now()).total_seconds()))

        return Response(
            {
                "iframe_url": iframe_url,
                "expires_in": expires_in,
            }
        )

    @action(methods=["POST"], detail=True, url_path="restart", throttle_classes=[ClickHouseBurstRateThrottle])
    def restart(self, request: Request, **kwargs: Any) -> Response:
        app = self.get_object()

        sandbox = self._get_sandbox_or_none(app)
        if sandbox and sandbox.status in (
            StreamlitAppSandbox.Status.STARTING,
            StreamlitAppSandbox.Status.STOPPING,
        ):
            return Response(
                StreamlitAppSerializer(app, context=self.get_serializer_context()).data,
                status=status.HTTP_202_ACCEPTED,
            )

        from products.streamlit_apps.backend.tasks import run_streamlit_app_lifecycle

        run_streamlit_app_lifecycle.delay(str(app.id), "restart", team_id=app.team_id)

        return Response(
            StreamlitAppSerializer(app, context=self.get_serializer_context()).data,
            status=status.HTTP_202_ACCEPTED,
        )
