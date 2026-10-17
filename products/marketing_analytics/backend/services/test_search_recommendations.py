from unittest import TestCase

from parameterized import parameterized

from posthog.schema import (
    MarketingAnalyticsSearchConversion,
    MarketingAnalyticsSearchConversionGoal,
    MarketingAnalyticsSearchMetrics,
    MarketingAnalyticsSearchQueryResponse,
    MarketingAnalyticsSearchRow,
    Platform,
)

from products.marketing_analytics.backend.services.search_recommendations import search_recommendations


class TestSearchRecommendations(TestCase):
    def setUp(self) -> None:
        self.row = MarketingAnalyticsSearchRow(
            platform="GoogleAds",
            keyword="example keyword",
            currency="USD",
            clicks=200,
            impressions=2000,
            cost=200,
            conversions=10,
            previous=MarketingAnalyticsSearchMetrics(clicks=200, impressions=2000, cost=100, conversions=10),
            posthogConversions=[
                MarketingAnalyticsSearchConversion(
                    id="purchase", name="Purchases", conversions=0, previousConversions=5, costPerConversion=None
                )
            ],
        )
        self.response = MarketingAnalyticsSearchQueryResponse(
            results=[self.row],
            posthogConversionGoals=[MarketingAnalyticsSearchConversionGoal(id="purchase", name="Purchases")],
        )

    def test_selected_goal_never_falls_back_to_platform_conversions(self) -> None:
        selected = search_recommendations(self.response, "purchase")
        self.assertEqual(selected.goal_id, "purchase")
        self.assertEqual(selected.recommendations[0].kind, "spend_without_conversions")
        platform = search_recommendations(self.response, None)
        self.assertEqual(platform.recommendations[0].kind, "higher_cpa")
        self.assertEqual((platform.recommendations[0].current, platform.recommendations[0].previous), (20, 10))
        self.row.posthogConversions = []
        self.assertEqual(search_recommendations(self.response, "purchase").recommendations, [])
        for goal_id, warning in (("missing", None), ("purchase", "Incomplete attribution")):
            with self.subTest(goal_id=goal_id, warning=warning):
                self.response.posthogConversionsWarning = warning
                result = search_recommendations(self.response, goal_id)
                self.assertEqual(result.recommendations, [])
                self.assertIsNotNone(result.warning)

    @parameterized.expand(
        [
            ("previous", None),
            ("currency", None),
            ("cost", None),
            ("cost", float("nan")),
            ("conversions", None),
            ("conversions", 2),
            ("conversions", -1),
            ("previous", MarketingAnalyticsSearchMetrics(clicks=200, impressions=2000, cost=0, conversions=10)),
            ("previous", MarketingAnalyticsSearchMetrics(clicks=200, impressions=2000, cost=100, conversions=0)),
        ]
    )
    def test_incomplete_paid_evidence(self, field: str, value: object) -> None:
        row = self.row.model_copy(update={field: value})
        self.assertEqual(
            search_recommendations(self.response.model_copy(update={"results": [row]}), None).recommendations, []
        )

    def test_sample_thresholds_and_organic_traffic(self) -> None:
        self.row.clicks = 99
        self.assertEqual(search_recommendations(self.response, "purchase").recommendations, [])
        self.row.platform = Platform.GOOGLE_SEARCH_CONSOLE
        self.row.cost = None
        self.row.currency = None
        self.row.clicks = 20
        self.row.ctr = 0.99
        result = search_recommendations(self.response, None)
        self.assertEqual(result.recommendations[0].kind, "lower_organic_ctr")
        self.assertEqual(result.recommendations[0].current, 0.01)
        self.row.impressions = 999
        self.assertEqual(search_recommendations(self.response, None).recommendations, [])
