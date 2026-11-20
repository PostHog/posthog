"""Trino logins of the warehouse for the console.

hogtower is the only store of these logins and their password hashes. PostHog never keeps or logs a
password: a new password goes from hogtower's response to the caller once.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

from posthog.models.team import Team

from products.managed_warehouse.backend.facade.contracts import (
    ControlPlaneRejectedError,
    ControlPlaneUnavailableError,
    ControlPlaneUpstreamError,
    InvalidLoginTeamError,
    LoginKind,
    LoginMode,
    LoginNotFoundError,
    ProtectedLoginError,
    WarehouseLogin,
    WarehouseLoginCredential,
    WarehouseNotFoundError,
)
from products.managed_warehouse.backend.logic.console_upstream import call_control_plane, malformed_body_guard
from products.managed_warehouse.backend.presentation import hogtower

logger = structlog.get_logger(__name__)

ROOT_USERNAME = "root"
ACTIVITY_DAYS = 30
# The only logins the console may change. Any other login is listed read-only.
PROJECT_ACCESS_MODES = frozenset({"project_reader", "project_user"})


def _is_root(username: str) -> bool:
    return username.lower() == ROOT_USERNAME


def _team_names(organization_id: str, users: list[dict[str, Any]]) -> dict[int, str]:
    ids = {int(u["team_id"]) for u in users if u.get("team_id") is not None}
    return dict(Team.objects.filter(pk__in=ids, organization_id=organization_id).values_list("pk", "name"))


def _scope_label(user: dict[str, Any], team_names: dict[int, str]) -> str:
    if _is_root(user["username"]):
        return "Root"
    team_id = user.get("team_id")
    project = team_names.get(int(team_id), f"project {team_id}") if team_id is not None else None
    match user.get("access_mode"):
        case "project_reader":
            return f"Read only · {project}"
        case "project_user":
            return f"Read and write · {project}"
        case _:
            return "Full access"


def _kind(user: dict[str, Any]) -> LoginKind:
    if _is_root(user["username"]):
        return "root"
    match user.get("access_mode"):
        case "project_reader":
            return "project_reader"
        case "project_user":
            return "project_user"
        case _:
            return "other"


def _login(user: dict[str, Any], team_names: dict[int, str], activity: dict[str, Any]) -> WarehouseLogin:
    return WarehouseLogin(
        username=str(user["username"]),
        kind=_kind(user),
        team_id=int(user["team_id"]) if user.get("team_id") is not None else None,
        scope_label=_scope_label(user, team_names),
        disabled=bool(user.get("disabled")),
        created_at=user.get("created_at"),
        updated_at=user.get("updated_at"),
        queries_30d=int(activity.get("queries") or 0),
        billable_bytes_30d=int(activity.get("billable_bytes") or 0),
    )


def _activity_by_principal(organization_id: str) -> dict[str, dict[str, Any]]:
    today = datetime.now(UTC).date()
    try:
        body = call_control_plane(
            lambda: hogtower.get_usage(
                organization_id,
                date_from=today - timedelta(days=ACTIVITY_DAYS),
                date_to=today + timedelta(days=1),
                group_by="principal",
                timeout=hogtower.CONSOLE_SECONDARY_TIMEOUT_SECONDS,
            )
        )
        with malformed_body_guard():
            return {str(row["key"]): row for row in body.get("compute", []) if row["key"] != "__other__"}
    except (
        ControlPlaneUpstreamError,
        ControlPlaneUnavailableError,
        ControlPlaneRejectedError,
        WarehouseNotFoundError,
    ):
        # Activity is extra context. A login list without it is still useful.
        logger.warning("managed_warehouse_login_activity_unavailable", organization_id=organization_id)
        return {}


def list_logins(organization_id: str) -> list[WarehouseLogin]:
    users = call_control_plane(lambda: hogtower.list_users(organization_id)).get("users", [])
    activity = _activity_by_principal(organization_id)
    with malformed_body_guard():
        team_names = _team_names(organization_id, users)
        return [_login(u, team_names, activity.get(str(u["username"]), {})) for u in users]


def _credential(organization_id: str, body: dict[str, Any]) -> WarehouseLoginCredential:
    # `from None` in the guard keeps this frame, which holds the password, out of the error chain.
    with malformed_body_guard():
        user = body["user"]
        return WarehouseLoginCredential(
            login=_login(user, _team_names(organization_id, [user]), {}), password=str(body["password"])
        )


def _require_project_login(organization_id: str, username: str) -> None:
    """Allow a change only to a project login that exists. Root and other unrestricted logins stay read-only."""
    users = call_control_plane(lambda: hogtower.list_users(organization_id)).get("users", [])
    with malformed_body_guard():
        user = next((u for u in users if u["username"] == username), None)
        if user is None:
            raise LoginNotFoundError("The warehouse has no login with that name")
        is_project_login = user.get("access_mode") in PROJECT_ACCESS_MODES and not _is_root(username)
    if not is_project_login:
        raise ProtectedLoginError(
            "Only project logins can be changed here. To change the root password, use the root password "
            "reset in the warehouse settings."
        )


def create_project_login(
    organization_id: str, *, team_id: int, mode: LoginMode, acting_user_id: int
) -> WarehouseLoginCredential:
    """Create the project's login for ``mode``, or give it a new password when it exists."""
    if not Team.objects.filter(pk=team_id, organization_id=organization_id).exists():
        raise InvalidLoginTeamError("That project does not belong to this organization")
    body = call_control_plane(lambda: hogtower.put_project_login(organization_id, team_id, mode))
    credential = _credential(organization_id, body)
    logger.info(
        "managed_warehouse_login_created_or_rotated",
        organization_id=organization_id,
        username=credential.login.username,
        team_id=team_id,
        user_id=acting_user_id,
    )
    return credential


def rotate_login(organization_id: str, username: str, *, acting_user_id: int) -> WarehouseLoginCredential:
    _require_project_login(organization_id, username)
    body = call_control_plane(
        lambda: hogtower.patch_user(organization_id, username, rotate_password=True), not_found=LoginNotFoundError
    )
    credential = _credential(organization_id, body)
    logger.info(
        "managed_warehouse_login_rotated", organization_id=organization_id, username=username, user_id=acting_user_id
    )
    return credential


def set_login_disabled(organization_id: str, username: str, *, disabled: bool, acting_user_id: int) -> WarehouseLogin:
    _require_project_login(organization_id, username)
    body = call_control_plane(
        lambda: hogtower.patch_user(organization_id, username, disabled=disabled), not_found=LoginNotFoundError
    )
    logger.info(
        "managed_warehouse_login_disabled_changed",
        organization_id=organization_id,
        username=username,
        disabled=disabled,
        user_id=acting_user_id,
    )
    with malformed_body_guard():
        user = body["user"]
        return _login(user, _team_names(organization_id, [user]), {})


def delete_login(organization_id: str, username: str, *, acting_user_id: int) -> None:
    _require_project_login(organization_id, username)
    call_control_plane(lambda: hogtower.delete_user(organization_id, username), not_found=LoginNotFoundError)
    logger.info(
        "managed_warehouse_login_deleted", organization_id=organization_id, username=username, user_id=acting_user_id
    )
