"""Read-time refresh of the saved metric snapshots on signal reports.

A report's prose is a point-in-time description and never changes here. Only the numbers do: when a
person opens the inbox list or a report, the metrics on screen re-run their stored query through the
normal query cache and the newest result replaces the saved ``value``, ``value_at``, and ``series``
and clears any legacy ``comparison``.
This is the error tracking model: counts are computed on read, cached, and bounded by what the page
shows, so a report nobody opens costs no queries.

The refresh runs without a requesting user, like the query cache the detail view shares, so the
stored snapshot is one shared value under the team's default property rules. A viewer whose
property or resource access differs from that context can neither trigger nor read it; the same
``ReportMetricAccessPolicy`` gates both.
"""

from __future__ import annotations

import math
import time
from collections.abc import Sequence
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone

import structlog

from posthog.schema import ChartDisplayType

from posthog.clickhouse.query_tagging import tag_queries
from posthog.dataclasses import frozen
from posthog.models import Team

from products.product_analytics.backend.facade.queries import run_cached_trends_query
from products.signals.backend.models import SignalReport
from products.signals.backend.report_metric_access import ReportMetricAccessPolicy
from products.signals.backend.report_metrics import MAX_METRIC_SERIES_POINTS, ReportMetric

logger = structlog.get_logger(__name__)

# A snapshot younger than this is served as is, so reopening the inbox does not re-run every row's
# query. The detail view still shows the live value through its own query.
REPORT_METRIC_SNAPSHOT_FRESH_FOR = timedelta(minutes=15)
# One inbox page, so a single request never carries a fleet-sized id list.
MAX_REPORT_METRIC_REFRESH_REPORTS = 20
# Each Trends shape can run once per source series. The source-run cap and deadline bound the work;
# whatever does not fit stays on its previous snapshot until the next open.
MAX_REPORT_METRIC_SOURCE_RUNS_PER_REQUEST = 40
REPORT_METRIC_REFRESH_TIME_BUDGET_SECONDS = 20.0
REPORT_METRIC_REFRESH_QUERY_TIMEOUT_SECONDS = 20

CURRENT_REPORT_STATUSES = (SignalReport.Status.READY, SignalReport.Status.PENDING_INPUT)


@frozen
class MetricMeasurement:
    value: float
    measured_at: datetime
    series: list[float] | None


@frozen
class ReportMetricRefreshSummary:
    refreshed: int
    skipped: int
    failed: int


def card_metric_id(metrics: object) -> str | None:
    """The metric an inbox row shows: the affected-users count, else the primary observation."""

    if not isinstance(metrics, list):
        return None
    rows = [row for row in metrics if isinstance(row, dict) and isinstance(row.get("metric_id"), str)]
    for predicate in (lambda row: row.get("kind") == "affected_users", lambda row: row.get("role") == "primary"):
        for row in rows:
            if predicate(row):
                return row["metric_id"]
    return None


