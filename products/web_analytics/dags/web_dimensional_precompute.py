"""Scheduled population of the fixed-dimension web precompute tables.

This job drives the precomputation framework: for each selected team it calls
`ensure_*_dimensional_precomputed` over a rolling window, and the
framework splits that into daily jobs, tracks them in Postgres
(`PreaggregationJob`) and only (re)computes windows whose jobs have expired. So
the heavy raw-table scan happens on a schedule for a known audience rather than
lazily on every user query, while re-runs are cheap because already-fresh
windows are skipped.

Rollout is intentionally decoupled from the v2 pre-aggregation pipeline and its
team selection. The audience defaults to a small per-region built-in rollout list
(`DEFAULT_ROLLOUT_TEAM_IDS_BY_REGION`) on PostHog Cloud, and is fully overridable via the
`WEB_DIMENSIONAL_PRECOMPUTE_TEAM_IDS` env var (comma-separated team IDs; set it
to empty to disable the job). Self-hosted instances default to no teams so the
job never precomputes for unrelated teams that happen to share those IDs. There
is no dependency on the v2 team-selection dictionary or flag.

The write path is not yet wired into any query runner — this job only populates
the tables (so the new output can be compared with v2's side by side).

After the writers, a coverage check reads the READY jobs back from Postgres and
fails the run when a team has a day without a fresh job or a stale current day.
A failed run alerts the job owner through `notify_slack_on_failure`.
"""

import os
from collections.abc import Iterable
from datetime import UTC, date, datetime, time, timedelta

from django.conf import settings

import dagster
import structlog
from prometheus_client import Counter, Gauge

from posthog.cloud_utils import is_cloud
from posthog.dags.common import JobOwners, chunk_ranges, skip_on_kill_switch
from posthog.dataclasses import frozen
from posthog.metrics import pushed_metrics_registry
from posthog.models import Team

from products.analytics_platform.backend.models.preaggregation_job import PreaggregationJob
from products.web_analytics.backend.hogql_queries.web_dimensional_precompute import (
    DIMENSIONAL_TTL_SECONDS,
    ensure_web_bounces_dimensional_precomputed,
    ensure_web_stats_dimensional_precomputed,
)
from products.web_analytics.dags.web_preaggregated_utils import check_for_concurrent_runs

logger = structlog.get_logger(__name__)

# Rolling window kept warm, so that a later read path can serve any sub-window
# without falling back to raw tables. Sized independently of the lazy precompute
# `MAX_PRECOMPUTE_DAYS`, because this window is a fixed cost the dag pays for
# every enrolled team, not a per-shape span the tenant's own demand bounds.
# Widen it through the env var once the storage cost is agreed.
# A `-90d` read starts at the team's local midnight 90 days back, and the window ends at the next UTC
# midnight. 92 UTC days hold that start for every UTC offset from -12h to +14h. 91 days hold it only
# for a team in UTC.
PRECOMPUTE_WINDOW_DAYS = int(os.getenv("WEB_DIMENSIONAL_PRECOMPUTE_WINDOW_DAYS", "92"))

# Each ensure_precomputed call covers at most this many days. The framework merges
# a fully-missing range into ONE INSERT, so without chunking a cold backfill would
# scan the entire window (e.g. 90 days of raw sessions+events) in a single query —
# the real memory/overload risk for a high-volume team. Chunking bounds each INSERT's
# scan; combined with the job's max_runtime and ensure_precomputed's idempotency, a
# cold backfill self-paces across runs (a killed run resumes from the first unfilled
# chunk). Defaults to 1 so every INSERT scans a single UTC day — the safest memory
# profile, matching v2's per-day partition granularity. Raise via the env var to
# trade more bytes/INSERT for fewer INSERTs on lower-volume teams.
PRECOMPUTE_CHUNK_DAYS = int(os.getenv("WEB_DIMENSIONAL_PRECOMPUTE_CHUNK_DAYS", "1"))

