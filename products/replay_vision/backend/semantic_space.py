"""Shared vector maths for search themes and feed groups.

Both compare a scanner's issue observations on a short prefix of their embedding, with the scanner's running mean
taken out, because every observation of one scanner shares the wording of its question and would otherwise look
alike. A young scanner's mean is mostly its own few rows, so until the mean has enough members both compare plain
vectors at a plain similarity.
"""

import uuid
from datetime import UTC, datetime

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
    sums: np.ndarray,
    counts: np.ndarray,
    space: SemanticSpace,
    centred_threshold: float,
    raw_threshold: float,
    squared_norms: np.ndarray | None = None,
) -> int | None:
    """The index of the cluster whose mean is closest to the vector, or None when none is close enough."""
    if not len(counts):
        return None
    if squared_norms is None:
        squared_norms = np.einsum("ij,ij->i", sums, sums)
    direction = unit(space.vector - space.mean)
    # Each centred mean's projection and length come from the sums and their cached squared norms, so a scanner with
    # thousands of clusters costs two matrix-vector products rather than a new matrix of centroids.
    projections = (sums @ direction) / counts
    lengths_squared = squared_norms / counts**2
    if space.centring:
        projections -= float(space.mean @ direction)
        lengths_squared += float(space.mean @ space.mean) - 2 * (sums @ space.mean) / counts
    lengths = np.sqrt(np.maximum(lengths_squared, 0))
    similarities = np.divide(projections, lengths, out=np.zeros_like(projections), where=lengths > 1e-6)
    best = int(np.argmax(similarities))
    threshold = centred_threshold if space.centring else raw_threshold
    return best if similarities[best] >= threshold else None


class ClusterArrays:
    """Clusters as arrays with spare capacity, with each sum's squared norm kept current for `nearest_cluster`."""

    def __init__(self, ids: list[uuid.UUID], sums: list[np.ndarray], counts: list[int], last: list[datetime]) -> None:
        self.size = len(ids)
        capacity = max(16, self.size * 2)
        self.ids = list(ids)
        self._sums = np.zeros((capacity, SEMANTIC_DIMENSIONS), dtype=np.float32)
        self._counts = np.zeros(capacity, dtype=np.float32)
        self._last = np.zeros(capacity, dtype=np.float64)
        self._squares = np.zeros(capacity, dtype=np.float32)
        if self.size:
            self._sums[: self.size] = sums
            self._counts[: self.size] = counts
            self._last[: self.size] = [at.timestamp() for at in last]
            self._squares[: self.size] = np.einsum("ij,ij->i", self.sums, self.sums)

    def __len__(self) -> int:
        return self.size

    @property
    def capacity(self) -> int:
        return len(self._counts)

    @property
    def sums(self) -> np.ndarray:
        return self._sums[: self.size]

    @property
    def counts(self) -> np.ndarray:
        return self._counts[: self.size]

    @property
    def last(self) -> np.ndarray:
        return self._last[: self.size]

    def nearest(
        self, space: SemanticSpace, active_since: datetime, centred_threshold: float, raw_threshold: float
    ) -> int | None:
        """The closest cluster that took a member since `active_since`, or None when none is close enough."""
        active = np.nonzero(self.last >= active_since.timestamp())[0]
        if len(active) == self.size:
            return nearest_cluster(
                self.sums, self.counts, space, centred_threshold, raw_threshold, self._squares[: self.size]
            )
        best = nearest_cluster(
            self.sums[active], self.counts[active], space, centred_threshold, raw_threshold, self._squares[active]
        )
        return None if best is None else int(active[best])

    def add(self, cluster_id: uuid.UUID, vector: np.ndarray, at: datetime) -> int:
        if self.size == self.capacity:
            self._sums = np.concatenate([self._sums, np.zeros_like(self._sums)])
            self._counts = np.concatenate([self._counts, np.zeros_like(self._counts)])
            self._last = np.concatenate([self._last, np.zeros_like(self._last)])
            self._squares = np.concatenate([self._squares, np.zeros_like(self._squares)])
        index = self.size
        self.ids.append(cluster_id)
        self._sums[index] = vector
        self._counts[index] = 1.0
        self._last[index] = at.timestamp()
        self._squares[index] = float(vector @ vector)
        self.size += 1
        return index

    def join(self, index: int, vector: np.ndarray, at: datetime) -> None:
        self._sums[index] += vector
        self._squares[index] = float(self._sums[index] @ self._sums[index])
        self._counts[index] += 1
        # The backfill replays old rows while the consumer adds new ones, so the latest member time never moves back.
        self._last[index] = max(self._last[index], at.timestamp())

    def last_member_at(self, index: int) -> datetime:
        return datetime.fromtimestamp(self._last[index], tz=UTC)

    def keep(self, indices: np.ndarray) -> None:
        """Keep only the clusters at these indices, in this order."""
        if len(indices) == self.size:
            return
        self.ids = [self.ids[i] for i in indices]
        for array in (self._sums, self._counts, self._last, self._squares):
            array[: len(indices)] = array[: self.size][indices]
        self.size = len(indices)
