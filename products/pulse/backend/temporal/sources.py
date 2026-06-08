"""Anomaly sources for Pulse: where the findings to enrich come from.

Each source implements the AnomalySource protocol (get_findings -> list[Finding]). A scan runs every
source via gather_findings and merges the results, so sources compose without anything downstream of
Finding caring where a finding came from. Two ship today:
  - DeterministicSource: selects popular candidates and scores them with the change detector.
  - ScoutAnomalySource: consumes the Signals anomaly-detection scout (no-ops where it isn't enrolled).
"""

import asyncio
from typing import TYPE_CHECKING, Protocol

import structlog

from posthog.schema import PulseScanConfig

from posthog.models import Team
from posthog.sync import database_sync_to_async

from products.pulse.backend.temporal.detection import (
    DETECTION_CONCURRENCY,
    _build_detection_query,
    _build_finding,
    _extract_weekly_series,
    detect_changes,
    score_series,
)
from products.pulse.backend.temporal.metrics import increment_anomaly_source_failure, increment_scout_anomaly_outcome
from products.pulse.backend.temporal.selection import insight_to_descriptor, select_candidates
from products.pulse.backend.temporal.types import Finding, run_trends_query_sync

if TYPE_CHECKING:
    from products.signals.backend.facade.api import AnomalyFinding

logger = structlog.get_logger(__name__)

# Bound the re-scoring fan-out so a runaway scout emission can't blow the activity timeout. The scout
# only watches viewed insights, so real counts are a handful; if it ever floods, keep the highest-weight
# anomalies (the survivors are re-ranked by impact downstream) and log the truncation.
MAX_ANOMALIES_PER_SCAN = 50


class AnomalySource(Protocol):
    async def get_findings(
        self, team_id: int, period_start: str, period_end: str, config: PulseScanConfig
    ) -> list[Finding]: ...


class DeterministicSource:
    """Selects popular candidates (insights, dashboards, top events) and scores them with the change
    detector — the always-on baseline source, available for every team."""

    async def get_findings(
        self, team_id: int, period_start: str, period_end: str, config: PulseScanConfig
    ) -> list[Finding]:
        candidates = await select_candidates(team_id, config)
        return await detect_changes(team_id, candidates, config)


async def _adapt_anomaly_to_finding(team: Team, anomaly: "AnomalyFinding", config: PulseScanConfig) -> Finding | None:
    """Best-effort: load the scout-flagged insight by short_id and re-score it for display numbers.

    Does NOT re-gate — the scout already decided this is anomalous, so we always build a Finding when the
    insight + series resolve. That includes neutralizing the volume floor (min_baseline_value): it's a
    detection gate that would zero out change_pct/impact for low-volume metrics, dropping anomalies the
    scout deliberately surfaced. impact already damps low volume via sqrt(baseline), so ranking still works.
    Increments a counter so the unresolvable rate is measurable.

    Re-scoring math (score_series, _build_detection_query, ...) is reused from detection.py."""
    from products.product_analytics.backend.models.insight import Insight  # noqa: PLC0415 — app-init cycle

    if not anomaly.insight_short_id:
        increment_scout_anomaly_outcome("unresolvable_insight")
        return None

    @database_sync_to_async
    def _load() -> "Insight | None":
        return Insight.objects.filter(team=team, short_id=anomaly.insight_short_id, deleted=False).first()

    insight = await _load()
    if insight is None:
        increment_scout_anomaly_outcome("unresolvable_insight")
        logger.warning("pulse_scout_anomaly_unresolvable", team_id=team.id, short_id=anomaly.insight_short_id)
        return None

    descriptor = insight_to_descriptor(insight, "scout_anomaly")
    if descriptor is None:  # insight resolved but isn't a TrendsQuery — can't re-score
        increment_scout_anomaly_outcome("unsupported_query_kind")
        logger.warning("pulse_scout_anomaly_unsupported_query", team_id=team.id, short_id=anomaly.insight_short_id)
        return None

    assert config.baseline_weeks is not None
    try:
        # Re-score over the recent baseline window (now), not the scout's original anomaly window — these
        # are display numbers; the scout already made the trigger decision.
        result = await run_trends_query_sync(team, _build_detection_query(descriptor.query, config.baseline_weeks))
    except Exception as exc:
        increment_scout_anomaly_outcome("query_failed")
        logger.warning(
            "pulse_scout_anomaly_query_failed",
            team_id=team.id,
            short_id=anomaly.insight_short_id,
            error=str(exc),
        )
        return None

    series = _extract_weekly_series(result)
    # min_baseline_value=0: the scout owns the surface decision, so don't let the volume floor suppress it.
    scored = score_series(series, config.model_copy(update={"min_baseline_value": 0.0}))
    if scored is None:
        increment_scout_anomaly_outcome("no_series")
        logger.warning("pulse_scout_anomaly_no_series", team_id=team.id, short_id=anomaly.insight_short_id)
        return None

    detection_result, current, sparkline = scored
    if detection_result.baseline_median == 0:  # 0→N rise has no defined % change; skip cleanly, don't show +0%
        increment_scout_anomaly_outcome("zero_baseline")
        logger.warning("pulse_scout_anomaly_zero_baseline", team_id=team.id, short_id=anomaly.insight_short_id)
        return None
    increment_scout_anomaly_outcome("resolved")
    return _build_finding(descriptor, detection_result, current, sparkline)


