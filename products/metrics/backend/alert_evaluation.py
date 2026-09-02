"""Evaluate a metrics alert against ClickHouse metric data.

This is the domain-specific half of the alerting contract: it turns a
`MetricsAlertConfiguration` into the normalized `CheckResult` the shared state
machine consumes. It owns the metric query (via `MetricQueryRunner`) and the
threshold decision; it knows nothing about lifecycle state, cooldowns, or delivery.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any

import structlog

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.models.team import Team

from products.metrics.backend.alert_state_machine import CheckResult
from products.metrics.backend.facade.contracts import MetricFilter, MetricGroupBy
from products.metrics.backend.facade.enums import AttributeScope, FilterOp
from products.metrics.backend.metric_query_runner import MetricQueryRunner

if True:  # TYPE_CHECKING-style import without triggering Temporal sandbox issues
    from products.metrics.backend.models import MetricsAlertConfiguration

logger = structlog.get_logger(__name__)


class TransientMetricQueryError(Exception):
    """A ClickHouse / query-layer failure worth retrying rather than counting toward BROKEN."""


def _parse_filters(raw: list[dict[str, Any]]) -> tuple[MetricFilter, ...]:
    filters: list[MetricFilter] = []
    for f in raw or []:
        try:
            filters.append(
                MetricFilter(
                    key=f["key"],
                    op=FilterOp(f.get("op", FilterOp.EQ)),
                    value=str(f.get("value", "")),
                    scope=AttributeScope(f.get("scope", AttributeScope.AUTO)),
                )
            )
        except (KeyError, ValueError) as e:
            raise ValueError(f"Invalid metric alert filter {f!r}: {e}") from e
    return tuple(filters)


def _parse_group_by(raw: list[dict[str, Any]]) -> tuple[MetricGroupBy, ...]:
    group_by: list[MetricGroupBy] = []
    for g in raw or []:
        try:
            group_by.append(
                MetricGroupBy(
                    key=g["key"],
                    scope=AttributeScope(g.get("scope", AttributeScope.AUTO)),
                )
            )
        except (KeyError, ValueError) as e:
            raise ValueError(f"Invalid metric alert group_by {g!r}: {e}") from e
    return tuple(group_by)


def _compare(value: float, operator: str, threshold: float) -> bool:
    if operator == "below":
        return value < threshold
    return value > threshold


def evaluate_metric_alert(
    alert: MetricsAlertConfiguration,
    team: Team,
    *,
    date_to: datetime,
    query_runner_cls: type = MetricQueryRunner,
) -> CheckResult:
    """Run the alert's metric query over its trailing window and produce a CheckResult.

    The window is `[date_to - window_minutes, date_to)`. With no group_by the latest
    bucket's value is compared to the threshold. With group_by, the alert breaches if
    ANY group's latest value breaches, and that group's labels are carried on the
    result for the breach message. No data at all is a clear (non-breaching) check.
    """
    date_from = date_to - timedelta(minutes=alert.window_minutes)
    start = time.perf_counter()
    tag_queries(product=Product.METRICS, feature=Feature.ALERTING)
    try:
        runner = query_runner_cls(
            team=team,
            metric_name=alert.metric_name,
            aggregation=alert.aggregation,
            date_from=date_from,
            date_to=date_to,
            filters=_parse_filters(alert.filters),
            group_by=_parse_group_by(alert.group_by),
            quantile=alert.quantile,
        )
        rows = runner.run()
    except ValueError as e:
        # Config / query-shape problems are permanent, not transient.
        duration_ms = int((time.perf_counter() - start) * 1000)
        logger.warning("Metric alert query rejected", alert_id=str(alert.id), error=str(e))
        return CheckResult(
            value=None,
            threshold_breached=False,
            error_message=str(e),
            query_duration_ms=duration_ms,
            is_transient_error=False,
        )
    except Exception as e:
        duration_ms = int((time.perf_counter() - start) * 1000)
        logger.warning("Metric alert query failed", alert_id=str(alert.id), error=str(e))
        return CheckResult(
            value=None,
            threshold_breached=False,
            error_message=f"Metric query failed: {e}",
            query_duration_ms=duration_ms,
            is_transient_error=True,
        )

    duration_ms = int((time.perf_counter() - start) * 1000)
    return _check_result_from_rows(alert, rows, duration_ms)


def _check_result_from_rows(
    alert: MetricsAlertConfiguration,
    rows: list[dict[str, Any]],
    query_duration_ms: int,
) -> CheckResult:
    """Pure decision from runner rows — separated for unit testing.

    Rows are `{"time", "value", "labels"}`. We take the most recent bucket per
    group and breach if any group's value crosses the threshold.
    """
    # Latest value per group (labels-tuple -> value). Buckets arrive time-ordered,
    # so overwriting keeps the newest.
    latest_by_group: dict[tuple, tuple[float, dict]] = {}
    for row in rows:
        value = row.get("value")
        if value is None:
            continue
        labels = row.get("labels") or {}
        key = tuple(sorted(labels.items()))
        latest_by_group[key] = (float(value), labels)

    if not latest_by_group:
        return CheckResult(
            value=None,
            threshold_breached=False,
            query_duration_ms=query_duration_ms,
        )

    # Pick the "most breaching" group: for `above`, the max value; for `below`, the min.
    groups = list(latest_by_group.values())
    if alert.threshold_operator == "below":
        value, labels = min(groups, key=lambda g: g[0])
    else:
        value, labels = max(groups, key=lambda g: g[0])

    breached = _compare(value, alert.threshold_operator, alert.threshold_value)
    return CheckResult(
        value=value,
        threshold_breached=breached,
        labels=labels,
        query_duration_ms=query_duration_ms,
    )
