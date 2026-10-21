"""Stable topic identity across runs.

A re-fit produces fresh clusters with fresh centroids. Matching each cluster to the closest existing
topic by cosine similarity keeps the topic id, so trends and drift can span months.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

DEFAULT_MATCH_THRESHOLD = 0.85


@dataclass(frozen=True)
class ExistingTopic:
    id: str
    centroid: np.ndarray


@dataclass(frozen=True)
class MatchResult:
    reused: dict[int, str] = field(default_factory=dict)  # cluster index -> topic id
    created: list[int] = field(default_factory=list)  # cluster indexes that become new topics
    unmatched_topics: list[str] = field(default_factory=list)  # existing topics no cluster claimed


def _unit_rows(matrix: np.ndarray) -> np.ndarray:
    matrix = np.asarray(matrix, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


def match_clusters_to_topics(
    cluster_centroids: np.ndarray,
    cluster_sizes: Sequence[int],
    existing: Sequence[ExistingTopic],
    threshold: float = DEFAULT_MATCH_THRESHOLD,
) -> MatchResult:
    """Greedy one-to-one matching by descending cosine similarity.

    Ties break on the larger cluster, then the lower cluster index, then the topic id, so the
    outcome is deterministic for identical inputs.
    """
    n_clusters = len(cluster_centroids)
    if n_clusters == 0:
        return MatchResult(unmatched_topics=[topic.id for topic in existing])
    if not existing:
        return MatchResult(created=list(range(n_clusters)))

    clusters = _unit_rows(cluster_centroids)
    topics = _unit_rows(np.stack([topic.centroid for topic in existing]))
    similarity = clusters @ topics.T

    candidates = [
        (float(similarity[cluster_idx, topic_idx]), cluster_idx, topic_idx)
        for cluster_idx in range(n_clusters)
        for topic_idx in range(len(existing))
        if similarity[cluster_idx, topic_idx] >= threshold
    ]
    candidates.sort(
        key=lambda item: (-item[0], -int(cluster_sizes[item[1]]), item[1], existing[item[2]].id),
    )

    reused: dict[int, str] = {}
    claimed_topics: set[int] = set()
    for _, cluster_idx, topic_idx in candidates:
        if cluster_idx in reused or topic_idx in claimed_topics:
            continue
        reused[cluster_idx] = existing[topic_idx].id
        claimed_topics.add(topic_idx)

    created = [idx for idx in range(n_clusters) if idx not in reused]
    unmatched = [topic.id for idx, topic in enumerate(existing) if idx not in claimed_topics]
    return MatchResult(reused=reused, created=created, unmatched_topics=unmatched)