async def _adapt_guarded(
    team: Team, anomaly: "AnomalyFinding", config: PulseScanConfig, semaphore: asyncio.Semaphore
) -> Finding | None:
    """Re-score one anomaly under the concurrency limit, isolating failures so one can't abort the scan."""
    async with semaphore:
        try:
            return await _adapt_anomaly_to_finding(team, anomaly, config)
        except Exception:
            increment_scout_anomaly_outcome("adapter_error")
            logger.exception("pulse_scout_anomaly_adapter_error", team_id=team.id, short_id=anomaly.insight_short_id)
            return None


class ScoutAnomalySource:
    """v1 AnomalySource: consume the Signals anomaly-detection scout's findings."""

    async def get_findings(
        self, team_id: int, period_start: str, period_end: str, config: PulseScanConfig
    ) -> list[Finding]:
        # Lazy import: the pulse package is eagerly preloaded via posthog.api; importing the signals
        # facade at module level risks an app-init cycle (matches the pattern in delivery.py).
        from products.signals.backend.facade.api import get_team_anomalies  # noqa: PLC0415 — app-init cycle

        team = await database_sync_to_async(lambda: Team.objects.get(id=team_id))()
        anomalies = await get_team_anomalies(team, period_start, period_end)  # async — await directly
        if len(anomalies) > MAX_ANOMALIES_PER_SCAN:
            logger.warning(
                "pulse_scout_anomalies_truncated",
                team_id=team_id,
                count=len(anomalies),
                cap=MAX_ANOMALIES_PER_SCAN,
            )
            anomalies = sorted(anomalies, key=lambda a: a.weight, reverse=True)[:MAX_ANOMALIES_PER_SCAN]

        # Re-score concurrently under a bounded semaphore (mirrors the prior detect_changes path) so a
        # batch of cache-cold insights doesn't serialize into the activity timeout. gather preserves order.
        semaphore = asyncio.Semaphore(DETECTION_CONCURRENCY)
        results = await asyncio.gather(*(_adapt_guarded(team, a, config, semaphore) for a in anomalies))
        return [f for f in results if f is not None]


# The sources a scan runs. The scout no-ops where it isn't enrolled, so non-scout teams transparently
# get just the deterministic findings — "additional source", not a replacement.
ALL_SOURCES: list[AnomalySource] = [DeterministicSource(), ScoutAnomalySource()]


async def _safe_get_findings(
    source: AnomalySource, team_id: int, period_start: str, period_end: str, config: PulseScanConfig
) -> list[Finding]:
    """Isolate a source: one failing source degrades to the others' findings rather than failing the scan."""
    try:
        return await source.get_findings(team_id, period_start, period_end, config)
    except Exception:
        increment_anomaly_source_failure(type(source).__name__)
        logger.exception("pulse_anomaly_source_failed", source=type(source).__name__, team_id=team_id)
        return []


def _dedup_findings(findings: list[Finding]) -> list[Finding]:
    """One finding per insight (keyed by descriptor.url = /insights/<short_id>); a scout finding wins over
    a deterministic one for the same insight (richer hypothesis/severity). Findings with no url (e.g.
    top-event metrics) are all kept."""
    chosen: dict[str, Finding] = {}
    unkeyed: list[Finding] = []
    for f in findings:
        key = f.descriptor.url
        if not key:
            unkeyed.append(f)
            continue
        current = chosen.get(key)
        if current is None:
            chosen[key] = f
        elif current.descriptor.source != "scout_anomaly" and f.descriptor.source == "scout_anomaly":
            chosen[key] = f  # upgrade a deterministic finding to the scout's for the same insight
    return list(chosen.values()) + unkeyed


async def gather_findings(
    team_id: int,
    period_start: str,
    period_end: str,
    config: PulseScanConfig,
    sources: list[AnomalySource] | None = None,
) -> list[Finding]:
    """Run every anomaly source concurrently and merge their findings, deduped by insight."""
    sources = ALL_SOURCES if sources is None else sources
    per_source = await asyncio.gather(
        *(_safe_get_findings(s, team_id, period_start, period_end, config) for s in sources)
    )
    return _dedup_findings([f for findings in per_source for f in findings])
