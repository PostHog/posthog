from __future__ import annotations

import io
import uuid
import hashlib

from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from django.utils import timezone

import structlog

from posthog.models.activity_logging.activity_log import Detail, changes_between, log_activity
from posthog.models.user import User
from posthog.storage import object_storage

from products.streamlit_apps.backend.facade import contracts
from products.streamlit_apps.backend.logic.app_runtime import (
    AppRuntimeConcurrencyError,
    AppRuntimeError,
    AppRuntimeService,
    sync_sandbox_status,
)
from products.streamlit_apps.backend.logic.bridge import execute_bridge_query
from products.streamlit_apps.backend.logic.oauth import (
    create_streamlit_access_token,
    find_reusable_streamlit_access_token,
    get_streamlit_oauth_app,
)
from products.streamlit_apps.backend.logic.zip_validator import MAX_ZIP_SIZE, validate_zip
from products.streamlit_apps.backend.models import (
    MAX_CPU_CORES,
    MAX_MEMORY_GB,
    MIN_CPU_CORES,
    MIN_MEMORY_GB,
    StreamlitApp,
    StreamlitAppSandbox,
    StreamlitAppVersion,
)
from products.streamlit_apps.backend.tasks import (
    auto_restart_crashed_streamlit_sandboxes,
    cleanup_deleted_streamlit_app_zips,
    cleanup_expired_streamlit_oauth_tokens,
    prune_old_streamlit_app_versions,
    run_streamlit_app_lifecycle,
    stop_idle_streamlit_sandboxes,
)

logger = structlog.get_logger(__name__)

_LAST_ACTIVITY_DEBOUNCE_SECONDS = 30

__all__ = [
    "AppRuntimeConcurrencyError",
    "AppRuntimeError",
    "AppNotFoundError",
    "ZipTooLargeError",
    "InvalidZipError",
    "ConcurrentUploadError",
    "VersionNotFoundError",
    "NoActiveVersionError",
    "AppNotRunningError",
    "ConnectUnavailableError",
    "MAX_ZIP_SIZE",
    "MIN_CPU_CORES",
    "MAX_CPU_CORES",
    "MIN_MEMORY_GB",
    "MAX_MEMORY_GB",
    "check_zip_size",
    "list_apps",
    "get_app",
    "create_app",
    "update_app",
    "delete_app",
    "list_versions",
    "upload_version",
    "activate_version",
    "get_status",
    "start_app",
    "stop_app",
    "restart_app",
    "get_connect_info",
    "execute_bridge_query",
    "get_streamlit_oauth_app",
    "auto_restart_crashed_streamlit_sandboxes",
    "cleanup_deleted_streamlit_app_zips",
    "cleanup_expired_streamlit_oauth_tokens",
    "prune_old_streamlit_app_versions",
    "stop_idle_streamlit_sandboxes",
]


class AppNotFoundError(Exception):
    def __init__(self, short_id: str) -> None:
        self.short_id = short_id
        super().__init__(f"App {short_id!r} not found.")


class ZipTooLargeError(Exception):
    def __init__(self) -> None:
        super().__init__(f"Zip file too large (max {MAX_ZIP_SIZE // (1024 * 1024)} MB).")


class InvalidZipError(Exception):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("Invalid zip file: " + "; ".join(errors))


class ConcurrentUploadError(Exception):
    def __init__(self) -> None:
        super().__init__("Concurrent upload detected. Please try again.")


class VersionNotFoundError(Exception):
    def __init__(self) -> None:
        super().__init__("Version not found.")


class NoActiveVersionError(Exception):
    def __init__(self) -> None:
        super().__init__("No active version. Upload a zip file first.")


class AppNotRunningError(Exception):
    def __init__(self) -> None:
        super().__init__("App is not running.")


class ConnectUnavailableError(Exception):
    def __init__(self) -> None:
        super().__init__("Unable to connect to app.")


# --- Converters (model -> DTO) ---


def _hedgehog_config(user: User) -> dict | None:
    if not user.hedgehog_config:
        return None
    if user.hedgehog_config.get("version") == 2:
        actor_options = user.hedgehog_config.get("actor_options", {})
        return {
            "use_as_profile": user.hedgehog_config.get("use_as_profile"),
            "color": actor_options.get("color"),
            "accessories": actor_options.get("accessories"),
            "skin": actor_options.get("skin"),
        }
    return {
        "use_as_profile": user.hedgehog_config.get("use_as_profile"),
        "color": user.hedgehog_config.get("color"),
        "accessories": user.hedgehog_config.get("accessories"),
        "skin": user.hedgehog_config.get("skin"),
    }


