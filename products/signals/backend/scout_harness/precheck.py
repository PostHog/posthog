"""Pre-check for scheduled scout runs.

A scout config can carry a HogQL query that a scheduled run evaluates before it starts. When the
query returns no rows, or one row with one false value (`false`, `0`, null or empty), there is
nothing new to look at, so the run is skipped before it creates a run row, a sandbox, or an LLM
call. Any other result starts the run. The single-value rule lets a `SELECT count() ...` gate work
as written, because a count always returns one row. Only the coordinator's scheduled dispatch
evaluates it: a manual, workflow, or check run already has a reason to run.

A skip writes nothing. The coordinator stamped `last_run_at` (the dispatch anchor) when it
dispatched the run, so the next tick does not dispatch it again at once. `{since}` reads the last
run row, so the next run that starts still sees everything since the last run that actually ran.
The failure breaker and the inactivity sweep read run rows, so a quiet scout is never paused for
being quiet.

A query error never turns the scout off: the run continues as if there were no pre-check.

The query comes from the first source that applies (`resolve_effective_precheck`):

1. `precheck_disabled` on the config: no pre-check, the scout runs every due tick.
2. The config's own `precheck_query`.
3. The default the canonical skill ships (`scout-precheck-query` frontmatter), for a project
   inside that skill's rollout (`precheck_default_rollout` in the `signals-scout` flag payload).
   Projects outside the rollout run as if there were no default, and form the control group.
"""

from __future__ import annotations

import json
import time
import dataclasses
from datetime import datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from django.utils import timezone

import structlog
import posthoganalytics
from croniter import CroniterError, croniter

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.errors import ExposedCHQueryError
from posthog.event_usage import groups
from posthog.models import Team

from products.signals.backend.models import SignalScoutConfig, SignalScoutRun
from products.signals.backend.scout_harness.lazy_seed import canonical_precheck_query_for, scout_skill_origin
from products.signals.backend.scout_harness.limits import MAX_PRECHECK_ROWS_BYTES, SCOUT_TRIAL_METADATA_KEY
from products.signals.backend.scout_harness.team_limits import (
    precheck_default_rollout_bucket,
    precheck_default_rollout_percent,
)
from products.skills.backend.models.skills import LLMSkill

logger = structlog.get_logger(__name__)

PRECHECK_TIMEOUT_S = 10
PRECHECK_MAX_ROWS = 50
PRECHECK_MAX_QUERY_LENGTH = 10_000

PrecheckOutcome = Literal["run", "skip", "error"]
# `rows`: the query found rows. `no_rows`: it found none. `false_value`: it returned one false
# value. `query_error`: the query failed and the run continues.
PrecheckReason = Literal["rows", "no_rows", "false_value", "query_error"]
# Where the query came from. `off` means no pre-check runs.
PrecheckQuerySource = Literal["config", "skill_default", "off"]


@frozen
class EffectivePrecheck:
    query: str | None
    source: PrecheckQuerySource
    # The project's 0-99 bucket for the skill default. None when the skill ships no default.
    rollout_bucket: int | None = None


@frozen
class PrecheckResult:
    outcome: PrecheckOutcome
    reason: PrecheckReason
    row_count: int = 0
    # The capped rows, one JSON object per line, for the run prompt.
    rows_text: str | None = None
    query_source: PrecheckQuerySource = "config"

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


@frozen
class PrecheckDryRunResult:
    would_run: bool
    reason: PrecheckReason
    since: datetime
    now: datetime
    interval_minutes: int
    row_count: int = 0
    columns: tuple[str, ...] = ()
    rows_text: str = ""
    # Set only for an error the person who wrote the query can act on, such as a syntax error.
    error: str | None = None


def parse_precheck_query(query: str) -> ast.SelectQuery | ast.SelectSetQuery:
    """Parse a pre-check query with its `{since}`, `{now}` and `{interval_minutes}` placeholders bound.

    Raises on a bad query.
    """
    moment = timezone.now()
    return parse_select(query, placeholders=_placeholders(since=moment, now=moment, interval_minutes=1))


def _placeholders(*, since: datetime, now: datetime, interval_minutes: int) -> dict[str, ast.Expr]:
    return {
        "since": ast.Constant(value=since),
        "now": ast.Constant(value=now),
        "interval_minutes": ast.Constant(value=interval_minutes),
    }


def resolve_effective_precheck(config: SignalScoutConfig, *, is_canonical: bool) -> EffectivePrecheck:
    """The pre-check query a scheduled run of this scout uses, and where it came from.

    `is_canonical` says whether the project's skill row is the one the harness ships. A team's own
    skill can share a canonical name, and it inherits no default from disk.
    """
    if config.precheck_disabled:
        return EffectivePrecheck(query=None, source="off")
    if config.precheck_query:
        return EffectivePrecheck(query=config.precheck_query, source="config")
    default = canonical_precheck_query_for(config.skill_name) if is_canonical else None
    if not default:
        return EffectivePrecheck(query=None, source="off")
    bucket = precheck_default_rollout_bucket(config.team_id, config.skill_name)
    if bucket >= precheck_default_rollout_percent(config.skill_name):
        return EffectivePrecheck(query=None, source="off", rollout_bucket=bucket)
    return EffectivePrecheck(query=default, source="skill_default", rollout_bucket=bucket)


def scout_skill_is_canonical(team_id: int, skill_name: str) -> bool:
    """Whether the project's latest skill row for this scout is the one the harness ships."""
    metadata = (
        LLMSkill.objects.filter(team_id=team_id, name=skill_name, is_latest=True, deleted=False)
        .values_list("metadata", flat=True)
        .first()
    )
    return metadata is not None and scout_skill_origin(skill_name, metadata) == "canonical"


