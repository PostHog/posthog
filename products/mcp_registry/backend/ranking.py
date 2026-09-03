"""Versioned static ranking over the registry index.

Every version is a pure function from a server's signals to a score with an
explainable component breakdown. Versions are never edited in place: iterate by
adding a new key, running it, and comparing its ordering against the incumbent via
the API before promoting DEFAULT_RANKING_VERSION. Query-time relevance (does this
server match the search?) is layered on top by the API; these scores are the
query-independent "is this server any good?" half.
"""

import math
from collections.abc import Callable

from django.utils import timezone

import structlog

from posthog.dataclasses import frozen

from products.mcp_registry.backend.models import MCPMeasuredStats, MCPRankingRun, MCPRankingScore, MCPRegistryServer

logger = structlog.get_logger(__name__)

# How much each probed liveness state is worth. Dead servers stay in the index (the
# listing is still real) but rank under everything alive.
LIVENESS_WEIGHTS: dict[str, float] = {
    "alive_open": 1.0,
    "alive_auth": 0.95,
    "alive_protocol": 0.8,
    "package_only": 0.55,
    "unprobed": 0.4,
    "not_mcp": 0.25,
    "dead": 0.1,
}

# Calls at which measured volume confidence saturates (log scale).
_VOLUME_SATURATION_CALLS = 100_000


@frozen
class ScoreResult:
    score: float
    components: dict[str, float | str | bool]


def _metadata_prior(server: MCPRegistryServer) -> float:
    """Weak trust prior from public metadata alone, which any registry could compute."""
    prior = 0.45
    if server.repository_url:
        prior += 0.1
    if server.tools.exists():
        prior += 0.1
    return min(prior, 1.0)


def _measured_trust(stats: list[MCPMeasuredStats]) -> tuple[float, dict[str, float]]:
    """Behavioral trust from MCP Analytics: reliability weighted by volume confidence.

    Multiple stats rows (same server measured in several projects) combine by call
    volume, so a high-traffic deployment dominates a toy one.
    """
    total_calls = sum(row.calls for row in stats)
    if total_calls <= 0:
        return 0.0, {}
    reliability = sum((1 - row.error_rate_pct / 100) * row.calls for row in stats) / total_calls
    intent_coverage = sum(row.intent_coverage_pct * row.calls for row in stats) / total_calls / 100
    volume_confidence = min(math.log10(total_calls + 1) / math.log10(_VOLUME_SATURATION_CALLS), 1.0)
    trust = 0.65 + 0.35 * (reliability * volume_confidence)
    return min(trust, 1.0), {
        "measured_reliability": round(reliability, 4),
        "measured_volume_confidence": round(volume_confidence, 4),
        "measured_intent_coverage": round(intent_coverage, 4),
    }


def _score_v1_metadata_prior(server: MCPRegistryServer, stats: list[MCPMeasuredStats]) -> ScoreResult:
    """Baseline: liveness x public-metadata trust. Ignores measured signal on purpose because
    this is the control arm any registry could replicate."""
    liveness = LIVENESS_WEIGHTS.get(server.liveness, 0.4)
    trust = _metadata_prior(server)
    score = (liveness**0.5) * (trust**0.5)
    return ScoreResult(
        score=round(score, 6),
        components={"liveness": liveness, "trust": round(trust, 4), "measured": False},
    )


def _score_v2_measured_trust(server: MCPRegistryServer, stats: list[MCPMeasuredStats]) -> ScoreResult:
    """v1 plus behavioral trust for measured servers, the arm that uses our signal."""
    liveness = LIVENESS_WEIGHTS.get(server.liveness, 0.4)
    components: dict[str, float | str | bool] = {"liveness": liveness, "measured": False}
    trust = _metadata_prior(server)
    if stats:
        measured_trust, measured_components = _measured_trust(stats)
        if measured_trust > 0:
            trust = measured_trust
            components["measured"] = True
            components.update(measured_components)
    components["trust"] = round(trust, 4)
    score = (liveness**0.5) * (trust**0.5)
    return ScoreResult(score=round(score, 6), components=components)


RANKING_VERSIONS: dict[str, Callable[[MCPRegistryServer, list[MCPMeasuredStats]], ScoreResult]] = {
    "v1_metadata_prior": _score_v1_metadata_prior,
    "v2_measured_trust": _score_v2_measured_trust,
}

DEFAULT_RANKING_VERSION = "v2_measured_trust"

_BULK_BATCH_SIZE = 1_000


def compute_ranking_run(version: str) -> MCPRankingRun:
    """Score every server under one version, persisting a new run + its scores."""
    scorer = RANKING_VERSIONS.get(version)
    if scorer is None:
        raise ValueError(f"unknown ranking version: {version}")

    run = MCPRankingRun.objects.create(version=version)
    try:
        batch: list[MCPRankingScore] = []
        count = 0
        for server in MCPRegistryServer.objects.prefetch_related("measured_stats", "tools").iterator(chunk_size=500):
            result = scorer(server, list(server.measured_stats.all()))
            batch.append(MCPRankingScore(run=run, server=server, score=result.score, components=result.components))
            count += 1
            if len(batch) >= _BULK_BATCH_SIZE:
                MCPRankingScore.objects.bulk_create(batch)
                batch = []
        if batch:
            MCPRankingScore.objects.bulk_create(batch)
        run.status = "completed"
        run.server_count = count
        run.computed_at = timezone.now()
        run.save(update_fields=["status", "server_count", "computed_at"])
        logger.info("mcp_registry.ranking.completed", version=version, servers=count, run_id=str(run.id))
    except Exception as exc:
        run.status = "failed"
        run.error = str(exc)[:2000]
        run.save(update_fields=["status", "error"])
        raise
    return run


def latest_completed_run(version: str) -> MCPRankingRun | None:
    return MCPRankingRun.objects.filter(version=version, status="completed").order_by("-created_at").first()
