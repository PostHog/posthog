"""Census of teams whose experiment queries would benefit from precomputation.

Finds teams whose experiment metric reads run as direct event scans only because the
team is not enrolled in precomputation (`experiment_precompute_skip_reason = 'team_disabled'`),
measures their pain over a trailing window, and reports the ones crossing the enrollment
criteria. Report-only: this module never writes to `TeamExperimentsConfig`.
"""

from django.db.models import Count

import structlog

from posthog.clickhouse.client import sync_execute
from posthog.dataclasses import frozen

from products.experiments.backend.models.experiment import Experiment

logger = structlog.get_logger(__name__)

CENSUS_WINDOW_DAYS = 14

# A team must have this many direct-scan reads in the window for precomputation to have
# enough repeat traffic to amortize its builds. Nightly recalculation counts, deliberately:
# recalc is where precompute saves the most.
MIN_DIRECT_READS = 50

# Pain thresholds. Any one qualifies a team (given MIN_DIRECT_READS).
SLOW_READ_MS = 15_000
SLOW_READ_FRACTION = 0.10
TOTAL_READ_BYTES_THRESHOLD = 5 * 10**12  # 5 TB rescanned per window
HARD_FAILURE_CODES = (159, 241)  # TIMEOUT_EXCEEDED, MEMORY_LIMIT_EXCEEDED
HARD_FAILURES_THRESHOLD = 5

# A single read this large means the team's full-window scans approach the per-query byte
# cap, so precompute build INSERTs over the same events likely would too. Enrolling such a
# team burns ClickHouse on failing builds (error 307) with no speedup; keep them out until
# build window chunking can handle them.
BUILD_CAP_EXCLUSION_BYTES = int(2.5 * 10**12)

EXCLUSION_BUILD_BYTE_CAP = "build_byte_cap"

# Reads query_log_archive, not system.query_log: the archive outlives query_log's short
# retention and stores log_comment as a typed JSON column. The lc_product prefilter keeps
# the scan small enough for one query over the full window; the raw system.query_log
# needed day-chunking to stay under the per-query byte cap.
# Slow-read and duration stats only count successful reads — failed ones have truncated durations.
CENSUS_SQL = """
    SELECT
        team_id,
        count() AS direct_reads,
        countIf(query_duration_ms > %(slow_read_ms)s AND exception_code = 0) AS slow_reads,
        max(read_bytes) AS max_read_bytes,
        sum(read_bytes) AS total_read_bytes,
        countIf(exception_code IN %(hard_failure_codes)s) AS hard_failures,
        uniqExact(lc_experiment_id) AS experiment_count
    FROM query_log_archive
    WHERE event_date >= toDate(now() - INTERVAL %(window_days)s DAY)
        AND event_time > now() - INTERVAL %(window_days)s DAY
        AND lc_product = 'experiments'
        AND toString(log_comment.experiment_query_surface) = 'metric'
        AND ifNull(toString(log_comment.experiment_exposures_path), '') = 'direct_scan'
        AND ifNull(toString(log_comment.experiment_precompute_skip_reason), '') = 'team_disabled'
        AND is_initial_query
        AND toInt8(type) > 1
    GROUP BY team_id
    HAVING direct_reads >= %(min_direct_reads)s
    SETTINGS skip_unavailable_shards=1
"""


@frozen
class TeamDirectScanStats:
    """Aggregated direct-scan pain for one team over the census window."""

    team_id: int
    direct_reads: int
    slow_reads: int
    max_read_bytes: int
    total_read_bytes: int
    hard_failures: int
    experiment_count: int


@frozen
class EnrollmentCandidate:
    stats: TeamDirectScanStats
    reasons: tuple[str, ...]
    # Projected nightly build load: recalculation, not human views, is what turns
    # enrollment into daily spend.
    running_experiments: int
    running_metrics: int


@frozen
class ExcludedTeam:
    stats: TeamDirectScanStats
    reason: str


@frozen
class TeamRunningLoad:
    running_experiments: int
    running_metrics: int


@frozen
class EnrollmentCensusReport:
    window_days: int
    evaluated_teams: int
    candidates: tuple[EnrollmentCandidate, ...]
    excluded: tuple[ExcludedTeam, ...]


def qualifying_reasons(stats: TeamDirectScanStats) -> tuple[str, ...]:
    """Which enrollment criteria the team crosses; empty means it does not qualify."""
    if stats.direct_reads < MIN_DIRECT_READS:
        return ()
    reasons = []
    if stats.slow_reads / stats.direct_reads > SLOW_READ_FRACTION:
        reasons.append("slow_reads")
    if stats.total_read_bytes > TOTAL_READ_BYTES_THRESHOLD:
        reasons.append("scan_volume")
    if stats.hard_failures >= HARD_FAILURES_THRESHOLD:
        reasons.append("hard_failures")
    return tuple(reasons)


