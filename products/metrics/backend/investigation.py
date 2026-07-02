"""Orchestrates a metric-symptom investigation into one structured result.

Composes the existing primitives — characterize the primary metric, check each
companion metric over the same window, classify blast radius from the movers —
into a single `InvestigationResult`. That result is the seam between investigate
and display: the agent narrates it, the in-app explorer renders it, and the
incident report serializes it, all from the same shape.

The metric->trace pivot (`evidence.trace_exemplars`) is left empty until the
`metric_samples` table lands; the seam is defined here so wiring it in later
doesn't change the result shape.
"""

from __future__ import annotations

import datetime as dt

from posthog.models import Team

from products.metrics.backend.anomaly import characterize_anomaly, dimension_magnitude
from products.metrics.backend.facade.contracts import (
    CompanionMetric,
    CompanionVerdict,
    InvestigationChartSpec,
    InvestigationEvidence,
    InvestigationResult,
    MetricAnomalyReport,
    MetricFilter,
)

# A companion counts as "moved with the symptom" once it changes by more than
# this fraction over the window (matches the eye test of "basically flat"
# throughput vs a real shift).
COMPANION_MOVE_THRESHOLD = 0.25

# One mover dominates (-> localized cause) when its change is at least this
# multiple of the next mover's.
DOMINANT_MOVER_RATIO = 2.0

# histogram_quantile defaults to p95 when the caller names no quantile (matching
# characterize_anomaly); every other aggregation carries none.
_DEFAULT_HISTOGRAM_QUANTILE = 0.95

# Label keys that name the emitting service, used to implicate one for the
# logs/traces pivot.
_SERVICE_KEYS = ("service_name", "service.name")


def investigate(
    *,
    team: Team,
    metric_name: str,
    anomaly_from: dt.datetime,
    anomaly_to: dt.datetime,
    baseline_from: dt.datetime | None = None,
    baseline_to: dt.datetime | None = None,
    aggregation: str | None = None,
    quantile: float | None = None,
    filters: tuple[MetricFilter, ...] = (),
    candidate_keys: tuple[str, ...] | None = None,
    companions: tuple[CompanionMetric, ...] = (),
) -> InvestigationResult:
    """Investigate a metric symptom and return a structured result.

    Characterizes `metric_name` over the anomaly window (vs the preceding window
    by default), characterizes each companion over the SAME window to confirm or
    rule it out, classifies blast radius from the movers, and builds re-runnable
    chart specs. Raises `ValueError` for invalid windows (surfaced as 400 by
    callers).
    """
    symptom = characterize_anomaly(
        team=team,
        metric_name=metric_name,
        anomaly_from=anomaly_from,
        anomaly_to=anomaly_to,
        baseline_from=baseline_from,
        baseline_to=baseline_to,
        aggregation=aggregation,
        quantile=quantile,
        filters=filters,
        candidate_keys=candidate_keys,
    )

    companion_verdicts = tuple(
        _assess_companion(
            team=team,
            companion=companion,
            anomaly_from=anomaly_from,
            anomaly_to=anomaly_to,
            baseline_from=baseline_from,
            baseline_to=baseline_to,
            filters=filters,
        )
        for companion in companions
    )

    blast_radius = _classify_blast_radius(symptom)
    service_name = _implicated_service(symptom)
    evidence = InvestigationEvidence(
        service_name=service_name,
        trace_exemplars=(),  # filled by the trace-pivot primitive once samples land
        log_filter=_log_filter(service_name, symptom) if service_name else None,
    )
    chart_specs = _build_chart_specs(symptom, companion_verdicts, filters, quantile)
    confidence = _confidence(symptom, companion_verdicts, blast_radius)
    narrative = _narrate(symptom, companion_verdicts, blast_radius)

    return InvestigationResult(
        metric_name=metric_name,
        symptom=symptom,
        blast_radius=blast_radius,
        companions=companion_verdicts,
        chart_specs=chart_specs,
        evidence=evidence,
        confidence=confidence,
        narrative=narrative,
    )


def _assess_companion(
    *,
    team: Team,
    companion: CompanionMetric,
    anomaly_from: dt.datetime,
    anomaly_to: dt.datetime,
    baseline_from: dt.datetime | None,
    baseline_to: dt.datetime | None,
    filters: tuple[MetricFilter, ...],
) -> CompanionVerdict:
    report = characterize_anomaly(
        team=team,
        metric_name=companion.metric_name,
        anomaly_from=anomaly_from,
        anomaly_to=anomaly_to,
        baseline_from=baseline_from,
        baseline_to=baseline_to,
        aggregation=companion.aggregation,
        quantile=companion.quantile,
        filters=filters,
    )
    moved = report.direction != "flat" and abs(report.change_ratio - 1.0) >= COMPANION_MOVE_THRESHOLD
    return CompanionVerdict(
        metric_name=companion.metric_name,
        role=companion.role,
        aggregation=report.aggregation,
        direction=report.direction,
        change_ratio=report.change_ratio,
        moved_with_symptom=moved,
        quantile=companion.quantile,
    )


