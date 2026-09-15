"""Attribute key/value autocomplete for the metrics filter bar.

Keys and values use precomputed counts from `metric_attributes`.
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

# Without an explicit window, suggest from recent data only — same lookback the
# metric names picker uses.
_DEFAULT_LOOKBACK = dt.timedelta(days=7)

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
    # Include the hour that contains the start of the requested window.
    return resolved_from.astimezone(dt.UTC).replace(minute=0, second=0, microsecond=0), resolved_to


def _validate_limit(limit: int) -> int:
    if limit <= 0 or limit > 1000:
        raise ValueError("limit must be in [1, 1000]")
    return limit


class MetricAttributeKeysQueryRunner:
    """Attribute keys ordered by occurrence count, with service_name first."""

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
        query = parse_select(
            """
                SELECT
                    attribute_key,
                    sum(attribute_count) AS occurrences
                FROM posthog.metric_attributes
                WHERE time_bucket >= {date_from}
                  AND time_bucket < {date_to}
                  AND {metric_name_filter}
                  AND {search_filter}
                GROUP BY attribute_key
                ORDER BY occurrences DESC, attribute_key ASC
                LIMIT {limit}
            """,
            placeholders={
                "date_from": ast.Constant(value=self.date_from),
                "date_to": ast.Constant(value=self.date_to),
                "metric_name_filter": (
                    ast.Constant(value=True)
                    if not self.metric_name
                    else ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Field(chain=["metric_name"]),
                        right=ast.Constant(value=self.metric_name),
                    )
                ),
                "search_filter": (
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.ILike,
                        left=ast.Field(chain=["attribute_key"]),
                        right=ast.Constant(value=ilike_pattern(self.search)),
                    )
                    if self.search
                    else ast.Constant(value=True)
                ),
                "limit": ast.Constant(value=self.limit + len(_SERVICE_NAME_KEYS)),
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

        # Remove service aliases after aggregation to avoid filtering each attribute row.
        results = [
            {"name": row[0], "attribute_count": int(row[1])}
            for row in response.results
            if row[0] not in _SERVICE_NAME_KEYS
        ]
        search_lower = self.search.lower()
        if search_lower in "service_name" or search_lower in "service.name":
            # The first-class service column has no attribute occurrence count.
            results.insert(0, {"name": "service_name", "attribute_count": None})
        return results[: self.limit]


class MetricAttributeValuesQueryRunner:
    """Observed values for one attribute key in a window, most frequent first.
    `service_name`/`service.name` read the first-class column instead of
    attribute rows, matching how filters on it are executed."""

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
                ast.Constant(value=True)
                if not self.metric_name
                else ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["metric_name"]),
                    right=ast.Constant(value=self.metric_name),
                )
            ),
            "search_pattern": ast.Constant(value=ilike_pattern(self.search)),
            "exact": ast.Constant(value=self.search),
            "limit": ast.Constant(value=self.limit),
        }
