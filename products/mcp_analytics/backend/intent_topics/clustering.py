"""Weekly topic fit (UMAP + HDBSCAN on a sample) and the numpy twin of the SQL assignment step."""

from dataclasses import dataclass

import numpy as np

from posthog.temporal.ai_observability.trace_clustering.clustering import (
    perform_hdbscan_clustering,
    reduce_dimensions_for_clustering,
)

OUTLIER_DISTANCE_PERCENTILE = 95
MIN_POINTS_FOR_UMAP = 50


@dataclass(frozen=True)
class FitOutput:
    labels: np.ndarray  # (n,) cluster index per point, -1 for noise
    centroids: np.ndarray  # (k, d) unit vectors in the original embedding space
    outlier_distances: np.ndarray  # (k,) p95 cosine distance of members to their centroid
    pca_mean: np.ndarray  # (d,)
    pca_components: np.ndarray  # (2, d)
    coords_2d: np.ndarray  # (n, 2)


def _unit_rows(matrix: np.ndarray) -> np.ndarray:
    matrix = np.asarray(matrix, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


@dataclass(frozen=True)
class PcaFit:
    mean: np.ndarray  # (d,)
    components: np.ndarray  # (2, d)


@dataclass(frozen=True)
class NearestCentroid:
    topic_index: np.ndarray  # (n,)
    distance: np.ndarray  # (n,) cosine distance to the chosen centroid
    is_outlier: np.ndarray  # (n,) bool


def fit_pca_2d(vectors: np.ndarray, weights: np.ndarray | None = None) -> PcaFit:
    """A weighted 2D PCA basis for the map."""
    if weights is None:
        weights = np.ones(len(vectors), dtype=np.float32)
    weights = np.asarray(weights, dtype=np.float32)
    mean = (vectors * weights[:, None]).sum(axis=0) / weights.sum()
    centered = (vectors - mean) * np.sqrt(weights)[:, None]
    _, _, vt = np.linalg.svd(centered, full_matrices=False)
    return PcaFit(mean=mean.astype(np.float32), components=vt[:2].astype(np.float32))


def project_2d(vectors: np.ndarray, pca_mean: np.ndarray, pca_components: np.ndarray) -> np.ndarray:
    return ((np.asarray(vectors, dtype=np.float32) - pca_mean) @ pca_components.T).astype(np.float32)


def fit_topics(vectors: np.ndarray, weights: np.ndarray | None, *, random_state: int = 42) -> FitOutput:
    """Cluster unit-normalised vectors into topics.

    Weights (call counts) shape the centroids and the PCA basis, not HDBSCAN itself: HDBSCAN finds
    the dense regions of distinct intent texts; a heavily repeated text then pulls its topic's
    centroid towards it.
    """
    unit = _unit_rows(vectors)
    n = len(unit)
    if weights is None:
        weights = np.ones(n, dtype=np.float32)
    weights = np.asarray(weights, dtype=np.float32)

    if n >= MIN_POINTS_FOR_UMAP:
        reduced, _ = reduce_dimensions_for_clustering(unit, random_state=random_state)
    else:
        reduced = unit
    labels = np.asarray(perform_hdbscan_clustering(reduced).labels)

    cluster_ids = sorted(set(labels.tolist()) - {-1})
    centroids = []
    outlier_distances = []
    for cluster_id in cluster_ids:
        members = labels == cluster_id
        weighted = (unit[members] * weights[members][:, None]).sum(axis=0)
        centroid = weighted / (np.linalg.norm(weighted) or 1.0)
        centroids.append(centroid)
        distances = 1.0 - unit[members] @ centroid
        outlier_distances.append(float(np.percentile(distances, OUTLIER_DISTANCE_PERCENTILE)))
    # Relabel to a dense 0..k-1 range in case HDBSCAN skipped an index.
    relabel = {cluster_id: idx for idx, cluster_id in enumerate(cluster_ids)}
    dense_labels = np.array([relabel.get(int(label), -1) for label in labels], dtype=np.int64)

    pca = fit_pca_2d(unit, weights)
    pca_mean, pca_components = pca.mean, pca.components
    return FitOutput(
        labels=dense_labels,
        centroids=np.stack(centroids).astype(np.float32) if centroids else np.zeros((0, unit.shape[1]), np.float32),
        outlier_distances=np.asarray(outlier_distances, dtype=np.float32),
        pca_mean=pca_mean,
        pca_components=pca_components,
        coords_2d=project_2d(unit, pca_mean, pca_components),
    )


def assign_by_nearest_centroid(
    vectors: np.ndarray, centroids: np.ndarray, outlier_distances: np.ndarray
) -> NearestCentroid:
    """Numpy twin of the ClickHouse assignment SQL, used to pin its semantics in tests."""
    unit = _unit_rows(vectors)
    unit_centroids = _unit_rows(centroids)
    distances = 1.0 - unit @ unit_centroids.T
    topic_index = distances.argmin(axis=1)
    distance = distances[np.arange(len(unit)), topic_index]
    is_outlier = distance > np.asarray(outlier_distances, dtype=np.float32)[topic_index]
    return NearestCentroid(topic_index=topic_index, distance=distance.astype(np.float32), is_outlier=is_outlier)
