"""Take a moving project's environments out of the old organization's managed warehouse.

hogtower removes the old organization's rows for them before the move commits, and a failed move puts
them back once a locked re-read shows it did not commit. After the commit the removal is repeated at
once and 10 minutes later. Both the delayed removal and a failed restore are retried while hogtower is
down. Organizations without PostHog warehouse state never call hogtower.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import replace
from typing import Any
from uuid import UUID

from django.db import connection, transaction

import structlog

from posthog.models import Project, Team

from products.managed_warehouse.backend import cp_teams
from products.managed_warehouse.backend.facade.contracts import CPUnavailableError, ProjectMoveOut
from products.managed_warehouse.backend.models import DuckgresServer, ManagedWarehouseSourceLifecycle
from products.managed_warehouse.backend.presentation import hogtower

logger = structlog.get_logger(__name__)

TRY_AGAIN = "Could not update your organization's managed warehouse for this move. Try again in a few minutes."
CHANGED = "The project changed while it was being moved. Try again."
MIXED = "This project's environments are in more than one organization. Contact support."
MAX_TEAMS = 100  # per moved-teams call
REPEAT_DELAY_SECONDS = 600  # longer than the web pods' 180 s termination period


def has_warehouse_state(organization_id: UUID | str) -> bool:
    """The gate: hogtower is configured and PostHog has warehouse state for the org. Reads only."""
    return hogtower.is_configured() and (
        DuckgresServer.objects.filter(organization_id=organization_id).exists()
        or ManagedWarehouseSourceLifecycle.objects.filter(organization_id=organization_id).exists()
    )


@contextmanager
def project_move_out(
    project_id: int, organization_id: UUID | str, team_organization_ids: Mapping[int, UUID | str]
) -> Iterator[ProjectMoveOut]:
    """Remove the rows on entry; put them back if the block raises, its commit included."""
    move = _remove_before_commit(project_id, str(organization_id), team_organization_ids)
    try:
        yield move
    except Exception:
        undo(move)
        raise


def _remove_before_commit(
    project_id: int, organization_id: str, team_organization_ids: Mapping[int, UUID | str]
) -> ProjectMoveOut:
    move = ProjectMoveOut(project_id=project_id, organization_id=organization_id, guarded=hogtower.is_configured())
    if not move.guarded:
        return move
    if _mixed_with_state(organization_id, team_organization_ids):
        return replace(move, refusal=MIXED)
    if not has_warehouse_state(organization_id):
        return move
    if len(team_organization_ids) > MAX_TEAMS:
        return replace(move, refusal=f"Projects with more than {MAX_TEAMS} environments can't be moved.")
    listed = _call("GET", organization_id, "/teams")
    rows = [] if listed is not None and listed.status_code == 404 else _rows(listed)
    if rows is None:
        return replace(move, refusal=TRY_AGAIN)
    move = replace(move, rows=tuple(row for row in rows if _team_id(row) in team_organization_ids))
    if not move.rows:
        return move
    # Logged before the call, so that a crash right after it leaves the rows for the runbook.
    logger.info("managed_warehouse_action", action="move_out", project_id=project_id, rows=move.rows)
    if remove_rows(organization_id, [int(row["team_id"]) for row in move.rows]):
        return move
    undo(move)  # the call may have applied before it failed
    return replace(move, rows=(), refusal=TRY_AGAIN)


def commit_project_move_out(
    move: ProjectMoveOut, organization_id: UUID | str, team_organization_ids: Mapping[int, UUID | str]
) -> str | None:
    """Under the project lock: refuse if a concurrent move committed since the removal, else repeat it after commit."""
    if not move.guarded:
        return None
    if str(organization_id) != move.organization_id or _mixed_with_state(move.organization_id, team_organization_ids):
        return CHANGED
    team_ids = list(team_organization_ids)
    transaction.on_commit(lambda: _after_commit(move.organization_id, team_ids), robust=True)
    return None


def _after_commit(organization_id: str, team_ids: list[int]) -> None:
    from products.managed_warehouse.backend.tasks.tasks import repeat_project_move_out  # noqa: PLC0415

    try:
        # On every move, so that it also covers a provisioning request that was already past its checks.
        repeat_project_move_out.apply_async(args=[organization_id, team_ids], countdown=REPEAT_DELAY_SECONDS)
    finally:
        repeat_move_out(organization_id, team_ids)


def _mixed_with_state(organization_id: str, team_organization_ids: Mapping[int, UUID | str]) -> bool:
    """An environment in another org, where any of the orgs has warehouse state: its rows would stay there."""
    organization_ids = {organization_id, *map(str, team_organization_ids.values())}
    return len(organization_ids) > 1 and any(has_warehouse_state(org) for org in organization_ids)


def repeat_move_out(organization_id: str, team_ids: list[int]) -> bool:
    """Remove the org's rows for the teams it no longer owns, which a writer may have re-created.

    False when hogtower did not confirm the removal.
    """
    if not has_warehouse_state(organization_id):
        return True
    kept = set(Team.objects.filter(id__in=team_ids, organization_id=organization_id).values_list("id", flat=True))
    moved = [team_id for team_id in team_ids if team_id not in kept]
    if moved and not remove_rows(organization_id, moved):
        logger.warning("move_out_repeat_failed", organization_id=organization_id, team_ids=moved)
        return False
    return True


def undo(move: ProjectMoveOut) -> None:
    """Put the removed rows back unless the move committed. A task retries the rows that fail."""
    if not move.rows:
        return
    failed = list(move.rows)
    try:
        failed = restore_rows(move.project_id, move.organization_id, list(move.rows))
    except Exception:
        logger.exception("Project move undo failed", organization_id=move.organization_id, project_id=move.project_id)
    if failed:
        logger.warning("move_undo_skipped", project_id=move.project_id, rows=failed)
        try:
            from products.managed_warehouse.backend.tasks.tasks import restore_project_move_out  # noqa: PLC0415

            restore_project_move_out.apply_async(args=[move.project_id, move.organization_id, failed], countdown=60)
        except Exception:
            logger.exception("Could not schedule the project move restore", project_id=move.project_id)


def restore_rows(project_id: int, organization_id: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Upsert the rows of teams the org still owns, unless the project left it. Returns the unconfirmed rows."""
    if not connection.in_atomic_block:
        connection.close_if_unusable_or_obsolete()  # a failed commit can leave it broken
    in_old_org = Project.objects.filter(pk=project_id, organization_id=organization_id)
    team_ids = [int(row["team_id"]) for row in rows]
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout = '3s'")
        # A deleted project counts as moved.
        committed = not in_old_org.select_for_update(no_key=True).exists()
    if committed:  # its commit hooks may not have run, e.g. when the commit's acknowledgement was lost
        _after_commit(organization_id, team_ids)
        return []
    owned = set(Team.objects.filter(id__in=team_ids, organization_id=organization_id).values_list("id", flat=True))
    # hogtower ignores the row's read-only fields (org_id, created_at, updated_at).
    failed = [r for r in rows if int(r["team_id"]) in owned and not _ok(_call("POST", organization_id, "/teams", r))]
    cp_teams.invalidate_org_cache(organization_id)
    # A concurrent move may have committed, and run its own repeat, before the rows went back.
    if not in_old_org.exists():
        repeat_move_out(organization_id, team_ids)
    return failed


