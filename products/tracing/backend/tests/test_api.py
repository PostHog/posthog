from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from posthog.schema import TraceSpansQueryResponse


class TestTracingSpansAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.url_prefix = f"/api/environments/{self.team.pk}/tracing/spans"

    def test_sparkline_accepts_heatmap_breakdown(self):
        fake_response = TraceSpansQueryResponse(
            results=[
                {
                    "time": "2025-01-01T00:00:00+00:00",
                    "duration_log2_bucket": 10,
                    "service": "api",
                    "count": 3,
                }
            ]
        )

        with patch("products.tracing.backend.presentation.views.TraceSpansSparklineQueryRunner") as runner_cls:
            runner_cls.return_value.run.return_value = fake_response
            response = self.client.post(
                f"{self.url_prefix}/sparkline/",
                {
                    "query": {
                        "dateRange": {"date_from": "-1h", "date_to": None},
                        "sparklineBreakdownBy": "service_and_latency_log2",
                        "heatmapIncludeQuantiles": True,
                        "rootSpans": True,
                    }
                },
                format="json",
            )

        assert response.status_code == status.HTTP_200_OK, response.json()
        body = response.json()
        assert body["results"][0]["duration_log2_bucket"] == 10

    def test_sparkline_returns_400_on_exposed_hogql_error(self):
        from posthog.hogql.errors import ExposedHogQLError

        with patch("products.tracing.backend.presentation.views.TraceSpansSparklineQueryRunner") as runner_cls:
            runner_cls.return_value.run.side_effect = ExposedHogQLError("read limit")
            response = self.client.post(
                f"{self.url_prefix}/sparkline/",
                {"query": {"dateRange": {"date_from": "-1h", "date_to": None}}},
                format="json",
            )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["code"] == "tracing_sparkline_query_too_large"

    def test_bubble_up_requires_region_timestamps(self):
        response = self.client.post(
            f"{self.url_prefix}/bubble-up/",
            {
                "query": {
                    "dateRange": {"date_from": "-1h", "date_to": None},
                    "region": {
                        "duration_min_nano": 1,
                        "duration_max_nano": 1000,
                    },
                }
            },
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
