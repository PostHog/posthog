"""Attribute key/value autocomplete for the metrics filter bar.

Keys for one metric count distinct attribute values from series metadata.
Keys across all metrics and values use the `metric_attributes` aggregate table:
scanning series metadata without a metric name reads every attribute map.
Both queries merge metric attributes and resource attributes.

Suggestions come only from the selected time range. A range longer than
`_RECENT_SLICE` runs as two queries: the most recent slice first, then the
older part only when the first query returns fewer rows than the limit.
"""

import datetime as dt
from collections.abc import Callable, Sequence
from typing import Any

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.database.schema.metrics import HOGQL_MAX_BYTES_TO_READ_FOR_METRICS_USER_QUERIES
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.models import Team

from products.metrics.backend.search import ilike_pattern

# The OTel service name is a first-class column on `metric_attributes` (extracted
# at ingest), never an attribute row — both spellings resolve to it, mirroring
# `metric_query_runner.attribute_field`.
_SERVICE_NAME_KEYS: frozenset[str] = frozenset({"service_name", "service.name"})

# Without an explicit window, suggest from recent data only — same lookback the
# metric names picker uses.
_DEFAULT_LOOKBACK = dt.timedelta(hours=24)

# Longer ranges read this recent slice first, and the older part only to fill the limit.
_RECENT_SLICE = dt.timedelta(hours=2)

# Autocomplete tolerates partial results, so reads break at the budget instead
# of erroring the way the chart queries do.
_QUERY_SETTINGS = HogQLGlobalSettings(
    max_bytes_to_read=HOGQL_MAX_BYTES_TO_READ_FOR_METRICS_USER_QUERIES,
    read_overflow_mode="break",
)

# One slice query: (slice start, slice end, names already found, rows still needed) -> (name, count) rows.
_SliceQuery = Callable[[dt.datetime, dt.datetime, list[str], int], list[tuple[str, int]]]


def _as_utc(value: dt.datetime) -> dt.datetime:
    return value.replace(tzinfo=dt.UTC) if value.tzinfo is None else value.astimezone(dt.UTC)


def _resolve_window(date_from: dt.datetime | None, date_to: dt.datetime | None) -> tuple[dt.datetime, dt.datetime]:
    resolved_to = _as_utc(date_to) if date_to else dt.datetime.now(dt.UTC)
    resolved_from = _as_utc(date_from) if date_from else resolved_to - _DEFAULT_LOOKBACK
    if resolved_to <= resolved_from:
        raise ValueError("date_to must be after date_from")
    return resolved_from, resolved_to


def _validate_limit(limit: int) -> int:
    if limit <= 0 or limit > 1000:
        raise ValueError("limit must be in [1, 1000]")
    return limit


def _bucket_start(value: dt.datetime) -> dt.datetime:
    # `time_bucket` floors timestamps to UTC hours, so the bucket that holds `value` starts here.
    return value.replace(minute=0, second=0, microsecond=0)


def _slices(date_from: dt.datetime, date_to: dt.datetime) -> list[tuple[dt.datetime, dt.datetime]]:
    split = date_to - _RECENT_SLICE
    if split <= date_from:
        return [(date_from, date_to)]
    return [(split, date_to), (date_from, split)]


def _run_slices(
    date_from: dt.datetime, date_to: dt.datetime, limit: int, run_slice: _SliceQuery
) -> list[tuple[str, int]]:
    rows: list[tuple[str, int]] = []
    for slice_from, slice_to in _slices(date_from, date_to):
        rows.extend(run_slice(slice_from, slice_to, [name for name, _ in rows], limit - len(rows)))
        if len(rows) >= limit:
            break
    return rows


def _not_seen(expr: ast.Expr, seen: Sequence[str]) -> ast.Expr:
    # The older slice skips names the recent slice found, so its rows only fill the remaining limit.
    if not seen:
        return ast.Constant(value=True)
    return ast.CompareOperation(
        op=ast.CompareOperationOp.NotIn,
        left=expr,
        right=ast.Tuple(exprs=[ast.Constant(value=name) for name in seen]),
    )


