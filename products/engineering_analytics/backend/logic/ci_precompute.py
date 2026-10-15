"""The stored CI rows: the output of the runs builder and of the jobs builder, kept in ClickHouse.

A read of the warehouse tables parses every payload and repeats the hand-off shell filter each time.
The lazy computation framework stores the parsed rows instead, one job for the rows that one
repository created on one day. A refresh after a data load computes only the days that are missing
or too old, so its cost follows the new data and not the history.

Every day from the first raw row of a repository is stored. So a read keyed by pull request number,
which has no floor, can take the stored rows too. Each refresh finds the first row again, so a
backfill of older rows reaches the stored days on the next load.
"""

import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from django.core.cache import cache

import structlog

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.escape_sql import escape_hogql_string
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.dataclasses import frozen
from posthog.models.team import Team

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    LazyComputationResult,
    LazyComputationTable,
    TtlSchedule,
    ensure_precomputed,
    parse_ttl_schedule,
)
from products.engineering_analytics.backend.logic.queries._workflow_filters import JOB_FLOOR_SLACK_ON_RUN_STARTED
from products.engineering_analytics.backend.logic.sources import JobSourceTables, resolve_precompute_sources
from products.engineering_analytics.backend.logic.views import depot_ci, job_costs, workflow_jobs, workflow_runs
from products.engineering_analytics.backend.logic.views.created_window import CreatedWindow

logger = structlog.get_logger(__name__)

# GitHub ends a workflow run after 35 days, so a run was created at most that long before its newest
# start and before any of its jobs.
RUN_LIFETIME = timedelta(days=35)

_RECENT_DAYS_MAX_AGE_SECONDS = 15 * 60
_LAST_WEEK_MAX_AGE_SECONDS = 6 * 60 * 60
_RUN_LIFETIME_MAX_AGE_SECONDS = 5 * 24 * 60 * 60
_SETTLED_DAYS_MAX_AGE_SECONDS = 30 * 24 * 60 * 60
_SETTLED_DAYS_MAX_AGE_SPREAD_SECONDS = 15 * 24 * 60 * 60

# A refresh stores the newest days first, this many at a time, so a recent page can read stored rows
# long before the whole history is stored.
_BACKFILL_STEP = timedelta(days=30)

# The time one table of one repository has to start its inserts, and the time a whole refresh has.
# A refresh that runs out of either keeps the days it stored, and the next load continues from there.
_REFRESH_BUDGET_SECONDS = 4 * 60
_TASK_BUDGET_SECONDS = 20 * 60
# A budget only stops new inserts, so a running insert can pass it. The mark that a refresh runs
# must last as long as the task can, or a second refresh of the team starts next to the first.
REFRESH_TASK_TIME_LIMIT_SECONDS = 35 * 60
# After a failed insert the team starts no refresh for this long. A load lands every few minutes, and
# a day that cannot be stored would otherwise scan the warehouse tables again on each one.
_FAILED_REFRESH_PAUSE_SECONDS = 30 * 60
# A read that can take the stored rows marks its team for this long. A refresh runs only while the
# mark lasts, so a load does not store days again for a team that no one reads.
_IN_USE_SECONDS = 60 * 60


_WINDOW = CreatedWindow(slack_days=JOB_FLOOR_SLACK_ON_RUN_STARTED.days)

RUN_COLUMNS = (
    "id",
    "workflow_name",
    "head_sha",
    "head_branch",
    "status",
    "conclusion",
    "run_started_at",
    "updated_at",
    "created_at",
    "run_attempt",
    "is_merge_queue",
    "pr_number",
    "commit_pr_number",
    "duration_seconds",
    "repo_owner",
    "repo_name",
    "ci_engine",
    "native_run_id",
    "native_workflow_run_id",
    "workflow_id",
    "event",
    *depot_ci.WINDOWED_RUN_COLUMNS,
)

JOB_COLUMNS = (*workflow_jobs.COLUMNS, *job_costs.COST_COLUMNS)


def source_literal(source_id: str) -> str:
    return escape_hogql_string(str(UUID(source_id)))


def repository_literal(repository: str) -> str:
    # GitHub names are case-insensitive, and a source can store them in either case.
    return escape_hogql_string(repository.casefold())


def _stored_rows(source: JobSourceTables, columns: tuple[str, ...], rows: str) -> str:
    select = ", ".join(f"built.{column} AS {column}" for column in columns)
    return f"""
        SELECT
            {source_literal(source.source_id)} AS source_id,
            {repository_literal(source.repository)} AS repository,
            {select}
        FROM ({rows}) AS built
    """


