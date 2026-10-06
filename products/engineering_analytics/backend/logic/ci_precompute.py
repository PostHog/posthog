"""The stored CI rows: the output of the runs builder and of the jobs builder, kept in ClickHouse.

A read of the warehouse tables parses every payload and repeats the hand-off shell filter each time.
The lazy computation framework stores the parsed rows instead, one job for the rows that one
repository created on one day. A refresh after a data load computes only the days that are missing
or too old, so its cost follows the new data and not the history.

Each stored row depends only on raw rows created near its own day. That is why a job row carries its
cost, which reads no run column, and not the attribution of its run: a re-run moves the start of a
run, and a job row that copied it would keep the old value. A read joins the two tables.

A job covers one source and one repository. A repository that two GitHub sources sync is stored once
for each, with its Depot CI rows, and a read takes the rows of the one source it resolved.

The stored days are what a page range of 30 days reads. A read reaches one more span before its
range: a timeline also reads the CI from ``CI_LOOKBACK`` before it, and a comparison reads the
previous period. Three more days cover the day a read floors below its window, the whole date of a
floor, and the UTC day of a stored row. A longer range reads the warehouse tables.

A refresh computes a day again once its rows pass the age of their band. Most rows stop changing
within a day of their creation. A re-run or an expired run changes an older row, and the table shows
it after that age. The older days are first stored together, so their ages are spread, or they would
all expire in one refresh.
"""

import time
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from django.core.cache import cache

import structlog

from posthog.hogql.database.database import Database
from posthog.hogql.escape_sql import escape_hogql_string
from posthog.hogql.modifiers import create_default_modifiers_for_team

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.dataclasses import frozen
from posthog.models.team import Team

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    WAIT_TIMEOUT_ERROR,
    LazyComputationResult,
    LazyComputationTable,
    TtlSchedule,
    ensure_precomputed,
    parse_ttl_schedule,
)
from products.engineering_analytics.backend.facade.contracts import STORED_READS_FEATURE_FLAG
from products.engineering_analytics.backend.logic.feature_flags import team_flag
from products.engineering_analytics.backend.logic.queries._workflow_filters import (
    CI_LOOKBACK,
    JOB_FLOOR_SLACK_ON_RUN_STARTED,
)
from products.engineering_analytics.backend.logic.sources import JobSourceTables, resolve_precompute_sources
from products.engineering_analytics.backend.logic.views import depot_ci, job_costs, workflow_jobs, workflow_runs
from products.engineering_analytics.backend.logic.views.created_window import CreatedWindow

logger = structlog.get_logger(__name__)

_LONGEST_STORED_RANGE = timedelta(days=30)
_FLOOR_MARGIN = timedelta(days=3)
_LOWEST_RUN_STARTED_FLOOR = _LONGEST_STORED_RANGE + max(_LONGEST_STORED_RANGE, CI_LOOKBACK) + _FLOOR_MARGIN

# GitHub ends a workflow run after 35 days, so a run was created at most that long before its newest
# start and before any of its jobs.
RUN_LIFETIME = timedelta(days=35)

STORED_JOB_DAYS = _LOWEST_RUN_STARTED_FLOOR + JOB_FLOOR_SLACK_ON_RUN_STARTED
STORED_RUN_DAYS = STORED_JOB_DAYS + RUN_LIFETIME

_RECENT_DAYS_MAX_AGE_SECONDS = 15 * 60
_LAST_WEEK_MAX_AGE_SECONDS = 6 * 60 * 60
_OLDER_DAYS_MAX_AGE_SECONDS = 5 * 24 * 60 * 60
_OLDER_DAYS_MAX_AGE_SPREAD_SECONDS = 2 * 24 * 60 * 60

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


def _raw_day(moment: str) -> str:
    return f"formatDateTime(toTimeZone({moment}, 'UTC'), '%Y-%m-%d')"


_RERUN_SLACK_DAYS = JOB_FLOOR_SLACK_ON_RUN_STARTED.days

_WINDOW = CreatedWindow(
    start=_raw_day("{time_window_min}"),
    end=_raw_day("{time_window_max}"),
    earlier_start=_raw_day(f"{{time_window_min}} - INTERVAL {_RERUN_SLACK_DAYS} DAY"),
    later_end=_raw_day(f"{{time_window_max}} + INTERVAL {_RERUN_SLACK_DAYS} DAY"),
)

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
    )
    rows = workflow_runs.build_query(
        runs, pull_requests_table=source.pull_requests, passthrough=depot_ci.WINDOWED_RUN_COLUMNS
    )
    return _stored_rows(source, RUN_COLUMNS, rows)


def _jobs_insert_query(source: JobSourceTables) -> str:
    jobs = depot_ci.windowed_jobs(source.github_workflow_jobs, source.depot_job_attempts, _WINDOW)
    rows = job_costs.build_costed_jobs_query(workflow_jobs.build_query(jobs))
    return _stored_rows(source, JOB_COLUMNS, rows)


@frozen
class StoredRows:
    """One table of stored rows."""

    table: LazyComputationTable
    insert_query: Callable[[JobSourceTables], str]
    days: timedelta
    query_type: str


STORED_RUNS = StoredRows(
    table=LazyComputationTable.ENGINEERING_ANALYTICS_CI_RUNS_PRECOMPUTED,
    insert_query=_runs_insert_query,
    days=STORED_RUN_DAYS,
    query_type="engineering_analytics.ci_runs_precompute",
)
STORED_JOBS = StoredRows(
    table=LazyComputationTable.ENGINEERING_ANALYTICS_CI_JOBS_PRECOMPUTED,
    insert_query=_jobs_insert_query,
    days=STORED_JOB_DAYS,
    query_type="engineering_analytics.ci_jobs_precompute",
)


