"""Pre-check for scheduled scout runs.

A scout config can carry a HogQL query that a scheduled run evaluates before it starts. When the
query returns no rows, or one row with one false value (`false`, `0`, null or empty), there is
nothing new to look at, so the run is skipped before it creates a run row, a sandbox, or an LLM
call. Any other result starts the run. The single-value rule lets a `SELECT count() ...` gate work
as written, because a count always returns one row. Only the coordinator's scheduled dispatch evaluates it: a
manual, workflow, or check run already has a reason to run.

A skip writes nothing. The coordinator stamped `last_run_at` (the dispatch anchor) when it
dispatched the run, so the next tick does not dispatch it again at once. `{since}` reads the last
run row, so the next run that starts still sees everything since the last run that actually ran.
The failure breaker and the inactivity sweep read run rows, so a quiet scout is never paused for
being quiet.

A query error never turns the scout off: the run continues as if there were no pre-check.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any, Literal

from django.utils import timezone

import structlog
import posthoganalytics

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.event_usage import groups
from posthog.models import Team

from products.signals.backend.models import SignalScoutConfig, SignalScoutRun
from products.signals.backend.scout_harness.limits import SCOUT_TRIAL_METADATA_KEY

logger = structlog.get_logger(__name__)

PRECHECK_TIMEOUT_S = 10
PRECHECK_MAX_ROWS = 50
PRECHECK_MAX_TEXT_BYTES = 8 * 1024

PrecheckOutcome = Literal["run", "skip", "error"]
# `rows`: the query found rows. `no_rows`: it found none. `false_value`: it returned one false
# value. `query_error`: the query failed and the run continues.
PrecheckReason = Literal["rows", "no_rows", "false_value", "query_error"]


@frozen
class PrecheckResult:
    outcome: PrecheckOutcome
    reason: PrecheckReason
    row_count: int = 0
    # The capped rows, one JSON object per line, for a later prompt block.
    rows_text: str | None = None

    @property
    def should_run(self) -> bool:
        return self.outcome != "skip"


@frozen
class _PrecheckRows:
    columns: list[Any]
    rows: list[Any]

    @property
    def is_single_false_value(self) -> bool:
        return len(self.rows) == 1 and len(self.rows[0]) == 1 and self.rows[0][0] in (None, False, 0, "")


def evaluate_scout_precheck(team_id: int, skill_name: str, now: datetime | None = None) -> PrecheckResult | None:
    """Evaluate the pre-check of one scout. Return None when the scout has no pre-check.

    Never raises for a query problem: a failed query returns an `error` outcome that runs the scout.
    """
    config = (
        SignalScoutConfig.objects.for_team(team_id)
        .filter(skill_name=skill_name)
        .only("id", "team_id", "skill_name", "created_at", "status", "precheck_query")
        .first()
    )
    # A paused lane only runs as a breaker probe, which exists to find out whether the lane can
    # succeed. A skip would hold the lane paused for as long as it stays quiet.
    if config is None or not config.precheck_query or config.status not in SignalScoutConfig.RUNNABLE_STATUSES:
        return None

    now = now or timezone.now()
    since = _last_real_run_at(team_id, skill_name) or config.created_at
    team = Team.objects.select_related("organization").get(pk=team_id)
    started = time.monotonic()
    error_type: str | None = None

    try:
        found = _run_query(team, config.precheck_query, since=since, now=now)
    except Exception as error:
        error_type = type(error).__name__
        logger.warning(
            "signals_scout: pre-check query failed, running the scout",
            team_id=team_id,
            skill_name=skill_name,
            error_type=error_type,
            exc_info=True,
        )
        result = PrecheckResult(outcome="error", reason="query_error")
    else:
        result = _result_from_rows(found)

    _capture_precheck_evaluated(
        team=team,
        config=config,
        result=result,
        duration_ms=round((time.monotonic() - started) * 1000),
        error_type=error_type,
    )
    return result


def _last_real_run_at(team_id: int, skill_name: str) -> datetime | None:
    return (
        SignalScoutRun.objects.for_team(team_id)
        .filter(skill_name=skill_name)
        .exclude(metadata__has_key=SCOUT_TRIAL_METADATA_KEY)
        .order_by("-created_at")
        .values_list("created_at", flat=True)
        .first()
    )


def _result_from_rows(found: _PrecheckRows) -> PrecheckResult:
    if not found.rows:
        return PrecheckResult(outcome="skip", reason="no_rows")
    if found.is_single_false_value:
        return PrecheckResult(outcome="skip", reason="false_value", row_count=1)
    return PrecheckResult(outcome="run", reason="rows", row_count=len(found.rows), rows_text=_render_rows(found))


def _run_query(team: Team, query: str, *, since: datetime, now: datetime) -> _PrecheckRows:
    parsed = parse_select(query, placeholders={"since": ast.Constant(value=since), "now": ast.Constant(value=now)})
    capped = _cap_rows(parsed)
    with tags_context(product=Product.SIGNALS, feature=Feature.ENRICHMENT, team_id=team.pk):
        response = execute_hogql_query(
            query_type="scout_precheck",
            query=capped,
            team=team,
            workload=Workload.OFFLINE,
            settings=HogQLGlobalSettings(max_execution_time=PRECHECK_TIMEOUT_S),
        )
    return _PrecheckRows(columns=response.columns or [], rows=(response.results or [])[:PRECHECK_MAX_ROWS])


def _cap_rows(parsed: ast.SelectQuery | ast.SelectSetQuery) -> ast.SelectQuery:
    """Cap the rows whatever the owner wrote, including a union or no LIMIT at all."""
    if isinstance(parsed, ast.SelectQuery):
        # Set the limit in place. `SELECT *` over a subquery loses unaliased columns, so a wrapper
        # would turn `SELECT false` into an unnamed `1`.
        current = parsed.limit
        if not (
            isinstance(current, ast.Constant) and isinstance(current.value, int) and current.value <= PRECHECK_MAX_ROWS
        ):
            parsed.limit = ast.Constant(value=PRECHECK_MAX_ROWS)
        return parsed
    return ast.SelectQuery(
        select=[ast.Field(chain=["*"])],
        select_from=ast.JoinExpr(table=parsed),
        limit=ast.Constant(value=PRECHECK_MAX_ROWS),
    )


def _render_rows(found: _PrecheckRows) -> str:
    """Render rows one JSON object per line, and stop before the text passes the size cap."""
    lines: list[str] = []
    size = 0
    for row in found.rows:
        line = json.dumps(dict(zip(found.columns, row)), default=str, ensure_ascii=False)
        size += len(line.encode("utf-8")) + 1
        if size > PRECHECK_MAX_TEXT_BYTES:
            break
        lines.append(line)
    return "\n".join(lines)


def _capture_precheck_evaluated(
    *,
    team: Team,
    config: SignalScoutConfig,
    result: PrecheckResult,
    duration_ms: int,
    error_type: str | None,
) -> None:
    try:
        posthoganalytics.capture(
            event="scout_precheck_evaluated",
            distinct_id=str(team.uuid),
            properties={
                "skill_name": config.skill_name,
                "scout_config_id": str(config.id),
                "outcome": result.outcome,
                "reason": result.reason,
                "row_count": result.row_count,
                "duration_ms": duration_ms,
                "error_type": error_type,
            },
            groups=groups(team.organization, team),
        )
    except Exception:
        logger.warning(
            "signals_scout: failed to capture pre-check analytics event",
            team_id=team.pk,
            skill_name=config.skill_name,
        )