def _to_user_basic(user: User) -> contracts.StreamlitAppUserInfo:
    return contracts.StreamlitAppUserInfo(
        id=user.id,
        uuid=user.uuid,
        distinct_id=user.distinct_id,
        first_name=user.first_name,
        last_name=user.last_name,
        email=user.email,
        is_email_verified=user.is_email_verified,
        hedgehog_config=_hedgehog_config(user),
        role_at_organization=user.role_at_organization,
    )


def _version_to_contract(version: StreamlitAppVersion) -> contracts.AppVersionContract:
    return contracts.AppVersionContract(
        id=version.id,
        version_number=version.version_number,
        zip_hash=version.zip_hash,
        snapshot_id=version.snapshot_id,
        created_by=_to_user_basic(version.created_by) if version.created_by else None,
        created_at=version.created_at,
    )


def _sandbox_to_contract(sandbox: StreamlitAppSandbox) -> contracts.AppSandboxContract:
    return contracts.AppSandboxContract(
        status=sandbox.status,
        restart_count=sandbox.app.restart_count,
        last_error=sandbox.last_error,
        started_at=sandbox.started_at,
        last_activity_at=sandbox.last_activity_at,
        version_number=sandbox.version.version_number if sandbox.version else None,
    )


def _get_sandbox_or_none(app: StreamlitApp) -> StreamlitAppSandbox | None:
    try:
        return app.sandbox
    except StreamlitAppSandbox.DoesNotExist:
        return None


def _app_to_contract(app: StreamlitApp) -> contracts.AppContract:
    sandbox = _get_sandbox_or_none(app)
    return contracts.AppContract(
        id=app.id,
        short_id=app.short_id,
        name=app.name,
        description=app.description,
        cpu_cores=app.cpu_cores,
        memory_gb=app.memory_gb,
        status=sandbox.status if sandbox is not None else "stopped",
        active_version=_version_to_contract(app.active_version) if app.active_version else None,
        sandbox=_sandbox_to_contract(sandbox) if sandbox is not None else None,
        created_by=_to_user_basic(app.created_by) if app.created_by else None,
        created_at=app.created_at,
        updated_at=app.updated_at,
    )


# --- Query helpers ---


def _app_queryset(team_id: int) -> QuerySet[StreamlitApp]:
    return (
        StreamlitApp.objects.for_team(team_id)
        .filter(deleted=False)
        .select_related("created_by", "active_version", "active_version__created_by", "sandbox", "sandbox__version")
    )


def _get_app(team_id: int, short_id: str) -> StreamlitApp:
    try:
        return _app_queryset(team_id).get(short_id=short_id)
    except StreamlitApp.DoesNotExist:
        raise AppNotFoundError(short_id) from None


def _get_sandbox_and_stop_if_live(app: StreamlitApp) -> None:
    """Stop a running/starting sandbox so the next viewer request boots the
    newly-activated version. Best-effort: failures are logged but don't fail
    the version change."""
    sandbox = _get_sandbox_or_none(app)
    if sandbox is None:
        return
    if sandbox.status not in (StreamlitAppSandbox.Status.RUNNING, StreamlitAppSandbox.Status.STARTING):
        return
    try:
        AppRuntimeService().stop_app(app)
    except Exception:
        logger.warning("streamlit_app_stop_on_version_change_failed", app_id=str(app.id), exc_info=True)


def _validate_resource_bounds(cpu_cores: float | None, memory_gb: float | None) -> None:
    if cpu_cores is not None and (cpu_cores < MIN_CPU_CORES or cpu_cores > MAX_CPU_CORES):
        raise ValueError(f"CPU cores must be between {MIN_CPU_CORES} and {MAX_CPU_CORES}.")
    if memory_gb is not None and (memory_gb < MIN_MEMORY_GB or memory_gb > MAX_MEMORY_GB):
        raise ValueError(f"Memory must be between {MIN_MEMORY_GB} and {MAX_MEMORY_GB} GB.")