def exclusion_reason(stats: TeamDirectScanStats) -> str | None:
    if stats.max_read_bytes > BUILD_CAP_EXCLUSION_BYTES:
        return EXCLUSION_BUILD_BYTE_CAP
    return None


def fetch_direct_scan_stats(window_days: int) -> list[TeamDirectScanStats]:
    rows = sync_execute(
        CENSUS_SQL,
        {
            "window_days": window_days,
            "slow_read_ms": SLOW_READ_MS,
            "hard_failure_codes": HARD_FAILURE_CODES,
            "min_direct_reads": MIN_DIRECT_READS,
        },
    )
    return [
        TeamDirectScanStats(
            team_id=row[0],
            direct_reads=row[1],
            slow_reads=row[2],
            max_read_bytes=row[3],
            total_read_bytes=row[4],
            hard_failures=row[5],
            experiment_count=row[6],
        )
        for row in rows
    ]


def running_experiment_load(team_ids: list[int]) -> dict[int, TeamRunningLoad]:
    """Per team: running experiment count and metric count across them.

    Counts inline, secondary, and saved metrics — the same set nightly recalculation
    resolves — so the projected build load matches what enrollment would actually run.
    """
    load: dict[int, TeamRunningLoad] = {}
    experiments = (
        Experiment.objects.filter(team_id__in=team_ids, start_date__isnull=False, end_date__isnull=True)
        .exclude(deleted=True)
        .annotate(saved_metric_count=Count("experimenttosavedmetric"))
        .values_list("team_id", "metrics", "metrics_secondary", "saved_metric_count")
    )
    for team_id, metrics, metrics_secondary, saved_metric_count in experiments:
        current = load.get(team_id, TeamRunningLoad(running_experiments=0, running_metrics=0))
        load[team_id] = TeamRunningLoad(
            running_experiments=current.running_experiments + 1,
            running_metrics=current.running_metrics
            + len(metrics or [])
            + len(metrics_secondary or [])
            + saved_metric_count,
        )
    return load


def build_census_report(stats: list[TeamDirectScanStats], window_days: int) -> EnrollmentCensusReport:
    qualified: list[tuple[TeamDirectScanStats, tuple[str, ...]]] = []
    excluded: list[ExcludedTeam] = []
    for team_stats in stats:
        reasons = qualifying_reasons(team_stats)
        if not reasons:
            continue
        exclusion = exclusion_reason(team_stats)
        if exclusion is not None:
            excluded.append(ExcludedTeam(stats=team_stats, reason=exclusion))
            continue
        qualified.append((team_stats, reasons))

    load = running_experiment_load([team_stats.team_id for team_stats, _ in qualified])
    no_load = TeamRunningLoad(running_experiments=0, running_metrics=0)
    candidates = tuple(
        EnrollmentCandidate(
            stats=team_stats,
            reasons=reasons,
            running_experiments=load.get(team_stats.team_id, no_load).running_experiments,
            running_metrics=load.get(team_stats.team_id, no_load).running_metrics,
        )
        for team_stats, reasons in sorted(qualified, key=lambda pair: -pair[0].total_read_bytes)
    )
    return EnrollmentCensusReport(
        window_days=window_days,
        evaluated_teams=len(stats),
        candidates=candidates,
        excluded=tuple(excluded),
    )


def run_enrollment_census_sync(window_days: int = CENSUS_WINDOW_DAYS) -> EnrollmentCensusReport:
    stats = fetch_direct_scan_stats(window_days)
    report = build_census_report(stats, window_days)

    for candidate in report.candidates:
        logger.info(
            "experiment_precompute_enrollment_candidate",
            team_id=candidate.stats.team_id,
            reasons=list(candidate.reasons),
            direct_reads=candidate.stats.direct_reads,
            slow_reads=candidate.stats.slow_reads,
            total_read_bytes=candidate.stats.total_read_bytes,
            max_read_bytes=candidate.stats.max_read_bytes,
            hard_failures=candidate.stats.hard_failures,
            experiment_count=candidate.stats.experiment_count,
            running_experiments=candidate.running_experiments,
            running_metrics=candidate.running_metrics,
        )
    for excluded_team in report.excluded:
        logger.info(
            "experiment_precompute_enrollment_excluded",
            team_id=excluded_team.stats.team_id,
            reason=excluded_team.reason,
            max_read_bytes=excluded_team.stats.max_read_bytes,
            total_read_bytes=excluded_team.stats.total_read_bytes,
        )
    logger.info(
        "experiment_precompute_enrollment_census_finished",
        window_days=report.window_days,
        evaluated_teams=report.evaluated_teams,
        candidates=len(report.candidates),
        excluded=len(report.excluded),
    )
    return report
