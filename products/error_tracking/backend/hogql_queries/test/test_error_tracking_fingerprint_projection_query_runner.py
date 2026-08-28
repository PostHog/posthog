import math
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status
from rest_framework.response import Response

from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value
from posthog.rate_limit import ErrorTrackingFingerprintProjectionBurstRateThrottle

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


class TestFingerprintProjectionQueryScope(APIBaseTest):
    def _query(self, *, headers: dict[str, str] | None = None) -> Response:
        return self.client.post(
            f"/api/projects/{self.team.pk}/query/",
            {"query": {"kind": "ErrorTrackingFingerprintProjectionQuery", "issueId": str(uuid4())}},
            format="json",
            headers=headers,
        )

    @parameterized.expand(
        [
            (["query:read"], status.HTTP_403_FORBIDDEN),
            (["error_tracking:read"], status.HTTP_403_FORBIDDEN),
            (["query:read", "error_tracking:read"], status.HTTP_200_OK),
        ]
    )
    def test_query_endpoint_requires_query_and_error_tracking_scopes(
        self, scopes: list[str], expected_status: int
    ) -> None:
        value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="fingerprint projection query",
            user=self.user,
            secure_value=hash_key_value(value),
            scopes=scopes,
        )

        response = self._query(headers={"authorization": f"Bearer {value}"})

        assert response.status_code == expected_status, response.data

    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    def test_query_endpoint_throttles_session_requests(self, _enabled: object) -> None:
        cache.clear()
        self.addCleanup(cache.clear)

        with patch.object(ErrorTrackingFingerprintProjectionBurstRateThrottle, "rate", "1/minute"):
            assert self._query().status_code == status.HTTP_200_OK
            assert self._query().status_code == status.HTTP_429_TOO_MANY_REQUESTS
