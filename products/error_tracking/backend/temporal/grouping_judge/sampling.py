import hashlib

from posthog.dataclasses import frozen

from products.error_tracking.backend.temporal.grouping_judge.types import JudgeBand

# Fixed so bands and buckets stay comparable across changes to the live auto-merge threshold. They label
# rows for analysis and do not change the sample rate.
LOW_BAND_EDGE = 0.019
HIGH_BAND_EDGE = 0.08
DISTANCE_BUCKET_EDGES: tuple[float, ...] = (0, 0.005, 0.01, 0.019, 0.03, 0.05, 0.08)
REJUDGE_RATE = 0.1


@frozen
class JudgeSample:
    sampled: bool
    swapped: bool
    rejudge: bool


def band_for(distance: float) -> JudgeBand:
    if distance < LOW_BAND_EDGE:
        return "low"
    if distance < HIGH_BAND_EDGE:
        return "mid"
    return "high"


def distance_bucket_for(distance: float) -> str:
    edges = DISTANCE_BUCKET_EDGES
    for lower, upper in zip(edges, edges[1:]):
        if distance < upper:
            return f"{lower}-{upper}"
    return f"{edges[-1]}+"


def _unit_hash(purpose: str, team_id: int, fingerprint: str) -> float:
    """A stable value in [0, 1), so an activity retry makes the same choice for the same pair."""
    digest = hashlib.sha256(f"{purpose}:{team_id}:{fingerprint}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def sample_pair(team_id: int, fingerprint: str, sample_rate: float) -> JudgeSample:
    # Separate hashes per choice, so the swap and the re-judge are independent of being sampled.
    return JudgeSample(
        sampled=_unit_hash("sample", team_id, fingerprint) < sample_rate,
        swapped=_unit_hash("swap", team_id, fingerprint) < 0.5,
        rejudge=_unit_hash("rejudge", team_id, fingerprint) < REJUDGE_RATE,
    )
