from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from parameterized import parameterized

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

from products.marketing_analytics.backend.hogql_queries.marketing_analytics_actors_query_runner import (
    MarketingAnalyticsActorsQueryRunner,
)


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

    def _session_and_conversion(
        self, distinct_id: str, campaign: str, source: str, click_id: str | None = None
    ) -> None:
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
                **({click_id: "example-click-id"} if click_id else {}),
            },
        )
        _create_event(
            team=self.team,
            event="purchase",
            distinct_id=distinct_id,
            timestamp="2023-01-11T12:00:00Z",
            properties={},
        )

    @parameterized.expand([("utm_source", "google", None), ("gclid", "", "gclid"), ("gad_source", "", "gad_source")])
    def test_returns_only_people_attributed_to_the_clicked_campaign_and_source(
        self, _name: str, source_name: str, click_id: str | None
    ) -> None:
        google_person = create_person(team=self.team, distinct_ids=["google-person"])
        newsletter_person = create_person(team=self.team, distinct_ids=["newsletter-person"])
        other_campaign_person = create_person(team=self.team, distinct_ids=["other-campaign-person"])
        self._session_and_conversion("google-person", "winter-sale", source_name, click_id)
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

    def test_unwarmed_conversion_details_schedule_warming_and_return_not_ready(self) -> None:
        source = MarketingAnalyticsTableQuery(
            dateRange=DateRange(date_from="2023-01-01", date_to="2023-01-31"), properties=[]
        )
        runner = ActorsQueryRunner(
            query=ActorsQuery(
                source=MarketingAnalyticsActorsQuery(
                    source=source,
                    conversionGoalId="purchases",
                    breakdown=MarketingAnalyticsActorsBreakdown(value="winter-sale", source="google"),
                ),
                select=["actor"],
            ),
            team=self.team,
        )
        assert isinstance(runner.source_query_runner, MarketingAnalyticsActorsQueryRunner)
        runner.source_query_runner.config.conversion_goal_precomputation_enabled = True

        with patch(
            "products.marketing_analytics.backend.tasks.lazy_precompute_revalidation"
            ".revalidate_marketing_analytics_precompute.delay"
        ) as warm:
            response = runner.calculate()

        assert response.precomputeNotReady is True
        assert response.results == []
        assert response.hasMore is False
        warm.assert_called_once()
        assert warm.call_args.kwargs["team_id"] == self.team.pk
        assert source.dateRange is not None
        assert warm.call_args.kwargs["query"]["dateRange"] == source.dateRange.model_dump(exclude_none=True)