def moved_team_rows(organization_id: str, *, remove: bool = False) -> dict[str, list[int]]:
    """By warehouse, the rows earlier moves left: the org's rows for teams now in another org, and other
    warehouses' rows for teams the org now owns. Rows of deleted teams stay."""
    organization_id = str(UUID(organization_id))
    if not has_warehouse_state(organization_id):
        raise ValueError("hogtower is not configured, or PostHog has no warehouse state for this organization.")
    rows = _rows(_call("GET", "", "teams"))
    if rows is None:
        raise CPUnavailableError("Could not list hogtower's team rows.")
    team_ids = [team_id for team_id in map(_team_id, rows) if team_id is not None]
    owners = {team: str(org) for team, org in Team.objects.filter(id__in=team_ids).values_list("id", "organization_id")}
    stale: dict[str, list[int]] = {}
    for row in rows:
        warehouse, owner = str(row.get("org_id")), owners.get(_team_id(row) or 0)
        if owner is not None and (warehouse == organization_id) != (owner == organization_id):
            stale.setdefault(warehouse, []).append(int(row["team_id"]))
    for warehouse, moved in stale.items() if remove else ():
        if not remove_rows(warehouse, moved):
            raise CPUnavailableError(f"Could not remove warehouse {warehouse}'s rows {moved}; found {stale}.")
    return stale


def remove_rows(organization_id: str, team_ids: list[int]) -> bool:
    """Remove the org's rows for these teams through hogtower's moved-teams route."""
    chunks = [team_ids[start : start + MAX_TEAMS] for start in range(0, len(team_ids), MAX_TEAMS)]
    removed = all(_ok(_call("POST", organization_id, "/moved-teams", {"team_ids": chunk})) for chunk in chunks)
    cp_teams.invalidate_org_cache(organization_id)
    return removed


def _call(method: str, organization_id: str, path: str, body: dict | None = None) -> hogtower.TranslatedResponse | None:
    """One hogtower call, or None when it raised (it may still have applied)."""
    try:
        resp = hogtower.request(method, organization_id, path, json_body=body)
    except Exception:
        logger.exception("Project move hogtower call failed", method=method, path=path, organization_id=organization_id)
        return None
    if not resp.ok:
        logger.warning("Project move hogtower call answered", method=method, path=path, status_code=resp.status_code)
    return resp


def _ok(resp: hogtower.TranslatedResponse | None) -> bool:
    return resp is not None and resp.ok


def _rows(resp: hogtower.TranslatedResponse | None) -> list[dict[str, Any]] | None:
    teams = resp.body.get("teams") if resp is not None and resp.ok and isinstance(resp.body, dict) else None
    return [row for row in teams if isinstance(row, dict)] if isinstance(teams, list) else None


def _team_id(row: dict[str, Any]) -> int | None:
    try:
        return int(row["team_id"])
    except (KeyError, TypeError, ValueError):
        return None
