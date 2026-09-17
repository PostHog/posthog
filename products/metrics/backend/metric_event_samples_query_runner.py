"""Return raw metric samples for the Samples and metric-to-trace views.

Join samples to deduplicated series labels by `series_fingerprint`.
The sample row supplies name and type if its series row is missing.
The API uses hex trace IDs. Storage uses base64 trace IDs.
"""

import base64
import datetime as dt
from collections.abc import Sequence
from typing import Any

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.database.schema.metrics import HOGQL_MAX_BYTES_TO_READ_FOR_METRICS_USER_QUERIES
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.models import Team

from products.metrics.backend.facade.contracts import MetricFilter
from products.metrics.backend.facade.enums import MetricType
from products.metrics.backend.metric_query_runner import series_scope_expr, time_range_expr, type_filter_expr

# This query uses the shared ClickHouse cluster. Limit reads and fail on overflow.
_QUERY_SETTINGS = HogQLGlobalSettings(
    max_bytes_to_read=HOGQL_MAX_BYTES_TO_READ_FOR_METRICS_USER_QUERIES,
    read_overflow_mode="throw",
)


def _normalise_to_base64(value: str) -> str:
    """Convert API hex trace or span IDs to storage base64.

    Return invalid hex values unchanged to match tracing filters.
    """
    try:
        int(value, 16)
        return base64.b64encode(bytes.fromhex(value)).decode()
    except ValueError:
        return value


class MetricEventSamplesQueryRunner:
    def __init__(
        self,
        team: Team,
        *,
        metric_name: str | None = None,
        date_from: dt.datetime,
        date_to: dt.datetime,
        trace_id: str | None = None,
        span_id: str | None = None,
        filters: Sequence[MetricFilter] = (),
        metric_type: MetricType | None = None,
        limit: int = 100,
    ) -> None:
        # A trace query covers every metric name. `trace_id` has a bloom-filter index.
        if not metric_name and not trace_id:
            raise ValueError("metric_name or trace_id is required")
        if not metric_name and (filters or metric_type is not None):
            # Label filters need one metric name. Keep trace queries unscoped.
            raise ValueError("filters and metric_type require metric_name")
        if date_to <= date_from:
            raise ValueError("date_to must be after date_from")
        if limit <= 0 or limit > 1000:
            raise ValueError("limit must be in [1, 1000]")

        if span_id and not trace_id:
            # A span ID is unique only within its trace.
            raise ValueError("span_id requires trace_id")

        self.team = team
        self.metric_name = metric_name or ""
        self.date_from = date_from
        self.date_to = date_to
        self.trace_id = _normalise_to_base64((trace_id or "").strip())
        self.span_id = _normalise_to_base64((span_id or "").strip())
        self.filters = tuple(filters)
        self.metric_type = metric_type
        self.limit = limit

    def run(self) -> list[dict[str, Any]]:
        # An empty `trace_id` matches every row, so the query needs no optional clause.
        # Filter and limit samples in the CTE. Join labels after that selection.
        # Apply label filters before LIMIT. Otherwise, filtered results can look empty.
        # Read labels only for matched samples. Trace queries must not read every series.
        query = parse_select(
            """
                WITH matched_samples AS (
                    SELECT
                        team_id,
                        metric_name,
                        series_fingerprint,
                        timestamp,
                        value,
                        count,
                        trace_id,
                        span_id,
                        metric_type,
                        unit,
                        aggregation_temporality,
                        is_monotonic,
                        service_name
                    FROM posthog.metrics
                    WHERE ({metric_name} = '' OR metric_name = {metric_name})
                      AND {time_range}
                      AND ({trace_id} = '' OR trace_id = {trace_id})
                      AND ({span_id} = '' OR span_id = {span_id})
                      AND {type_filter}
                      AND {series_scope}
                    ORDER BY timestamp DESC
                    LIMIT {limit}
                )
                SELECT
                    s.timestamp,
                    s.metric_name,
                    s.metric_type,
                    s.value,
                    s.count,
                    s.unit,
                    s.aggregation_temporality,
                    s.is_monotonic,
                    s.service_name,
                    hex(tryBase64Decode(s.trace_id)) AS trace_id,
                    hex(tryBase64Decode(s.span_id)) AS span_id,
                    ser.attributes,
                    ser.resource_attributes
                FROM matched_samples AS s
                LEFT JOIN (
                    SELECT
                        team_id,
                        metric_name,
                        series_fingerprint,
                        any(attributes) AS attributes,
                        any(resource_attributes) AS resource_attributes
                    FROM posthog.metric_series
                    WHERE (metric_name, series_fingerprint) IN (
                        SELECT metric_name, series_fingerprint FROM matched_samples
                    )
                    GROUP BY team_id, metric_name, series_fingerprint
                ) AS ser
                    ON s.team_id = ser.team_id
                    AND s.metric_name = ser.metric_name
                    AND s.series_fingerprint = ser.series_fingerprint
                ORDER BY s.timestamp DESC
            """,
            placeholders={
                "metric_name": ast.Constant(value=self.metric_name),
                "time_range": time_range_expr(self.date_from, self.date_to),
                "trace_id": ast.Constant(value=self.trace_id),
                "span_id": ast.Constant(value=self.span_id),
                "type_filter": type_filter_expr(self.metric_type.value if self.metric_type else None),
                "series_scope": series_scope_expr(self.metric_name, self.filters, self.date_from),
                "limit": ast.Constant(value=self.limit),
            },
        )
        assert isinstance(query, ast.SelectQuery)

        response = execute_hogql_query(
            query_type="MetricEventSamplesQuery",
            query=query,
            team=self.team,
            workload=Workload.LOGS,  # metrics share the logs ClickHouse workload pool for now
            settings=_QUERY_SETTINGS,
        )

        return [
            {
                "timestamp": row[0].isoformat() if hasattr(row[0], "isoformat") else str(row[0]),
                "metric_name": row[1],
                "metric_type": row[2],
                "value": row[3],
                "count": int(row[4]),
                "unit": row[5],
                "aggregation_temporality": row[6],
                "is_monotonic": bool(row[7]),
                "service_name": row[8],
                "trace_id": row[9],
                "span_id": row[10],
                "attributes": dict(row[11]) if row[11] else {},
                "resource_attributes": dict(row[12]) if row[12] else {},
            }
            for row in response.results
        ]
