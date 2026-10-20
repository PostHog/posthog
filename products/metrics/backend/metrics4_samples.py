"""Read metric points from `metric_samples` (`metrics4_samples`) instead of the `metrics` view.

The `metrics` view reads `metrics2` before the cut-over hour and expands every
`metrics4_samples` array after it. A read whose range starts at or after the
cut-over needs only `metrics4_samples`. That table has one row for each
series-hour, so row filters skip complete series-hours before the `ARRAY JOIN`.
The `timestamp_min` and `timestamp_max` minmax indexes skip granules by point time.

A series-hour can have more than one row until ClickHouse merges them. Each
point is in exactly one row, so an `ARRAY JOIN` over the rows returns each point once.
"""

import datetime as dt
from collections.abc import Sequence

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select

from posthog.clickhouse.metrics.metrics2 import DEFAULT_RETENTION_DAYS
from posthog.clickhouse.metrics.metrics4 import METRICS4_VIEW_CUTOVER

METRICS4_CUTOVER = dt.datetime.fromisoformat(METRICS4_VIEW_CUTOVER).replace(tzinfo=dt.UTC)

METRICS_RETENTION = dt.timedelta(days=DEFAULT_RETENTION_DAYS)

# Each point column of `metrics` maps to one array of `metric_samples`.
_POINT_ARRAYS: dict[str, str] = {
    "timestamp": "timestamp_arr",
    "observed_timestamp": "observed_timestamp_arr",
    "value": "value_arr",
    "count": "count_arr",
    "histogram_counts": "histogram_counts_arr",
    "trace_id": "trace_id_arr",
    "span_id": "span_id_arr",
    "trace_flags": "trace_flags_arr",
}

_ROW_COLUMNS: frozenset[str] = frozenset(
    {
        "team_id",
        "metric_name",
        "time_bucket",
        "series_fingerprint",
        "resource_fingerprint",
        "service_name",
        "metric_type",
        "unit",
        "aggregation_temporality",
        "is_monotonic",
        "has_labels",
        "instrumentation_scope",
        "histogram_bounds",
    }
)


def _as_utc(value: dt.datetime) -> dt.datetime:
    return value.replace(tzinfo=dt.UTC) if value.tzinfo is None else value.astimezone(dt.UTC)


def reads_metrics4_only(scan_from: dt.datetime) -> bool:
    """Return true when a read that starts at `scan_from` needs no `metrics2` data."""
    return _as_utc(scan_from) >= METRICS4_CUTOVER


def _utc_hour(value: dt.datetime) -> dt.datetime:
    return _as_utc(value).replace(minute=0, second=0, microsecond=0)


def metric_name_expr(metric_names: Sequence[str] | None) -> ast.Expr:
    """Limit a read to `metric_names`. `None` keeps every name."""
    if metric_names is None:
        return ast.Constant(value=True)
    if len(metric_names) == 1:
        return parse_expr("metric_name = {name}", placeholders={"name": ast.Constant(value=metric_names[0])})
    return parse_expr(
        "metric_name IN {names}",
        placeholders={"names": ast.Tuple(exprs=[ast.Constant(value=name) for name in metric_names])},
    )


def _row_range_expr(date_from: dt.datetime, date_to: dt.datetime) -> ast.Expr:
    """Keep rows that can hold a point in `[date_from, date_to)`."""
    return parse_expr(
        """
            time_bucket >= {bucket_from}
            AND time_bucket <= {bucket_to}
            AND timestamp_max >= {date_from}
            AND timestamp_min < {date_to}
        """,
        placeholders={
            "bucket_from": ast.Constant(value=_utc_hour(date_from)),
            "bucket_to": ast.Constant(value=_utc_hour(date_to)),
            "date_from": ast.Constant(value=date_from),
            "date_to": ast.Constant(value=date_to),
        },
    )


def samples_points_query(
    *,
    columns: Sequence[str],
    metric_names: Sequence[str] | None,
    date_from: dt.datetime,
    date_to: dt.datetime,
    timezone: str,
    row_filters: Sequence[ast.Expr] = (),
    point_filters: Sequence[ast.Expr] = (),
) -> ast.SelectQuery:
    """Return one row per point in `[date_from, date_to)`, with the column names of `metrics`.

    HogQL converts only `DateTime` fields to the project time zone, not array
    elements. So `timestamp` is converted to `timezone` here, to bucket as `metrics` does.

    `row_filters` can use only row columns. They apply before the `ARRAY JOIN`.
    `point_filters` can use the selected columns. They apply after it.
    `metric_names=None` reads every metric name.
    """
    unknown = [column for column in columns if column not in _POINT_ARRAYS and column not in _ROW_COLUMNS]
    if unknown:
        raise ValueError(f"Unknown metric_samples columns: {unknown!r}")

    # The time filter always needs the timestamp array.
    point_columns = ["timestamp", *(column for column in columns if column in _POINT_ARRAYS and column != "timestamp")]
    row_columns = [column for column in columns if column in _ROW_COLUMNS]

    rows = parse_select(
        "SELECT 1 FROM posthog.metric_samples WHERE {metric_name} AND {row_range}",
        placeholders={"metric_name": metric_name_expr(metric_names), "row_range": _row_range_expr(date_from, date_to)},
    )
    assert isinstance(rows, ast.SelectQuery)
    rows.select = [
        *(ast.Field(chain=[column]) for column in row_columns),
        *(ast.Field(chain=[_POINT_ARRAYS[column]]) for column in point_columns),
    ]
    if row_filters:
        assert rows.where is not None
        rows.where = ast.And(exprs=[rows.where, *row_filters])

    point_range = parse_expr(
        "point_timestamp >= {date_from} AND point_timestamp < {date_to}",
        placeholders={"date_from": ast.Constant(value=date_from), "date_to": ast.Constant(value=date_to)},
    )

    select: list[ast.Expr] = [
        ast.Alias(
            alias="timestamp",
            expr=ast.Call(name="toTimeZone", args=[ast.Field(chain=["point_timestamp"]), ast.Constant(value=timezone)]),
        )
        if column == "timestamp"
        else ast.Field(chain=[column])
        for column in columns
    ]
    return ast.SelectQuery(
        select=select,
        select_from=ast.JoinExpr(table=rows),
        array_join_op="ARRAY JOIN",
        array_join_list=[
            ast.Alias(
                alias="point_timestamp" if column == "timestamp" else column,
                expr=ast.Field(chain=[_POINT_ARRAYS[column]]),
            )
            for column in point_columns
        ],
        where=ast.And(exprs=[point_range, *point_filters]),
    )


def series_in_range_query(metric_name: str, date_from: dt.datetime, date_to: dt.datetime) -> ast.SelectQuery:
    """Return the fingerprints of the series with a point in `[date_from, date_to)`.

    This read needs no `ARRAY JOIN`. It checks the timestamp array of each row.
    """
    query = parse_select(
        """
            SELECT series_fingerprint
            FROM posthog.metric_samples
            WHERE metric_name = {metric_name}
              AND {row_range}
              AND arrayExists(t -> t >= {date_from} AND t < {date_to}, timestamp_arr)
            GROUP BY series_fingerprint
        """,
        placeholders={
            "metric_name": ast.Constant(value=metric_name),
            "row_range": _row_range_expr(date_from, date_to),
            "date_from": ast.Constant(value=date_from),
            "date_to": ast.Constant(value=date_to),
        },
    )
    assert isinstance(query, ast.SelectQuery)
    return query
