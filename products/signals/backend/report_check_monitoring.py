from __future__ import annotations

from datetime import datetime, timedelta

from django.db import transaction

import structlog

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.workload import Workload

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import CheckObservation
from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalReportCheck
from products.signals.backend.report_check_evaluation import errored_check_explanation, evaluate_check_value
from products.signals.backend.report_check_timing import monitoring_metric_query
from products.signals.backend.report_checks import (
    MAX_CONSECUTIVE_CHECK_ERRORS,
    MetricThresholdConfig,
    monitoring_comparison,
    monitoring_interval_minutes,
    monitoring_window_end,
    parse_check_config,
    validate_metric_check_for_write,
)
from products.signals.backend.report_content_gates import team_report_monitoring_enabled
from products.signals.backend.report_metric_refresh import MetricQueryBudgetExhausted, measure_metric

logger = structlog.get_logger(__name__)
MONITORING_ERROR_RETRY_AFTER = timedelta(hours=6)


class MonitoringWindowClosed(Exception):
    pass


def measure_monitoring_check(check: SignalReportCheck, *, now: datetime, deadline: float) -> CheckObservation:
    start = check.report.monitoring_started_at
    assert start is not None
    end = monitoring_window_end(start, check.soak_minutes)
    if now >= end:
        raise MonitoringWindowClosed
    comparison = None
    config = None
    try:
        config = parse_check_config(check.kind, check.config)
        assert isinstance(config, MetricThresholdConfig)
        validate_metric_check_for_write(config)
        assert config.query is not None
        comparison = monitoring_comparison(config, now - start)
        query = monitoring_metric_query(config.query, start=start, cutoff=now)
        measurement = measure_metric(
            query,
            check.report.team,
            deadline=deadline,
            include_series=False,
            ch_user=ClickHouseUser.SIGNALS,
            workload=Workload.OFFLINE,
        )
        verdict = evaluate_check_value(comparison=comparison, observed_value=measurement.value, subject=check.title)
        return CheckObservation(
            check_id=str(check.id),
            title=check.title,
            monitoring_started_at=start,
            measured_at=now,
            monitoring_ends_at=end,
            value_format=config.value_format if isinstance(config, MetricThresholdConfig) else None,
            unit=config.unit if isinstance(config, MetricThresholdConfig) else None,
            comparison=comparison,
            observed_value=measurement.value,
            matches=verdict.outcome == "passed",
            explanation=verdict.explanation,
        )
    except MetricQueryBudgetExhausted:
        raise
    except Exception as error:
        logger.exception(
            "signals.report_check.monitoring_measurement_failed", check_id=str(check.id), team_id=check.team_id
        )
        return CheckObservation(
            check_id=str(check.id),
            title=check.title,
            monitoring_started_at=start,
            measured_at=now,
            monitoring_ends_at=end,
            value_format=config.value_format if isinstance(config, MetricThresholdConfig) else None,
            unit=config.unit if isinstance(config, MetricThresholdConfig) else None,
            comparison=comparison,
            error=errored_check_explanation(error, subject=check.title),
            explanation=errored_check_explanation(error, subject=check.title),
        )


def record_monitoring_observation(check: SignalReportCheck, observation: CheckObservation) -> bool:
    with transaction.atomic():
        report = SignalReport.objects.select_for_update().filter(id=check.report_id, team_id=check.team_id).first()
        if (
            report is None
            or report.status != SignalReport.Status.MONITORING
            or report.monitoring_started_at != observation.monitoring_started_at
            or not team_report_monitoring_enabled(check.team_id)
        ):
            return False
        current = (
            SignalReportCheck.objects.for_team(check.team_id)
            .select_for_update()
            .filter(
                id=check.id,
                report_id=report.id,
                status=SignalReportCheck.Status.ACTIVE,
            )
            .first()
        )
        if (
            current is None
            or current.updated_at != check.updated_at
            or current.config != check.config
            or current.next_run_at != check.next_run_at
            or current.last_run_at != check.last_run_at
            or current.measurement_start_at != observation.monitoring_started_at
            or current.expires_at <= observation.measured_at
            or observation.measured_at >= monitoring_window_end(observation.monitoring_started_at, current.soak_minutes)
            or (
                observation.monitoring_ends_at is not None
                and observation.monitoring_ends_at
                != monitoring_window_end(observation.monitoring_started_at, current.soak_minutes)
            )
        ):
            return False
        current.last_run_at = observation.measured_at
        if observation.error is not None:
            current.consecutive_errors += 1
            if current.consecutive_errors >= MAX_CONSECUTIVE_CHECK_ERRORS:
                current.status = SignalReportCheck.Status.ERRORED
            current.next_run_at = observation.measured_at + MONITORING_ERROR_RETRY_AFTER
        else:
            current.consecutive_errors = 0
            current.next_run_at = observation.measured_at + timedelta(
                minutes=monitoring_interval_minutes(current.run_interval_minutes)
            )
        current.next_run_at = min(
            current.next_run_at, monitoring_window_end(observation.monitoring_started_at, current.soak_minutes)
        )
        current.save(update_fields=["last_run_at", "consecutive_errors", "next_run_at", "status", "updated_at"])
        SignalReportArtefact.add_log(
            team_id=current.team_id,
            report_id=str(current.report_id),
            content=observation,
            attribution=ArtefactAttribution.system(),
        )
        return True
