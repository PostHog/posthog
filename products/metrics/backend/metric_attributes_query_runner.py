"""Attribute key/value autocomplete for the metrics filter bar.

Keys for one metric count distinct attribute values from recent series metadata.
Keys across all metrics and values (for one metric or all) use the `metric_attributes` aggregate table:
scanning series metadata without a metric name reads every attribute map.
Both queries merge metric attributes and resource attributes.
"""

import datetime as dt
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

# `time_bucket` floors timestamps to hourly buckets (see `_attributes_mv` in
# posthog/clickhouse/metrics/metrics2.py); widen the lower bound so points near
# the window start aren't dropped with their bucket.
_TIME_BUCKET_INTERVAL = dt.timedelta(hours=1)

# Without an explicit window, suggest from recent data only — same lookback the
# metric names picker uses.
_DEFAULT_LOOKBACK = dt.timedelta(hours=24)

# Value search probes `attribute_value` with ILIKE %search%, which scans far more rows than the
# key-only path. Require a meaningfully specific term, as logs and traces do.
MIN_VALUE_SEARCH_LENGTH = 4

# Autocomplete tolerates partial results, so reads break at the budget instead
# of erroring the way the chart queries do.
_QUERY_SETTINGS = HogQLGlobalSettings(
    max_bytes_to_read=HOGQL_MAX_BYTES_TO_READ_FOR_METRICS_USER_QUERIES,
    read_overflow_mode="break",
)


def _resolve_window(date_from: dt.datetime | None, date_to: dt.datetime | None) -> tuple[dt.datetime, dt.datetime]:
    resolved_to = date_to or dt.datetime.now(dt.UTC)
    resolved_from = date_from or (resolved_to - _DEFAULT_LOOKBACK)
    if resolved_to <= resolved_from:
        raise ValueError("date_to must be after date_from")
    return resolved_from - _TIME_BUCKET_INTERVAL, resolved_to


def _validate_limit(limit: int) -> int:
    if limit <= 0 or limit > 1000:
        raise ValueError("limit must be in [1, 1000]")
    return limit