# Built-in rollout audience used when the env var is unset, keyed by Cloud region.
# Region-keyed because team IDs are not unique across US and EU — a single flat list
# would enroll an unrelated same-ID team in the other region. Applied on PostHog
# Cloud only (see get_selected_team_ids). US holds the dogfood project (2), the
# high-volume pilot (55348), and the teams currently reading the v2 tables, for the
# v2 side-by-side.
DEFAULT_ROLLOUT_TEAM_IDS_BY_REGION: dict[str, list[int]] = {
    "US": [2, 39058, 47074, 55348],
    "EU": [1, 1589, 126918],
}

# Comma-separated team IDs to precompute. Overrides the per-region default;
# set to empty to disable the job entirely.
SELECTED_TEAM_IDS_ENV_VAR = "WEB_DIMENSIONAL_PRECOMPUTE_TEAM_IDS"

SCHEDULE_INTERVAL_MINUTES = 20

# A day counts as covered while its newest READY job is at most two runs past its expiry. The check
# runs after the writers, so a job that expires between the write and the check must not fail it.
COVERAGE_GRACE_SECONDS = 2 * SCHEDULE_INTERVAL_MINUTES * 60

# The current day's job stays fresh for its whole TTL, so its age reaches the TTL in a healthy run.
# Alert only when it is also two runs past that.
TODAY_MAX_LAG_SECONDS = DIMENSIONAL_TTL_SECONDS["0d"] + COVERAGE_GRACE_SECONDS

STATS_TABLE = "web_stats_dimensional_preaggregated"
BOUNCES_TABLE = "web_bounces_dimensional_preaggregated"

# Run pods exit after the run, so nothing scrapes their in-process registry. The gauges go through
# the push gateway instead, under this group name. A push replaces every gauge of the group.
COVERAGE_METRICS_JOB = "web_dimensional_precompute_coverage"
COVERAGE_MISSING_DAYS_GAUGE = "web_dimensional_precompute_coverage_missing_days"
COVERAGE_TODAY_LAG_GAUGE = "web_dimensional_precompute_today_lag_seconds"


def get_selected_team_ids() -> list[int]:
    """Resolve the team allowlist.

    The env var wins if set (even to empty): a comma-separated list, blank/invalid
    entries skipped. If unset, fall back to the current region's default — but only
    on PostHog Cloud; self-hosted defaults to none so the job never runs for
    unrelated teams that happen to share those IDs.
    """
    raw = os.getenv(SELECTED_TEAM_IDS_ENV_VAR)
    if raw is not None:
        return [int(part.strip()) for part in raw.split(",") if part.strip().isdigit()]
    if not is_cloud():
        return []
    region = (settings.CLOUD_DEPLOYMENT or "").upper()
    return list(DEFAULT_ROLLOUT_TEAM_IDS_BY_REGION.get(region, []))


WEB_DIMENSIONAL_PRECOMPUTE_TEAM_DONE = Counter(
    "web_dimensional_precompute_team_done_total",
    "Teams whose dimensional precompute window was ensured, by table.",
    ["table"],
)
WEB_DIMENSIONAL_PRECOMPUTE_TEAM_FAILED = Counter(
    "web_dimensional_precompute_team_failed_total",
    "Teams whose dimensional precompute failed, by table and exception type.",
    ["table", "error_type"],
)


@frozen
class TimeSpan:
    start: datetime
    end: datetime


def precompute_window(now: datetime) -> TimeSpan:
    # chunk_ranges slices backwards from `end`, so ending on a UTC midnight makes every chunk one UTC
    # day. The framework builds one job per UTC day, and a chunk that straddles midnight merges two
    # missing days into a single INSERT that reads twice the data.
    end = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    return TimeSpan(start=end - timedelta(days=PRECOMPUTE_WINDOW_DAYS), end=end)


@frozen
class DimensionalPrecomputeRun:
    teams: int
    failures: int
    team_ids: tuple[int, ...]
    # The window the writers requested and the UTC day they treated as current. The coverage check
    # reads these instead of its own clock: a run that crosses UTC midnight would otherwise look for
    # a day no writer was asked to build.
    window: TimeSpan
    current_day: date
    # One job id per (team id, table) from the writers of this run. The coverage check reads its
    # query_hash, because the executor derives the hash from the INSERT template and has no public
    # helper for it.
    sample_job_ids: dict[tuple[int, str], str]


