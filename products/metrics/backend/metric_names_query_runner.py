"""Distinct metric names for a team's picker UI.

Reads `metric_series` (one row per metric + label-set) rather than the raw
`metrics` datapoint table. Both are fed from the same Kafka Avro stream, so
they carry the same names, but the series table is two orders of magnitude
smaller for the same window — on a busy team, ~3.6M rows against ~800M. It also
sorts by `(team_id, metric_name, series_fingerprint)`, so `metric_name` is the
leading key once `team_id` is pinned, where `metrics1` buries it behind
`time_bucket` and `service_name`.

No FINAL. ReplacingMergeTree duplicates share `(team_id, metric_name,
series_fingerprint)`, and `max(last_seen)` picks the row FINAL would keep, since
`last_seen` is the engine's version column. `metric_type` is an input to the
fingerprint (see `rust/capture-logs/src/metric_record.rs`), so every duplicate
of one fingerprint agrees on it and `any()` cannot return a stale type.

Surfaces `metric_type` alongside the name so the viewer can hint at the
type-appropriate default aggregation (gauge -> avg, counter/sum -> sum, etc.)
without a second round-trip.
"""

import datetime as dt
from collections.abc import Sequence
from hashlib import sha256
from typing import Any

from django.core.cache import cache

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.database.schema.metrics import HOGQL_MAX_BYTES_TO_READ_FOR_METRICS_USER_QUERIES
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.models import Team

from products.metrics.backend.search import ilike_pattern

# Autocomplete tolerates partial results, so reads break at the budget instead
# of erroring the way the chart queries do. Mirrors MetricAttributeKeysQueryRunner.
_QUERY_SETTINGS = HogQLGlobalSettings(
    max_bytes_to_read=HOGQL_MAX_BYTES_TO_READ_FOR_METRICS_USER_QUERIES,
    read_overflow_mode="break",
)

# `metric_series` drops rows 90 days past `last_seen`; `metrics1` has no TTL.
# A lookback beyond this would quietly return fewer names than the raw table has.
SERIES_RETENTION = dt.timedelta(days=90)

# Short enough that a new metric shows up while someone is still wiring it up,
# long enough to absorb the burst of mounts a team generates in a working session.
METRIC_NAMES_CACHE_TTL = 60

# Past this the picker is not scoped to anything a person can hold in their head,
# and the bound keeps one request from building an unbounded IN list.
MAX_PICKER_SERVICES = 50

# Sparklines summarize this window, downsampled to at most this many points. A
# card only needs the recent shape, so the window is far shorter than the name
# lookback and the point count is bounded to keep one row small.
SPARKLINE_WINDOW = dt.timedelta(hours=6)
SPARKLINE_MAX_POINTS = 24


def _isoformat(value: Any) -> str | None:
    """ClickHouse hands back datetimes, but a driver or JSON round-trip can leave a
    string. The API serializer accepts ISO either way, so normalize without assuming."""
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