def check_zip_size(declared_size: int | None) -> None:
    """Reject an oversized upload by its declared size. Exposed so callers can check
    before reading the body into memory (`upload_version` also checks it after read)."""
    if declared_size is not None and declared_size > MAX_ZIP_SIZE:
        raise ZipTooLargeError()


# --- App API ---


def list_apps(team_id: int) -> list[contracts.AppContract]:
    apps = _app_queryset(team_id).order_by("-updated_at")
    return [_app_to_contract(app) for app in apps]


def get_app(team_id: int, short_id: str) -> contracts.AppContract:
    return _app_to_contract(_get_app(team_id, short_id))


def create_app(
    team_id: int, user: User, data: contracts.CreateAppInput, was_impersonated: bool
) -> contracts.AppContract:
    _validate_resource_bounds(data.cpu_cores, data.memory_gb)

    app = StreamlitApp.objects.for_team(team_id).create(
        team_id=team_id,
        created_by=user,
        name=data.name,
        description=data.description,
        cpu_cores=data.cpu_cores,
        memory_gb=data.memory_gb,
    )

    log_activity(
        organization_id=user.current_organization_id,
        team_id=team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=str(app.id),
        scope="StreamlitApp",
        activity="created",
        detail=Detail(name=app.name),
    )

    return _app_to_contract(app)


def update_app(
    team_id: int, short_id: str, user: User, data: contracts.UpdateAppInput, was_impersonated: bool
) -> contracts.AppContract:
    app = _get_app(team_id, short_id)
    before_update = StreamlitApp.objects.for_team(team_id).get(pk=app.pk)

    _validate_resource_bounds(data.cpu_cores, data.memory_gb)

    if data.name is not None:
        app.name = data.name
    if data.description is not None:
        app.description = data.description
    if data.cpu_cores is not None:
        app.cpu_cores = data.cpu_cores
    if data.memory_gb is not None:
        app.memory_gb = data.memory_gb
    app.save()

    changes = changes_between("StreamlitApp", previous=before_update, current=app)
    if changes:
        log_activity(
            organization_id=user.current_organization_id,
            team_id=team_id,
            user=user,
            was_impersonated=was_impersonated,
            item_id=str(app.id),
            scope="StreamlitApp",
            activity="updated",
            detail=Detail(changes=changes, name=app.name),
        )

    return _app_to_contract(app)


def delete_app(team_id: int, short_id: str, user: User, was_impersonated: bool) -> None:
    app = _get_app(team_id, short_id)

    try:
        AppRuntimeService().stop_app(app)
    except Exception:
        logger.warning("streamlit_app_stop_on_delete_failed", app_id=str(app.id))

    app.deleted = True
    app.deleted_at = timezone.now()
    app.save(update_fields=["deleted", "deleted_at", "updated_at"])

    log_activity(
        organization_id=user.current_organization_id,
        team_id=team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=str(app.id),
        scope="StreamlitApp",
        activity="deleted",
        detail=Detail(name=app.name),
    )


# --- Version API ---


def list_versions(team_id: int, short_id: str) -> list[contracts.AppVersionContract]:
    app = _get_app(team_id, short_id)
    versions = app.versions.select_related("created_by").order_by("-version_number")[:50]
    return [_version_to_contract(v) for v in versions]


def upload_version(
    team_id: int,
    short_id: str,
    user: User,
    file_content: bytes,
    declared_size: int | None,
    was_impersonated: bool,
) -> contracts.AppVersionContract:
    app = _get_app(team_id, short_id)

    check_zip_size(declared_size)

    validation = validate_zip(io.BytesIO(file_content))
    if not validation.valid:
        raise InvalidZipError(validation.errors)

    zip_hash = hashlib.sha256(file_content).hexdigest()

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
                created_by=user,
            )

            app.active_version = version
            app.save(update_fields=["active_version", "updated_at"])
    except IntegrityError:
        _cleanup_orphan()
        raise ConcurrentUploadError() from None
    except Exception:
        _cleanup_orphan()
        raise

    _get_sandbox_and_stop_if_live(app)

    log_activity(
        organization_id=user.current_organization_id,
        team_id=team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=str(app.id),
        scope="StreamlitApp",
        activity="uploaded_version",
        detail=Detail(name=f"{app.name} v{next_version_number}"),
    )

    return _version_to_contract(version)


