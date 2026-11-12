"""Distinct metric names for a team's picker UI."""

import math
import datetime as dt
from collections.abc import Sequence
from hashlib import sha256
from typing import Any

from django.core.cache import cache

import re2

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.database.schema.metrics import HOGQL_MAX_BYTES_TO_READ_FOR_METRICS_USER_QUERIES
from posthog.hogql.errors import QueryError
from posthog.hogql.parser import parse_expr, parse_order_expr, parse_select
from posthog.hogql.property import validate_regex
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.visitor import clone_expr

from posthog.clickhouse.client.connection import Workload
from posthog.models import Team

from products.metrics.backend.facade.contracts import MAX_SPARKLINE_BATCH_SIZE
from products.metrics.backend.facade.enums import MetricNameMatchMode
from products.metrics.backend.metric_query_runner import points_query
from products.metrics.backend.metrics4_samples import reads_metrics4_only
from products.metrics.backend.search import ilike_pattern, ilike_prefix_pattern

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

# Prometheus classic histograms export one histogram as these three names.
_CLASSIC_HISTOGRAM_SUFFIXES = ("_bucket", "_sum", "_count")


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
        match: str = "substring",
        include_first_seen: bool = False,
    ) -> None:
        if match not in MetricNameMatchMode.values:
            raise ValueError(f"match must be one of {', '.join(MetricNameMatchMode.values)}")
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
        self.match = match
        self.include_first_seen = include_first_seen
        if self.search and self.match == "regex":
            try:
                validate_regex(self.search)
            except QueryError as exc:
                raise ValueError(str(exc)) from exc

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

    def _search_filter(self) -> ast.Expr:
        search = ast.Constant(value=self.search)
        if self.match == "regex":
            # ClickHouse match() is RE2, the engine `validate_regex` checked the pattern with.
            return parse_expr("match(metric_name, {search})", placeholders={"search": search})
        pattern = ilike_prefix_pattern(self.search) if self.match == "prefix" else ilike_pattern(self.search)
        return parse_expr("metric_name ILIKE {pattern}", placeholders={"pattern": ast.Constant(value=pattern)})

    def _search_rank(self) -> list[ast.OrderExpr]:
        """Sort keys that float the closest matches above the activity order."""
        if self.match == "regex":
            return []
        placeholders: dict[str, ast.Expr] = {"search": ast.Constant(value=self.search)}
        keys = ["lower(metric_name) = lower({search}) DESC"]
        if self.match == "substring":
            keys += [
                "startsWith(lower(metric_name), lower({search})) DESC",
                "endsWith(lower(metric_name), lower({search})) DESC",
            ]
        return [parse_order_expr(key, placeholders=placeholders) for key in keys]

    def _names_query(self) -> ast.SelectQuery:
        if not self.search:
            # A separate query, because ClickHouse reads a constant sort key as a column position.
            query = parse_select(
                """
                    SELECT
                        metric_name,
                        uniqExact(service_name) AS matching_services,
                        -- Rows written before the names table had a type read ''.
                        anyIf(metric_type, metric_type != '') AS name_metric_type
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
                        metric_name,
                        uniqExact(service_name) AS matching_services,
                        -- Rows written before the names table had a type read ''.
                        anyIf(metric_type, metric_type != '') AS name_metric_type
                    FROM posthog.metric_names
                    WHERE time_bucket >= {lookback_start}
                      AND {search_filter}
                    GROUP BY metric_name
                    ORDER BY
                        matching_services DESC,
                        metric_name ASC
                    LIMIT {limit}
                """,
                placeholders={
                    "lookback_start": self._lookback_start(),
                    "search_filter": self._search_filter(),
                    "limit": ast.Constant(value=self.limit),
                },
            )
            assert isinstance(query, ast.SelectQuery)
            query.order_by = [*self._search_rank(), *(query.order_by or [])]

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

    def _build_query(self) -> ast.SelectQuery:
        # One round trip: the names pick the page, and the series join adds type, unit and last seen.
        names_query = self._names_query()
        # Not aliased `last_seen`: HogQL would resolve the WHERE's `last_seen` to the aggregate.
        query = parse_select(
            """
                SELECT
                    names.metric_name AS name,
                    details.metric_type AS metric_type,
                    details.unit AS unit,
                    if(details.matched = 1, details.last_seen_at, NULL) AS last_seen_at
                FROM {names} AS names
                LEFT JOIN (
                    SELECT
                        metric_name AS series_metric_name,
                        -- An unmatched row reads 0 here, even for a metric named ''.
                        1 AS matched,
                        any(metric_type) AS metric_type,
                        any(unit) AS unit,
                        max(last_seen) AS last_seen_at
                    FROM posthog.metric_series
                    WHERE last_seen >= {lookback_start}
                      AND metric_name IN (SELECT metric_name FROM {page_names})
                    GROUP BY metric_name
                ) AS details ON details.series_metric_name = names.metric_name
            """,
            placeholders={
                "names": names_query,
                "page_names": clone_expr(names_query),
                "lookback_start": self._lookback_start(),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        if self.services:
            assert query.select_from is not None and query.select_from.next_join is not None
            details = query.select_from.next_join.table
            assert isinstance(details, ast.SelectQuery) and details.where is not None
            details.where = ast.And(exprs=[details.where, self._services_expr()])
        # A join does not keep the page order, so the outer query sorts by the same keys.
        query.order_by = [clone_expr(order) for order in names_query.order_by or []]
        # Without its own LIMIT, the outer query gets the HogQL default and cuts a larger page.
        query.limit = clone_expr(names_query.limit) if names_query.limit else None
        return query

    def run_picker(self) -> list[dict[str, str]]:
        """Names and types only. Reads `metric_names` alone, which is much smaller than `metric_series`."""
        response = execute_hogql_query(
            query_type="MetricNamesQuery",
            query=self._names_query(),
            team=self.team,
            workload=Workload.METRICS,
            settings=_SPARKLINE_QUERY_SETTINGS if self.names else _QUERY_SETTINGS,
        )
        return [{"name": name, "metric_type": metric_type} for name, _services, metric_type in response.results]

    def run(self) -> list[dict[str, Any]]:
        settings = _SPARKLINE_QUERY_SETTINGS if self.names else _QUERY_SETTINGS
        response = execute_hogql_query(
            query_type="MetricNamesQuery",
            query=self._build_query(),
            team=self.team,
            workload=Workload.METRICS,
            settings=settings,
        )
        if not response.results:
            return []

        names = [row[0] for row in response.results]
        sparklines = self._sparklines(names) if self.include_sparklines else {}
        first_seen = self._first_seen(names) if self.include_first_seen else None

        rows: list[dict[str, Any]] = []
        for name, metric_type, unit, last_seen in response.results:
            row: dict[str, Any] = {
                "name": name,
                "metric_type": metric_type or "",
                "unit": unit or "",
                "last_seen": _isoformat(last_seen),
                "sparkline": sparklines.get(name, []),
            }
            if first_seen is not None:
                row["first_seen"] = _isoformat(first_seen.get(name))
            rows.append(row)
        return rows

    def _first_seen(self, names: Sequence[str]) -> dict[str, Any]:
        """The earliest hour each name arrived in, over the series table's whole retention.

        It ignores the lookback on purpose: the point is to tell a metric that only started
        arriving inside the window from one that was there all along.
        """
        if not names:
            return {}
        # metric_series is sorted by metric_name first, so this reads only these names' ranges.
        # The names table is sorted by hour first, so the same lookup there reads all retention.
        query = parse_select(
            """
                SELECT metric_name, min(time_bucket) AS first_seen
                FROM posthog.metric_series
                WHERE metric_name IN {names}
                GROUP BY metric_name
            """,
            placeholders={"names": ast.Tuple(exprs=[ast.Constant(value=name) for name in names])},
        )
        assert isinstance(query, ast.SelectQuery)
        assert query.where is not None
        if self.services:
            query.where = ast.And(exprs=[query.where, self._services_expr()])
        query.limit = ast.Constant(value=len(names))
        response = execute_hogql_query(
            query_type="MetricNamesFirstSeenQuery",
            query=query,
            team=self.team,
            workload=Workload.METRICS,
            settings=_SPARKLINE_QUERY_SETTINGS,
        )
        return dict(response.results)

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
        # One row per name and bucket. Without an explicit LIMIT, the HogQL default cuts the batch after a few names.
        # The extra bucket covers a point on the window's end.
        query.limit = ast.Constant(value=len(names) * (SPARKLINE_MAX_POINTS + 1))

        response = execute_hogql_query(
            query_type="MetricNamesSparklineQuery",
            query=query,
            team=self.team,
            workload=Workload.METRICS,
            settings=_SPARKLINE_QUERY_SETTINGS,
        )

        sparklines: dict[str, list[float]] = {}
        for name, _bucket_start, bucket_value in response.results:
            value = float(bucket_value)
            if math.isfinite(value):
                sparklines.setdefault(name, []).append(value)
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


def name_matches(name: str, search: str, match: str = "substring") -> bool:
    """The runner's name filter, in Python, for names that never reach the names table."""
    search = search.strip()
    if not search:
        return True
    if match == "regex":
        return re2.search(search, name) is not None
    if match == "prefix":
        return name.lower().startswith(search.lower())
    return search.lower() in name.lower()


def fold_classic_histograms(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fold each Prometheus classic histogram's `_bucket`, `_sum` and `_count` rows into its `_bucket` row.

    Only a complete triple of `sum` rows folds, and only when all three are in `rows`. The folded row keeps
    the `_bucket` name, which is the one PromQL's `histogram_quantile` reads, and lists the three
    underlying names under `classic_histogram`. Its `last_seen` is the newest and its
    `first_seen` the oldest of the three.
    """
    by_name = {row["name"]: row for row in rows}
    folded: dict[str, dict[str, Any]] = {}
    for name in by_name:
        if not name.endswith("_bucket"):
            continue
        base = name.removesuffix("_bucket")
        triple = [f"{base}{suffix}" for suffix in _CLASSIC_HISTOGRAM_SUFFIXES]
        # Ingestion only treats `sum` rows as histogram components, so gauges that share the suffixes stay apart.
        if base and all(by_name.get(member, {}).get("metric_type") == "sum" for member in triple):
            folded[name] = {"base_name": base, "bucket": triple[0], "sum": triple[1], "count": triple[2]}

    absorbed = {members[key] for members in folded.values() for key in ("sum", "count")}
    result: list[dict[str, Any]] = []
    for row in rows:
        if row["name"] in absorbed:
            continue
        members = folded.get(row["name"])
        if members is None:
            result.append(row)
            continue
        triple_rows = [by_name[members[key]] for key in ("bucket", "sum", "count")]
        merged = {**row, "classic_histogram": members}
        last_seen = [r["last_seen"] for r in triple_rows if r.get("last_seen")]
        merged["last_seen"] = max(last_seen) if last_seen else row.get("last_seen")
        if "first_seen" in row:
            first_seen = [r["first_seen"] for r in triple_rows if r.get("first_seen")]
            merged["first_seen"] = min(first_seen) if first_seen else None
        result.append(merged)
    return result


def cached_metric_names(
    team: Team,
    *,
    search: str = "",
    limit: int = 100,
    services: Sequence[str] = (),
    match: str = "substring",
    include_sparklines: bool = True,
    include_first_seen: bool = False,
) -> list[dict[str, Any]]:
    """Metric names for the picker. Only non-empty, unsearched lists are cached."""
    runner = MetricNamesQueryRunner(
        team=team,
        search=search,
        limit=limit,
        services=services,
        match=match,
        include_sparklines=include_sparklines,
        include_first_seen=include_first_seen,
    )
    if runner.search:
        return runner.run()

    # Hashed: service names can hold characters that a memcached key cannot.
    scope = sha256(repr(runner.services).encode()).hexdigest()[:16] if runner.services else "all"
    shape = f"{int(include_sparklines)}{int(include_first_seen)}"
    cache_key = f"metrics:{team.id}:metric_names:v4:{limit}:{shape}:{scope}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    names = runner.run()
    if names:
        cache.set(cache_key, names, METRIC_NAMES_CACHE_TTL)
    return names
