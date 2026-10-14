"""Prepare bounded report chart snapshots outside the reader's request."""

from __future__ import annotations

import json
import time
from copy import deepcopy
from datetime import datetime, timedelta

from django.core.cache import cache
from django.utils import timezone

import structlog
from celery import shared_task
from pydantic import BaseModel, ValidationError

from posthog.hogql.constants import HogQLGlobalSettings

from posthog.models import Team
from posthog.models.scoping import with_team_scope

from products.signals.backend.models import SignalReport
from products.signals.backend.report_charts import ReportChart

logger = structlog.get_logger(__name__)
SNAPSHOT_FRESH_FOR = timedelta(minutes=15)
MAX_SNAPSHOT_CHARS = 256_000
REFRESH_TIME_BUDGET_SECONDS = 45


def chart_snapshot_is_fresh(chart: dict, now: datetime) -> bool:
    measured_at = chart.get("cached_results_at")
    if not isinstance(chart.get("cached_results"), dict) or not isinstance(measured_at, str):
        return False
    try:
        timestamp = datetime.fromisoformat(measured_at.replace("Z", "+00:00"))
        return timestamp.tzinfo is not None and timedelta(0) <= now - timestamp < SNAPSHOT_FRESH_FOR
    except ValueError:
        return False


def _run_chart_query(chart: ReportChart, team: Team) -> BaseModel | None:
    # These runners import the complete query registry; keep it off Django's startup path.
    from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner  # noqa: PLC0415
    from posthog.hogql_queries.query_runner import ExecutionMode  # noqa: PLC0415

    from products.product_analytics.backend.facade.queries import TrendsQueryRunner  # noqa: PLC0415

    source = chart.query.get("source")
    if not isinstance(source, dict):
        return None
    settings = HogQLGlobalSettings(max_execution_time=10)
    response: BaseModel
    if chart.query["kind"] == "InsightVizNode" and source.get("kind") == "TrendsQuery":
        runner = TrendsQueryRunner(query=source, team=team, hogql_settings=settings)
        response = runner.run(execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE)
    elif chart.query["kind"] == "DataVisualizationNode" and source.get("kind") == "HogQLQuery":
        # Direct connections have their own timeout and permission context; keep their live path.
        if source.get("connectionId"):
            return None
        sql_runner = HogQLQueryRunner(query=source, team=team, settings=settings)
        response = sql_runner.run(execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE)
    else:
        return None
    return response if isinstance(getattr(response, "results", None), list) else None


@shared_task(ignore_result=True, soft_time_limit=55, time_limit=60)
@with_team_scope()
def refresh_report_chart_snapshots(team_id: int, report_id: str) -> None:
    report = SignalReport.objects.filter(team_id=team_id, id=report_id).first()
    if report is None or not isinstance(report.charts, list):
        return
    original = report.charts
    charts = deepcopy(original)
    team = Team.objects.get(id=team_id)
    deadline = time.monotonic() + REFRESH_TIME_BUDGET_SECONDS
    for chart in charts:
        if time.monotonic() >= deadline:
            break
        if not isinstance(chart, dict) or chart_snapshot_is_fresh(chart, timezone.now()):
            continue
        try:
            validated = ReportChart.model_validate(chart)
            response = _run_chart_query(validated, team)
            if response is None:
                continue
            snapshot = response.model_dump(mode="json")
            if len(json.dumps(snapshot, allow_nan=False)) > MAX_SNAPSHOT_CHARS:
                continue
            chart["cached_results"] = snapshot
            chart["cached_results_at"] = timezone.now().isoformat()
        except ValidationError:
            continue
        except Exception:
            logger.exception("report_chart_snapshot_failed", team_id=team_id, report_id=report_id)
    if charts != original:
        # Never restore a chart that was replaced or removed while its query was running.
        SignalReport.objects.filter(team_id=team_id, id=report_id, charts=original).update(charts=charts)


def schedule_report_chart_refresh(team_id: int, report_id: str) -> None:
    key = f"signals:chart-refresh:{team_id}:{report_id}"
    try:
        if cache.add(key, True, timeout=60):
            refresh_report_chart_snapshots.delay(team_id, report_id)
    except Exception:
        logger.exception("report_chart_refresh_enqueue_failed", team_id=team_id, report_id=report_id)
