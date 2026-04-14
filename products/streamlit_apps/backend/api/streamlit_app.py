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

# Window during which all `get_status` callers see the same _sync_sandbox_status
# result instead of each one re-hitting Modal. The token-refresh poller fires
# every 2 seconds, so anything below that lets us amortize Modal calls down to
# one-per-window per sandbox.
_STATUS_CACHE_TTL_SECONDS = 2

# Minimum time between last_activity_at writes for a single sandbox.
# connect_info is polled every ~2s by the token-refresh loop; writing on every
# call turned into a sandbox_row UPDATE every 2 seconds per active viewer, for
# no real gain (the field drives inactivity cleanup, which operates on minute
# granularity anyway). The write is now debounced so it only fires once per
# window per sandbox.
_LAST_ACTIVITY_DEBOUNCE_SECONDS = 30


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
        # restart_count lives on the app row now, but we surface it under the
        # sandbox object for frontend continuity.
        return obj.app.restart_count

    def get_version_number(self, obj: StreamlitAppSandbox) -> int | None:
        # Lets the viewer compare against the app's active_version.version_number
        # to decide whether a restart is needed after a version switch.
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


# -- Permissions --


class StreamlitAppsAccessPermission(BasePermission):
    """Gate the whole streamlit_apps API behind the `streamlit-apps` PostHog
    feature flag so unreleased functionality is hidden from any user who is
    not explicitly on the rollout.

    Evaluated against the user's distinct_id with the org as a group so we
    can roll out per-user or per-org as needed. Returns False (→ 403 via
    DRF) rather than raising NotFound: 403 matches the behavior of
    APIScopePermission / TeamMemberAccessPermission on the same viewset,
    and the scene-level NotFound gate on the frontend is what hides
    *existence* from the UI side.
    """

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


# -- ViewSet --


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

    def perform_destroy(self, instance: StreamlitApp) -> None:
        # Stop running sandbox before soft-deleting
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

    # -- Version management --

    @action(methods=["GET"], detail=True, url_path="versions")
    def versions(self, request: Request, **kwargs: Any) -> Response:
        app = self.get_object()
        # Cap the response to the 50 most recent versions — older history is
        # rarely needed and unbounded lists break the activity tab UI.
        # select_related avoids N+1 on created_by → User.
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

        # Write to storage BEFORE opening the DB transaction so we never commit
        # a record pointing to a nonexistent object. We key the storage path by
        # version UUID (not version_number) so it can be computed outside the lock.
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

        # The frontend banner uses requires_restart to prompt the user — we do
        # NOT auto-restart because the user might still be editing other fields.
        return Response(
            {
                "active_version": StreamlitAppVersionSerializer(version).data,
                "requires_restart": True,
            }
        )

    # -- Sandbox control --

    @action(methods=["GET"], detail=True, url_path="status")
    def get_status(self, request: Request, **kwargs: Any) -> Response:
        app = self.get_object()
        try:
            sandbox = app.sandbox
        except StreamlitAppSandbox.DoesNotExist:
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

        # Coalesce concurrent pollers for the same sandbox into a single Modal
        # call per _STATUS_CACHE_TTL_SECONDS window.
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

        # Check if already running or starting
        try:
            sandbox = app.sandbox
            if sandbox.status in (StreamlitAppSandbox.Status.RUNNING, StreamlitAppSandbox.Status.STARTING):
                return Response(StreamlitAppSerializer(app, context=self.get_serializer_context()).data)
        except StreamlitAppSandbox.DoesNotExist:
            pass

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

        # Debounce the activity-tracking UPDATE — the 2-second connect_info
        # poll was turning every active viewer into a constant stream of
        # per-sandbox row writes. Once per _LAST_ACTIVITY_DEBOUNCE_SECONDS is
        # plenty for the minute-granularity cleanup that consumes this field.
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

        # Reuse a non-near-expiry token if one exists for this user/team. Each
        # connect_info call used to mint a fresh token, which (a) bloated the
        # OAuth table and (b) gave attackers a free token-minting oracle if
        # they could call this endpoint without rate-limiting.
        access_token = find_reusable_streamlit_access_token(user=request.user, team_id=self.team_id)
        if access_token is None:
            access_token = create_streamlit_access_token(user=request.user, team_id=self.team_id)

        modal_url = connect_data["url"].rstrip("/")
        modal_token = connect_data["token"]
        # _modal_connect_token: consumed by Modal's routing layer (stripped before reaching proxy)
        # _posthog_modal_token: passed through to auth proxy, which captures it and injects
        #   into HTML so browser sub-requests carry _modal_connect_token automatically
        iframe_url = (
            f"{modal_url}/?_posthog_token={access_token.token}"
            f"&_modal_connect_token={modal_token}"
            f"&_posthog_modal_token={modal_token}"
        )

        # Report the REAL remaining lifetime, not the minting TTL. The frontend
        # uses this to schedule refresh — a stale value causes the iframe to
        # either refresh too late (401 blip) or too early (wasted calls).
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

        # Mirror the start action: if a lifecycle transition is already in
        # flight, return 202 as an idempotent no-op instead of enqueuing a
        # second task whose runtime will raise AppRuntimeConcurrencyError.
        try:
            sandbox = app.sandbox
            if sandbox.status in (
                StreamlitAppSandbox.Status.STARTING,
                StreamlitAppSandbox.Status.STOPPING,
            ):
                return Response(
                    StreamlitAppSerializer(app, context=self.get_serializer_context()).data,
                    status=status.HTTP_202_ACCEPTED,
                )
        except StreamlitAppSandbox.DoesNotExist:
            pass

        from products.streamlit_apps.backend.tasks import run_streamlit_app_lifecycle

        run_streamlit_app_lifecycle.delay(str(app.id), "restart")

        return Response(
            StreamlitAppSerializer(app, context=self.get_serializer_context()).data,
            status=status.HTTP_202_ACCEPTED,
        )
