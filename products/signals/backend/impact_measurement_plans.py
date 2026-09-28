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
    *,
    revise_metric_ids: list[str] | None = None,
    retire_metric_ids: list[str] | None = None,
    previous_plan_ids: Mapping[str, str] | None = None,
) -> list[dict]:
    """Move authored goals into immutable plans, appending explicit revisions and retirements."""
    existing = latest_measurement_plans(report)
    revise_ids = set(revise_metric_ids or [])
    retire_ids = set(retire_metric_ids or [])
    ambiguous_ids = revise_ids & retire_ids
    if ambiguous_ids:
        logger.warning("ignoring conflicting impact measurement decisions", report_id=str(report.id))
    clean_metrics = []
    for metric in metrics:
        clean_metrics.append({key: value for key, value in metric.items() if key not in REPORT_METRIC_GOAL_FIELDS})
        if metric.get("goal_value") is None or metric.get("goal_direction") is None:
            continue
        metric_id = metric.get("metric_id")
        if metric_id in ambiguous_ids:
            continue
        current = existing.get(metric_id)
        if current is not None:
            if metric_id not in revise_ids:
                continue
            if previous_plan_ids is None or previous_plan_ids.get(metric_id) != str(current[0].id):
                logger.info("skipping stale impact measurement revision", report_id=str(report.id), metric_id=metric_id)
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
        if current is not None and current[1].model_dump(exclude={"activated"}) == plan.model_dump(
            exclude={"activated"}
        ):
            continue
        if not can_append_measurement_plan(existing, plan):
            logger.warning("impact measurement limit reached", report_id=str(report.id), metric_id=metric_id)
            continue
        row = SignalReportArtefact.add_log(
            team_id=report.team_id, report_id=str(report.id), content=plan, attribution=attribution
        )
        existing[plan.metric_id] = (row, plan)
    for metric_id in retire_ids - ambiguous_ids:
        current = existing.get(metric_id)
        if current is None or current[1].retired:
            continue
        if previous_plan_ids is None or previous_plan_ids.get(metric_id) != str(current[0].id):
            logger.info("skipping stale impact measurement retirement", report_id=str(report.id), metric_id=metric_id)
            continue
        retired = current[1].model_copy(update={"activated": False, "retired": True})
        SignalReportArtefact.add_log(
            team_id=report.team_id, report_id=str(report.id), content=retired, attribution=attribution
        )
    return clean_metrics