@frozen
class TableCoverage:
    team_id: int
    table: str
    window_days: int
    missing_days: tuple[date, ...]
    # None when no READY job covers the writer's current UTC day.
    today_lag_seconds: float | None

    @property
    def covered_days(self) -> int:
        return self.window_days - len(self.missing_days)

    @property
    def healthy(self) -> bool:
        return (
            not self.missing_days
            and self.today_lag_seconds is not None
            and self.today_lag_seconds <= TODAY_MAX_LAG_SECONDS
        )

    def describe(self) -> str:
        lag = "none" if self.today_lag_seconds is None else f"{round(self.today_lag_seconds / 60)}m"
        missing = ",".join(d.isoformat() for d in self.missing_days[:10])
        if len(self.missing_days) > 10:
            missing += ",..."
        return (
            f"team={self.team_id} table={self.table} covered={self.covered_days}/{self.window_days} "
            f"missing=[{missing}] today_lag={lag}"
        )


def _merge_spans(spans: Iterable[TimeSpan]) -> list[TimeSpan]:
    merged: list[TimeSpan] = []
    for span in sorted(spans, key=lambda s: s.start):
        if merged and span.start <= merged[-1].end:
            merged[-1] = TimeSpan(start=merged[-1].start, end=max(merged[-1].end, span.end))
        else:
            merged.append(span)
    return merged


def summarize_coverage(
    *,
    team_id: int,
    table: str,
    ready_jobs: Iterable[PreaggregationJob],
    window: TimeSpan,
    current_day: date,
    now: datetime,
) -> TableCoverage:
    """Report which UTC days of the window have a fresh READY job, and how old the current day's job is.

    `window` and `current_day` come from the writer; `now` is the check's own clock and only drives
    freshness and lag. Jobs can span more than one day, so the check merges the job intervals instead
    of counting job start dates.
    """
    jobs = list(ready_jobs)
    fresh_cutoff = now - timedelta(seconds=COVERAGE_GRACE_SECONDS)
    merged = _merge_spans(
        TimeSpan(start=job.time_range_start, end=job.time_range_end)
        for job in jobs
        if job.expires_at is not None and job.expires_at >= fresh_cutoff
    )

    missing: list[date] = []
    day = window.start
    while day < window.end:
        day_end = day + timedelta(days=1)
        if not any(span.start <= day and span.end >= day_end for span in merged):
            missing.append(day.date())
        day = day_end

    today_start = datetime.combine(current_day, time(), tzinfo=UTC)
    today_end = today_start + timedelta(days=1)
    today_built_at = [
        job.computed_at or job.created_at
        for job in jobs
        if job.time_range_start <= today_start and job.time_range_end >= today_end
    ]
    today_lag = (now - max(today_built_at)).total_seconds() if today_built_at else None

    return TableCoverage(
        team_id=team_id,
        table=table,
        window_days=(window.end - window.start).days,
        missing_days=tuple(missing),
        today_lag_seconds=today_lag,
    )


def find_table_coverage(
    *,
    team_id: int,
    table: str,
    query_hash: str | None,
    window: TimeSpan,
    current_day: date,
    now: datetime,
) -> TableCoverage:
    # Expired READY jobs stay in the result, so the current day's lag still shows the age of the
    # newest build after its job expired.
    ready_jobs: list[PreaggregationJob] = []
    if query_hash is not None:
        ready_jobs = list(
            PreaggregationJob.objects.filter(
                team_id=team_id,
                query_hash=query_hash,
                status=PreaggregationJob.Status.READY,
                time_range_start__lt=window.end,
                time_range_end__gt=window.start,
            )
        )
    return summarize_coverage(
        team_id=team_id,
        table=table,
        ready_jobs=ready_jobs,
        window=window,
        current_day=current_day,
        now=now,
    )


