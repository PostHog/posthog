from __future__ import annotations

import json
import hashlib
from dataclasses import replace
from datetime import datetime
from uuid import UUID

import structlog

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.workload import Workload

from products.signals.backend.report_check_evaluation import evaluate_check_value
from products.signals.backend.report_check_evidence import (
    EvidenceScope,
    EvidenceSource,
    MetricEvidence,
    qualify_metric_evidence,
)
from products.signals.backend.report_check_final_candidates import FinalCheck
from products.signals.backend.report_check_timing import monitoring_metric_query
from products.signals.backend.report_checks import (
    MetricThresholdConfig,
    monitoring_comparison,
    parse_check_config,
    validate_metric_check_for_write,
)
from products.signals.backend.report_metric_refresh import MetricQueryBudgetExhausted, measure_metric
from products.signals.backend.report_monitoring_results import MonitoringEvaluation

logger = structlog.get_logger(__name__)


def metric_evidence_source(config: MetricThresholdConfig) -> EvidenceSource:
    assert config.query is not None
    source = config.query["source"]
    series = source["series"]
    if len(series) != 1 or source.get("samplingFactor") not in (None, 1):
        return "unsupported"
    if any((source.get("trendsFilter") or {}).get(key) for key in ("formula", "formulas", "formulaNodes")):
        return "unsupported"
    entity = series[0]
    if entity.get("math_property") == "$session_duration" or entity.get("math_property_type") == "session_properties":
        return "unsupported"
    if entity.get("math") in (None, "total"):
        return "count"
    if (
        entity.get("math_property_type") not in (None, "event_properties")
        or not isinstance(entity.get("math_property"), str)
        or not entity["math_property"].strip()
    ):
        return "unsupported"
    if entity.get("math") == "sum":
        return "sum"
    if entity.get("math") == "avg":
        return "average"
    return "unsupported"


def evaluate_final_metric(
    member: FinalCheck, *, submission_id: UUID, evaluated_at: datetime, deadline: float
) -> MonitoringEvaluation:
    check = member.check
    evaluation = MonitoringEvaluation(
        team_id=check.team_id,
        report_id=check.report_id,
        attempt_id=member.attempt_id,
        check_id=check.id,
        submission_id=submission_id,
        definition_version=member.definition_version,
        window_start=member.window_start,
        window_end=member.window_end,
        evaluated_at=evaluated_at,
        evidence_status="unsupported",
        evidence_reason="invalid_configuration",
        expectation_matches=None,
        explanation="The check's metric configuration cannot be evaluated. Review its query and target.",
    )
    try:
        config = parse_check_config(check.kind, check.config)
        assert isinstance(config, MetricThresholdConfig)
        validate_metric_check_for_write(config)
    except ValueError:
        return evaluation
    if config.monitoring is None:
        return replace(
            evaluation,
            evidence_status="unsupported",
            evidence_reason="missing_monitoring_definition",
            expectation_matches=None,
            explanation="The check needs a Monitoring measurement definition before its target can be evaluated.",
        )
    source = metric_evidence_source(config)
    if source == "unsupported" or source == "average":
        return replace(
            evaluation,
            evidence_status="unsupported" if source == "unsupported" else "insufficient",
            evidence_reason="unsupported_source" if source == "unsupported" else "minimum_denominator_unspecified",
            expectation_matches=None,
            explanation=(
                "This metric needs an evidence adapter before its target can be evaluated."
                if source == "unsupported"
                else "This average needs a source-specific minimum denominator before it can establish success or failure."
            ),
        )
    scope = EvidenceScope(
        team_id=check.team_id,
        population=f"check:{check.id}:{member.definition_version}",
        start=member.window_start,
        end=member.window_end,
    )
    if member.window_start == member.window_end:
        return replace(
            evaluation,
            evidence_status="insufficient",
            evidence_reason="empty_window",
            expectation_matches=None,
            explanation="The observation window is empty and cannot establish success or failure.",
        )
    assert config.query is not None
    query = monitoring_metric_query(config.query, start=member.window_start, cutoff=member.window_end)
    query_hash = hashlib.sha256(json.dumps(query, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    references = (f"signal-report-check:{check.id}:{member.definition_version}", f"trends-query:sha256:{query_hash}")
    try:
        measurement = measure_metric(
            query,
            check.report.team,
            deadline=deadline,
            include_series=False,
            require_full_timeout=True,
            ch_user=ClickHouseUser.SIGNALS,
            workload=Workload.OFFLINE,
        )
        if measurement.measured_at < member.window_end:
            return replace(
                evaluation,
                evidence_status="insufficient",
                evidence_reason="measurement_unavailable",
                expectation_matches=None,
                explanation="The query result predates the end of the observation window. A fresh result is needed.",
                evidence_refs=references,
            )
        qualification = qualify_metric_evidence(MetricEvidence(scope=scope, source=source, value=measurement.value))
        comparison = monitoring_comparison(config, member.window_end - member.window_start)
        verdict = evaluate_check_value(comparison=comparison, observed_value=measurement.value, subject=check.title)
    except MetricQueryBudgetExhausted:
        raise
    except Exception:
        logger.exception("signals.monitoring.final_metric_query_failed", team_id=check.team_id, check_id=str(check.id))
        return replace(
            evaluation,
            evidence_status="errored",
            evidence_reason="query_error",
            expectation_matches=None,
            explanation="The final metric query could not be completed. Review the check's query.",
            evidence_refs=references,
        )
    explanation = f"{verdict.explanation}. Query measured at {measurement.measured_at.isoformat()}."
    if qualification.status == "insufficient":
        explanation = f"The final value was {measurement.value}, measured at {measurement.measured_at.isoformat()}. Relevant activity for this metric's population has not been established; the value cannot establish success or failure."
    elif qualification.status == "unsupported":
        explanation = f"The final value was {measurement.value}, measured at {measurement.measured_at.isoformat()}. This value cannot establish success or failure under the metric's evidence policy."
    return replace(
        evaluation,
        evidence_status=qualification.status,
        evidence_reason=qualification.reason,
        expectation_matches=verdict.outcome == "passed"
        if qualification.status in {"sufficient", "insufficient"}
        else None,
        explanation=explanation,
        evidence_refs=references,
    )