class MetricAttributeKeysQueryRunner:
    """Attribute keys ordered by distinct value count from recent series.
    The synthetic `service_name` key only stands in for series without a `service.name`
    resource attribute, so senders see the one spelling they emit."""

    def __init__(
        self,
        team: Team,
        *,
        metric_name: str = "",
        search: str = "",
        search_values: bool = False,
        date_from: dt.datetime | None = None,
        date_to: dt.datetime | None = None,
        limit: int = 100,
    ) -> None:
        self.team = team
        self.metric_name = metric_name.strip()
        self.search = search.strip()
        self.search_values = search_values
        self.bucket_date_from, self.date_to = _resolve_window(date_from, date_to)
        self.date_from = self.bucket_date_from + _TIME_BUCKET_INTERVAL
        self.limit = _validate_limit(limit)

    def _should_search_values(self) -> bool:
        return self.search_values and len(self.search) >= MIN_VALUE_SEARCH_LENGTH

    def run(self) -> list[dict[str, Any]]:
        results = self._key_results()
        if self._should_search_values():
            results = self._with_value_matches(results)
        return results

    def _key_results(self) -> list[dict[str, Any]]:
        query = self._series_query() if self.metric_name else self._aggregate_query()

        response = execute_hogql_query(
            query_type="MetricAttributeKeysQuery",
            query=query,
            team=self.team,
            workload=Workload.LOGS,  # metrics share the logs ClickHouse workload pool for now
            settings=_QUERY_SETTINGS,
        )

        results = [{"name": row[0], "value_count": int(row[1])} for row in response.results]
        search_lower = self.search.lower()
        if not results and (search_lower in "service_name" or search_lower in "service.name"):
            results.append({"name": "service_name", "value_count": 0})
        return results

    def _with_value_matches(self, key_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # Keys whose name matches the search rank above keys that only match on a value, and a key
        # the name search already found keeps that plain row, so it is not listed twice.
        response = execute_hogql_query(
            query_type="MetricAttributeValueSearchQuery",
            query=self._value_matches_query(),
            team=self.team,
            workload=Workload.LOGS,  # metrics share the logs ClickHouse workload pool for now
            settings=_QUERY_SETTINGS,
        )

        known_keys = {row["name"] for row in key_results}
        value_results = [
            {
                "name": row[0],
                "value_count": int(row[2]),
                "matchedOn": "value",
                "matchedValue": row[1] or None,
            }
            for row in response.results
            if row[0] not in known_keys
        ]
        return (key_results + value_results)[: self.limit]

    def _value_matches_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        # Keys whose *values* match the search, which the key-only queries cannot find. The
        # synthetic service key is never an attribute row, so it gets its own branch.
        return parse_select(
            """
                SELECT attribute_key, sample_value, value_count
                FROM (
                    SELECT
                        attribute_key,
                        argMax(attribute_value, attribute_count) AS sample_value,
                        uniq(attribute_value) AS value_count
                    FROM posthog.metric_attributes
                    WHERE time_bucket >= {date_from}
                      AND {metric_name_filter}
                      AND attribute_key NOT IN ('service_name', 'service.name')
                      AND attribute_value ILIKE {search_pattern}
                    GROUP BY attribute_key

                    UNION ALL

                    SELECT
                        if(has_dotted_service_name, 'service.name', 'service_name') AS attribute_key,
                        any(service_name) AS sample_value,
                        uniq(service_name) AS value_count
                    FROM (
                        SELECT service_name,
                            max(attribute_type = 'resource' AND attribute_key = 'service.name') AS has_dotted_service_name
                        FROM posthog.metric_attributes
                        WHERE time_bucket >= {date_from}
                          AND {metric_name_filter}
                        GROUP BY metric_name, service_name
                    )
                    WHERE service_name ILIKE {search_pattern}
                    GROUP BY attribute_key
                )
                ORDER BY value_count DESC, attribute_key ASC
                LIMIT {limit}
            """,
            placeholders={
                "date_from": ast.Constant(value=self.bucket_date_from),
                "metric_name_filter": self._metric_name_filter(),
                "search_pattern": ast.Constant(value=ilike_pattern(self.search)),
                "limit": ast.Constant(value=self.limit),
            },
        )

    def _metric_name_filter(self) -> ast.Expr:
        if not self.metric_name:
            return ast.Constant(value=True)
        return ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=["metric_name"]),
            right=ast.Constant(value=self.metric_name),
        )

    def _aggregate_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        # Like the series query, the window end is not enforced: keys come from recent data.
        return parse_select(
            """
                SELECT attribute_key, value_count
                FROM (
                    SELECT attribute_key, uniq(attribute_value) AS value_count
                    FROM posthog.metric_attributes
                    WHERE time_bucket >= {date_from}
                      AND attribute_key NOT IN ('service_name', 'service.name')
                      AND attribute_key ILIKE {search_pattern}
                    GROUP BY attribute_key
                    UNION ALL
                    -- A metric of a service that sends `service.name` lists that key.
                    -- Other metrics list the synthetic `service_name` key.
                    SELECT if(has_dotted_service_name, 'service.name', 'service_name') AS attribute_key,
                        uniq(service) AS value_count
                    FROM (
                        SELECT service_name AS service,
                            max(attribute_type = 'resource' AND attribute_key = 'service.name') AS has_dotted_service_name
                        FROM posthog.metric_attributes
                        WHERE time_bucket >= {date_from}
                        GROUP BY metric_name, service_name
                    )
                    WHERE 'service_name' ILIKE {search_pattern} OR 'service.name' ILIKE {search_pattern}
                    GROUP BY attribute_key
                )
                ORDER BY value_count DESC, attribute_key ASC
                LIMIT {limit}
            """,
            placeholders={
                "date_from": ast.Constant(value=self.bucket_date_from),
                "search_pattern": ast.Constant(value=ilike_pattern(self.search)),
                "limit": ast.Constant(value=self.limit),
            },
        )

    def _series_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        return parse_select(
            """
                SELECT
                    arrayJoin(arrayDistinct(arrayConcat(
                        mapKeys(attributes), mapKeys(resource_attributes),
                        if(mapContains(resource_attributes, 'service.name'), [], ['service_name'])
                    ))) AS attribute_key,
                    uniqCombined64(if(attribute_key IN ('service_name', 'service.name'), service_name,
                        if(arrayElement(resource_attributes, attribute_key) != '',
                            arrayElement(resource_attributes, attribute_key),
                            arrayElement(attributes, attribute_key)))) AS value_count
                FROM posthog.metric_series
                WHERE last_seen >= {date_from}
                  AND {metric_name_filter}
                  AND (attribute_key ILIKE {search_pattern}
                       OR (attribute_key = 'service_name' AND 'service.name' ILIKE {search_pattern})
                       OR (attribute_key = 'service.name' AND 'service_name' ILIKE {search_pattern}))
                GROUP BY attribute_key
                ORDER BY value_count DESC, attribute_key ASC
                LIMIT {limit}
            """,
            placeholders={
                "date_from": ast.Constant(value=self.date_from),
                "metric_name_filter": self._metric_name_filter(),
                "search_pattern": ast.Constant(value=ilike_pattern(self.search)),
                "limit": ast.Constant(value=self.limit),
            },
        )


