from __future__ import annotations

import math
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from django.db import close_old_connections, transaction
from django.db.models import F, Q
from django.utils import timezone

import structlog
from pydantic import ValidationError
from temporalio import activity

from posthog.schema import ChartDisplayType, TrendsQuery

from posthog.hogql.constants import HogQLGlobalSettings

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import tag_queries
from posthog.hogql_queries.insights.trends.trends_query_runner import TrendsQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import Team

from products.signals.backend.models import SignalReport
from products.signals.backend.report_metrics import ReportMetric
from products.signals.backend.temporal.report_metric_refresh.types import (
    REPORT_METRIC_REFRESH_QUERY_TIMEOUT_SECONDS,
    ReportMetricRefreshBatchInput,
    ReportMetricRefreshBatchResult,
    ReportMetricRefreshCursor,
    ReportMetricRefreshPage,
    ReportMetricRefreshPageInput,
    ReportMetricRefreshTarget,
)

logger = structlog.get_logger(__name__)

_CURRENT_REPORT_STATUSES = (SignalReport.Status.READY, SignalReport.Status.PENDING_INPUT)


def _bounded_positive(value: int, *, default: int, maximum: int) -> int:
    return value if 0 < value <= maximum else default


def collect_report_metric_refresh_page(inputs: ReportMetricRefreshPageInput) -> ReportMetricRefreshPage:
    """Keyset-page the oldest eligible reports without sending a fleet-sized Temporal payload."""

    page_size = _bounded_positive(inputs.page_size, default=500, maximum=1_000)
    queryset = SignalReport.objects.filter(
        status__in=_CURRENT_REPORT_STATUSES,
        metrics__contains=[{"kind": "affected_users"}],
    ).filter(
        Q(metrics_last_refresh_attempt_at__isnull=True) | Q(metrics_last_refresh_attempt_at__lt=inputs.stale_before)
    )
    if inputs.cursor is not None:
        if inputs.cursor.attempted_at is None:
            queryset = queryset.filter(
                Q(metrics_last_refresh_attempt_at__isnull=True, id__gt=inputs.cursor.report_id)
                | Q(metrics_last_refresh_attempt_at__isnull=False)
            )
        else:
            queryset = queryset.filter(metrics_last_refresh_attempt_at__isnull=False).filter(
                Q(metrics_last_refresh_attempt_at__gt=inputs.cursor.attempted_at)
                | Q(
                    metrics_last_refresh_attempt_at=inputs.cursor.attempted_at,
                    id__gt=inputs.cursor.report_id,
                )
            )

    rows = list(
        queryset.order_by(F("metrics_last_refresh_attempt_at").asc(nulls_first=True), "id").values_list(
            "metrics_last_refresh_attempt_at", "team_id", "id"
        )[: page_size + 1]
    )
    page_rows = rows[:page_size]
    targets = [
        ReportMetricRefreshTarget(team_id=team_id, report_id=str(report_id)) for _, team_id, report_id in page_rows
    ]
    next_cursor = None
    if len(rows) > page_size and page_rows:
        attempted_at, _, report_id = page_rows[-1]
        next_cursor = ReportMetricRefreshCursor(attempted_at=attempted_at, report_id=str(report_id))
    return ReportMetricRefreshPage(targets=targets, next_cursor=next_cursor)


@activity.defn
def collect_report_metric_refresh_page_activity(inputs: ReportMetricRefreshPageInput) -> ReportMetricRefreshPage:
    close_old_connections()
    try:
        return collect_report_metric_refresh_page(inputs)
    finally:
        close_old_connections()


def _affected_users_metric(metrics: object) -> ReportMetric | None:
    if not isinstance(metrics, list):
        return None
    for raw_metric in metrics:
        if not isinstance(raw_metric, dict) or raw_metric.get("kind") != "affected_users":
            continue
        try:
            return ReportMetric.model_validate(raw_metric)
        except ValidationError:
            return None
    return None


def _whole_window_affected_users(query: dict[str, Any], team: Team) -> tuple[float, datetime]:
    source = query.get("source")
    if not isinstance(source, dict):
        raise ValueError("affected-users metric query has no Trends source")

    # Time-series responses expose buckets but no whole-window aggregate. Derive a total-value
    # query for materialization without changing the authored query used by the longitudinal chart.
    aggregate_source = deepcopy(source)
    trends_filter = aggregate_source.get("trendsFilter")
    aggregate_source["trendsFilter"] = {
        **(trends_filter if isinstance(trends_filter, dict) else {}),
        "display": ChartDisplayType.BOLD_NUMBER,
    }
    runner = TrendsQueryRunner(
        query=TrendsQuery.model_validate(aggregate_source),
        team=team,
        workload=Workload.OFFLINE,
        hogql_settings=HogQLGlobalSettings(max_execution_time=REPORT_METRIC_REFRESH_QUERY_TIMEOUT_SECONDS),
    )
    tag_queries(trigger="warming/signals_report_metric")
    response = runner.run(execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE)
    results = getattr(response, "results", None)
    if not isinstance(results, list) or not results or not isinstance(results[0], dict):
        raise ValueError("affected-users metric query returned no series")
    raw_value = results[0].get("aggregated_value")
    if isinstance(raw_value, bool) or not isinstance(raw_value, int | float):
        raise ValueError("affected-users metric query returned no aggregate")
    value = float(raw_value)
    if not math.isfinite(value) or value < 0 or not value.is_integer():
        raise ValueError("affected-users metric query returned an invalid count")
    last_refresh = getattr(response, "last_refresh", None)
    measured_at = last_refresh if isinstance(last_refresh, datetime) else timezone.now()
    if measured_at.tzinfo is None or measured_at.utcoffset() is None:
        measured_at = measured_at.replace(tzinfo=UTC)
    return value, measured_at


