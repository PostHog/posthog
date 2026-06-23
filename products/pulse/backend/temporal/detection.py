"""Change detection for Pulse candidate metrics (the `change_v1` strategy)."""

import math
import asyncio
import statistics
from typing import Any

import structlog

from posthog.schema import PulseScanConfig

from posthog.models import Team
from posthog.sync import database_sync_to_async

from products.pulse.backend.temporal.detectors.base import DetectionResult, PulseDetector
from products.pulse.backend.temporal.detectors.registry import get_detector, register_detector
from products.pulse.backend.temporal.metrics import increment_detection_outcome
from products.pulse.backend.temporal.types import CandidateMetric, Finding, MetricDescriptor, run_trends_query_sync

logger = structlog.get_logger(__name__)


DETECTION_CONCURRENCY = 8
MIN_BASELINE_WEEKS = 3  # hard floor: fewer completed weeks than this and a baseline median is too noisy to trust
MAX_BASELINE_WEEKS = 4  # default baseline window, also narrative.py's attribution window when none is configured


def _build_detection_query(base_query: dict, baseline_weeks: int) -> dict:
    query = {**base_query}
    # Fetch the configured baseline window plus the current and the in-progress (dropped) week.
    fetch_days = (baseline_weeks + 2) * 7
    query["dateRange"] = {"date_from": f"-{fetch_days}d", "date_to": None}
    query["interval"] = "week"
    # Strip breakdowns for the initial detection scan — we want the headline metric.
    if "breakdownFilter" in query:
        query["breakdownFilter"] = None
    return query


def _extract_weekly_series(result: Any) -> list[float]:
    if not isinstance(result, dict):
        return []
    results = result.get("results") or []
    if not results:
        return []
    first_series = results[0]
    if not isinstance(first_series, dict):
        return []
    data = first_series.get("data") or []
    return [float(v) for v in data if isinstance(v, int | float) and not isinstance(v, bool)]


def _compute_robust_z(current: float, baseline: list[float]) -> float:
    """Modified z-score: 0.6745 * |x - median| / MAD. Floors to 0.0 when MAD == 0.

    Secondary/informational only — never a sole trigger (the primary gate is change_pct).
    Mirrors posthog/tasks/alerts/detectors/statistical/mad.py's modified-z formula.
    """
    if len(baseline) < 2:
        return 0.0
    median = statistics.median(baseline)
    mad = statistics.median([abs(v - median) for v in baseline])
    if mad == 0:
        return 0.0
    return 0.6745 * abs(current - median) / mad


def _compute_impact(change_pct: float, baseline_median: float) -> float:
    """Rank weight: relative change scaled by sqrt(volume) so high-traffic moves rank higher."""
    return abs(change_pct) * math.sqrt(baseline_median)


@register_detector("change_v1")
class ChangeV1Detector(PulseDetector):
    """v1 deterministic change detection: median baseline + change_pct primary gate."""

    def detect(
        self,
        current: float,
        baseline: list[float],
        min_change_pct: float,
        robust_z_threshold: float,
        min_baseline_value: float,
    ) -> DetectionResult:
        baseline_median = statistics.median(baseline)
        robust_z = _compute_robust_z(current, baseline)
        # Guard the division: a zero baseline_median has no defined percentage change, and the volume floor
        # (min_baseline_value) suppresses low-volume metrics for the deterministic gate. Either short-circuits.
        if baseline_median == 0 or baseline_median < min_baseline_value:
            return DetectionResult(
                triggered=False,
                baseline_median=baseline_median,
                change_pct=0.0,
                impact=0.0,
                robust_z=robust_z,
            )
        change_pct = (current - baseline_median) / baseline_median
        impact = _compute_impact(change_pct, baseline_median)
        # Primary gate: change_pct only. robust_z is intentionally NOT a gate — it is undefined for a
        # flat baseline (MAD=0 → robust_z=0), where a change is actually the clearest possible signal, so
        # gating on it would suppress exactly those. robust_z stays a surfaced secondary signal and
        # ranking aid (robust_z_threshold is the reserved sensitivity knob), never a sole or co-trigger.
        triggered = abs(change_pct) >= min_change_pct
        return DetectionResult(
            triggered=triggered,
            baseline_median=baseline_median,
            change_pct=change_pct,
            impact=impact,
            robust_z=robust_z,
        )


