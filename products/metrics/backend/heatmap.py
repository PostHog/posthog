from posthog.schema import MetricsHistogramQuery, MetricsOtelType, MetricsQuery, MetricsQueryLanguage

from products.metrics.backend.facade.contracts import MetricsHeatmapIneligibleError

# A latency-over-time heatmap grids one distribution; gauges and counters have no per-bucket histogram.
HISTOGRAM_METRIC_TYPES = frozenset(
    {MetricsOtelType.HISTOGRAM, MetricsOtelType.EXPONENTIAL_HISTOGRAM, MetricsOtelType.SUMMARY}
)


def metrics_histogram_query_for(query: MetricsQuery) -> MetricsHistogramQuery:
    """Build the heatmap's histogram query from a metrics query with the heatmap display.

    Mirrors `heatmapEligible` and `histogramQueryNode` in the frontend `metricsViewerLogic`, so a stored
    query renders the same grid the editor previewed. Raises `MetricsHeatmapIneligibleError` with a
    user-facing message when the query can't grid a distribution.
    """
    if query.language not in (None, MetricsQueryLanguage.BUILDER):
        raise MetricsHeatmapIneligibleError("A heatmap needs a builder query. PromQL and SQL can't draw one.")
    if len(query.clauses) != 1 or query.formula:
        raise MetricsHeatmapIneligibleError("A heatmap needs exactly one metric and no formula.")
    clause = query.clauses[0]
    if clause.groupBy:
        raise MetricsHeatmapIneligibleError("A heatmap can't group by attributes. Remove the group-by.")
    if clause.metricType not in HISTOGRAM_METRIC_TYPES:
        raise MetricsHeatmapIneligibleError("A heatmap needs a histogram metric.")
    return MetricsHistogramQuery(
        metricName=clause.metricName.strip(),
        metricType=clause.metricType,
        filters=clause.filters or None,
        dateRange=query.dateRange,
        interval=query.interval,
        variables=query.variables,
    )
