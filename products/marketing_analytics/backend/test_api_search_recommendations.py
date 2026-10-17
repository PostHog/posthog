from posthog.test.base import APIBaseTest
from unittest.mock import patch

from posthog.schema import MarketingAnalyticsSearchQueryResponse


class TestSearchRecommendationsEndpoint(APIBaseTest):
    def test_flag_validation_and_server_side_metrics(self) -> None:
        url = f"/api/projects/{self.team.pk}/marketing_analytics/search_recommendations/"
        payload = {
            "query": {
                "kind": "MarketingAnalyticsSearchQuery",
                "sources": [],
                "compareFilter": {"compare": True},
                "response": {"results": []},
                "includePostHogConversions": True,
            },
        }
        with patch("products.marketing_analytics.backend.api.feature_enabled_or_false", return_value=False):
            self.assertEqual(self.client.post(url, payload, format="json").status_code, 404)
        with patch("products.marketing_analytics.backend.api.feature_enabled_or_false", return_value=True):
            self.assertEqual(self.client.post(url, {"query": {}}, format="json").status_code, 400)
            with patch("products.marketing_analytics.backend.api.MarketingAnalyticsSearchQueryRunner") as runner:
                runner.return_value.calculate.return_value = MarketingAnalyticsSearchQueryResponse(results=[])
                runner.return_value.get_api_queries_concurrency_limit.return_value = 5
                response = self.client.post(url, payload, format="json")
                self.assertEqual(response.status_code, 200, response.content)
                self.assertEqual(response.json()["result"]["recommendations"], [])
                query = runner.call_args.kwargs["query"]
                self.assertIsNone(query.response)
                self.assertFalse(query.includePostHogConversions)
                self.assertEqual(runner.call_args.kwargs["team"], self.team)
                self.assertEqual(runner.call_args.kwargs["user"], self.user)
