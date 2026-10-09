from collections.abc import Sequence

from products.metrics.backend.facade.api import MAX_SERIES_PER_CLAUSE
from products.metrics.backend.facade.contracts import MAX_CLAUSES_PER_QUERY, MetricPoint, MetricSeries
from products.metrics.backend.metric_query_runner import _MAX_BUCKET_COUNT

# The most a builder query can return: every clause at its series cap, on the longest bucket grid.
# A PromQL or SQL query chooses its own clauses and times, so these limits bound its output too.
MAX_SERIES_TOTAL = MAX_CLAUSES_PER_QUERY * MAX_SERIES_PER_CLAUSE
# An unaligned range start adds a partial first bucket, and a PromQL range query includes its end.
MAX_POINTS_TOTAL = MAX_SERIES_TOTAL * (_MAX_BUCKET_COUNT + 2)

Row = tuple[dict[str, str], str | None, str | None, list[MetricPoint]]


def rank_and_fill_series(rows: Sequence[Row], *, fill: float | None) -> list[MetricSeries]:
    """Keep the largest series of each clause and put every series on one shared time grid.

    Each row is `(labels, metric_name, clause, points)`. Series rank by summed absolute value and the
    cap applies per clause, as in the builder engine. The grid is every time of every row, also the
    rows the cap drops, as in the builder engine. A bucket with no point gets `fill`.
    """
    grid = sorted({point.time for row in rows for point in row[3]})
    rows_by_clause: dict[str | None, list[Row]] = {}
    for row in rows:
        rows_by_clause.setdefault(row[2], []).append(row)
    ranked = [
        row
        for clause_rows in rows_by_clause.values()
        for row in sorted(
            clause_rows,
            key=lambda row: (
                -sum(abs(point.value) for point in row[3] if point.value is not None),
                sorted(row[0].items()),
            ),
        )[:MAX_SERIES_PER_CLAUSE]
    ]
    if len(ranked) > MAX_SERIES_TOTAL or len(ranked) * len(grid) > MAX_POINTS_TOTAL:
        raise ValueError(
            f"The query returns too many series or time buckets to chart ({len(ranked)} series, "
            f"{len(grid)} buckets). Use fewer series, a coarser interval, or a shorter date range."
        )
    series: list[MetricSeries] = []
    for labels, metric_name, clause, points in ranked:
        values = {point.time: point.value for point in points}
        series.append(
            MetricSeries(
                labels=labels,
                points=tuple(MetricPoint(time=time, value=values.get(time, fill)) for time in grid),
                metric_name=metric_name,
                clause=clause,
            )
        )
    return series