def score_series(
    weekly_values: list[float], config: PulseScanConfig, detection_mode: str = "change_v1"
) -> tuple[DetectionResult, float, list[float]] | None:
    """Compute the change-detection result for a weekly series WITHOUT applying the trigger gate.

    Returns (result, current_value, sparkline_series) or None when there's too little data. Callers
    that want the detection gate check `result.triggered`; callers that already know the metric is
    anomalous (the scout source) ignore it and use the numbers for display.
    """
    assert config.baseline_weeks is not None
    assert config.min_change_pct is not None
    assert config.robust_z_threshold is not None
    assert config.min_baseline_value is not None
    if len(weekly_values) < MIN_BASELINE_WEEKS + 2:
        return None
    completed = weekly_values[:-1]  # drop the in-progress (partial) week
    current = completed[-1]
    baseline = completed[:-1][-config.baseline_weeks :]
    if len(baseline) < MIN_BASELINE_WEEKS:
        return None
    result = get_detector(detection_mode).detect(
        current, baseline, config.min_change_pct, config.robust_z_threshold, config.min_baseline_value
    )
    # The recent completed weeks (baseline window + current) drive the card's trend sparkline; kept
    # unrounded so the last point equals current_value exactly (matters for avg/median/p90 metrics).
    series = [float(v) for v in completed[-(config.baseline_weeks + 1) :]]
    return result, current, series


def _build_finding(
    descriptor: MetricDescriptor, result: DetectionResult, current: float, series: list[float]
) -> Finding:
    return Finding(
        descriptor=descriptor,
        current_value=current,
        baseline_value=result.baseline_median,
        change_pct=result.change_pct,
        impact=result.impact,
        robust_z=result.robust_z,
        series=series,
    )


def _evaluate_candidate(
    candidate: CandidateMetric,
    weekly_values: list[float],
    config: PulseScanConfig,
    detection_mode: str = "change_v1",
) -> Finding | None:
    scored = score_series(weekly_values, config, detection_mode)
    if scored is None:
        return None
    result, current, series = scored
    if not result.triggered:
        return None
    return _build_finding(candidate.descriptor, result, current, series)


async def _evaluate_one(
    team: Team,
    candidate: CandidateMetric,
    config: PulseScanConfig,
    semaphore: asyncio.Semaphore,
) -> Finding | None:
    # Validate the resolved config BEFORE the try: an AssertionError inside it would be swallowed as a
    # per-candidate "failed" tick, disguising a config bug as N transient query failures.
    assert config.baseline_weeks is not None  # Optional in the generated schema; always set on a resolved config
    assert config.min_change_pct is not None
    assert config.robust_z_threshold is not None
    assert config.min_baseline_value is not None
    async with semaphore:
        try:
            query = _build_detection_query(candidate.descriptor.query, config.baseline_weeks)
            result = await run_trends_query_sync(team, query)
            series = _extract_weekly_series(result)
            return _evaluate_candidate(candidate, series, config)
        except Exception as exc:
            logger.exception(
                "pulse_detection_candidate_failed",
                team_id=team.id,
                metric=candidate.descriptor.label,
                error=str(exc),
            )
            increment_detection_outcome("failed")
            return None


async def detect_changes(team_id: int, candidates: list[CandidateMetric], config: PulseScanConfig) -> list[Finding]:
    """The deterministic AnomalySource's scoring pass: score every selected candidate, keep the triggered
    ones. Wrapped by sources.DeterministicSource and run alongside the scout each scan. Its scoring helpers
    (score_series, _build_detection_query, _extract_weekly_series, _build_finding) are also reused by the
    scout adapter."""

    @database_sync_to_async
    def _get_team() -> Team:
        return Team.objects.get(id=team_id)

    team = await _get_team()
    semaphore = asyncio.Semaphore(DETECTION_CONCURRENCY)
    results = await asyncio.gather(*[_evaluate_one(team, c, config, semaphore) for c in candidates])
    return [f for f in results if f is not None]
