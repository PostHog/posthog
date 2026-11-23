"""Query history, cancel and storage for the managed warehouse console."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import structlog

from posthog.models.team import Team

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.managed_warehouse.backend.facade.contracts import (
    ControlPlaneRejectedError,
    ControlPlaneUnavailableError,
    ControlPlaneUpstreamError,
    QueryHistoryPage,
    QueryHistoryRow,
    QueryNotFoundError,
    StorageOverview,
    StorageTableUsage,
    WarehouseNotFoundError,
)
from products.managed_warehouse.backend.logic import console_pricing
from products.managed_warehouse.backend.logic.console_labels import (
    member_display_names,
    principal_label,
    principal_team_ids,
    source_label,
    sql_editor_user_ids,
    team_display_names,
)
from products.managed_warehouse.backend.logic.console_upstream import call_control_plane, malformed_body_guard
from products.managed_warehouse.backend.presentation import hogtower

if TYPE_CHECKING:
    from posthog.models.user import User

logger = structlog.get_logger(__name__)


def _opt_int(value: Any) -> int | None:
    return int(value) if value is not None else None


def _billable_bytes(row: dict[str, Any]) -> int:
    # hogtower reports only whether the query is billable. A billable query bills every scanned byte.
    return int(row.get("logical_bytes_scanned") or 0) if row.get("billable") else 0


def _teams_with_project_access(organization_id: str, user: User, team_ids: set[int]) -> set[int]:
    teams = Team.objects.filter(organization_id=organization_id, pk__in=team_ids)
    return {team.pk for team in teams if UserAccessControl(user=user, team=team).has_project_access}


def list_query_history(
    organization_id: str,
    *,
    date_from: datetime | None,
    date_to: datetime | None,
    principal: str | None,
    source: str | None,
    state: str | None,
    team_id: int | None,
    limit: int | None,
    cursor: str | None,
    redact_for_user: User | None = None,
) -> QueryHistoryPage:
    """A page of finished queries.

    With ``redact_for_user``, the SQL text stays only on queries of projects that user can access.
    Everything else about a row is visible to the whole organization.
    """
    params: dict[str, Any] = {
        "from": date_from.isoformat() if date_from else None,
        "to": date_to.isoformat() if date_to else None,
        "principal": principal,
        "source": source,
        "state": state,
        "team_id": team_id,
        "limit": limit,
        "cursor": cursor,
    }
    body = call_control_plane(
        lambda: hogtower.list_query_history(
            organization_id, params={k: v for k, v in params.items() if v not in (None, "")}
        )
    )
    with malformed_body_guard():
        rows = body.get("queries", [])
        principals = [str(r["principal"]) for r in rows]
        member_names = member_display_names(organization_id, sql_editor_user_ids(principals))
        team_names = team_display_names(organization_id, principal_team_ids(principals))
        visible_teams: set[int] | None = None
        if redact_for_user is not None:
            team_ids = {int(r["team_id"]) for r in rows if r.get("team_id") is not None}
            visible_teams = _teams_with_project_access(organization_id, redact_for_user, team_ids)
        return QueryHistoryPage(
            queries=tuple(_history_row(r, member_names, team_names, visible_teams) for r in rows),
            next_cursor=body.get("next_cursor") or None,
        )


def _history_row(
    r: dict[str, Any], member_names: dict[int, str], team_names: dict[int, str], visible_teams: set[int] | None
) -> QueryHistoryRow:
    team_id = _opt_int(r.get("team_id"))
    show_query = visible_teams is None or (team_id is not None and team_id in visible_teams)
    return QueryHistoryRow(
        id=int(r["id"]),
        query_id=str(r["query_id"]),
        principal=str(r["principal"]),
        principal_label=principal_label(str(r["principal"]), member_names, team_names),
        team_id=team_id,
        source=str(r.get("source") or ""),
        source_label=source_label(str(r.get("source") or "")),
        state=str(r["state"]),
        error_code=r.get("error_code"),
        error_type=r.get("error_type"),
        created_at=r.get("created_at"),
        completed_at=r.get("completed_at"),
        elapsed_ms=_opt_int(r.get("elapsed_ms")),
        queued_ms=_opt_int(r.get("queued_ms")),
        logical_bytes_scanned=int(r.get("logical_bytes_scanned") or 0),
        billable=bool(r.get("billable")),
        billable_bytes=_billable_bytes(r),
        cpu_seconds=r.get("cpu_seconds"),
        query=str(r.get("query") or "") if show_query else None,
        estimated_cost_usd=Decimal(_billable_bytes(r))
        / Decimal(console_pricing.TIB)
        * console_pricing.COMPUTE_USD_PER_TIB,
    )


def cancel_query(organization_id: str, query_id: str, *, principal: str | None = None) -> None:
    """Cancel a running query. With ``principal``, hogtower refuses unless the query runs as that principal."""
    call_control_plane(
        lambda: hogtower.cancel_query(organization_id, query_id, principal=principal), not_found=QueryNotFoundError
    )


def get_storage_overview(organization_id: str) -> StorageOverview:
    body = call_control_plane(lambda: hogtower.list_storage_tables(organization_id))
    maintenance: dict[str, Any] | None
    try:
        maintenance = call_control_plane(
            lambda: hogtower.get_maintenance(organization_id, timeout=hogtower.CONSOLE_SECONDARY_TIMEOUT_SECONDS)
        )
    except (
        ControlPlaneUpstreamError,
        ControlPlaneUnavailableError,
        ControlPlaneRejectedError,
        WarehouseNotFoundError,
    ) as error:
        logger.warning(
            "managed_warehouse_maintenance_unavailable",
            organization_id=organization_id,
            error_type=type(error).__name__,
        )
        maintenance = None
    with malformed_body_guard():
        return StorageOverview(
            tables=tuple(
                StorageTableUsage(
                    schema=str(t["schema"]),
                    table=str(t["table"]),
                    data_bytes=int(t.get("data_bytes") or 0),
                    delete_bytes=int(t.get("delete_bytes") or 0),
                    file_count=int(t.get("file_count") or 0),
                    row_count=int(t.get("row_count") or 0),
                    last_modified_at=t.get("last_modified_at"),
                )
                for t in body.get("tables", [])
            ),
            total_bytes=int(body.get("total_bytes") or 0),
            pending_deletion_files=int(body.get("pending_deletion_files") or 0),
            read_at=body.get("read_at"),
            maintenance=maintenance,
        )