def _execute(query_type: str, query: ast.SelectQuery | ast.SelectSetQuery, team: Team) -> list[tuple[str, int]]:
    response = execute_hogql_query(
        query_type=query_type,
        query=query,
        team=team,
        workload=Workload.LOGS,  # metrics share the logs ClickHouse workload pool for now
        settings=_QUERY_SETTINGS,
    )
    return [(row[0], int(row[1])) for row in response.results]


class MetricAttributeKeysQueryRunner:
    """Attribute keys ordered by distinct value count, most recent slice first."""

    def __init__(
        self,
        team: Team,
        *,
        metric_name: str = "",
        search: str = "",
        date_from: dt.datetime | None = None,
        date_to: dt.datetime | None = None,
        limit: int = 100,
    ) -> None:
        self.team = team
        self.metric_name = metric_name.strip()
        self.search = search.strip()
        self.date_from, self.date_to = _resolve_window(date_from, date_to)
        self.limit = _validate_limit(limit)

    def run(self) -> list[dict[str, Any]]:
        rows = _run_slices(self.date_from, self.date_to, self.limit, self._run_slice)
        results = [{"name": name, "value_count": count} for name, count in rows]
        search_lower = self.search.lower()
        if not results and (search_lower in "service_name" or search_lower in "service.name"):
            results.append({"name": "service_name", "value_count": 0})
        return results

    def _run_slice(
        self, slice_from: dt.datetime, slice_to: dt.datetime, seen: list[str], limit: int
    ) -> list[tuple[str, int]]:
        if self.metric_name:
            query = self._series_query(slice_from, slice_to, seen, limit)
        else:
            query = self._aggregate_query(slice_from, slice_to, seen, limit)
        return _execute("MetricAttributeKeysQuery", query, self.team)

    def _aggregate_query(
        self, slice_from: dt.datetime, slice_to: dt.datetime, seen: list[str], limit: int
    ) -> ast.SelectQuery | ast.SelectSetQuery:
        return parse_select(
            """
                SELECT attribute_key, value_count
                FROM (
                    SELECT attribute_key, uniq(attribute_value) AS value_count
                    FROM posthog.metric_attributes
                    WHERE time_bucket >= {bucket_from}
                      AND time_bucket < {date_to}
                      AND attribute_key ILIKE {search_pattern}
                      AND {key_not_seen}
                    GROUP BY attribute_key
                    UNION ALL
                    SELECT 'service_name' AS attribute_key, uniq(service_name) AS value_count
                    FROM posthog.metric_attributes
                    WHERE time_bucket >= {bucket_from}
                      AND time_bucket < {date_to}
                      AND ('service_name' ILIKE {search_pattern} OR 'service.name' ILIKE {search_pattern})
                      AND {service_not_seen}
                    HAVING value_count > 0
                )
                ORDER BY value_count DESC, attribute_key ASC
                LIMIT {limit}
            """,
            placeholders={
                "bucket_from": ast.Constant(value=_bucket_start(slice_from)),
                "date_to": ast.Constant(value=slice_to),
                "search_pattern": ast.Constant(value=ilike_pattern(self.search)),
                "key_not_seen": _not_seen(ast.Field(chain=["attribute_key"]), seen),
                "service_not_seen": _not_seen(ast.Constant(value="service_name"), seen),
                "limit": ast.Constant(value=limit),
            },
        )

    def _series_query(
        self, slice_from: dt.datetime, slice_to: dt.datetime, seen: list[str], limit: int
    ) -> ast.SelectQuery | ast.SelectSetQuery:
        # A series row covers one hour and keeps its latest point there. A row whose
        # latest point is after the slice end can still hold points inside it, so the
        # end bound compares the hour.
        return parse_select(
            """
                SELECT
                    arrayJoin(arrayDistinct(arrayConcat(
                        mapKeys(attributes), mapKeys(resource_attributes), ['service_name']
                    ))) AS attribute_key,
                    uniqCombined64(if(attribute_key IN ('service_name', 'service.name'), service_name,
                        if(arrayElement(resource_attributes, attribute_key) != '',
                            arrayElement(resource_attributes, attribute_key),
                            arrayElement(attributes, attribute_key)))) AS value_count
                FROM posthog.metric_series
                WHERE metric_name = {metric_name}
                  AND last_seen >= {date_from}
                  AND toStartOfHour(last_seen) < {date_to}
                  AND (attribute_key ILIKE {search_pattern}
                       OR (attribute_key = 'service_name' AND 'service.name' ILIKE {search_pattern}))
                  AND {key_not_seen}
                GROUP BY attribute_key
                ORDER BY value_count DESC, attribute_key ASC
                LIMIT {limit}
            """,
            placeholders={
                "metric_name": ast.Constant(value=self.metric_name),
                "date_from": ast.Constant(value=slice_from),
                "date_to": ast.Constant(value=slice_to),
                "search_pattern": ast.Constant(value=ilike_pattern(self.search)),
                "key_not_seen": _not_seen(ast.Field(chain=["attribute_key"]), seen),
                "limit": ast.Constant(value=limit),
            },
        )