def activate_version(
    team_id: int, short_id: str, user: User, version_number: int, was_impersonated: bool
) -> contracts.AppVersionContract:
    app = _get_app(team_id, short_id)
    try:
        version = app.versions.get(version_number=version_number)
    except StreamlitAppVersion.DoesNotExist:
        raise VersionNotFoundError() from None

    app.active_version = version
    app.save(update_fields=["active_version", "updated_at"])

    _get_sandbox_and_stop_if_live(app)

    log_activity(
        organization_id=user.current_organization_id,
        team_id=team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=str(app.id),
        scope="StreamlitApp",
        activity="activated_version",
        detail=Detail(name=f"{app.name} v{version_number}"),
    )

    return _version_to_contract(version)


# --- Sandbox lifecycle API ---


def get_status(team_id: int, short_id: str) -> contracts.AppSandboxContract:
    app = _get_app(team_id, short_id)
    sandbox = _get_sandbox_or_none(app)
    if sandbox is None:
        return contracts.AppSandboxContract(
            status="stopped",
            restart_count=app.restart_count,
            last_error="",
            started_at=None,
            last_activity_at=None,
            version_number=None,
        )
    sandbox = sync_sandbox_status(sandbox)
    return _sandbox_to_contract(sandbox)


def start_app(team_id: int, short_id: str) -> tuple[contracts.AppContract, bool]:
    """Returns (app, already_running). Dispatches the async lifecycle task unless
    the sandbox is already running or starting."""
    app = _get_app(team_id, short_id)
    if not app.active_version:
        raise NoActiveVersionError()

    sandbox = _get_sandbox_or_none(app)
    already_running = sandbox is not None and sandbox.status in (
        StreamlitAppSandbox.Status.RUNNING,
        StreamlitAppSandbox.Status.STARTING,
    )
    if not already_running:
        run_streamlit_app_lifecycle.delay(str(app.id), "start", team_id=app.team_id)

    return _app_to_contract(app), already_running


def stop_app(team_id: int, short_id: str) -> contracts.AppContract:
    app = _get_app(team_id, short_id)
    AppRuntimeService().stop_app(app)
    return _app_to_contract(app)


def restart_app(team_id: int, short_id: str) -> tuple[contracts.AppContract, bool]:
    """Returns (app, transitioning). Dispatches the async lifecycle task unless
    the sandbox is already starting or stopping."""
    app = _get_app(team_id, short_id)
    sandbox = _get_sandbox_or_none(app)
    transitioning = sandbox is not None and sandbox.status in (
        StreamlitAppSandbox.Status.STARTING,
        StreamlitAppSandbox.Status.STOPPING,
    )
    if not transitioning:
        run_streamlit_app_lifecycle.delay(str(app.id), "restart", team_id=app.team_id)

    return _app_to_contract(app), transitioning


def get_connect_info(team_id: int, short_id: str, user: User) -> contracts.StreamlitConnectInfo:
    app = _get_app(team_id, short_id)
    sandbox = _get_sandbox_or_none(app)
    if sandbox is None or sandbox.status != StreamlitAppSandbox.Status.RUNNING:
        raise AppNotRunningError()

    runtime = AppRuntimeService()
    connect_data = runtime.get_connect_url(app, user_id=user.id, team_id=team_id)
    if not connect_data:
        raise ConnectUnavailableError()

    now = timezone.now()
    if (
        sandbox.last_activity_at is None
        or (now - sandbox.last_activity_at).total_seconds() > _LAST_ACTIVITY_DEBOUNCE_SECONDS
    ):
        sandbox.last_activity_at = now
        sandbox.save(update_fields=["last_activity_at"])

    access_token = find_reusable_streamlit_access_token(user=user, team_id=team_id)
    if access_token is None:
        access_token = create_streamlit_access_token(user=user, team_id=team_id)

    sandbox_url = connect_data["url"].rstrip("/")
    # Docker sandboxes have no Modal connect token; only Modal tunnels need it.
    modal_token = connect_data["token"]
    iframe_url = f"{sandbox_url}/?_posthog_token={access_token.token}"
    if modal_token:
        iframe_url += f"&_modal_connect_token={modal_token}&_posthog_modal_token={modal_token}"

    expires_in = max(0, int((access_token.expires - timezone.now()).total_seconds()))

    return contracts.StreamlitConnectInfo(iframe_url=iframe_url, expires_in=expires_in)
