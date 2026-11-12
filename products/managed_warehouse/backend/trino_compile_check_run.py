"""Run the Trino compile check for one team and report each row as a PostHog event."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

import structlog

from posthog.models import Team
from posthog.ph_client import ph_scoped_capture
from posthog.utils import get_instance_region

from products.managed_warehouse.backend.presentation import hogtower
from products.managed_warehouse.backend.tasks import run_trino_compile_check_task
from products.managed_warehouse.backend.trino_compile_check import (
    TrinoCompileCheckReport,
    TrinoCompileCheckRow,
    check_trino_compile,
)

logger = structlog.get_logger(__name__)

RESULT_EVENT = "trino_compile_check_result"
COMPLETED_EVENT = "trino_compile_check_completed"
HOGTOWER_NOT_CONFIGURED = "hogtower_not_configured"


def is_control_plane_configured() -> bool:
    return hogtower.is_configured()


def start_trino_compile_check(team_id: int, *, explain: bool, limit: int | None = None) -> str:
    run_id = str(uuid.uuid4())
    run_trino_compile_check_task.delay(team_id=team_id, run_id=run_id, explain=explain, limit=limit)
    return run_id


def run_trino_compile_check(
    team_id: int,
    *,
    run_id: str,
    explain: bool,
    limit: int | None = None,
    saved_query_ids: Sequence[str] | None = None,
) -> None:
    team = Team.objects.get(pk=team_id)
    run_properties = {
        "run_id": run_id,
        "team_id": team_id,
        "organization_id": str(team.organization_id),
        "explain": explain,
        "$process_person_profile": False,
    }
    with ph_scoped_capture(event_region=get_instance_region()) as capture:

        def emit(event: str, properties: dict[str, Any]) -> None:
            capture(distinct_id=run_id, event=event, properties={**run_properties, **properties})

        if not is_control_plane_configured():
            logger.error("trino_compile_check_hogtower_not_configured", run_id=run_id, team_id=team_id)
            emit(COMPLETED_EVENT, {**_summary(()), "error": HOGTOWER_NOT_CONFIGURED})
            return

        rows: list[TrinoCompileCheckRow] = []
        try:
            for row in check_trino_compile(team, saved_query_ids=saved_query_ids, explain=explain, limit=limit):
                rows.append(row)
                emit(RESULT_EVENT, row.to_json())
        except Exception as error:
            logger.exception("trino_compile_check_run_failed", run_id=run_id, team_id=team_id)
            emit(COMPLETED_EVENT, {**_summary(rows), "error": type(error).__name__, "message": str(error)[:300]})
            raise
        emit(COMPLETED_EVENT, _summary(rows))


def _summary(rows: Sequence[TrinoCompileCheckRow]) -> dict[str, Any]:
    report = TrinoCompileCheckReport(rows=tuple(rows))
    return {"ok": report.ok_count, "total": len(report.rows), "error_counts": report.error_counts}