def precheck_interval_minutes(config: SignalScoutConfig, team: Team, now: datetime) -> int:
    """The `{interval_minutes}` value: the gap between two scheduled runs of this scout.

    For a cron schedule it is the gap between the fire time before `now` and the one after it,
    read in the project's timezone like the coordinator reads it. Otherwise it is the rolling
    `run_interval_minutes`.
    """
    if config.run_cron_schedule:
        try:
            local_now = now.astimezone(ZoneInfo(team.timezone)).replace(tzinfo=None)
            following: datetime = croniter(config.run_cron_schedule, local_now).get_next(datetime)
            previous: datetime = croniter(config.run_cron_schedule, following).get_prev(datetime)
            return max(1, round((following - previous).total_seconds() / 60))
        except (CroniterError, ValueError, KeyError):
            pass
    return config.run_interval_minutes


def evaluate_scout_precheck(team_id: int, skill_name: str, now: datetime | None = None) -> PrecheckResult | None:
    """Evaluate the effective pre-check of one scout. Return None when the scout has no pre-check.

    Never raises for a query problem: a failed query returns an `error` outcome that runs the scout.
    """
    config = (
        SignalScoutConfig.objects.for_team(team_id)
        .filter(skill_name=skill_name)
        .only(
            "id",
            "team_id",
            "skill_name",
            "created_at",
            "status",
            "precheck_query",
            "precheck_disabled",
            "run_interval_minutes",
            "run_cron_schedule",
        )
        .first()
    )
    # A paused lane only runs as a breaker probe, which exists to find out whether the lane can
    # succeed. A skip would hold the lane paused for as long as it stays quiet.
    if config is None or config.status not in SignalScoutConfig.RUNNABLE_STATUSES:
        return None
    effective = resolve_effective_precheck(config, is_canonical=scout_skill_is_canonical(team_id, skill_name))
    if effective.query is None:
        return None

    now = now or timezone.now()
    since = precheck_since(config)
    team = Team.objects.select_related("organization").get(pk=team_id)
    interval_minutes = precheck_interval_minutes(config, team, now)
    started = time.monotonic()
    error_type: str | None = None

    try:
        found = _run_query(team, effective.query, since=since, now=now, interval_minutes=interval_minutes)
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
    result = dataclasses.replace(result, query_source=effective.source)

    _capture_precheck_evaluated(
        team=team,
        config=config,
        result=result,
        effective=effective,
        duration_ms=round((time.monotonic() - started) * 1000),
        error_type=error_type,
    )
    return result


def dry_run_scout_precheck(
    team: Team, config: SignalScoutConfig, query: str, now: datetime | None = None
) -> PrecheckDryRunResult:
    """Run a pre-check query the way the next scheduled run would, and change nothing."""
    now = now or timezone.now()
    since = precheck_since(config)
    interval_minutes = precheck_interval_minutes(config, team, now)
    try:
        found = _run_query(team, query, since=since, now=now, interval_minutes=interval_minutes)
    except Exception as error:
        logger.info(
            "signals_scout: pre-check dry run failed",
            team_id=team.pk,
            skill_name=config.skill_name,
            error_type=type(error).__name__,
        )
        # Other errors can carry generated SQL, so only an exposed error reaches the caller as written.
        exposed = isinstance(error, ExposedHogQLError | ExposedCHQueryError)
        message = str(error) if exposed else "The query could not run."
        return PrecheckDryRunResult(
            would_run=True,
            reason="query_error",
            since=since,
            now=now,
            interval_minutes=interval_minutes,
            error=message,
        )
    result = _result_from_rows(found)
    return PrecheckDryRunResult(
        would_run=result.should_run,
        reason=result.reason,
        since=since,
        now=now,
        interval_minutes=interval_minutes,
        row_count=len(found.rows),
        columns=tuple(str(column) for column in found.columns),
        rows_text=_render_rows(found),
    )


def precheck_since(config: SignalScoutConfig) -> datetime:
    """The `{since}` bound: the last run that actually ran, or the config's creation."""
    last_run_at = (
        SignalScoutRun.objects.for_team(config.team_id)
        .filter(skill_name=config.skill_name)
        .exclude(metadata__has_key=SCOUT_TRIAL_METADATA_KEY)
        .order_by("-created_at")
        .values_list("created_at", flat=True)
        .first()
    )
    return last_run_at or config.created_at


def _result_from_rows(found: _PrecheckRows) -> PrecheckResult:
    if not found.rows:
        return PrecheckResult(outcome="skip", reason="no_rows")
    if found.is_single_false_value:
        return PrecheckResult(outcome="skip", reason="false_value", row_count=1)
    return PrecheckResult(outcome="run", reason="rows", row_count=len(found.rows), rows_text=_render_rows(found))


def _run_query(team: Team, query: str, *, since: datetime, now: datetime, interval_minutes: int) -> _PrecheckRows:
    parsed = parse_select(query, placeholders=_placeholders(since=since, now=now, interval_minutes=interval_minutes))
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
        if size > MAX_PRECHECK_ROWS_BYTES:
            break
        lines.append(line)
    return "\n".join(lines)


def _capture_precheck_evaluated(
    *,
    team: Team,
    config: SignalScoutConfig,
    result: PrecheckResult,
    effective: EffectivePrecheck,
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
                "query_source": effective.source,
                "rollout_bucket": effective.rollout_bucket,
            },
            groups=groups(team.organization, team),
        )
    except Exception:
        logger.warning(
            "signals_scout: failed to capture pre-check analytics event",
            team_id=team.pk,
            skill_name=config.skill_name,
        )