def _classify_blast_radius(symptom: MetricAnomalyReport) -> str:
    """One mover that dwarfs the rest is a localized culprit; several moving
    together is a shared cause; no movers leaves it unknown. Movers arrive
    ranked by magnitude (relative change blended with scale), so the dominance
    test must use that same measure — comparing raw change_ratio here can rank
    a high-magnitude mover below a tiny but explosive one and flip the verdict."""
    movers = symptom.top_movers
    if not movers:
        return "unknown"
    if len(movers) == 1:
        return "localized"
    top, second = dimension_magnitude(movers[0]), dimension_magnitude(movers[1])
    if second == 0.0 or top >= second * DOMINANT_MOVER_RATIO:
        return "localized"
    return "shared"


def _implicated_service(symptom: MetricAnomalyReport) -> str | None:
    for mover in symptom.top_movers:
        if mover.key in _SERVICE_KEYS:
            return mover.label
    return None


def _log_filter(service_name: str, symptom: MetricAnomalyReport) -> dict[str, str]:
    """A ready-to-run query-logs filter bracketing onset (or the window start)
    through the anomaly end, errors first."""
    return {
        "service_name": service_name,
        "severity": "error",
        "date_from": symptom.onset_time or symptom.anomaly_from,
        "date_to": symptom.anomaly_to,
    }


def _chart_quantile(aggregation: str, quantile: float | None) -> float | None:
    """The quantile a chart re-run needs to reproduce the aggregation: only
    histogram_quantile uses one, defaulting to p95 when unspecified."""
    if aggregation == "histogram_quantile":
        return quantile if quantile is not None else _DEFAULT_HISTOGRAM_QUANTILE
    return None


def _build_chart_specs(
    symptom: MetricAnomalyReport,
    companions: tuple[CompanionVerdict, ...],
    filters: tuple[MetricFilter, ...],
    symptom_quantile: float | None,
) -> tuple[InvestigationChartSpec, ...]:
    """The hero chart (the symptom) plus one per companion, all on the symptom's
    window so the grids line up when rendered side by side. Each spec carries the
    quantile its aggregation needs so a re-run reproduces the same line."""
    specs = [
        InvestigationChartSpec(
            title=f"{symptom.metric_name} ({symptom.aggregation})",
            metric_name=symptom.metric_name,
            aggregation=symptom.aggregation,
            anomaly_from=symptom.anomaly_from,
            anomaly_to=symptom.anomaly_to,
            filters=filters,
            quantile=_chart_quantile(symptom.aggregation, symptom_quantile),
        )
    ]
    specs.extend(
        InvestigationChartSpec(
            title=f"{companion.role}: {companion.metric_name} ({companion.aggregation})",
            metric_name=companion.metric_name,
            aggregation=companion.aggregation,
            anomaly_from=symptom.anomaly_from,
            anomaly_to=symptom.anomaly_to,
            filters=filters,
            quantile=_chart_quantile(companion.aggregation, companion.quantile),
        )
        for companion in companions
    )
    return tuple(specs)


def _confidence(
    symptom: MetricAnomalyReport,
    companions: tuple[CompanionVerdict, ...],
    blast_radius: str,
) -> str:
    if symptom.direction == "flat":
        return "low"
    explained = any(companion.moved_with_symptom for companion in companions)
    if blast_radius == "localized" or explained:
        return "high"
    return "medium"


def _narrate(
    symptom: MetricAnomalyReport,
    companions: tuple[CompanionVerdict, ...],
    blast_radius: str,
) -> str:
    parts: list[str] = []
    if symptom.direction == "flat":
        parts.append(f"{symptom.metric_name} held flat over the window — no clear anomaly.")
    else:
        onset = f" starting around {symptom.onset_time}" if symptom.onset_time else ""
        parts.append(
            f"{symptom.metric_name} {_direction_phrase(symptom)}{onset} "
            f"(peak {symptom.anomaly_peak:g} vs baseline {symptom.baseline_mean:g})."
        )
    if blast_radius == "localized" and symptom.top_movers:
        mover = symptom.top_movers[0]
        parts.append(f"Localized to {mover.key}={mover.label}.")
    elif blast_radius == "shared":
        parts.append("Several labels moved together — a shared cause.")
    for companion in companions:
        if companion.moved_with_symptom:
            moved = "moved with it"
        elif companion.direction == "flat":
            moved = "stayed flat"
        else:
            moved = "did not move significantly"
        parts.append(f"{companion.role.capitalize()} ({companion.metric_name}) {moved}.")
    return " ".join(parts)


def _direction_phrase(symptom: MetricAnomalyReport) -> str:
    if symptom.direction == "down":
        return f"fell to {symptom.change_ratio:.2f}x baseline"
    return f"rose {symptom.change_ratio:.1f}x"