class MetricAttributeValuesQueryRunner:
    """Observed values for one attribute key in a window, most frequent first.
    `service_name`/`service.name` read the first-class column instead of
    attribute rows, matching how filters on it are executed. A metric name
    limits values to values seen on that metric."""

    def __init__(
        self,
        team: Team,
        *,
        key: str,
        metric_name: str = "",
        search: str = "",
        date_from: dt.datetime | None = None,
        date_to: dt.datetime | None = None,
        limit: int = 100,
    ) -> None:
        if not key:
            raise ValueError("key is required")
        self.team = team
        self.key = key
        self.metric_name = metric_name.strip()
        self.search = search.strip()
        self.date_from, self.date_to = _resolve_window(date_from, date_to)
        self.limit = _validate_limit(limit)

    def run(self) -> list[dict[str, Any]]:
        if self.key in _SERVICE_NAME_KEYS:
            query = parse_select(
                """
                    SELECT
                        service_name AS value,
                        sum(attribute_count) AS total_count
                    FROM posthog.metric_attributes
                    WHERE time_bucket >= {date_from}
                      AND time_bucket < {date_to}
                      AND {metric_name_filter}
                      AND service_name ILIKE {search_pattern}
                    GROUP BY service_name
                    ORDER BY
                        lower(service_name) = lower({exact}) DESC,
                        sum(attribute_count) DESC,
                        service_name ASC
                    LIMIT {limit}
                """,
                placeholders=self._placeholders(),
            )
        else:
            query = parse_select(
                """
                    SELECT
                        attribute_value AS value,
                        sum(attribute_count) AS total_count
                    FROM posthog.metric_attributes
                    WHERE time_bucket >= {date_from}
                      AND time_bucket < {date_to}
                      AND {metric_name_filter}
                      AND attribute_key = {key}
                      AND attribute_value ILIKE {search_pattern}
                    GROUP BY attribute_value
                    ORDER BY
                        lower(attribute_value) = lower({exact}) DESC,
                        sum(attribute_count) DESC,
                        attribute_value ASC
                    LIMIT {limit}
                """,
                placeholders=self._placeholders(),
            )
        assert isinstance(query, ast.SelectQuery)

        response = execute_hogql_query(
            query_type="MetricAttributeValuesQuery",
            query=query,
            team=self.team,
            workload=Workload.LOGS,  # metrics share the logs ClickHouse workload pool for now
            settings=_QUERY_SETTINGS,
        )

        return [{"id": row[0], "name": row[0], "count": int(row[1])} for row in response.results]

    def _placeholders(self) -> dict[str, ast.Expr]:
        return {
            "date_from": ast.Constant(value=self.date_from),
            "date_to": ast.Constant(value=self.date_to),
            "key": ast.Constant(value=self.key),
            "metric_name_filter": (
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["metric_name"]),
                    right=ast.Constant(value=self.metric_name),
                )
                if self.metric_name
                else ast.Constant(value=True)
            ),
            "search_pattern": ast.Constant(value=ilike_pattern(self.search)),
            "exact": ast.Constant(value=self.search),
            "limit": ast.Constant(value=self.limit),
        }
