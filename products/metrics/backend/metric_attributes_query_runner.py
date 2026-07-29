"""Attribute key/value autocomplete for the metrics filter bar.

Queries the `metric_attributes` aggregate table (fed by MVs on `metrics1`)
rather than the raw events table, mirroring the logs product's
`LogAttributesQueryRunner`/`LogValuesQueryRunner` pair. Keys are searched
across both datapoint ('metric') and resource attributes in one pass — the
viewer filters with scope 'auto', so the split is invisible to users.
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

# The OTel service name is a first-class column on `metric_attributes` (extracted
# at ingest), never an attribute row — both spellings resolve to it, mirroring
# `metric_query_runner.attribute_field`.
_SERVICE_NAME_KEYS: frozenset[str] = frozenset({"service_name", "service.name"})

# `time_bucket` floors timestamps to 10-minute buckets (see the MVs in
# posthog/clickhouse/metrics/metrics1.py); widen the lower bound so points near
# the window start aren't dropped with their bucket.
_TIME_BUCKET_INTERVAL = dt.timedelta(minutes=10)

# Without an explicit window, suggest from recent data only — same lookback the
# metric names picker uses.
_DEFAULT_LOOKBACK = dt.timedelta(days=7)

# Autocomplete tolerates partial results, so reads break at the budget instead
# of erroring the way the chart queries do.
_QUERY_SETTINGS = HogQLGlobalSettings(
    max_bytes_to_read=HOGQL_MAX_BYTES_TO_READ_FOR_METRICS_USER_QUERIES,
    read_overflow_mode="break",
)


def _ilike_pattern(search: str) -> str:
    """Escape ILIKE metacharacters so a literal '%'/'_' in the search doesn't wildcard."""
    escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


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
    """Distinct attribute keys seen on the team's metrics in a window, most
    frequent first, exact search matches floated to the top."""

    def __init__(
        self,
        team: Team,
        *,
        search: str = "",
        date_from: dt.datetime | None = None,
        date_to: dt.datetime | None = None,
        limit: int = 100,
    ) -> None:
        self.team = team
        self.search = search.strip()
        self.date_from, self.date_to = _resolve_window(date_from, date_to)
        self.limit = _validate_limit(limit)

    def run(self) -> list[dict[str, Any]]:
        query = parse_select(
            """
                SELECT
                    attribute_key AS name,
                    sum(attribute_count) AS total_count
                FROM posthog.metric_attributes
                WHERE time_bucket >= {date_from}
                  AND time_bucket < {date_to}
                  AND attribute_key ILIKE {search_pattern}
                GROUP BY attribute_key
                ORDER BY
                    lower(attribute_key) = lower({exact}) DESC,
                    sum(attribute_count) DESC,
                    attribute_key ASC
                LIMIT {limit}
            """,
            placeholders={
                "date_from": ast.Constant(value=self.date_from),
                "date_to": ast.Constant(value=self.date_to),
                "search_pattern": ast.Constant(value=_ilike_pattern(self.search)),
                "exact": ast.Constant(value=self.search),
                "limit": ast.Constant(value=self.limit),
            },
        )
        assert isinstance(query, ast.SelectQuery)

        response = execute_hogql_query(
            query_type="MetricAttributeKeysQuery",
            query=query,
            team=self.team,
            workload=Workload.LOGS,  # metrics share the logs ClickHouse workload pool for now
            settings=_QUERY_SETTINGS,
        )

        keys = [row[0] for row in response.results]
        # service_name lives in its own column, so it never appears as an attribute
        # row; surface it whenever it matches the search (mirrors anomaly key discovery).
        search_lower = self.search.lower()
        if (search_lower in "service_name" or search_lower in "service.name") and "service_name" not in keys:
            keys.insert(0, "service_name")
        return [{"name": key} for key in keys[: self.limit]]


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
        if self.key in _SERVICE_NAME_KEYS:
            query = parse_select(
                """
                    SELECT
                        service_name AS value,
                        sum(attribute_count) AS total_count
                    FROM posthog.metric_attributes
                    WHERE time_bucket >= {date_from}
                      AND time_bucket < {date_to}
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
            "search_pattern": ast.Constant(value=_ilike_pattern(self.search)),
            "exact": ast.Constant(value=self.search),
            "limit": ast.Constant(value=self.limit),
        }
