from products.metrics.backend.facade.api import MAX_SERIES_PER_CLAUSE
from products.metrics.backend.facade.contracts import MetricPoint, MetricSeries


def rank_and_fill_series(
    rows: list[tuple[dict[str, str], str | None, str | None, list[MetricPoint]]],
) -> list[MetricSeries]:
    """Keep the largest series of each clause and put every series on one shared time grid.

    Each row is `(labels, metric_name, clause, points)`. Series rank by summed absolute value and the
    cap applies per clause, as in the builder engine. A bucket with no point is a gap (None), not
    zero: a PromQL or SQL query with no row for a bucket has no data there.
    """
    rows_by_clause: dict[str | None, list[tuple[dict[str, str], str | None, str | None, list[MetricPoint]]]] = {}
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
    grid = sorted({point.time for row in ranked for point in row[3]})
    series: list[MetricSeries] = []
    for labels, metric_name, clause, points in ranked:
        values = {point.time: point.value for point in points}
        series.append(
            MetricSeries(
                labels=labels,
                points=tuple(MetricPoint(time=time, value=values.get(time)) for time in grid),
                metric_name=metric_name,
                clause=clause,
            )
        )
    return series
