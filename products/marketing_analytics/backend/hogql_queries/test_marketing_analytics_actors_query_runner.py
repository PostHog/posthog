from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from posthog.schema import (
    ActorsQuery,
    BaseMathType,
    ConversionGoalFilter1,
    DateRange,
    MarketingAnalyticsActorsBreakdown,
    MarketingAnalyticsActorsQuery,
    MarketingAnalyticsDrillDownLevel,
    MarketingAnalyticsTableQuery,
    NodeKind,
)

from posthog.hogql_queries.actors_query_runner import ActorsQueryRunner
from posthog.models.utils import uuid7
from posthog.test.persons import create_person


class TestMarketingAnalyticsActorsQueryRunner(ClickhouseTestMixin, BaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self) -> None:
        super().setUp()
        config = self.team.marketing_analytics_config
        config.attribution_window_days = 30
        config.conversion_goals = [
            ConversionGoalFilter1(
                kind=NodeKind.EVENTS_NODE,
                event="purchase",
                name="Purchases",
                conversion_goal_id="purchases",
                conversion_goal_name="Purchases",
                math=BaseMathType.TOTAL,
                schema_map={},
            ).model_dump()
        ]
        config.save()

    def _session_and_conversion(self, distinct_id: str, campaign: str, source: str) -> None:
        session_id = str(uuid7("2023-01-10T12:00:00Z"))
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=distinct_id,
            timestamp="2023-01-10T12:00:00Z",
            properties={
                "$session_id": session_id,
                "$current_url": "https://example.com/",
                "utm_campaign": campaign,
                "utm_source": source,
            },
        )
        _create_event(
            team=self.team,
            event="purchase",
            distinct_id=distinct_id,
            timestamp="2023-01-11T12:00:00Z",
            properties={},
        )

    def test_returns_only_people_attributed_to_the_clicked_campaign_and_source(self) -> None:
        google_person = create_person(team=self.team, distinct_ids=["google-person"])
        newsletter_person = create_person(team=self.team, distinct_ids=["newsletter-person"])
        other_campaign_person = create_person(team=self.team, distinct_ids=["other-campaign-person"])
        self._session_and_conversion("google-person", "winter-sale", "google")
        self._session_and_conversion("newsletter-person", "winter-sale", "newsletter")
        self._session_and_conversion("other-campaign-person", "spring-sale", "google")
        flush_persons_and_events()

        source = MarketingAnalyticsTableQuery(
            dateRange=DateRange(date_from="2023-01-01", date_to="2023-01-31"),
            drillDownLevel=MarketingAnalyticsDrillDownLevel.CAMPAIGN,
            properties=[],
        )
        query = MarketingAnalyticsActorsQuery(
            source=source,
            conversionGoalId="purchases",
            breakdown=MarketingAnalyticsActorsBreakdown(value="winter-sale", source="google"),
        )

        response = ActorsQueryRunner(
            query=ActorsQuery(source=query, select=["actor"]),
            team=self.team,
        ).calculate()
        person_ids = {row[0]["id"] for row in response.results}

        assert person_ids == {google_person.uuid}
        assert newsletter_person.uuid not in person_ids
        assert other_campaign_person.uuid not in person_ids
