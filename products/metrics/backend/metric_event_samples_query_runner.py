"""Raw metric emissions for a metric, from the metrics/metric_series split.

Unlike `MetricQueryRunner` (which aggregates `metrics` into a time series), this
returns individual emissions — value, attributes, and the trace linkage — newest
first. It backs the Samples view and the metric->trace pivot.

Joins `posthog.metrics` (one row per data point) to `posthog.metric_series`
(the deduped label set) on `series_fingerprint`. Samples are filtered + limited
first, then enriched with their series' labels; the series side is grouped so a
ReplacingMergeTree duplicate never multiplies a sample. Everything except the
two label maps comes from the sample row itself, so an emission whose series
row hasn't landed yet still renders with its name and type (labels fall back
to empty).

Trace/span ids are stored base64-encoded (as capture-logs writes exemplars) but
cross the API boundary as hex, matching the tracing product's contract — so a
sample's trace_id can be passed straight to the trace endpoint / trace URL.
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

# This runs on the ClickHouse cluster shared with the live logs/traces
# products, so cap how much one request may read. Same budget the chart
# queries get, and the same throw-on-overflow: a truncated sample list would
# read as "these are the emissions" while silently hiding most of them.
_QUERY_SETTINGS = HogQLGlobalSettings(
    max_bytes_to_read=HOGQL_MAX_BYTES_TO_READ_FOR_METRICS_USER_QUERIES,
    read_overflow_mode="throw",
)


def _normalise_to_base64(value: str) -> str:
    """Hex trace/span ids (the API form) become the base64 the storage holds.

    No-op for values that aren't valid hex, mirroring the tracing product's
    filter normalisation so both pivot directions accept the same id string.
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
        # A trace-only query (the trace->metrics pivot) spans every metric name; it stays
        # bounded because trace_id carries a bloom-filter index (idx_trace_id_bf).
        if not metric_name and not trace_id:
            raise ValueError("metric_name or trace_id is required")
        if not metric_name and (filters or metric_type is not None):
            # Label filters scope the series of ONE metric; without a name there is no
            # series set to scope. The type constraint is kept to the same rule so the
            # trace pivot stays a plain "everything this trace touched" view.
            raise ValueError("filters and metric_type require metric_name")
        if date_to <= date_from:
            raise ValueError("date_to must be after date_from")
        if limit <= 0 or limit > 1000:
            raise ValueError("limit must be in [1, 1000]")

        if span_id and not trace_id:
            # A span id is only unique within its trace, so an unanchored span filter
            # would silently mix emissions from unrelated traces.
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
        # The trace filter is an always-present predicate that is a no-op when no
        # trace is given, so the optional clause never has to be spliced into the
        # query string (which would collide with the HogQL placeholder braces) —
        # an empty {trace_id} matches every row. Samples are filtered + limited in
        # the CTE, then left-joined to the deduped series for labels. The label
        # filters sit inside the CTE, before its LIMIT: filtering after the LIMIT
        # would take the newest `limit` emissions across every series and then
        # discard most of them, so a filtered view would look almost empty while
        # the chart shows plenty. The series side reads only the label sets of
        # the matched samples: without that bound, a query with no metric name
        # (the trace pivot) would aggregate every series in the project just to
        # enrich at most {limit} rows.
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
                "series_scope": series_scope_expr(self.metric_name, self.filters),
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
