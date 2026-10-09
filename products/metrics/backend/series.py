from products.metrics.backend.facade.api import MAX_SERIES_PER_CLAUSE
from products.metrics.backend.facade.contracts import MetricPoint, MetricSeries


def rank_and_fill_series(
    rows: list[tuple[dict[str, str], str | None, str | None, list[MetricPoint]]],
) -> list[MetricSeries]:
    """Keep the largest series and put every series on one shared time grid.

    Each row is `(labels, metric_name, clause, points)`. Series rank by summed absolute value, as in
    the builder engine. A bucket with no point is a gap (None), not zero: a PromQL or SQL query
    with no row for a bucket has no data there.
    """
    ranked = sorted(
        rows,
        key=lambda row: (-sum(abs(point.value) for point in row[3] if point.value is not None), sorted(row[0].items())),
    )[:MAX_SERIES_PER_CLAUSE]
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
