import os

# The production module forces the TBB Numba layer on Linux x86_64 for thread safety across
# Temporal activities. A single-process test does not need it, and TBB is often missing locally.
os.environ.setdefault("NUMBA_THREADING_LAYER", "workqueue")

import pytest  # noqa: E402

import numpy as np  # noqa: E402

from products.mcp_analytics.backend.intent_topics.clustering import assign_by_nearest_centroid, fit_topics  # noqa: E402


def _umap_threading_available() -> bool:
    """UMAP needs a Numba threading layer (TBB); mirror the trace_clustering test guard."""
    try:
        import umap

        umap.UMAP(n_components=2, n_neighbors=2, random_state=0).fit(np.random.default_rng(0).normal(size=(5, 4)))
        return True
    except Exception:
        return False


skip_without_umap = pytest.mark.skipif(
    not _umap_threading_available(), reason="UMAP threading backend (TBB) not available"
)


def _two_blobs(seed: int = 7, n_per_blob: int = 150, dim: int = 256) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    centers = rng.normal(size=(2, dim))
    centers /= np.linalg.norm(centers, axis=1, keepdims=True)
    points = np.concatenate([center + rng.normal(scale=0.02, size=(n_per_blob, dim)) for center in centers])
    truth = np.repeat([0, 1], n_per_blob)
    return points.astype(np.float32), truth


@skip_without_umap
class TestFitTopics:
    def test_two_tight_groups_become_two_topics(self) -> None:
        vectors, truth = _two_blobs()

        fit = fit_topics(vectors, weights=None, random_state=1)

        topics = sorted(set(fit.labels.tolist()) - {-1})
        assert len(topics) == 2
        # members of one blob share a label
        for blob in (0, 1):
            labels_in_blob = fit.labels[truth == blob]
            labels_in_blob = labels_in_blob[labels_in_blob >= 0]
            assert len(set(labels_in_blob.tolist())) == 1
        assert fit.centroids.shape == (2, 256)
        np.testing.assert_allclose(np.linalg.norm(fit.centroids, axis=1), 1.0, atol=1e-5)
        assert fit.outlier_distances.shape == (2,)
        assert np.all((fit.outlier_distances >= 0) & (fit.outlier_distances <= 1))
        assert fit.coords_2d.shape == (300, 2)
        assert fit.pca_mean.shape == (256,)
        assert fit.pca_components.shape == (2, 256)

    def test_weights_move_the_centroid_towards_heavy_points(self) -> None:
        vectors, _ = _two_blobs()
        weights = np.ones(len(vectors))
        weights[0] = 1000.0

        heavy = fit_topics(vectors, weights=weights, random_state=1)
        plain = fit_topics(vectors, weights=None, random_state=1)

        label = heavy.labels[0]
        assert label >= 0
        heavy_centroid = heavy.centroids[label]
        plain_centroid = plain.centroids[plain.labels[0]]
        point = vectors[0] / np.linalg.norm(vectors[0])
        assert float(point @ heavy_centroid) > float(point @ plain_centroid)


class TestAssignByNearestCentroid:
    def test_assigns_nearest_and_flags_outliers(self) -> None:
        centroids = np.stack([[1.0, 0.0], [0.0, 1.0]]).astype(np.float32)
        outlier_distances = np.array([0.05, 0.05], dtype=np.float32)
        vectors = np.array([[0.99, 0.1], [0.1, 0.99], [0.7, 0.7]], dtype=np.float32)

        nearest = assign_by_nearest_centroid(vectors, centroids, outlier_distances)
        topic_index, distance, is_outlier = nearest.topic_index, nearest.distance, nearest.is_outlier

        assert topic_index.tolist() == [0, 1, 0]
        assert is_outlier.tolist() == [False, False, True]
        assert distance[2] > distance[0]
