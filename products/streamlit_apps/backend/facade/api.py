from __future__ import annotations

from typing import TYPE_CHECKING

from django.db.models import QuerySet

if TYPE_CHECKING:
    from posthog.models.user import User

from products.streamlit_apps.backend.facade.contracts import (
    AppContract,
    AppSandboxContract,
    AppVersionContract,
    ConnectInfoContract,
)
from products.streamlit_apps.backend.logic.app_runtime import (
    AppRuntimeConcurrencyError,
    AppRuntimeError,
    AppRuntimeService,
)
from products.streamlit_apps.backend.logic.oauth import (
    create_sandbox_bridge_token,
    create_streamlit_access_token,
    find_reusable_streamlit_access_token,
)
from products.streamlit_apps.backend.logic.zip_validator import validate_zip
from products.streamlit_apps.backend.models import StreamlitApp, StreamlitAppSandbox, StreamlitAppVersion

__all__ = [
    "AppRuntimeConcurrencyError",
    "AppRuntimeError",
    "create_sandbox_bridge_token",
    "validate_zip",
    "list_apps",
    "get_app",
    "get_app_status",
    "get_connect_info",
]


def _version_to_contract(version: StreamlitAppVersion) -> AppVersionContract:
    return AppVersionContract(
        id=version.id,
        version_number=version.version_number,
        zip_file=version.zip_file,
        zip_hash=version.zip_hash,
        snapshot_id=version.snapshot_id,
        created_by_id=version.created_by_id,
        created_at=version.created_at,
    )


def _sandbox_to_contract(sandbox: StreamlitAppSandbox) -> AppSandboxContract:
    return AppSandboxContract(
        status=sandbox.status,
        restart_count=sandbox.app.restart_count,
        last_error=sandbox.last_error,
        started_at=sandbox.started_at,
        last_activity_at=sandbox.last_activity_at,
        version_number=sandbox.version.version_number if sandbox.version else None,
    )


def _app_to_contract(app: StreamlitApp) -> AppContract:
    try:
        sandbox = _sandbox_to_contract(app.sandbox)
    except StreamlitAppSandbox.DoesNotExist:
        sandbox = None

    return AppContract(
        id=app.id,
        short_id=app.short_id,
        name=app.name,
        description=app.description,
        cpu_cores=app.cpu_cores,
        memory_gb=app.memory_gb,
        is_active=not app.deleted,
        active_version=_version_to_contract(app.active_version) if app.active_version else None,
        sandbox=sandbox,
        created_by_id=app.created_by_id,
        created_at=app.created_at,
        updated_at=app.updated_at,
    )


def list_apps(team_id: int) -> QuerySet[StreamlitApp]:
    return StreamlitApp.objects.filter(team_id=team_id, deleted=False)


def get_app(team_id: int, short_id: str) -> StreamlitApp:
    return StreamlitApp.objects.get(team_id=team_id, short_id=short_id, deleted=False)


def get_app_status(app: StreamlitApp) -> AppSandboxContract | None:
    runtime = AppRuntimeService()
    runtime._sync_sandbox_status(app)
    try:
        app.sandbox.refresh_from_db()
        return _sandbox_to_contract(app.sandbox)
    except StreamlitAppSandbox.DoesNotExist:
        return None


def get_connect_info(app: StreamlitApp, user: User, team_id: int) -> ConnectInfoContract:
    token_obj = find_reusable_streamlit_access_token(user, team_id)
    if token_obj is None:
        token_obj = create_streamlit_access_token(user, team_id)

    runtime = AppRuntimeService()
    connect = runtime.get_connect_url(app, user_id=user.id, team_id=team_id)

    return ConnectInfoContract(
        url=connect["url"],
        token=token_obj.token,
        expires_at=token_obj.expires,
    )