class MetricNamesQueryRunner:
    def __init__(
        self,
        team: Team,
        *,
        search: str = "",
        limit: int = 100,
        lookback: dt.timedelta = dt.timedelta(days=7),
        services: Sequence[str] = (),
    ) -> None:
        if limit <= 0 or limit > 1000:
            raise ValueError("limit must be in [1, 1000]")
        if lookback <= dt.timedelta(0):
            raise ValueError("lookback must be positive")
        if len(services) > MAX_PICKER_SERVICES:
            raise ValueError(f"at most {MAX_PICKER_SERVICES} services may be selected")

        self.team = team
        self.search = search.strip()
        self.limit = limit
        self.lookback = lookback
        # Sorted and deduped so two callers that picked the same services in a
        # different order share one cache entry. An empty string is a real
        # selection: a sender that omits the `service.name` resource attribute
        # lands in the group the overview labels "unknown".
        self.services = tuple(sorted(set(services)))

    def _build_query(self) -> ast.SelectQuery:
        # The alias is `last_seen_at`, not `last_seen`: HogQL registers select
        # aliases before it resolves WHERE and prefers an alias over a table
        # column, so `max(last_seen) AS last_seen` would put an aggregate in the
        # WHERE clause.
        lookback = ast.Call(name="toIntervalSecond", args=[ast.Constant(value=int(self.lookback.total_seconds()))])

        if not self.search:
            # With no search the ILIKE ('%%') and the exact-match sort key are
            # both no-ops. They're dropped rather than passed as neutral
            # constants: ClickHouse reads a bare integer in ORDER BY positionally.
            query = parse_select(
                """
                    SELECT
                        metric_name AS name,
                        any(metric_type) AS metric_type,
                        any(unit) AS unit,
                        max(last_seen) AS last_seen_at
                    FROM posthog.metric_series
                    WHERE last_seen > now() - {lookback}
                    GROUP BY metric_name
                    ORDER BY last_seen_at DESC
                    LIMIT {limit}
                """,
                placeholders={"lookback": lookback, "limit": ast.Constant(value=self.limit)},
            )
        else:
            query = parse_select(
                """
                    SELECT
                        metric_name AS name,
                        any(metric_type) AS metric_type,
                        any(unit) AS unit,
                        max(last_seen) AS last_seen_at
                    FROM posthog.metric_series
                    WHERE last_seen > now() - {lookback}
                      AND metric_name ILIKE {search_pattern}
                    GROUP BY metric_name
                    ORDER BY
                        lower(metric_name) = lower({exact}) DESC,
                        last_seen_at DESC
                    LIMIT {limit}
                """,
                placeholders={
                    "lookback": lookback,
                    "search_pattern": ast.Constant(value=ilike_pattern(self.search)),
                    "exact": ast.Constant(value=self.search),
                    "limit": ast.Constant(value=self.limit),
                },
            )

        assert isinstance(query, ast.SelectQuery)
        # Both variants above filter on the lookback, so there is always a WHERE to
        # extend; the assert is what tells the type checker so.
        assert query.where is not None

        # Appended to the parsed tree rather than written into both SQL variants
        # above, so the scoped and unscoped pickers stay one query definition.
        # `service_name` is the only filterable column with its own skip index
        # (`idx_service_set`), which is what keeps a type-ahead affordable —
        # attribute predicates read the label maps and belong in the chart query.
        if self.services:
            query.where = ast.And(
                exprs=[
                    query.where,
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.In,
                        left=ast.Field(chain=["service_name"]),
                        right=ast.Tuple(exprs=[ast.Constant(value=service) for service in self.services]),
                    ),
                ]
            )
        return query

    def run(self) -> list[dict[str, Any]]:
        response = execute_hogql_query(
            query_type="MetricNamesQuery",
            query=self._build_query(),
            team=self.team,
            workload=Workload.LOGS,  # metrics share the logs ClickHouse workload pool for now
            settings=_QUERY_SETTINGS,
        )

        names = [row[0] for row in response.results]
        sparklines = self._sparklines(names)

        return [
            {
                "name": row[0],
                "metric_type": row[1],
                "unit": row[2],
                "last_seen": _isoformat(row[3]),
                "sparkline": sparklines.get(row[0], []),
            }
            for row in response.results
        ]

    def _sparklines(self, names: Sequence[str]) -> dict[str, list[float]]:
        """A small recent shape per metric, for the catalog cards.

        Reads `metric_samples` (raw emissions) rather than the pre-aggregated
        `metrics` table, so a series written without a metrics row still draws —
        the same reason the name list reads `metric_series`. Each metric is
        bucketed onto a fixed grid and averaged per bucket across its series; a
        card only shows direction and spikes, so per-series fidelity is not worth
        the rows it would cost. Only the names this page returned are read, so a
        scoped picker never scans the whole samples table.
        """
        if not names:
            return {}

        bucket_seconds = max(int(SPARKLINE_WINDOW.total_seconds()) // SPARKLINE_MAX_POINTS, 1)
        query = parse_select(
            """
                SELECT
                    metric_name AS name,
                    toStartOfInterval(timestamp, {bucket}) AS bucket_start,
                    avg(value) AS bucket_value
                FROM posthog.metric_samples
                WHERE timestamp > now() - {window}
                  AND metric_name IN {names}
                GROUP BY name, bucket_start
                ORDER BY name, bucket_start
            """,
            placeholders={
                "bucket": ast.Call(name="toIntervalSecond", args=[ast.Constant(value=bucket_seconds)]),
                "window": ast.Call(
                    name="toIntervalSecond", args=[ast.Constant(value=int(SPARKLINE_WINDOW.total_seconds()))]
                ),
                "names": ast.Tuple(exprs=[ast.Constant(value=name) for name in names]),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        # No service filter here: `names` is already the scoped set the name query
        # returned, so the sparkline can never draw a metric outside the scope.
        # `metric_samples` has no service_name column, and the per-metric bucketed
        # average is over all of that metric's series regardless.

        response = execute_hogql_query(
            query_type="MetricNamesSparklineQuery",
            query=query,
            team=self.team,
            workload=Workload.LOGS,
            settings=_QUERY_SETTINGS,
        )

        sparklines: dict[str, list[float]] = {}
        for name, _bucket_start, bucket_value in response.results:
            sparklines.setdefault(name, []).append(float(bucket_value))
        return sparklines


def cached_metric_names(
    team: Team, *, search: str = "", limit: int = 100, services: Sequence[str] = ()
) -> list[dict[str, Any]]:
    """Metric names for the picker, with the unsearched list cached per team.

    Only the empty-search prime is cached: every viewer mount issues it and the
    answer is the same for everyone on the team. Searches are per-keystroke and
    per-user, so caching them would fill the cache with single-hit entries.

    The service scope is part of the key, not a filter over one cached list: the
    unscoped list is capped at `limit` names, so narrowing it in Python would hide
    metrics that a scoped query returns.

    Only non-empty results are cached, matching `team_has_metrics`: a team that
    just wired up OTel must not be pinned to an empty picker while the setup
    prompt's poll has already let them through.
    """
    runner = MetricNamesQueryRunner(team=team, search=search, limit=limit, services=services)
    if runner.search:
        return runner.run()

    # `repr` of the sorted tuple, hashed: service names come from user data, so
    # they can carry spaces and unicode that a memcached key cannot.
    scope = sha256(repr(runner.services).encode()).hexdigest()[:16] if runner.services else "all"
    cache_key = f"metrics:{team.id}:metric_names:v2:{limit}:{scope}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    names = runner.run()
    if names:
        cache.set(cache_key, names, METRIC_NAMES_CACHE_TTL)
    return names