def _runs_insert_query(source: JobSourceTables) -> str:
    runs = depot_ci.windowed_runs(
        source.github_workflow_runs,
        source.depot_job_attempts,
        source.pull_requests,
        source.github_workflow_jobs,
        _WINDOW,
        optional_columns=source.workflow_runs_optional_columns,
    )
    rows = workflow_runs.build_query(
        runs, pull_requests_table=source.pull_requests, passthrough=depot_ci.WINDOWED_RUN_COLUMNS
    )
    return _stored_rows(source, RUN_COLUMNS, rows)


def _jobs_insert_query(source: JobSourceTables) -> str:
    jobs = depot_ci.windowed_jobs(source.github_workflow_jobs, source.depot_job_attempts, _WINDOW)
    rows = job_costs.build_costed_jobs_query(workflow_jobs.build_query(jobs))
    return _stored_rows(source, JOB_COLUMNS, rows)


def _first_created_query(table: str, depot: depot_ci.DepotJobAttempts | None, depot_column: str) -> str:
    github = f"SELECT min(nullIf(created_at, '')) AS created_at FROM {table}"
    if depot is None:
        return github
    return f"SELECT min(created_at) FROM ({github} UNION ALL {depot_ci.first_created(depot, depot_column)})"


@frozen
class StoredRows:
    """One table of stored rows. ``first_created`` gives a query for the raw creation time of the
    oldest row, the time the windows of ``insert_query`` compare."""

    table: LazyComputationTable
    insert_query: Callable[[JobSourceTables], str]
    first_created: Callable[[JobSourceTables], str]
    query_type: str


STORED_RUNS = StoredRows(
    table=LazyComputationTable.ENGINEERING_ANALYTICS_CI_RUNS_PRECOMPUTED,
    insert_query=_runs_insert_query,
    first_created=lambda source: _first_created_query(
        source.github_workflow_runs, source.depot_job_attempts, "workflow_created_at"
    ),
    query_type="engineering_analytics.ci_runs_precompute",
)
STORED_JOBS = StoredRows(
    table=LazyComputationTable.ENGINEERING_ANALYTICS_CI_JOBS_PRECOMPUTED,
    insert_query=_jobs_insert_query,
    first_created=lambda source: _first_created_query(
        source.github_workflow_jobs, source.depot_job_attempts, "attempt_started_at"
    ),
    query_type="engineering_analytics.ci_jobs_precompute",
)


def _max_age_schedule() -> TtlSchedule:
    # UTC bands, like the jobs: a cut at the team's midnight ages the previous UTC day too early.
    return parse_ttl_schedule(
        {
            "1d": _RECENT_DAYS_MAX_AGE_SECONDS,
            "7d": _LAST_WEEK_MAX_AGE_SECONDS,
            f"{RUN_LIFETIME.days}d": _RUN_LIFETIME_MAX_AGE_SECONDS,
            "default": _SETTLED_DAYS_MAX_AGE_SECONDS,
        },
        "UTC",
        max_window_days=1,
        default_ttl_jitter_seconds=_SETTLED_DAYS_MAX_AGE_SPREAD_SECONDS,
    )


def _history_start_key(stored: StoredRows, team: Team, source: JobSourceTables) -> str:
    return f"engineering_analytics:ci_history_start:{team.pk}:{stored.table}:{source.source_id}:{source.repository}"


def history_start(stored: StoredRows, team: Team, source: JobSourceTables) -> datetime | None:
    """The UTC day of the oldest raw row of one repository, as the last refresh found it, or None."""
    start = cache.get(_history_start_key(stored, team, source))
    return start if isinstance(start, datetime) else None