class MetricAttributeValuesQueryRunner:
    """Observed values for one attribute key in a window, most frequent first.
    `service_name`/`service.name` read the first-class column instead of
    attribute rows, matching how filters on it are executed."""

    def __init__(
        self,
        team: Team,
        *,
        key: str,
        search: str = "",
        date_from: dt.datetime | None = None,
        date_to: dt.datetime | None = None,
        limit: int = 100,
    ) -> None:
        if not key:
            raise ValueError("key is required")
        self.team = team
        self.key = key
        self.search = search.strip()
        self.date_from, self.date_to = _resolve_window(date_from, date_to)
        self.limit = _validate_limit(limit)

    def run(self) -> list[dict[str, Any]]:
        rows = _run_slices(self.date_from, self.date_to, self.limit, self._run_slice)
        return [{"id": value, "name": value, "count": count} for value, count in rows]

    def _run_slice(
        self, slice_from: dt.datetime, slice_to: dt.datetime, seen: list[str], limit: int
    ) -> list[tuple[str, int]]:
        if self.key in _SERVICE_NAME_KEYS:
            query = parse_select(
                """
                    SELECT
                        service_name AS value,
                        sum(attribute_count) AS total_count
                    FROM posthog.metric_attributes
                    WHERE time_bucket >= {bucket_from}
                      AND time_bucket < {date_to}
                      AND service_name ILIKE {search_pattern}
                      AND {not_seen}
                    GROUP BY service_name
                    ORDER BY
                        lower(service_name) = lower({exact}) DESC,
                        sum(attribute_count) DESC,
                        service_name ASC
                    LIMIT {limit}
                """,
                placeholders=self._placeholders(slice_from, slice_to, "service_name", seen, limit),
            )
        else:
            query = parse_select(
                """
                    SELECT
                        attribute_value AS value,
                        sum(attribute_count) AS total_count
                    FROM posthog.metric_attributes
                    WHERE time_bucket >= {bucket_from}
                      AND time_bucket < {date_to}
                      AND attribute_key = {key}
                      AND attribute_value ILIKE {search_pattern}
                      AND {not_seen}
                    GROUP BY attribute_value
                    ORDER BY
                        lower(attribute_value) = lower({exact}) DESC,
                        sum(attribute_count) DESC,
                        attribute_value ASC
                    LIMIT {limit}
                """,
                placeholders=self._placeholders(slice_from, slice_to, "attribute_value", seen, limit),
            )
        return _execute("MetricAttributeValuesQuery", query, self.team)

    def _placeholders(
        self, slice_from: dt.datetime, slice_to: dt.datetime, value_column: str, seen: list[str], limit: int
    ) -> dict[str, ast.Expr]:
        return {
            "bucket_from": ast.Constant(value=_bucket_start(slice_from)),
            "date_to": ast.Constant(value=slice_to),
            "key": ast.Constant(value=self.key),
            "search_pattern": ast.Constant(value=ilike_pattern(self.search)),
            "exact": ast.Constant(value=self.search),
            "not_seen": _not_seen(ast.Field(chain=[value_column]), seen),
            "limit": ast.Constant(value=limit),
        }
