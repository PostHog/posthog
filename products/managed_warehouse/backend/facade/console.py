"""Managed warehouse console: usage, spend estimates, query history, storage and spend settings."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Literal

from posthog.models.team import Team

if TYPE_CHECKING:
    from posthog.models.user import User

from products.managed_warehouse.backend.facade.contracts import (
    ConsoleSettings,
    LoginMode,
    QueryCostEstimate,
    QueryHistoryPage,
    StorageOverview,
    UsageSummary,
    WarehouseLogin,
    WarehouseLoginCredential,
)
from products.managed_warehouse.backend.logic import console_logins, console_queries, console_usage, query_estimate
from products.managed_warehouse.backend.logic.console_access import is_console_enabled as _is_console_enabled
from products.managed_warehouse.backend.logic.console_labels import SQL_EDITOR_PRINCIPAL

__all__ = [
    "create_project_login",
    "delete_login",
    "estimate_managed_trino_query",
    "list_logins",
    "rotate_login",
    "set_login_disabled",
    "build_usage_summary",
    "cancel_query",
    "get_console_settings",
    "get_max_scan_bytes_per_query",
    "get_storage_overview",
    "is_console_enabled",
    "is_own_sql_editor_principal",
    "list_query_history",
    "update_console_settings",
]


def is_console_enabled(organization_id: str) -> bool:
    """Whether the organization has the managed warehouse, so the console may show it."""
    return _is_console_enabled(organization_id)


def build_usage_summary(
    organization_id: str,
    *,
    period: Literal["current_month", "last_month"],
    group_by: Literal["source", "principal", "team"],
) -> UsageSummary:
    return console_usage.build_usage_summary(organization_id, period=period, group_by=group_by)


def list_query_history(
    organization_id: str,
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    principal: str | None = None,
    source: str | None = None,
    state: str | None = None,
    team_id: int | None = None,
    limit: int | None = None,
    cursor: str | None = None,
    redact_for_user: User | None = None,
) -> QueryHistoryPage:
    return console_queries.list_query_history(
        organization_id,
        date_from=date_from,
        date_to=date_to,
        principal=principal,
        source=source,
        state=state,
        team_id=team_id,
        limit=limit,
        cursor=cursor,
        redact_for_user=redact_for_user,
    )


def cancel_query(organization_id: str, query_id: str, *, principal: str | None = None) -> None:
    console_queries.cancel_query(organization_id, query_id, principal=principal)


def get_storage_overview(organization_id: str) -> StorageOverview:
    return console_queries.get_storage_overview(organization_id)


def get_console_settings(organization_id: str) -> ConsoleSettings:
    return console_usage.get_console_settings(organization_id)


def update_console_settings(organization_id: str, *, changes: Mapping[str, int | Decimal | None]) -> ConsoleSettings:
    """Write only the settings named in ``changes``: ``max_scan_bytes_per_query`` and ``monthly_budget_usd``."""
    return console_usage.update_console_settings(organization_id, changes=changes)


def get_max_scan_bytes_per_query(organization_id: str) -> int | None:
    """The per-query scan cap the SQL editor applies, or None for no cap."""
    return console_usage.get_max_scan_bytes_per_query(organization_id)


def is_own_sql_editor_principal(principal: str, *, organization_id: str, user_id: int) -> bool:
    """Whether ``principal`` is the SQL editor principal of ``user_id`` on a project of the organization."""
    match = SQL_EDITOR_PRINCIPAL.fullmatch(principal)
    if match is None or int(match.group("user_id")) != user_id:
        return False
    return Team.objects.filter(pk=int(match.group("team_id")), organization_id=organization_id).exists()


def list_logins(organization_id: str) -> list[WarehouseLogin]:
    return console_logins.list_logins(organization_id)


def create_project_login(
    organization_id: str, *, team_id: int, mode: LoginMode, acting_user_id: int
) -> WarehouseLoginCredential:
    return console_logins.create_project_login(
        organization_id, team_id=team_id, mode=mode, acting_user_id=acting_user_id
    )


def rotate_login(organization_id: str, username: str, *, acting_user_id: int) -> WarehouseLoginCredential:
    return console_logins.rotate_login(organization_id, username, acting_user_id=acting_user_id)


def set_login_disabled(organization_id: str, username: str, *, disabled: bool, acting_user_id: int) -> WarehouseLogin:
    return console_logins.set_login_disabled(
        organization_id, username, disabled=disabled, acting_user_id=acting_user_id
    )


def delete_login(organization_id: str, username: str, *, acting_user_id: int) -> None:
    console_logins.delete_login(organization_id, username, acting_user_id=acting_user_id)


def estimate_managed_trino_query(
    team: Team,
    user: User,
    *,
    query: str,
    send_raw_query: bool,
    variables: Mapping[str, Any] | None = None,
    filters: Mapping[str, Any] | None = None,
) -> QueryCostEstimate:
    """Upper-bound scan size and cost of a SQL editor query. Raises ``ExposedHogQLError`` for an invalid query."""
    return query_estimate.estimate_managed_trino_query(
        team, user, query=query, send_raw_query=send_raw_query, variables=variables, filters=filters
    )