def _find_history_start(stored: StoredRows, team: Team, source: JobSourceTables, database: Database) -> datetime | None:
    response = execute_hogql_query(
        query=stored.first_created(source),
        team=team,
        query_type=f"{stored.query_type}.history_start",
        bypass_warehouse_access_control=True,
        context=HogQLContext(team_id=team.pk, bypass_warehouse_access_control=True, database=database),
    )
    first_created = response.results[0][0] if response.results else None
    try:
        start = datetime.strptime(str(first_created)[:10], "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        return None
    # No expiry: each refresh finds the first day again, and a team no one reads keeps its stored days.
    cache.set(_history_start_key(stored, team, source), start, timeout=None)
    return start


@frozen
class _Span:
    since: datetime
    until: datetime


def _newest_first(start: datetime, until: datetime | None = None, length: timedelta = _BACKFILL_STEP) -> list[_Span]:
    """The spans from ``start`` to ``until``, or to now, newest first, ``length`` long."""
    spans = []
    until = until or datetime.now(UTC)
    while until > start:
        since = max(start, until - length)
        spans.append(_Span(since=since, until=until))
        until = since
    return spans


def ensure_stored(
    stored: StoredRows,
    team: Team,
    source: JobSourceTables,
    *,
    since: datetime,
    until: datetime | None = None,
    database: Database | None = None,
    run_inserts: bool,
    stale_while_revalidate_seconds: float | None = None,
    wait_timeout_seconds: float = _REFRESH_BUDGET_SECONDS,
) -> LazyComputationResult:
    """The stored days of one repository from the day of ``since`` to ``until``, or to now.

    With ``run_inserts`` it stores each day that is missing or too old. Without, it only reports
    whether every day is stored.
    """
    return ensure_precomputed(
        team=team,
        insert_query=stored.insert_query(source),
        time_range_start=since,
        time_range_end=until or datetime.now(UTC),
        ttl_seconds=_max_age_schedule(),
        table=stored.table,
        query_type=stored.query_type,
        wait_timeout_seconds=wait_timeout_seconds,
        stale_while_revalidate_seconds=stale_while_revalidate_seconds,
        run_inserts=run_inserts,
        database=database,
    )


def _in_use_key(team: Team) -> str:
    return f"engineering_analytics:ci_precompute_in_use:{team.pk}"


def mark_in_use(team: Team) -> bool:
    """Mark a read of the team that can take the stored rows. True for the first such read in
    ``_IN_USE_SECONDS``, because no refresh kept the stored days current before it."""
    key = _in_use_key(team)
    if cache.add(key, True, timeout=_IN_USE_SECONDS):
        return True
    cache.touch(key, timeout=_IN_USE_SECONDS)
    return False


def refresh_after_load(team: Team) -> None:
    """Store the days that a data load made out of date, for every repository of the team that syncs
    both runs and jobs, while the team is in use. A load that lands while a refresh of the team runs
    starts no second one, and neither does a load that lands soon after an insert failed."""
    if not cache.get(_in_use_key(team)):
        return
    running = f"engineering_analytics:ci_precompute_refresh:{team.pk}"
    if not cache.add(running, True, timeout=REFRESH_TASK_TIME_LIMIT_SECONDS):
        return
    failed = True
    try:
        with tags_context(
            product=Product.ENGINEERING_ANALYTICS,
            feature=Feature.CACHE_WARMUP,
            team_id=team.pk,
        ):
            failed = _refresh(team)
    finally:
        if failed:
            cache.set(running, True, timeout=_FAILED_REFRESH_PAUSE_SECONDS)
        else:
            cache.delete(running)


def _refresh(team: Team) -> bool:
    """Whether an insert failed. A refresh that only ran out of its budget did not fail: the next
    load continues it."""
    sources = resolve_precompute_sources(team)
    if not sources:
        return False
    failed = False
    # One catalog for every insert: the framework otherwise builds the team's catalog for each day.
    database = Database.create_for(
        team=team,
        modifiers=create_default_modifiers_for_team(team),
        bypass_warehouse_access_control=True,
        trigger="engineering_analytics",
    )
    deadline = time.monotonic() + _TASK_BUDGET_SECONDS
    spans: list[tuple[StoredRows, JobSourceTables, list[_Span]]] = []
    for source in sources:
        for stored in (STORED_RUNS, STORED_JOBS):
            if time.monotonic() >= deadline:
                return failed
            try:
                start = _find_history_start(stored, team, source, database)
            except Exception:
                logger.warning(
                    "engineering_analytics_ci_history_start_failed",
                    team_id=team.pk,
                    table=str(stored.table),
                    source_id=source.source_id,
                    repository=source.repository,
                    exc_info=True,
                )
                failed = True
                continue
            if start is not None:
                spans.append((stored, source, _newest_first(start)))
    # Every table of every repository stores its newest step before any stores an older one, so the
    # backfill of one long history does not hold back the recent days of the others.
    while spans:
        for span in list(spans):
            stored, source, steps = span
            if not steps:
                spans.remove(span)
                continue
            step = steps.pop(0)
            if time.monotonic() >= deadline:
                return failed
            result = ensure_stored(
                stored,
                team,
                source,
                since=step.since,
                until=step.until,
                database=database,
                run_inserts=True,
                wait_timeout_seconds=min(_REFRESH_BUDGET_SECONDS, deadline - time.monotonic()),
            )
            if not result.ready:
                logger.warning(
                    "engineering_analytics_ci_precompute_incomplete",
                    team_id=team.pk,
                    table=str(stored.table),
                    source_id=source.source_id,
                    repository=source.repository,
                    errors=result.errors,
                )
                if result.timed_out:
                    spans.remove(span)
                    continue
                failed = True
                # The framework stores the days of a span oldest first and stops at the first day that
                # fails, so the newer days of a failed span are stored one at a time.
                if step.until - step.since > timedelta(days=1):
                    steps[0:0] = _newest_first(step.since, step.until, timedelta(days=1))
    return failed


# A read takes a stored day up to this long after a refresh would compute it again. A refresh runs
# after each data load, so a day older than this missed several loads.
_READ_GRACE_SECONDS = 40 * 60


class StoredCiReader:
    """The stored rows of one repository of one source, as subqueries for the reads of one request.

    Each method gives a subquery with the columns of the builder it stands for, or None when a day
    the read needs is not stored. ``floor`` is the date-only scan floor of the read, or None for a
    read of the whole history. The subquery still applies the floor placeholder of the builder, so it
    returns the rows the builder returns.

    A run is stored under the day it was created, and a re-run starts it again up to ``RUN_LIFETIME``
    later. So a read of runs, or of the runs that jobs belong to, needs the stored days from that
    long before its floor.
    """

    def __init__(self, team: Team, source: JobSourceTables) -> None:
        self._team = team
        self._source = source
        self._identity = (
            f"source_id = {source_literal(source.source_id)} AND repository = {repository_literal(source.repository)}"
        )
        self._days: dict[tuple[LazyComputationTable, datetime], str | None] = {}
        self._starts: dict[LazyComputationTable, datetime | None] = {}

    def runs(self, floor: str | None) -> str | None:
        rows = self._run_rows(floor)
        floored = " AND run_started_at_raw >= {run_started_floor}" if floor is not None else ""
        return rows and f"({rows}{floored})"

    def jobs(self, floor: str | None) -> str | None:
        rows = self._job_rows(floor, workflow_jobs.COLUMNS)
        return rows and f"({rows})"

    def job_costs(self, floor: str | None) -> str | None:
        jobs = self._job_rows(floor, JOB_COLUMNS)
        runs = self._run_rows(floor)
        if jobs is None or runs is None:
            return None
        return f"({job_costs.build_attributed_query(costed_jobs=jobs, runs=runs)})"

    def _run_rows(self, floor: str | None) -> str | None:
        stored = self._stored(STORED_RUNS, floor, reach=RUN_LIFETIME)
        if stored is None:
            return None
        columns = [column for column in RUN_COLUMNS if column not in depot_ci.WINDOWED_RUN_COLUMNS]
        return f"""
            SELECT {", ".join(columns)}, {workflow_runs.STOPPED_REPORTING_SQL} AS stopped_reporting
            FROM {STORED_RUNS.table}
            WHERE {stored} AND NOT is_handoff_shell
        """

    def _job_rows(self, floor: str | None, columns: tuple[str, ...]) -> str | None:
        stored = self._stored(STORED_JOBS, floor)
        stored_runs = self._stored(STORED_RUNS, floor, reach=RUN_LIFETIME)
        if stored is None or stored_runs is None:
            return None
        floored = " AND created_at_raw >= {job_created_floor}" if floor is not None else ""
        return f"""
            SELECT {", ".join(columns)}
            FROM {STORED_JOBS.table}
            WHERE {stored}{floored}
                AND (ci_engine, run_id) NOT IN (
                    SELECT ci_engine, id FROM {STORED_RUNS.table} WHERE {stored_runs} AND is_handoff_shell
                )
        """

    def _stored(self, stored: StoredRows, floor: str | None, *, reach: timedelta = timedelta(0)) -> str | None:
        """A predicate for the stored rows of this repository from ``reach`` before the floor, or from
        the first day of the history without a floor. None when a day in that span is not stored, the
        first day is not known, or the floor is not a date. No row is older than the first day, so a
        span that starts earlier starts there."""
        if stored.table not in self._starts:
            self._starts[stored.table] = history_start(stored, self._team, self._source)
        since = self._starts[stored.table]
        if since is None:
            return None
        if floor is not None:
            try:
                since = max(since, datetime.strptime(floor, "%Y-%m-%d").replace(tzinfo=UTC) - reach)
            except (ValueError, OverflowError):
                return None
        key = (stored.table, since)
        if key not in self._days:
            result = ensure_stored(
                stored,
                self._team,
                self._source,
                since=since,
                run_inserts=False,
                stale_while_revalidate_seconds=_READ_GRACE_SECONDS,
            )
            job_ids = ", ".join(f"'{UUID(str(job_id))}'" for job_id in result.job_ids)
            # A floor after today spans no day, so the check is ready with no job.
            servable = result.ready and bool(job_ids)
            self._days[key] = f"job_id IN ({job_ids}) AND {self._identity}" if servable else None
        return self._days[key]
