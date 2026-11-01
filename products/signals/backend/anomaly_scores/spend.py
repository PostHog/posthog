"""The ClickHouse CPU that anomaly scoring spends, read from the query log, for the CPU limits of the tick.

The query budgets of `queue.py` count queries, but the CPU of one query can be far more than the CPU of another.
One read of `query_log_archive` sums the CPU and the read bytes of the scoring queries of the current UTC day,
per team. The cache keeps the sum, and the tick reads the query log again only when the sum is older than
`_REFRESH_EVERY`. When the sum is missing or stale, the tick does not apply the CPU limits, and the query
budgets still apply.
"""

import datetime
from enum import StrEnum

from django.core.cache import cache

import structlog

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen

from products.signals.backend.anomaly_scores.config import AnomalyScoringConfig, ScoringRun

logger = structlog.get_logger(__name__)

# The `name` tag of each scoring query, set in `scoring.fetch_series`.
SCORING_QUERY_NAMES = tuple(f"anomaly_scoring_{run.value}" for run in ScoringRun)
# The query log reaches the archive through a buffer, so a few minutes of spend can be missing from a read.
_REFRESH_EVERY = datetime.timedelta(minutes=10)
# Older than this, a sum does not limit the tick.
_STALE_AFTER = datetime.timedelta(minutes=30)
_CACHE_KEY = "signals:anomaly_scores:cpu_spend"
_CACHE_TTL = datetime.timedelta(hours=2)
# Train picks stop at this share of the fleet limit, so the cheaper score picks still run up to the full limit.
TRAIN_STOP_SHARE = 0.8

# `query_log_archive` keeps one row for each node of a distributed query, until a merge sums them. The `lc_*`
# columns hold the tags on every row, `OSCPUVirtualTimeMicroseconds` holds the CPU of the node, and `read_bytes`
# is zero except on the initial row. So a plain sum over the rows gives the CPU of all nodes and the bytes once.
_SPEND_QUERY = """
SELECT
    team_id,
    sum(ProfileEvents_OSCPUVirtualTimeMicroseconds) AS cpu_microseconds,
    sum(read_bytes) AS read_bytes
FROM query_log_archive
WHERE initial_query_start_time >= %(since)s
    AND lc_product = %(product)s
    AND lc_feature = %(feature)s
    AND lc_name IN %(names)s
GROUP BY team_id
SETTINGS skip_unavailable_shards = 1
"""


class SpendStatus(StrEnum):
    FRESH = "fresh"
    # No sum for the current UTC day: the read failed, or no read ran yet.
    MISSING = "missing"
    STALE = "stale"


@frozen
class TeamSpend:
    cpu_seconds: float
    read_bytes: int


@frozen
class SpendSnapshot:
    """The scoring spend of each team from the start of ``day`` (UTC) to ``read_at``."""

    day: datetime.date
    read_at: datetime.datetime
    teams: dict[int, TeamSpend]

    @property
    def fleet_cpu_seconds(self) -> float:
        return sum(spend.cpu_seconds for spend in self.teams.values())

    @property
    def fleet_read_bytes(self) -> int:
        return sum(spend.read_bytes for spend in self.teams.values())


@frozen
class CpuGate:
    """What the CPU limits block in one plan. Without fresh spend, nothing is blocked."""

    status: SpendStatus
    # The teams at or over the per-project limit.
    blocked_teams: frozenset[int] = frozenset()
    # The plan kinds that the fleet limit stops.
    blocked_runs: frozenset[ScoringRun] = frozenset()
    fleet_cpu_seconds: float | None = None
    fleet_read_bytes: int | None = None

    def blocks(self, team_id: int, run: ScoringRun) -> bool:
        return run in self.blocked_runs or team_id in self.blocked_teams


@frozen
class CpuSpendReport:
    """What the CPU limits saw and did in one plan, for the tick event."""

    status: SpendStatus
    fleet_cpu_seconds: float | None = None
    fleet_read_bytes: int | None = None
    # Enrolled teams at or over the per-project limit.
    teams_over_limit: int = 0
    # Due insights that the walk of each pass left out because of a CPU limit.
    train_skipped: int = 0
    score_skipped: int = 0


def _utc_day(now: datetime.datetime) -> datetime.date:
    return now.astimezone(datetime.UTC).date()


def _day_start(day: datetime.date) -> datetime.datetime:
    return datetime.datetime.combine(day, datetime.time.min, tzinfo=datetime.UTC)


def read_spend(now: datetime.datetime) -> SpendSnapshot:
    """The scoring spend of each team in the UTC day of ``now``, from the query log."""
    day = _utc_day(now)
    tag_queries(product=Product.SIGNALS, feature=Feature.ALERTING, name="anomaly_scoring_spend")
    rows = sync_execute(
        _SPEND_QUERY,
        {
            "since": _day_start(day),
            "product": Product.SIGNALS.value,
            "feature": Feature.ALERTING.value,
            "names": SCORING_QUERY_NAMES,
        },
        workload=Workload.OFFLINE,
    )
    return SpendSnapshot(
        day=day,
        read_at=now,
        teams={
            int(team_id): TeamSpend(cpu_seconds=cpu_microseconds / 1_000_000, read_bytes=int(read_bytes))
            for team_id, cpu_microseconds, read_bytes in rows
        },
    )


def current_spend(now: datetime.datetime) -> SpendSnapshot | None:
    """The cached spend of the current UTC day. A cached spend older than `_REFRESH_EVERY` or of an earlier day is read again.

    A failed read keeps the cached spend, so the caller can tell a stale spend from a missing one.
    """
    cached = cache.get(_CACHE_KEY)
    snapshot = cached if isinstance(cached, SpendSnapshot) else None
    if snapshot is not None and snapshot.day == _utc_day(now) and now - snapshot.read_at < _REFRESH_EVERY:
        return snapshot
    try:
        snapshot = read_spend(now)
    except Exception as error:
        logger.warning("anomaly_scoring_spend_read_failed", error_class=type(error).__name__)
        return snapshot
    cache.set(_CACHE_KEY, snapshot, timeout=int(_CACHE_TTL.total_seconds()))
    return snapshot


def cpu_gate(config: AnomalyScoringConfig, now: datetime.datetime) -> CpuGate:
    """The teams and plan kinds that the CPU limits of ``config`` block now.

    The per-project limit blocks a team until the next UTC day. The fleet limit stops train picks at
    `TRAIN_STOP_SHARE` of it, and score picks at all of it.
    """
    snapshot = current_spend(now)
    if snapshot is None or snapshot.day != _utc_day(now):
        return CpuGate(status=SpendStatus.MISSING)
    if now - snapshot.read_at > _STALE_AFTER:
        return CpuGate(status=SpendStatus.STALE)
    fleet = snapshot.fleet_cpu_seconds
    blocked_runs: set[ScoringRun] = set()
    if limit := config.max_fleet_cpu_seconds_per_day:
        if fleet >= limit * TRAIN_STOP_SHARE:
            blocked_runs.add(ScoringRun.TRAIN)
        if fleet >= limit:
            blocked_runs.add(ScoringRun.SCORE)
    project_limit = config.max_cpu_seconds_per_project_per_day
    return CpuGate(
        status=SpendStatus.FRESH,
        blocked_teams=frozenset(
            team_id for team_id, spend in snapshot.teams.items() if project_limit and spend.cpu_seconds >= project_limit
        ),
        blocked_runs=frozenset(blocked_runs),
        fleet_cpu_seconds=fleet,
        fleet_read_bytes=snapshot.fleet_read_bytes,
    )
