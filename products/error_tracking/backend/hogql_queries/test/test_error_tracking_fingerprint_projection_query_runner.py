import math

from django.test import SimpleTestCase

from parameterized import parameterized

from products.error_tracking.backend.hogql_queries.error_tracking_fingerprint_projection_query_runner import (
    FingerprintEmbedding,
    project_fingerprint_embeddings,
)


class TestFingerprintEmbeddingProjection(SimpleTestCase):
    @parameterized.expand(
        [
            ("single", [[1.0, 0.0, 0.0]]),
            ("pair", [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]),
            ("small_cluster", [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]),
            ("identical", [[1.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 0.0, 0.0]]),
        ]
    )
    def test_projects_small_fingerprint_sets_without_dropping_points(
        self, _name: str, embeddings: list[list[float]]
    ) -> None:
        fingerprint_embeddings = [
            FingerprintEmbedding(fingerprint=f"fingerprint-{index}", embedding=embedding)
            for index, embedding in enumerate(embeddings)
        ]

        points = project_fingerprint_embeddings(fingerprint_embeddings)

        assert [point.fingerprint for point in points] == [item.fingerprint for item in fingerprint_embeddings]
        assert all(math.isfinite(point.x) and math.isfinite(point.y) for point in points)
