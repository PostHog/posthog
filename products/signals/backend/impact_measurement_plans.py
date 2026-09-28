"""Versioned impact proposals. Execution and check results live outside this definition."""

from __future__ import annotations

from collections.abc import Mapping

import structlog

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import ImpactMeasurementPlan
from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.report_metrics import MAX_REPORT_METRICS, REPORT_METRIC_GOAL_FIELDS

logger = structlog.get_logger(__name__)


def latest_measurement_plans(report: SignalReport) -> dict[str, tuple[SignalReportArtefact, ImpactMeasurementPlan]]:
    plans: dict[str, tuple[SignalReportArtefact, ImpactMeasurementPlan]] = {}
    rows = SignalReportArtefact.objects.filter(
        team_id=report.team_id,
        report_id=report.id,
        type=SignalReportArtefact.ArtefactType.IMPACT_MEASUREMENT_PLAN,
    ).order_by("-created_at", "-id")
    for row in rows:
        try:
            plan = ImpactMeasurementPlan.model_validate_json(row.content)
        except ValueError:
            continue
        plans.setdefault(plan.metric_id, (row, plan))
    return plans


def can_append_measurement_plan(
    existing: Mapping[str, tuple[SignalReportArtefact, ImpactMeasurementPlan]], plan: ImpactMeasurementPlan
) -> bool:
    if plan.retired:
        return True
    current = existing.get(plan.metric_id)
    if current is not None and not current[1].retired:
        return True
    return sum(not current_plan.retired for _, current_plan in existing.values()) < MAX_REPORT_METRICS


def persist_authored_measurement_plans(
    report: SignalReport,
    metrics: list[dict],
    attribution: ArtefactAttribution,
) -> list[dict]:
    """Move authored goals into immutable plans without replacing earlier proposals or approvals."""
    existing = latest_measurement_plans(report)
    clean_metrics = []
    for metric in metrics:
        clean_metrics.append({key: value for key, value in metric.items() if key not in REPORT_METRIC_GOAL_FIELDS})
        if metric.get("goal_value") is None or metric.get("goal_direction") is None:
            continue
        metric_id = metric.get("metric_id")
        if metric_id in existing:
            continue
        try:
            plan = ImpactMeasurementPlan.model_validate(
                {
                    **{
                        key: metric[key]
                        for key in (
                            "metric_id",
                            "title",
                            "kind",
                            "query",
                            "value_format",
                            "unit",
                            "goal_value",
                            "goal_direction",
                            "goal_grain",
                            "decision_window_days",
                            "minimum_data_points",
                            "eligibility_query",
                        )
                        if key in metric and (key not in {"goal_grain", "eligibility_query"} or metric[key] is not None)
                    },
                    "activated": False,
                }
            )
        except ValueError:
            logger.warning(
                "ignoring invalid proposed impact measurement", report_id=str(report.id), metric_id=metric_id
            )
            continue
        if not can_append_measurement_plan(existing, plan):
            logger.warning("impact measurement limit reached", report_id=str(report.id), metric_id=metric_id)
            continue
        row = SignalReportArtefact.add_log(
            team_id=report.team_id, report_id=str(report.id), content=plan, attribution=attribution
        )
        existing[plan.metric_id] = (row, plan)
    return clean_metrics
