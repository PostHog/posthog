import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import DateRange, MarketingAnalyticsDrillDownLevel, MarketingAnalyticsTableQuery

from products.marketing_analytics.backend.hogql_queries.errors import MarketingPrecomputeNotReady
from products.marketing_analytics.backend.hogql_queries.marketing_analytics_table_query_runner import (
    MarketingAnalyticsTableQueryRunner,
)
from products.marketing_analytics.backend.services.conversion_people import ConversionPeopleQuery


@time_machine.travel("2026-09-20T12:00:00Z", tick=False)
class TestConversionPeople(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self) -> None:
        super().setUp()
        config = self.team.marketing_analytics_config
        config.conversion_goals = [
            {
                "kind": "EventsNode",
                "event": "purchase",
                "name": "purchase",
                "math": "total",
                "conversion_goal_id": "purchase",
                "conversion_goal_name": "Purchases",
                "schema_map": {"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
            }
        ]
        config.attribution_window_days = 7
        config.save()
        self.source = MarketingAnalyticsTableQuery(
            properties=[],
            dateRange=DateRange(date_from="2026-09-15", date_to="2026-09-20"),
            select=["Campaign", "Source", "ID", "Purchases"],
        )
        self.flags = patch(
            "products.marketing_analytics.backend.hogql_queries.marketing_analytics_config.feature_enabled_or_false",
            return_value=False,
        )
        self.flags.start()
        self.addCleanup(self.flags.stop)
        for person, campaign in [("alex", "winter-sale"), ("sam", "winter-sale"), ("other", "other-sale")]:
            _create_person(team=self.team, distinct_ids=[person], properties={"email": f"{person}@example.com"})
            _create_event(
                team=self.team,
                distinct_id=person,
                event="$pageview",
                timestamp="2026-09-16T10:00:00Z",
                properties={"utm_campaign": campaign, "utm_source": "google", "utm_medium": "cpc"},
            )
            for hour in [11, 12]:
                _create_event(
                    team=self.team,
                    distinct_id=person,
                    event="purchase",
                    timestamp=f"2026-09-16T{hour}:00:00Z",
                    properties={},
                )
        flush_persons_and_events()

    @parameterized.expand(
        [
            (MarketingAnalyticsDrillDownLevel.CAMPAIGN, "winter-sale", "google", 2),
            (MarketingAnalyticsDrillDownLevel.SOURCE, "google", "", 3),
            (MarketingAnalyticsDrillDownLevel.MEDIUM, "cpc", "", 3),
        ]
    )
    def test_people_match_the_table_attribution(
        self, level: MarketingAnalyticsDrillDownLevel, group: str, source: str, count: int
    ) -> None:
        self.source.drillDownLevel = level
        self.source.select = None
        table = MarketingAnalyticsTableQueryRunner(query=self.source, team=self.team, user=self.user).calculate()
        self.assertTrue(table.results)
        result = ConversionPeopleQuery(query=self.source, team=self.team, user=self.user).people(
            "purchase", group, source, None, "", 0, 50
        )
        self.assertEqual(len(result["results"]), count)
        self.assertFalse(result["has_more"])
        self.assertFalse(result["preparing"])
        self.assertEqual(len({person["id"] for person in result["results"]}), count)

    def test_endpoint_search_and_pagination(self) -> None:
        url = f"/api/projects/{self.team.pk}/marketing_analytics/conversion_people/"
        payload = {
            "source": self.source.model_dump(mode="json"),
            "goal_id": "purchase",
            "group": "winter-sale",
            "source_name": "google",
            "limit": 1,
        }
        first = self.client.post(url, payload, format="json")
        self.assertEqual(first.status_code, 200, first.content)
        self.assertTrue(first.json()["has_more"])
        second = self.client.post(url, {**payload, "offset": 1}, format="json")
        self.assertEqual(second.status_code, 200, second.content)
        self.assertFalse(second.json()["has_more"])
        self.assertNotEqual(first.json()["results"][0]["id"], second.json()["results"][0]["id"])
        searched = self.client.post(url, {**payload, "search": "alex@"}, format="json")
        self.assertEqual([p["name"] for p in searched.json()["results"]], ["alex@example.com"])
        invalid = self.client.post(url, {**payload, "source": {"kind": "ActorsQuery"}}, format="json")
        self.assertEqual(invalid.status_code, 400)

    def test_campaign_mapping_and_missing_row(self) -> None:
        config = self.team.marketing_analytics_config
        config.campaign_name_mappings = {"GoogleAds": {"Winter campaign": ["winter-sale"]}}
        config.save()
        for group, expected in [("Winter campaign", 2), ("winter-sale", 0)]:
            result = ConversionPeopleQuery(query=self.source, team=self.team, user=self.user).people(
                "purchase", group, "google", None, "", 0, 50
            )
            self.assertEqual(len(result["results"]), expected)

    def test_cold_precompute_is_retryable(self) -> None:
        runner = ConversionPeopleQuery(query=self.source, team=self.team, user=self.user)
        with (
            patch.object(runner, "people_query", side_effect=MarketingPrecomputeNotReady("purchase")),
            patch("products.marketing_analytics.backend.services.conversion_people.handle_not_ready") as warm,
        ):
            self.assertEqual(
                runner.people("purchase", "winter-sale", "google", None, "", 0, 50),
                {"results": [], "has_more": False, "preparing": True},
            )
            warm.assert_called_once_with(team=self.team, query=self.source)
        result = runner.people("purchase", "winter-sale", "google", None, "", 0, 50)
        self.assertEqual(len(result["results"]), 2)
        self.assertFalse(result["preparing"])