def _max_age_schedule() -> TtlSchedule:
    # UTC bands, like the jobs: a cut at the team's midnight ages the previous UTC day too early.
    return parse_ttl_schedule(
        {"1d": _RECENT_DAYS_MAX_AGE_SECONDS, "7d": _LAST_WEEK_MAX_AGE_SECONDS, "default": _OLDER_DAYS_MAX_AGE_SECONDS},
        "UTC",
        max_window_days=1,
        default_ttl_jitter_seconds=_OLDER_DAYS_MAX_AGE_SPREAD_SECONDS,
    )


def ensure_stored(
    stored: StoredRows,
    team: Team,
    source: JobSourceTables,
    *,
    since: datetime,
    database: Database | None = None,
    run_inserts: bool,
    stale_while_revalidate_seconds: float | None = None,
    wait_timeout_seconds: float = _REFRESH_BUDGET_SECONDS,
) -> LazyComputationResult:
    """The stored days of one repository from the day of ``since`` to now.

    With ``run_inserts`` it stores each day that is missing or too old. Without, it only reports
    whether every day is stored.
    """
    return ensure_precomputed(
        team=team,
        insert_query=stored.insert_query(source),
        time_range_start=since,
        time_range_end=datetime.now(UTC),
        ttl_seconds=_max_age_schedule(),
        table=stored.table,
        query_type=stored.query_type,
        wait_timeout_seconds=wait_timeout_seconds,
        stale_while_revalidate_seconds=stale_while_revalidate_seconds,
        run_inserts=run_inserts,
        database=database,
    )


def refresh_after_load(team: Team) -> None:
    """Store the days that a data load made out of date, for every repository of the team that syncs
    both runs and jobs. A load that lands while a refresh of the team runs starts no second one, and
    neither does a load that lands soon after an insert failed."""
    if not team_flag(STORED_READS_FEATURE_FLAG, team):
        return
    running = f"engineering_analytics:ci_precompute_refresh:{team.pk}"
    if not cache.add(running, True, timeout=REFRESH_TASK_TIME_LIMIT_SECONDS):
        return
    failed = True
    try:
        with tags_context(product=Product.ENGINEERING_ANALYTICS, feature=Feature.PREAGGREGATION, team_id=team.pk):
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
    for source in sources:
        for stored in (STORED_RUNS, STORED_JOBS):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return failed
            result = ensure_stored(
                stored,
                team,
                source,
                since=datetime.now(UTC) - stored.days,
                database=database,
                run_inserts=True,
                wait_timeout_seconds=min(_REFRESH_BUDGET_SECONDS, remaining),
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
                failed = failed or any(error != WAIT_TIMEOUT_ERROR for error in result.errors)
    return failed


# A read takes a stored day up to this long after a refresh would compute it again. A refresh runs
# after each data load, so a day older than this missed several loads.
_READ_GRACE_SECONDS = 40 * 60


class StoredCiReader:
    """The stored rows of one repository of one source, as subqueries for the reads of one request.

    Each method gives a subquery with the columns of the builder it stands for, or None when a day
    the read needs is not stored. ``floor`` is the date-only scan floor of the read. The subquery
    still applies the floor placeholder of the builder, so it returns the rows the builder returns.

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
        self._lock = threading.Lock()

    def runs(self, floor: str) -> str | None:
        rows = self._run_rows(floor)
        return rows and f"({rows} AND run_started_at_raw >= {{run_started_floor}})"

    def jobs(self, floor: str) -> str | None:
        rows = self._job_rows(floor, workflow_jobs.COLUMNS)
        return rows and f"({rows})"

    def job_costs(self, floor: str) -> str | None:
        jobs = self._job_rows(floor, JOB_COLUMNS)
        runs = self._run_rows(floor)
        if jobs is None or runs is None:
            return None
        return f"({job_costs.build_attributed_query(costed_jobs=jobs, runs=runs)})"

    def _run_rows(self, floor: str) -> str | None:
        stored = self._stored(STORED_RUNS, floor, reach=RUN_LIFETIME)
        if stored is None:
            return None
        columns = [column for column in RUN_COLUMNS if column not in depot_ci.WINDOWED_RUN_COLUMNS]
        return f"""
            SELECT {", ".join(columns)}, {workflow_runs.STOPPED_REPORTING_SQL} AS stopped_reporting
            FROM {STORED_RUNS.table}
            WHERE {stored} AND NOT is_handoff_shell
        """

    def _job_rows(self, floor: str, columns: tuple[str, ...]) -> str | None:
        stored = self._stored(STORED_JOBS, floor)
        stored_runs = self._stored(STORED_RUNS, floor, reach=RUN_LIFETIME)
        if stored is None or stored_runs is None:
            return None
        return f"""
            SELECT {", ".join(columns)}
            FROM {STORED_JOBS.table}
            WHERE {stored} AND created_at_raw >= {{job_created_floor}}
                AND (ci_engine, run_id) NOT IN (
                    SELECT ci_engine, id FROM {STORED_RUNS.table} WHERE {stored_runs} AND is_handoff_shell
                )
        """

    def _stored(self, stored: StoredRows, floor: str, *, reach: timedelta = timedelta(0)) -> str | None:
        """A predicate for the stored rows of this repository from ``reach`` before the floor, or None
        when a day in that span is not stored or the floor is not a date."""
        try:
            since = datetime.strptime(floor, "%Y-%m-%d").replace(tzinfo=UTC) - reach
        except ValueError:
            return None
        # A floor below the stored days can never be served, and a lookup from a far-off floor
        # walks every day up to now.
        if since.date() < (datetime.now(UTC) - stored.days).date():
            return None
        key = (stored.table, since)
        with self._lock:
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