def _persist_refresh_result_if_state_matches(
    *,
    target: ReportMetricRefreshTarget,
    expected_metrics: object,
    metric_id: str | None,
    expected_value_at: datetime | None,
    attempted_at: datetime,
    snapshot: tuple[float, datetime] | None,
) -> tuple[bool, bool]:
    """Persist an attempt and optional snapshot only while the complete metric state still matches.

    The row lock makes the complete metrics value the compare-and-swap token, including concurrent
    edits that leave the query unchanged. Attempt timestamps only move forward, and a cached result
    measured before the snapshot we read may advance the attempt clock but cannot replace its value.
    The booleans report whether the state matched and whether the snapshot itself was updated.
    """

    with transaction.atomic():
        report = (
            SignalReport.objects.select_for_update()
            .filter(team_id=target.team_id, id=target.report_id, status__in=_CURRENT_REPORT_STATUSES)
            .first()
        )
        if report is None or report.metrics != expected_metrics:
            return False, False

        update_fields: list[str] = []
        if report.metrics_last_refresh_attempt_at is None or attempted_at > report.metrics_last_refresh_attempt_at:
            report.metrics_last_refresh_attempt_at = attempted_at
            update_fields.append("metrics_last_refresh_attempt_at")

        if snapshot is not None:
            if not isinstance(report.metrics, list) or metric_id is None:
                return False, False
            metric_index = next(
                (
                    index
                    for index, metric in enumerate(report.metrics)
                    if isinstance(metric, dict) and metric.get("metric_id") == metric_id
                ),
                None,
            )
            if metric_index is None:
                return False, False
            current_metric = report.metrics[metric_index]
            if not isinstance(current_metric, dict):
                return False, False
            value, measured_at = snapshot
            if expected_value_at is not None and measured_at < expected_value_at:
                if update_fields:
                    report.save(update_fields=update_fields)
                return True, False
            refreshed_metric = {**current_metric, "value": value, "value_at": measured_at.isoformat()}
            report.metrics = [*report.metrics[:metric_index], refreshed_metric, *report.metrics[metric_index + 1 :]]
            update_fields.append("metrics")
        if update_fields:
            report.save(update_fields=update_fields)
        return True, snapshot is not None


def refresh_report_metric_snapshots_batch(inputs: ReportMetricRefreshBatchInput) -> ReportMetricRefreshBatchResult:
    attempted = 0
    updated = 0
    failed = 0
    skipped = 0

    for target in inputs.targets:
        if activity.in_activity():
            activity.heartbeat(target.report_id)
        report = (
            SignalReport.objects.select_related("team")
            .filter(team_id=target.team_id, id=target.report_id, status__in=_CURRENT_REPORT_STATUSES)
            .filter(
                Q(metrics_last_refresh_attempt_at__isnull=True)
                | Q(metrics_last_refresh_attempt_at__lt=inputs.stale_before)
            )
            .first()
        )
        if report is None:
            skipped += 1
            continue
        metric = _affected_users_metric(report.metrics)
        if metric is None:
            # This can only happen after legacy/manual corruption. Advance the attempt marker when
            # the report's complete metric state is still current so it cannot starve every bounded
            # sweep without delaying a concurrently corrected definition.
            attempted += 1
            attempted_at = timezone.now()
            persisted, _ = _persist_refresh_result_if_state_matches(
                target=target,
                expected_metrics=report.metrics,
                metric_id=None,
                expected_value_at=None,
                attempted_at=attempted_at,
                snapshot=None,
            )
            if not persisted:
                skipped += 1
            failed += 1
            continue

        attempted += 1
        attempted_at = timezone.now()
        snapshot: tuple[float, datetime] | None = None
        try:
            snapshot = _whole_window_affected_users(metric.query, report.team)
        except Exception:
            failed += 1
            logger.exception(
                "signals.report_metric_refresh.query_failed",
                team_id=target.team_id,
                report_id=target.report_id,
                metric_id=metric.metric_id,
            )

        persisted, snapshot_updated = _persist_refresh_result_if_state_matches(
            target=target,
            expected_metrics=report.metrics,
            metric_id=metric.metric_id,
            expected_value_at=metric.value_at,
            attempted_at=attempted_at,
            snapshot=snapshot,
        )
        if not persisted:
            skipped += 1
        elif snapshot_updated:
            updated += 1
        elif snapshot is not None:
            skipped += 1

    return ReportMetricRefreshBatchResult(
        attempted=attempted,
        updated=updated,
        failed=failed,
        skipped=skipped,
    )


@activity.defn
def refresh_report_metric_snapshots_batch_activity(
    inputs: ReportMetricRefreshBatchInput,
) -> ReportMetricRefreshBatchResult:
    close_old_connections()
    try:
        return refresh_report_metric_snapshots_batch(inputs)
    finally:
        close_old_connections()