def _push_coverage_gauges(coverages: list[TableCoverage]) -> None:
    with pushed_metrics_registry(COVERAGE_METRICS_JOB) as registry:
        missing_days = Gauge(
            COVERAGE_MISSING_DAYS_GAUGE,
            "UTC days in the dimensional precompute window without a fresh READY job.",
            ["team_id", "table"],
            registry=registry,
        )
        today_lag = Gauge(
            COVERAGE_TODAY_LAG_GAUGE,
            "Age of the newest READY dimensional precompute job that covers the writer's current UTC day.",
            ["team_id", "table"],
            registry=registry,
        )
        for coverage in coverages:
            labels = {"team_id": str(coverage.team_id), "table": coverage.table}
            missing_days.labels(**labels).set(len(coverage.missing_days))
            # A current day without any job reads as infinitely stale, so a lag alert fires on it too.
            today_lag.labels(**labels).set(
                coverage.today_lag_seconds if coverage.today_lag_seconds is not None else float("inf")
            )


def _ensure_for_team(
    context: dagster.OpExecutionContext,
    team: Team,
    window: TimeSpan,
    chunk_days: int,
    sample_job_ids: dict[tuple[int, str], str],
) -> int:
    """Ensure both dimensional tables for one team, one bounded chunk at a time.

    Each chunk is a separate ensure_precomputed call (one INSERT scanning at most
    `chunk_days` of raw data), so no single query scans the whole window. Failures
    per (table, chunk) are caught so one bad chunk doesn't poison the rest;
    already-fresh chunks are cheap PG cache-checks with no INSERT.
    """
    failures = 0
    for table_label, ensure_fn in (
        (STATS_TABLE, ensure_web_stats_dimensional_precomputed),
        (BOUNCES_TABLE, ensure_web_bounces_dimensional_precomputed),
    ):
        for chunk_start, chunk_end in chunk_ranges(window.start, window.end, chunk_days):
            try:
                result = ensure_fn(team, chunk_start, chunk_end)
            except Exception as exc:
                WEB_DIMENSIONAL_PRECOMPUTE_TEAM_FAILED.labels(table=table_label, error_type=type(exc).__name__).inc()
                context.log.exception(
                    f"web_dimensional_precompute_failed team={team.pk} table={table_label} "
                    f"chunk=[{chunk_start}, {chunk_end})"
                )
                failures += 1
                continue
            # The executor catches a failed INSERT, marks the job FAILED and returns ready=False
            # instead of raising.
            if not result.ready:
                error_type = "memory_limit_exceeded" if result.memory_exceeded else "not_ready"
                WEB_DIMENSIONAL_PRECOMPUTE_TEAM_FAILED.labels(table=table_label, error_type=error_type).inc()
                context.log.warning(
                    f"web_dimensional_precompute_not_ready team={team.pk} table={table_label} "
                    f"chunk=[{chunk_start}, {chunk_end}) errors={result.errors}"
                )
                failures += 1
                continue
            WEB_DIMENSIONAL_PRECOMPUTE_TEAM_DONE.labels(table=table_label).inc()
            if result.job_ids:
                sample_job_ids.setdefault((team.pk, table_label), str(result.job_ids[0]))
    return failures


@dagster.op
def ensure_web_dimensional_precompute_op(context: dagster.OpExecutionContext) -> DimensionalPrecomputeRun:
    """Drive `ensure_*_dimensional_precomputed` over the rolling window for each selected team."""
    started_at = datetime.now(UTC)
    window = precompute_window(started_at)
    current_day = started_at.date()

    team_ids = get_selected_team_ids()
    context.log.info(
        f"web_dimensional_precompute_start teams={len(team_ids)} window=[{window.start}, {window.end}) "
        f"chunk_days={PRECOMPUTE_CHUNK_DAYS}"
    )
    if not team_ids:
        context.log.info(f"web_dimensional_precompute_noop ({SELECTED_TEAM_IDS_ENV_VAR} is empty)")
        context.add_output_metadata({"teams": 0, "failures": 0})
        return DimensionalPrecomputeRun(
            teams=0, failures=0, team_ids=(), sample_job_ids={}, window=window, current_day=current_day
        )

    teams_by_id = {t.pk: t for t in Team.objects.filter(pk__in=team_ids)}

    failures = 0
    processed: list[int] = []
    sample_job_ids: dict[tuple[int, str], str] = {}
    for team_id in team_ids:
        team = teams_by_id.get(team_id)
        if team is None:
            context.log.warning(f"web_dimensional_precompute_team_missing team_id={team_id}")
            continue
        failures += _ensure_for_team(context, team, window, PRECOMPUTE_CHUNK_DAYS, sample_job_ids)
        processed.append(team_id)

    context.log.info(f"web_dimensional_precompute_complete teams={len(processed)} failures={failures}")
    context.add_output_metadata({"teams": len(processed), "failures": failures})
    return DimensionalPrecomputeRun(
        teams=len(processed),
        failures=failures,
        team_ids=tuple(processed),
        sample_job_ids=sample_job_ids,
        window=window,
        current_day=current_day,
    )


