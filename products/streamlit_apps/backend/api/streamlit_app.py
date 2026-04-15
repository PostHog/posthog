import io
import uuid
import hashlib
from typing import Any

from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from django.utils import timezone

import structlog
import posthoganalytics
from loginas.utils import is_impersonated_session
from rest_framework import serializers, status, viewsets
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import action
from posthog.models.activity_logging.activity_log import Detail, changes_between, log_activity
from posthog.rate_limit import ClickHouseBurstRateThrottle

from products.streamlit_apps.backend.models import StreamlitApp, StreamlitAppSandbox, StreamlitAppVersion
from products.streamlit_apps.backend.services.app_runtime import AppRuntimeService
from products.streamlit_apps.backend.services.zip_validator import validate_zip

logger = structlog.get_logger(__name__)

# Amortize concurrent pollers for the same sandbox to one Modal call per window.
# Token-refresh fires every ~2s, so this keeps sync calls to 1/window/sandbox.
_STATUS_CACHE_TTL_SECONDS = 2

# Debounce last_activity_at writes. connect_info polls every ~2s per viewer and
# the cleanup consumer only needs minute-granularity, so a UPDATE on every hit
# was pure write amplification.
_LAST_ACTIVITY_DEBOUNCE_SECONDS = 30


class StreamlitAppVersionSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = StreamlitAppVersion
        fields = [
            "id",
            "version_number",
            "zip_file",
            "zip_hash",
            "snapshot_id",
            "created_by",
            "created_at",
        ]
        read_only_fields = fields


class StreamlitAppSandboxSerializer(serializers.ModelSerializer):
    restart_count = serializers.SerializerMethodField()
    version_number = serializers.SerializerMethodField()

    class Meta:
        model = StreamlitAppSandbox
        fields = [
            "status",
            "restart_count",
            "last_error",
            "started_at",
            "last_activity_at",
            "version_number",
        ]
        read_only_fields = fields

    def get_restart_count(self, obj: StreamlitAppSandbox) -> int:
        return obj.app.restart_count

    def get_version_number(self, obj: StreamlitAppSandbox) -> int | None:
        # Compared with active_version.version_number to prompt "restart needed".
        return obj.version.version_number if obj.version else None


class StreamlitAppMinimalSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    status = serializers.SerializerMethodField()

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
            "created_by",
            "created_at",
            "updated_at",
        ]

    def validate_cpu_cores(self, value: float) -> float:
        if value < 0.25 or value > 8:
            raise serializers.ValidationError("CPU cores must be between 0.25 and 8.")
        return value

    def validate_memory_gb(self, value: float) -> float:
        if value < 0.5 or value > 16:
            raise serializers.ValidationError("Memory must be between 0.5 and 16 GB.")
        return value

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


class StreamlitAppsAccessPermission(BasePermission):
    """Gate the streamlit_apps API behind the `streamlit-apps` feature flag."""

    message = "Streamlit apps is not available."

    def has_permission(self, request, view) -> bool:
        user = request.user
        if not user or not user.is_authenticated:
            return False
        org_id = str(view.organization.id)
        return bool(
            posthoganalytics.feature_enabled(
                "streamlit-apps",
                user.distinct_id,
                groups={"organization": org_id},
                group_properties={"organization": {"id": org_id}},
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )


class StreamlitAppViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "streamlit_app"
    permission_classes = [StreamlitAppsAccessPermission]
    queryset = StreamlitApp.objects.all()
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
        # Cap at 50 to keep the activity tab bounded.
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

        # Write to storage BEFORE the DB transaction so we never commit a
        # record pointing to a missing object. Path is keyed by UUID so it
        # can be computed before we hold the row lock.
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

        # Frontend banner uses requires_restart to prompt; we don't auto-restart.
        return Response(
            {
                "active_version": StreamlitAppVersionSerializer(version).data,
                "requires_restart": True,
            }
        )

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

        from products.streamlit_apps.backend.services.app_runtime import _sync_sandbox_status

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

        run_streamlit_app_lifecycle.delay(str(app.id), "start")

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
        """Return an iframe URL with OAuth + Modal connect tokens baked in.

        The frontend uses this URL directly as the iframe src — no Django proxy needed.
        The auth proxy inside the sandbox validates the OAuth token via introspection.
        """
        app = self.get_object()
        sandbox_record = StreamlitAppSandbox.objects.filter(app=app).first()
        if not sandbox_record or sandbox_record.status != StreamlitAppSandbox.Status.RUNNING:
            return Response({"detail": "App is not running."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        runtime = AppRuntimeService()
        connect_data = runtime.get_connect_url(app, user_id=request.user.id, team_id=self.team_id)
        if not connect_data:
            return Response({"detail": "Unable to connect to app."}, status=status.HTTP_502_BAD_GATEWAY)

        # Debounced to _LAST_ACTIVITY_DEBOUNCE_SECONDS — see constant comment.
        now = timezone.now()
        if (
            sandbox_record.last_activity_at is None
            or (now - sandbox_record.last_activity_at).total_seconds() > _LAST_ACTIVITY_DEBOUNCE_SECONDS
        ):
            sandbox_record.last_activity_at = now
            sandbox_record.save(update_fields=["last_activity_at"])

        from products.streamlit_apps.backend.services.oauth import (
            create_streamlit_access_token,
            find_reusable_streamlit_access_token,
        )

        # Reuse non-near-expiry tokens to avoid bloating the OAuth table.
        access_token = find_reusable_streamlit_access_token(user=request.user, team_id=self.team_id)
        if access_token is None:
            access_token = create_streamlit_access_token(user=request.user, team_id=self.team_id)

        modal_url = connect_data["url"].rstrip("/")
        modal_token = connect_data["token"]
        # _modal_connect_token: consumed by Modal's router (stripped before proxy).
        # _posthog_modal_token: forwarded to the proxy, which re-injects it into
        # HTML so browser sub-requests carry the modal token automatically.
        iframe_url = (
            f"{modal_url}/?_posthog_token={access_token.token}"
            f"&_modal_connect_token={modal_token}"
            f"&_posthog_modal_token={modal_token}"
        )

        # Report REAL remaining lifetime so the refresh scheduler stays accurate.
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

        # Idempotent 202 if a transition is already in flight — avoids a
        # second task whose runtime would raise AppRuntimeConcurrencyError.
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

        run_streamlit_app_lifecycle.delay(str(app.id), "restart")

        return Response(
            StreamlitAppSerializer(app, context=self.get_serializer_context()).data,
            status=status.HTTP_202_ACCEPTED,
        )
