"""Distinct metric names for a team's picker UI."""

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

# Autocomplete tolerates partial results, so reads break at the budget instead of erroring.
_QUERY_SETTINGS = HogQLGlobalSettings(
    max_bytes_to_read=HOGQL_MAX_BYTES_TO_READ_FOR_METRICS_USER_QUERIES,
    read_overflow_mode="break",
)
_SPARKLINE_QUERY_SETTINGS = HogQLGlobalSettings(
    max_bytes_to_read=HOGQL_MAX_BYTES_TO_READ_FOR_METRICS_USER_QUERIES,
    read_overflow_mode="throw",
)

METRIC_NAMES_CACHE_TTL = 60

MAX_PICKER_SERVICES = 50

SPARKLINE_WINDOW = dt.timedelta(hours=6)
SPARKLINE_MAX_POINTS = 24


def _isoformat(value: Any) -> str | None:
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
        # Sorted so the same selection in a different order shares one cache entry.
        self.services = tuple(sorted(set(services)))
        self.include_sparklines = include_sparklines
        self.names = tuple(sorted(set(names)))

    def _lookback_start(self) -> ast.Expr:
        # Hour-aligned to match `metric_names.time_bucket`, so both queries cover the same window.
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
            # A separate query, because ClickHouse reads a constant sort key as a column position.
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

        if self.services:
            query.where = ast.And(exprs=[query.where, self._services_expr()])
        return query

    def _details_query(self, names: Sequence[str]) -> ast.SelectQuery:
        # Not aliased `last_seen`: HogQL would resolve the WHERE's `last_seen` to the aggregate.
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
        if self.services:
            query.where = ast.And(exprs=[query.where, self._services_expr()])
        return query

    def run(self) -> list[dict[str, Any]]:
        settings = _SPARKLINE_QUERY_SETTINGS if self.names else _QUERY_SETTINGS
        response = execute_hogql_query(
            query_type="MetricNamesQuery",
            query=self._build_query(),
            team=self.team,
            workload=Workload.LOGS,
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
        if not names:
            return {}

        # Buckets anchor to the window start, so the window holds exactly SPARKLINE_MAX_POINTS of them.
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
                "points": points_query(
                    from_samples=reads_metrics4_only(window_start),
                    columns=("metric_name", "timestamp", "value"),
                    metric_names=names,
                    date_from=window_start,
                    date_to=window_start + SPARKLINE_WINDOW,
                    timezone=self.team.timezone,
                    # Samples have no service column, so the service scope goes through the series.
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
    """Metric names for the picker. Only non-empty, unsearched lists are cached."""
    runner = MetricNamesQueryRunner(team=team, search=search, limit=limit, services=services)
    if runner.search:
        return runner.run()

    # Hashed: service names can hold characters that a memcached key cannot.
    scope = sha256(repr(runner.services).encode()).hexdigest()[:16] if runner.services else "all"
    cache_key = f"metrics:{team.id}:metric_names:v3:{limit}:{scope}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    names = runner.run()
    if names:
        cache.set(cache_key, names, METRIC_NAMES_CACHE_TTL)
    return names