@dagster.op
def check_web_dimensional_precompute_coverage_op(
    context: dagster.OpExecutionContext, run: DimensionalPrecomputeRun
) -> None:
    """Fail the run when a processed team has a missing day or a stale current day in either table."""
    now = datetime.now(UTC)
    query_hash_by_job_id = {
        str(job_id): query_hash
        for job_id, query_hash in PreaggregationJob.objects.filter(
            id__in=list(run.sample_job_ids.values())
        ).values_list("id", "query_hash")
    }

    coverages: list[TableCoverage] = []
    for team_id in run.team_ids:
        for table in (STATS_TABLE, BOUNCES_TABLE):
            job_id = run.sample_job_ids.get((team_id, table))
            coverages.append(
                find_table_coverage(
                    team_id=team_id,
                    table=table,
                    query_hash=query_hash_by_job_id.get(job_id) if job_id is not None else None,
                    window=run.window,
                    current_day=run.current_day,
                    now=now,
                )
            )

    _push_coverage_gauges(coverages)
    unhealthy = [coverage for coverage in coverages if not coverage.healthy]
    metadata: dict[str, dagster.MetadataValue] = {
        "checked": dagster.MetadataValue.int(len(coverages)),
        "unhealthy": dagster.MetadataValue.int(len(unhealthy)),
        "details": dagster.MetadataValue.md("\n".join(f"- {c.describe()}" for c in coverages) or "none"),
    }
    if unhealthy:
        raise dagster.Failure(
            description=(
                f"Dimensional precompute coverage is incomplete for {len(unhealthy)} of {len(coverages)} "
                "team tables: " + "; ".join(c.describe() for c in unhealthy)
            ),
            metadata=metadata,
        )
    context.log.info(f"web_dimensional_precompute_coverage_ok checked={len(coverages)}")
    context.add_output_metadata(metadata)


@dagster.job(
    description=(
        f"Populates the fixed-dimension web precompute tables (web_stats_dimensional_preaggregated / "
        f"web_bounces_dimensional_preaggregated) over the trailing {PRECOMPUTE_WINDOW_DAYS} days for the teams in "
        f"the {SELECTED_TEAM_IDS_ENV_VAR} allowlist, by driving the precomputation framework's ensure_precomputed. "
        f"No-op when the allowlist is empty. Re-runs only recompute windows whose jobs have expired. "
        f"Fails when a team has a UTC day without a fresh job, or a current-day job older than "
        f"{TODAY_MAX_LAG_SECONDS // 60} minutes."
    ),
    tags={
        "owner": JobOwners.TEAM_WEB_ANALYTICS.value,
        "dagster/max_runtime": str(2 * 60 * 60),
    },
)
def web_dimensional_precompute_job():
    check_web_dimensional_precompute_coverage_op(ensure_web_dimensional_precompute_op())


@dagster.schedule(
    # The current day's job expires after an hour (see DIMENSIONAL_TTL_SECONDS), and a run rebuilds
    # it only once it has expired. A 20-minute cadence bounds that gap to one interval; older
    # windows are computed once and skipped. The minute offsets keep clear of the sibling web
    # analytics schedules. check_for_concurrent_runs skips a tick while a run is still active, so a
    # slow run does not stack up behind it.
    cron_schedule="7,27,47 * * * *",
    job=web_dimensional_precompute_job,
    execution_timezone="UTC",
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
@skip_on_kill_switch
def web_dimensional_precompute_schedule(
    context: dagster.ScheduleEvaluationContext,
) -> "dagster.RunRequest | dagster.SkipReason":
    skip_reason = check_for_concurrent_runs(context)
    if skip_reason:
        return skip_reason
    return dagster.RunRequest()