def snapshot_is_fresh(metric: dict[str, Any], now: datetime) -> bool:
    value_at = metric.get("value_at")
    if metric.get("value") is None or not isinstance(value_at, str):
        return False
    try:
        measured_at = datetime.fromisoformat(value_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    if measured_at.tzinfo is None:
        measured_at = measured_at.replace(tzinfo=UTC)
    return now - measured_at < REPORT_METRIC_SNAPSHOT_FRESH_FOR


def _source_count(query: dict[str, Any]) -> int:
    source = query.get("source")
    series = source.get("series") if isinstance(source, dict) else None
    return len(series) if isinstance(series, list) and series else 1


def _run_metric_query(
    query: dict[str, Any], team: Team, display: ChartDisplayType, *, deadline: float
) -> tuple[dict, datetime | None]:
    """Run the stored query in one derived display shape and return its first series and response.

    The derived shapes match the ones the report detail sends through the frontend Query path, so
    both sides read and warm the same cache entries.
    """

    source = query.get("source")
    if not isinstance(source, dict):
        raise ValueError("metric query has no Trends source")

    shaped_source = deepcopy(source)
    trends_filter = shaped_source.get("trendsFilter")
    shaped_filter = {**(trends_filter if isinstance(trends_filter, dict) else {}), "display": display}
    if display == ChartDisplayType.ACTIONS_BAR:
        shaped_filter["showPercentStackView"] = False
        shaped_filter.pop("hiddenLegendIndexes", None)
    shaped_source["trendsFilter"] = shaped_filter
    remaining = deadline - time.monotonic()
    source_count = _source_count(query)
    if remaining < source_count:
        raise TimeoutError("report metric refresh budget expired")
    timeout = (
        REPORT_METRIC_REFRESH_QUERY_TIMEOUT_SECONDS
        if math.isinf(remaining)
        else min(REPORT_METRIC_REFRESH_QUERY_TIMEOUT_SECONDS, int(remaining / source_count))
    )
    tag_queries(trigger="signals_report_metric_refresh")
    response = run_cached_trends_query(
        query=shaped_source,
        team=team,
        max_execution_time_seconds=timeout,
        cache_age_seconds=int(REPORT_METRIC_SNAPSHOT_FRESH_FOR.total_seconds()),
    )
    results = response.results
    if not isinstance(results, list) or not results or not isinstance(results[0], dict):
        raise ValueError("metric query returned no series")
    return results[0], response.last_refresh


def _finite_number(raw: object, *, what: str) -> float:
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        raise ValueError(f"metric query returned a non-numeric {what}")
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError(f"metric query returned a non-finite {what}")
    return value


def whole_window_value(query: dict[str, Any], team: Team, *, deadline: float = math.inf) -> tuple[float, datetime]:
    first_series, last_refresh = _run_metric_query(query, team, ChartDisplayType.BOLD_NUMBER, deadline=deadline)
    value = _finite_number(first_series.get("aggregated_value"), what="aggregate")
    measured_at = last_refresh if isinstance(last_refresh, datetime) else timezone.now()
    if measured_at.tzinfo is None or measured_at.utcoffset() is None:
        measured_at = measured_at.replace(tzinfo=UTC)
    return value, measured_at


def longitudinal_values(query: dict[str, Any], team: Team, *, deadline: float = math.inf) -> list[float]:
    """The trailing per-bucket values, oldest first, for the row-sized trend strip."""

    first_series, _ = _run_metric_query(query, team, ChartDisplayType.ACTIONS_BAR, deadline=deadline)
    raw_points = first_series.get("data")
    if not isinstance(raw_points, list):
        raise ValueError("metric query returned no buckets")
    return [_finite_number(point, what="bucket") for point in raw_points[-MAX_METRIC_SERIES_POINTS:]]


def measure_metric(query: dict[str, Any], team: Team, *, deadline: float, include_series: bool) -> MetricMeasurement:
    value, measured_at = whole_window_value(query, team, deadline=deadline)
    series: list[float] | None
    if not include_series or time.monotonic() >= deadline:
        return MetricMeasurement(value=value, measured_at=measured_at, series=None)
    try:
        series = longitudinal_values(query, team, deadline=deadline)
    except Exception:
        # The buckets only decorate the row, so losing them must not cost the headline value.
        logger.exception("signals.report_metric_refresh.series_query_failed", team_id=team.id)
        series = None
    return MetricMeasurement(value=value, measured_at=measured_at, series=series)


def _persist_metric_snapshot(
    *,
    team_id: int,
    report_id: str,
    expected_metrics: list[dict[str, Any]],
    metric_id: str,
    measurement: MetricMeasurement,
) -> list[dict[str, Any]] | None:
    """Write the snapshot only while the complete metric state still matches what was measured.

    The row lock makes the whole metrics value the compare-and-swap token, so a concurrent edit that
    replaced or reordered the set wins. A cached result measured before the saved snapshot cannot
    replace it. `updated_at` is left alone so the inbox does not reorder reports because a number
    refreshed. Returns the new metrics list, or None when nothing was written.
    """

    with transaction.atomic():
        report = (
            SignalReport.objects.select_for_update()
            .filter(team_id=team_id, id=report_id, status__in=CURRENT_REPORT_STATUSES)
            .first()
        )
        if report is None or report.metrics != expected_metrics:
            return None
        metric_index = next(
            (index for index, row in enumerate(expected_metrics) if row.get("metric_id") == metric_id),
            None,
        )
        if metric_index is None:
            return None
        current = expected_metrics[metric_index]
        saved_at = current.get("value_at")
        if isinstance(saved_at, str):
            try:
                saved_at_dt = datetime.fromisoformat(saved_at.replace("Z", "+00:00"))
            except ValueError:
                saved_at_dt = None
            if saved_at_dt is not None and (saved_at_dt.tzinfo is None or saved_at_dt.utcoffset() is None):
                saved_at_dt = saved_at_dt.replace(tzinfo=UTC)
            if saved_at_dt is not None and measurement.measured_at < saved_at_dt:
                return None
        refreshed = {
            **current,
            "value": measurement.value,
            "value_at": measurement.measured_at.isoformat(),
            "series": measurement.series,
            "comparison": None,
        }
        # The kind's own rules decide what a valid number is (a count is a whole non-negative
        # number, a rate's value stays within its bounds), so an out-of-range result is dropped
        # here instead of stored as a snapshot no reader could format. Those range rules cover the
        # headline value and the comparison, not the bucket series, which carries only the shared
        # finite and count rules.
        ReportMetric.model_validate(refreshed)
        metrics = [*expected_metrics[:metric_index], refreshed, *expected_metrics[metric_index + 1 :]]
        report.metrics = metrics
        report.save(update_fields=["metrics"])
        return metrics


def refresh_report_metric_snapshots(
    *,
    team: Team,
    reports: Sequence[SignalReport],
    policy: ReportMetricAccessPolicy,
) -> ReportMetricRefreshSummary:
    """Refresh the stale snapshots on the given reports, in place, within one request's budget.

    Every report's row metric comes first, then the supporting metrics, so an inbox page refreshes
    what each row shows before any report's tiles. Each report's in-memory `metrics` is updated as
    snapshots land, so the caller can serialize the instances it passed in.
    """

    now = timezone.now()
    deadline = time.monotonic() + REPORT_METRIC_REFRESH_TIME_BUDGET_SECONDS
    planned: list[tuple[SignalReport, str]] = []
    supporting: list[tuple[SignalReport, str]] = []
    for report in reports:
        if not isinstance(report.metrics, list):
            continue
        card_id = card_metric_id(report.metrics)
        for row in report.metrics:
            if not isinstance(row, dict) or not isinstance(row.get("metric_id"), str):
                continue
            (planned if row["metric_id"] == card_id else supporting).append((report, row["metric_id"]))
    planned.extend(supporting)

    refreshed = skipped = failed = 0
    source_runs = 0
    for report, metric_id in planned:
        row = next((r for r in report.metrics if isinstance(r, dict) and r.get("metric_id") == metric_id), None)
        if row is None or snapshot_is_fresh(row, now) or not policy.may_read_snapshot(row):
            skipped += 1
            continue
        query = row.get("query")
        source_count = _source_count(query if isinstance(query, dict) else {})
        if source_runs + source_count > MAX_REPORT_METRIC_SOURCE_RUNS_PER_REQUEST or time.monotonic() >= deadline:
            skipped += 1
            continue
        source_runs += source_count
        try:
            metric = ReportMetric.model_validate(row)
            include_series = source_runs + source_count <= MAX_REPORT_METRIC_SOURCE_RUNS_PER_REQUEST
            if include_series:
                source_runs += source_count
            measurement = measure_metric(metric.query, team, deadline=deadline, include_series=include_series)
            metrics = _persist_metric_snapshot(
                team_id=team.id,
                report_id=str(report.id),
                expected_metrics=report.metrics,
                metric_id=metric_id,
                measurement=measurement,
            )
        except Exception:
            failed += 1
            logger.exception(
                "signals.report_metric_refresh.failed",
                team_id=team.id,
                report_id=str(report.id),
                metric_id=metric_id,
            )
            continue
        if metrics is None:
            skipped += 1
            continue
        report.metrics = metrics
        refreshed += 1

    return ReportMetricRefreshSummary(refreshed=refreshed, skipped=skipped, failed=failed)
