"""Distinct metric names for a team's picker UI.

Names are found and ranked from `metric_names`, which holds one row per name,
service and UTC hour, so it is far smaller than `metric_series` for the same
window. The ranking is: exact match, prefix match, suffix match (all
case-insensitive), then the number of services that reported the name, then
the name itself. Without a search only the last two apply.

`metric_names` carries no type, unit or timestamp, so a second read takes them
from `metric_series` for the ranked page only. That table sorts by
`(team_id, metric_name, series_fingerprint)`, so the read stays on the page's
names.

No FINAL on `metric_series`. ReplacingMergeTree duplicates share `(team_id,
metric_name, series_fingerprint)`, and `max(last_seen)` picks the row FINAL would
keep, since `last_seen` is the engine's version column. `metric_type` is an input
to the fingerprint (see `rust/capture-logs/src/metric_record.rs`), so every
duplicate of one fingerprint agrees on it and `any()` cannot return a stale type.

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
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.models import Team

from products.metrics.backend.facade.contracts import MAX_SPARKLINE_BATCH_SIZE
from products.metrics.backend.metric_query_runner import points_query
from products.metrics.backend.metrics4_samples import reads_metrics4_only
from products.metrics.backend.search import ilike_pattern

# Autocomplete tolerates partial results, so reads break at the budget instead
# of erroring the way the chart queries do. Mirrors MetricAttributeKeysQueryRunner.
_QUERY_SETTINGS = HogQLGlobalSettings(
    max_bytes_to_read=HOGQL_MAX_BYTES_TO_READ_FOR_METRICS_USER_QUERIES,
    read_overflow_mode="break",
)
_SPARKLINE_QUERY_SETTINGS = HogQLGlobalSettings(
    max_bytes_to_read=HOGQL_MAX_BYTES_TO_READ_FOR_METRICS_USER_QUERIES,
    read_overflow_mode="throw",
)

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
        lookback: dt.timedelta = dt.timedelta(hours=24),
        services: Sequence[str] = (),
        include_sparklines: bool = True,
        names: Sequence[str] = (),
    ) -> None:
        if limit <= 0 or limit > 1000:
            raise ValueError("limit must be in [1, 1000]")
        if lookback <= dt.timedelta(0):
            raise ValueError("lookback must be positive")
        if len(services) > MAX_PICKER_SERVICES:
            raise ValueError(f"at most {MAX_PICKER_SERVICES} services may be selected")
        if len(names) > MAX_SPARKLINE_BATCH_SIZE:
            raise ValueError(f"at most {MAX_SPARKLINE_BATCH_SIZE} metric names may be selected")

        self.team = team
        self.search = search.strip()
        self.limit = limit
        self.lookback = lookback
        # Sorted and deduped so two callers that picked the same services in a
        # different order share one cache entry. An empty string is a real
        # selection: a sender that omits the `service.name` resource attribute
        # lands in the group the overview labels "unknown".
        self.services = tuple(sorted(set(services)))
        # Sparklines read the `metrics` data points, so the scan is the
        # expensive part of a name lookup. Callers that only need the type
        # (anomaly defaults) skip it.
        self.include_sparklines = include_sparklines
        self.names = tuple(sorted(set(names)))

    def _lookback_start(self) -> ast.Expr:
        # Hour-aligned so the series read covers every hour the names read counted.
        # Otherwise a name last seen early in the first hour has no series to describe it.
        return parse_expr(
            "toStartOfHour(now() - toIntervalSecond({seconds}))",
            placeholders={"seconds": ast.Constant(value=int(self.lookback.total_seconds()))},
        )

    def _services_expr(self) -> ast.Expr:
        return ast.CompareOperation(
            op=ast.CompareOperationOp.In,
            left=ast.Field(chain=["service_name"]),
            right=ast.Tuple(exprs=[ast.Constant(value=service) for service in self.services]),
        )

    def _build_query(self) -> ast.SelectQuery:
        if not self.search:
            # With no search the ILIKE ('%%') and the match sort keys are all
            # no-ops. They're dropped rather than passed as neutral constants:
            # ClickHouse reads a bare integer in ORDER BY positionally.
            query = parse_select(
                """
                    SELECT
                        metric_name AS name,
                        uniqExact(service_name) AS matching_services
                    FROM posthog.metric_names
                    WHERE time_bucket >= {lookback_start}
                    GROUP BY metric_name
                    ORDER BY
                        matching_services DESC,
                        metric_name ASC
                    LIMIT {limit}
                """,
                placeholders={"lookback_start": self._lookback_start(), "limit": ast.Constant(value=self.limit)},
            )
        else:
            query = parse_select(
                """
                    SELECT
                        metric_name AS name,
                        uniqExact(service_name) AS matching_services
                    FROM posthog.metric_names
                    WHERE time_bucket >= {lookback_start}
                      AND metric_name ILIKE {search_pattern}
                    GROUP BY metric_name
                    ORDER BY
                        lower(metric_name) = lower({search}) DESC,
                        startsWith(lower(metric_name), lower({search})) DESC,
                        endsWith(lower(metric_name), lower({search})) DESC,
                        matching_services DESC,
                        metric_name ASC
                    LIMIT {limit}
                """,
                placeholders={
                    "lookback_start": self._lookback_start(),
                    "search_pattern": ast.Constant(value=ilike_pattern(self.search)),
                    "search": ast.Constant(value=self.search),
                    "limit": ast.Constant(value=self.limit),
                },
            )

        assert isinstance(query, ast.SelectQuery)
        # Both variants above filter on the lookback, so there is always a WHERE to
        # extend; the assert is what tells the type checker so.
        assert query.where is not None
        if self.names:
            query.where = ast.And(
                exprs=[
                    query.where,
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.In,
                        left=ast.Field(chain=["metric_name"]),
                        right=ast.Tuple(exprs=[ast.Constant(value=name) for name in self.names]),
                    ),
                ]
            )

        # Appended to the parsed tree rather than written into both SQL variants
        # above, so the scoped and unscoped pickers stay one query definition. The
        # filter runs before the GROUP BY, so `matching_services` counts only the
        # selected services.
        if self.services:
            query.where = ast.And(exprs=[query.where, self._services_expr()])
        return query

    def _details_query(self, names: Sequence[str]) -> ast.SelectQuery:
        # The alias is `last_seen_at`, not `last_seen`: HogQL registers select
        # aliases before it resolves WHERE and prefers an alias over a table
        # column, so `max(last_seen) AS last_seen` would put an aggregate in the
        # WHERE clause.
        query = parse_select(
            """
                SELECT
                    metric_name AS name,
                    any(metric_type) AS metric_type,
                    any(unit) AS unit,
                    max(last_seen) AS last_seen_at
                FROM posthog.metric_series
                WHERE last_seen >= {lookback_start}
                  AND metric_name IN {names}
                GROUP BY metric_name
            """,
            placeholders={
                "lookback_start": self._lookback_start(),
                "names": ast.Tuple(exprs=[ast.Constant(value=name) for name in names]),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        assert query.where is not None
        # `service_name` has its own skip index (`idx_service_set`) here, and a
        # scoped picker must describe the metric as the selected services send it.
        if self.services:
            query.where = ast.And(exprs=[query.where, self._services_expr()])
        return query

    def run(self) -> list[dict[str, Any]]:
        settings = _SPARKLINE_QUERY_SETTINGS if self.names else _QUERY_SETTINGS
        response = execute_hogql_query(
            query_type="MetricNamesQuery",
            query=self._build_query(),
            team=self.team,
            workload=Workload.LOGS,  # metrics share the logs ClickHouse workload pool for now
            settings=settings,
        )
        names = [row[0] for row in response.results]
        if not names:
            return []

        details_response = execute_hogql_query(
            query_type="MetricNamesDetailsQuery",
            query=self._details_query(names),
            team=self.team,
            workload=Workload.LOGS,
            settings=settings,
        )
        details = {row[0]: row[1:] for row in details_response.results}
        sparklines = self._sparklines(names) if self.include_sparklines else {}

        rows = []
        for name in names:
            # A name with no series row in the window still lists; it just has
            # nothing to describe it.
            metric_type, unit, last_seen = details.get(name, ("", "", None))
            rows.append(
                {
                    "name": name,
                    "metric_type": metric_type,
                    "unit": unit,
                    "last_seen": _isoformat(last_seen),
                    "sparkline": sparklines.get(name, []),
                }
            )
        return rows

    def _sparklines(self, names: Sequence[str]) -> dict[str, list[float]]:
        """A small recent shape per metric, for the catalog cards.

        Reads the raw `metrics` data points. Each metric is bucketed onto a
        fixed grid and averaged per bucket across its series; a card only shows
        direction and spikes, so per-series fidelity is not worth the rows it
        would cost. Only the names this page returned are read, so a scoped
        picker never scans the whole table.
        """
        if not names:
            return {}

        # The grid anchors to the window start: bucket edges land on the window
        # endpoints, so the window always holds exactly MAX_POINTS buckets (a
        # bare toStartOfInterval aligns to wall-clock boundaries and a window
        # starting mid-bucket intersects one extra). The anchor is computed here
        # rather than from the query's `now()` so the predicate below and the
        # grid agree on the same instant.
        bucket_seconds = max(int(SPARKLINE_WINDOW.total_seconds()) // SPARKLINE_MAX_POINTS, 1)
        window_start = dt.datetime.now(dt.UTC) - SPARKLINE_WINDOW
        query = parse_select(
            """
                SELECT
                    metric_name AS name,
                    toDateTime(intDiv(toUnixTimestamp(timestamp) - toUnixTimestamp({window_start}), {bucket_seconds}) * {bucket_seconds} + toUnixTimestamp({window_start})) AS bucket_start,
                    avg(value) AS bucket_value
                FROM {points}
                GROUP BY name, bucket_start
                ORDER BY name, bucket_start
            """,
            placeholders={
                "bucket_seconds": ast.Constant(value=bucket_seconds),
                "window_start": ast.Constant(value=window_start),
                # The point read also bounds `time_bucket` (the UTC hour), which
                # lets ClickHouse skip everything older than the window.
                "points": points_query(
                    from_samples=reads_metrics4_only(window_start),
                    columns=("metric_name", "timestamp", "value"),
                    metric_names=names,
                    date_from=window_start,
                    date_to=window_start + SPARKLINE_WINDOW,
                    timezone=self.team.timezone,
                    # A sample carries no service column; its series_fingerprint is
                    # the link back to the series row that does. Without this scope,
                    # two services emitting one metric name share a card and a scoped
                    # catalog draws a shape blended across services.
                    row_filters=(
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.In,
                            left=ast.Field(chain=["series_fingerprint"]),
                            right=self._series_scope_subquery(names),
                        ),
                    ),
                ),
            },
        )
        assert isinstance(query, ast.SelectQuery)

        response = execute_hogql_query(
            query_type="MetricNamesSparklineQuery",
            query=query,
            team=self.team,
            workload=Workload.LOGS,
            settings=_SPARKLINE_QUERY_SETTINGS,
        )

        sparklines: dict[str, list[float]] = {}
        for name, _bucket_start, bucket_value in response.results:
            sparklines.setdefault(name, []).append(float(bucket_value))
        return sparklines

    def _series_scope_subquery(self, names: Sequence[str]) -> ast.SelectQuery:
        """The series fingerprints, for these names, owned by the scoped services.

        Built as its own parsed query so the service predicate is attached with an
        explicit And the way `_build_query` does, not spliced into the SQL text.
        """
        lookback = ast.Call(name="toIntervalSecond", args=[ast.Constant(value=int(self.lookback.total_seconds()))])
        subquery = parse_select(
            """
                SELECT series_fingerprint
                FROM posthog.metric_series
                WHERE last_seen > now() - {lookback}
                  AND metric_name IN {names}
                GROUP BY series_fingerprint
            """,
            placeholders={
                "lookback": lookback,
                "names": ast.Tuple(exprs=[ast.Constant(value=name) for name in names]),
            },
        )
        assert isinstance(subquery, ast.SelectQuery)
        assert subquery.where is not None
        if self.services:
            subquery.where = ast.And(exprs=[subquery.where, self._services_expr()])
        return subquery


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
    cache_key = f"metrics:{team.id}:metric_names:v3:{limit}:{scope}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    names = runner.run()
    if names:
        cache.set(cache_key, names, METRIC_NAMES_CACHE_TTL)
    return names
