"""Shared vector maths for search themes and feed groups.

Both compare a scanner's issue observations on a short prefix of their embedding, with the scanner's running mean
taken out, because every observation of one scanner shares the wording of its question and would otherwise look
alike. A young scanner's mean is mostly its own few rows, so until the mean has enough members both compare plain
vectors at a plain similarity.
"""

import numpy as np

from posthog.dataclasses import frozen

# text-embedding-3 vectors keep their meaning when cut short and renormalised, and a short one keeps the clusters
# cheap to hold and compare.
SEMANTIC_DIMENSIONS = 512
CENTRE_MIN_MEMBERS = 50


@frozen
class SemanticSpace:
    """One observation's vector and the scanner mean it is compared against."""

    vector: np.ndarray
    mean: np.ndarray
    centring: bool


def semantic_vector(vector: list[float] | np.ndarray) -> np.ndarray:
    head = np.zeros(SEMANTIC_DIMENSIONS, dtype=np.float32)
    values = np.asarray(vector[:SEMANTIC_DIMENSIONS], dtype=np.float32)
    head[: len(values)] = values
    return unit(head)


def unit(vector: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(vector, axis=-1, keepdims=True)
    return np.divide(vector, norm, out=np.zeros_like(vector), where=norm > 0)


def pack(vector: np.ndarray) -> bytes:
    return vector.astype(np.float32).tobytes()


def unpack(data: bytes | memoryview) -> np.ndarray:
    return np.frombuffer(bytes(data), dtype=np.float32)


def scanner_space(center_sum: np.ndarray, center_count: int, vector: np.ndarray) -> SemanticSpace:
    """The space for one new vector, given the scanner's sum and count before it joins."""
    mean = (center_sum + vector) / (center_count + 1)
    # A vector that matches the scanner mean has no direction once centred, so it compares plain like a young scanner.
    centring = center_count >= CENTRE_MIN_MEMBERS and bool(np.linalg.norm(vector - mean) > 1e-6)
    return SemanticSpace(vector=vector, mean=mean if centring else np.zeros_like(vector), centring=centring)


def nearest_cluster(
    sums: np.ndarray, counts: np.ndarray, space: SemanticSpace, centred_threshold: float, raw_threshold: float
) -> int | None:
    """The index of the cluster whose mean is closest to the vector, or None when none is close enough."""
    if not len(counts):
        return None
    centroids = unit(sums / counts[:, None] - space.mean)
    similarities = centroids @ unit(space.vector - space.mean)
    best = int(np.argmax(similarities))
    threshold = centred_threshold if space.centring else raw_threshold
    return best if similarities[best] >= threshold else None
