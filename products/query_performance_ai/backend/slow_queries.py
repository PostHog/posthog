"""Fetch slow-query candidates from prod ClickHouse's ``system.query_log``.

Only returns queries whose originating org has ``is_ai_data_processing_approved``
set — the tag is written into ``log_comment`` by PR #55214, so this is a pure
ClickHouse-side filter with no Postgres join required.

This module is called from the weekly Temporal workflow, **not** from a
sandbox — it uses the service ClickHouse client directly and must run with
read access to ``system.query_log`` on the prod cluster.
"""

from __future__ import annotations

from dataclasses import dataclass

from posthog.clickhouse.client import sync_execute

# A query is a "slow query candidate" when its p95 duration over the window
# crosses this threshold AND it runs often enough to be worth optimizing.
# Both are configurable per run so the weekly workflow can tune without a
# deploy.
DEFAULT_WINDOW_DAYS = 7
DEFAULT_MIN_DURATION_MS = 5_000
DEFAULT_MIN_EXECUTIONS = 5
DEFAULT_LIMIT = 20


@dataclass(frozen=True)
class SlowQueryCandidate:
    """One aggregated slow-query signature ready for autoresearch.

    Aggregation is keyed by ``normalized_query_hash`` (ClickHouse's built-in)
    so the autoresearch campaign operates on a query *shape*, not a specific
    parameterization. We still carry one concrete sample so the campaign has
    real SQL to run through the proxy.
    """

    normalized_query_hash: str
    team_id: int
    sample_query_id: str
    sample_sql: str
    p95_duration_ms: float
    total_read_bytes: int
    executions: int


_AGGREGATE_SQL = """
SELECT
    toString(normalized_query_hash) AS normalized_query_hash,
    JSONExtractInt(log_comment, 'team_id') AS team_id,
    any(query_id) AS sample_query_id,
    any(query) AS sample_sql,
    quantile(0.95)(query_duration_ms) AS p95_duration_ms,
    sum(read_bytes) AS total_read_bytes,
    count() AS executions
FROM clusterAllReplicas(%(cluster)s, system.query_log)
WHERE event_time >= now() - toIntervalDay(%(window_days)s)
  AND type = 'QueryFinish'
  AND query_duration_ms >= %(min_duration_ms)s
  AND JSONExtractBool(log_comment, 'ai_data_processing_approved') = 1
  AND JSONExtractInt(log_comment, 'team_id') > 0
GROUP BY normalized_query_hash, team_id
HAVING executions >= %(min_executions)s
ORDER BY p95_duration_ms * executions DESC
LIMIT %(limit)s
"""


def fetch_slow_query_candidates(
    *,
    cluster: str = "posthog",
    window_days: int = DEFAULT_WINDOW_DAYS,
    min_duration_ms: int = DEFAULT_MIN_DURATION_MS,
    min_executions: int = DEFAULT_MIN_EXECUTIONS,
    limit: int = DEFAULT_LIMIT,
) -> list[SlowQueryCandidate]:
    """Return the top slow-query candidates from the last ``window_days``.

    Ordering is by ``p95_duration_ms * executions`` so we prioritize queries
    that are both slow and frequent — optimizing a 10s query that runs once
    a week is less impactful than a 2s query running 5k times.
    """
    rows = sync_execute(
        _AGGREGATE_SQL,
        {
            "cluster": cluster,
            "window_days": window_days,
            "min_duration_ms": min_duration_ms,
            "min_executions": min_executions,
            "limit": limit,
        },
    )

    return [
        SlowQueryCandidate(
            normalized_query_hash=str(row[0]),
            team_id=int(row[1]),
            sample_query_id=str(row[2]),
            sample_sql=str(row[3]),
            p95_duration_ms=float(row[4]),
            total_read_bytes=int(row[5]),
            executions=int(row[6]),
        )
        for row in rows
    ]
