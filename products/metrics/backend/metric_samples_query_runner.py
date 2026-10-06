"""Run time-series queries on `metric_samples` when the range starts after the metrics4 cut-over.

`build_metric_query_runner` selects the runner. A range that starts before the
cut-over, including the predecessor lookback, still needs the `metrics2` data of
the `metrics` view.
"""

import datetime as dt
from collections.abc import Sequence

from posthog.models import Team

from products.metrics.backend.facade.contracts import MetricFilter, MetricGroupBy
from products.metrics.backend.metric_query_runner import MetricQueryRunner
from products.metrics.backend.metrics4_samples import reads_metrics4_only


class MetricSamplesQueryRunner(MetricQueryRunner):
    """Read points from `metric_samples`, and filter series-hours before the `ARRAY JOIN`."""

    reads_samples = True


def build_metric_query_runner(
    *,
    team: Team,
    metric_name: str,
    aggregation: str,
    date_from: dt.datetime,
    date_to: dt.datetime,
    filters: Sequence[MetricFilter] = (),
    group_by: Sequence[MetricGroupBy] = (),
    interval: str | None = None,
    quantile: float | None = None,
    metric_type: str | None = None,
    min_interval: str | None = None,
) -> MetricQueryRunner:
    """Return the runner for the table that holds all points of the range."""
    runner = MetricQueryRunner(
        team=team,
        metric_name=metric_name,
        aggregation=aggregation,
        date_from=date_from,
        date_to=date_to,
        filters=filters,
        group_by=group_by,
        interval=interval,
        quantile=quantile,
        metric_type=metric_type,
        min_interval=min_interval,
    )
    if not reads_metrics4_only(runner.scan_from):
        return runner
    return MetricSamplesQueryRunner(
        team=team,
        metric_name=metric_name,
        aggregation=aggregation,
        date_from=date_from,
        date_to=date_to,
        filters=filters,
        group_by=group_by,
        interval=interval,
        quantile=quantile,
        metric_type=metric_type,
        min_interval=min_interval,
    )
