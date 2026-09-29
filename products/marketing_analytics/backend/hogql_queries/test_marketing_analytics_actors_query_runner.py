from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from pathlib import Path

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import (
    ActorsQuery,
    BaseMathType,
    CompareFilter,
    ConversionGoalFilter1,
    ConversionGoalFilter3,
    DateRange,
    MarketingAnalyticsActorsBreakdown,
    MarketingAnalyticsActorsQuery,
    MarketingAnalyticsDrillDownLevel,
    MarketingAnalyticsTableQuery,
    NodeKind,
)

from posthog.constants import AvailableFeature
from posthog.hogql_queries.actors_query_runner import ActorsQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import OrganizationMembership
from posthog.models.utils import uuid7
from posthog.test.persons import create_person

from products.access_control.backend.facade.user_access_control import UserAccessControlError
from products.access_control.backend.models.access_control import AccessControl
from products.analytics_platform.backend.models.preaggregation_job import PreaggregationJob
from products.marketing_analytics.backend.hogql_queries.marketing_analytics_actors_query_runner import (
    MarketingAnalyticsActorsQueryRunner,
)
from products.marketing_analytics.backend.hogql_queries.marketing_analytics_table_query_runner import (
    MarketingAnalyticsTableQueryRunner,
)
from products.warehouse_sources.backend.facade.models import ExternalDataSource
from products.warehouse_sources.backend.facade.testing import create_data_warehouse_table_from_csv


class TestMarketingAnalyticsActorsQueryRunner(ClickhouseTestMixin, APIBaseTest):
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
                "utm_medium": "cpc" if source == "google" or click_id else "email",
                "utm_content": campaign,
                "utm_term": campaign,
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

    @parameterized.expand(
        [
            ("utm_source", "google", None, False),
            ("gclid", "", "gclid", False),
            ("gad_source", "", "gad_source", False),
            ("precompute_read_failure", "google", None, True),
        ]
    )
    @time_machine.travel("2023-02-01T12:00:00Z", tick=False)
    def test_returns_only_people_attributed_to_the_clicked_campaign_and_source(
        self, _name: str, source_name: str, click_id: str | None, precompute_failure: bool
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

        runner = ActorsQueryRunner(
            query=ActorsQuery(source=query, select=["actor"]),
            team=self.team,
        )
        assert isinstance(runner.source_query_runner, MarketingAnalyticsActorsQueryRunner)
        runner.source_query_runner.config.conversion_goal_precomputation_enabled = precompute_failure
        with (
            patch(
                "products.marketing_analytics.backend.hogql_queries.conversion_goal_processor.marketing_ensure_precomputed",
                side_effect=RuntimeError("Precompute storage unavailable"),
            )
            if precompute_failure
            else nullcontext()
        ) as precompute:
            response = runner.calculate()
            if precompute_failure:
                assert precompute is not None
                precompute.assert_called_once()
        person_ids = {row[0]["id"] for row in response.results}

        assert person_ids == {google_person.uuid}
        assert newsletter_person.uuid not in person_ids
        assert other_campaign_person.uuid not in person_ids

    @parameterized.expand([("campaign_name", False), ("campaign_id", False), ("campaign_id", True)])
    def test_campaign_match_key_round_trips_from_the_table(self, match_field: str, compare: bool) -> None:
        ads_source = ExternalDataSource.objects.create(
            team=self.team, source_id="example-ads", connection_id="example-connection", source_type="GoogleAds"
        )
        for table_name, columns in [
            (
                "campaign",
                {"campaign_id": "String", "campaign_name": "String", "campaign_advertising_channel_type": "String"},
            ),
            (
                "campaign_stats",
                {
                    "campaign_id": "String",
                    "segments_date": "Date",
                    "metrics_impressions": "Int64",
                    "metrics_clicks": "Int64",
                    "metrics_cost_micros": "Int64",
                    "metrics_conversions": "Int64",
                    "metrics_conversions_value": "Int64",
                },
            ),
        ]:
            *_, cleanup = create_data_warehouse_table_from_csv(
                Path(__file__).parent / f"test/google_ads/conversion_people_{table_name}.csv",
                f"googleads_{table_name}",
                columns,
                "test_storage_bucket-posthog.marketing_analytics.conversion_people",
                self.team,
                source=ads_source,
            )
            self.addCleanup(cleanup)

        person = create_person(team=self.team, distinct_ids=["mapped-person"])
        create_person(team=self.team, distinct_ids=["other-person"])
        self._session_and_conversion("mapped-person", "winter-sale", "google")
        self._session_and_conversion("other-person", "spring-sale", "google")
        flush_persons_and_events()
        config = self.team.marketing_analytics_config
        match_key = "10042" if match_field == "campaign_id" else "Winter sale"
        config.campaign_field_preferences = {"GoogleAds": {"match_field": match_field}}
        config.campaign_name_mappings = {"GoogleAds": {match_key: ["winter-sale"]}}
        config.save()

        source = MarketingAnalyticsTableQuery(
            dateRange=DateRange(date_from="2023-01-01", date_to="2023-01-31"),
            compareFilter=CompareFilter(compare=True) if compare else None,
            select=["Campaign", "Source", "Purchases"],
            properties=[],
        )
        table = MarketingAnalyticsTableQueryRunner(query=source, team=self.team).calculate()
        assert table.columns == ["Campaign", "Source", "Purchases"]
        campaign_row = next(row for row in table.results if row[0].value == "Winter sale")
        campaign = campaign_row[0]
        assert campaign_row[2].value == 1
        assert campaign.conversionMatchKey == match_key
        assert campaign.value == "Winter sale"

        response = ActorsQueryRunner(
            query=ActorsQuery(
                source=MarketingAnalyticsActorsQuery(
                    source=source,
                    conversionGoalId="purchases",
                    breakdown=MarketingAnalyticsActorsBreakdown(
                        value=str(campaign.value),
                        source=str(campaign_row[1].value),
                        matchKey=campaign.conversionMatchKey,
                    ),
                ),
                select=["actor"],
            ),
            team=self.team,
        ).calculate()
        assert {row[0]["id"] for row in response.results} == {person.uuid}

    @parameterized.expand(
        [
            (MarketingAnalyticsDrillDownLevel.SOURCE, "google", None, False),
            (MarketingAnalyticsDrillDownLevel.CHANNEL, "Paid Search", None, False),
            (MarketingAnalyticsDrillDownLevel.CHANNEL_SOURCE, "Paid Search", "google", False),
            (MarketingAnalyticsDrillDownLevel.MEDIUM, "cpc", None, False),
            (MarketingAnalyticsDrillDownLevel.CONTENT, "winter-sale", None, True),
            (MarketingAnalyticsDrillDownLevel.TERM, "winter-sale", None, True),
        ]
    )
    def test_other_breakdowns_select_their_attributed_population(
        self, level: MarketingAnalyticsDrillDownLevel, value: str, source: str | None, includes_newsletter: bool
    ) -> None:
        google = create_person(team=self.team, distinct_ids=["google-buyer"])
        newsletter = create_person(team=self.team, distinct_ids=["newsletter-buyer"])
        self._session_and_conversion("google-buyer", "winter-sale", "google")
        self._session_and_conversion("newsletter-buyer", "winter-sale", "newsletter")
        flush_persons_and_events()
        response = ActorsQueryRunner(
            query=ActorsQuery(
                source=MarketingAnalyticsActorsQuery(
                    source=MarketingAnalyticsTableQuery(
                        dateRange=DateRange(date_from="2023-01-01", date_to="2023-01-31"),
                        drillDownLevel=level,
                        properties=[],
                    ),
                    conversionGoalId="purchases",
                    breakdown=MarketingAnalyticsActorsBreakdown(value=value, source=source),
                ),
                select=["actor"],
            ),
            team=self.team,
        ).calculate()
        expected = {google.uuid, newsletter.uuid} if includes_newsletter else {google.uuid}
        assert {row[0]["id"] for row in response.results} == expected

    @parameterized.expand(
        [
            ("string", "String", "warehouse_conversions_empty_utm", "dw_user_2", "dw_user_1", False),
            ("numeric", "Int64", "conversion_people_numeric", "42", "43", False),
            ("nullable", "Nullable(Int64)", "conversion_people_nullable", "42", "43", False),
            ("cached_permissions", "String", "warehouse_conversions_empty_utm", "dw_user_2", "dw_user_1", True),
        ]
    )
    def test_warehouse_conversions_resolve_the_configured_distinct_id_to_a_person(
        self, _name: str, column_type: str, fixture: str, matched_id: str, other_id: str, check_permissions: bool
    ) -> None:
        table, _, _, _, cleanup = create_data_warehouse_table_from_csv(
            Path(__file__).parent / f"test/external/{fixture}.csv",
            "conversion_people",
            {
                "user_id": column_type,
                "event_timestamp": "DateTime",
                "campaign_name": "String",
                "source_name": "String",
                "revenue": "Int64",
            },
            "test_storage_bucket-posthog.marketing_analytics.conversion_people",
            self.team,
        )
        self.addCleanup(cleanup)
        person = create_person(team=self.team, distinct_ids=["primary-id", matched_id])
        create_person(team=self.team, distinct_ids=[other_id])
        flush_persons_and_events()
        config = self.team.marketing_analytics_config
        config.conversion_goals = [
            ConversionGoalFilter3(
                kind=NodeKind.DATA_WAREHOUSE_NODE,
                name="Purchases",
                id=table.name,
                table_name=table.name,
                conversion_goal_id="purchases",
                conversion_goal_name="Purchases",
                math=BaseMathType.TOTAL,
                distinct_id_field="user_id",
                id_field="user_id",
                timestamp_field="event_timestamp",
                schema_map={
                    "utm_campaign_name": "campaign_name",
                    "utm_source_name": "source_name",
                    "distinct_id_field": "user_id",
                    "timestamp_field": "event_timestamp",
                },
            ).model_dump()
        ]
        config.save()
        query = ActorsQuery(
            source=MarketingAnalyticsActorsQuery(
                source=MarketingAnalyticsTableQuery(
                    dateRange=DateRange(date_from="2023-01-01", date_to="2023-01-31"), properties=[]
                ),
                conversionGoalId="purchases",
                breakdown=MarketingAnalyticsActorsBreakdown(value="summer_sale", source="google"),
            ),
            select=["actor"],
        )
        response = ActorsQueryRunner(query=query, team=self.team).calculate()
        assert {row[0]["id"] for row in response.results} == {person.uuid}

        if check_permissions:
            self.organization.available_product_features = [
                {"key": AvailableFeature.ACCESS_CONTROL},
                {"key": AvailableFeature.ROLE_BASED_ACCESS},
            ]
            self.organization.save()
            other_user = self._create_user("restricted@example.com")
            membership = other_user.organization_memberships.get(organization=self.organization)
            membership.level = OrganizationMembership.Level.MEMBER
            membership.save()
            AccessControl.objects.create(
                team=self.team,
                resource="warehouse_table",
                resource_id=str(table.id),
                organization_member=membership,
                access_level="none",
            )
            request = {"query": query.model_dump(mode="json"), "refresh": "blocking"}
            url = f"/api/environments/{self.team.id}/query/"
            with patch("posthog.hogql.database.database.feature_enabled_or_false", return_value=True):
                granted = self.client.post(url, request)
                assert granted.status_code == 200, granted.content
                assert {row[0]["id"] for row in granted.json()["results"]} == {str(person.uuid)}
                cached = self.client.post(url, request)
                assert cached.status_code == 200, cached.content
                assert cached.json()["is_cached"] is True
                self.client.force_login(other_user)
                denied = self.client.post(url, request)
                assert denied.status_code == 400, denied.content
                assert denied.json()["code"] == "table_access_denied"

    @parameterized.expand([ExecutionMode.CALCULATE_BLOCKING_ALWAYS, ExecutionMode.CACHE_ONLY_NEVER_CALCULATE])
    def test_marketing_actors_check_access_before_calculation_or_cache(self, mode: ExecutionMode) -> None:
        AccessControl.objects.create(team=self.team, resource="web_analytics", access_level="none")
        self.organization.available_product_features = [{"key": AvailableFeature.ACCESS_CONTROL}]
        self.organization.save()
        runner = ActorsQueryRunner(
            team=self.team,
            query=ActorsQuery(
                source=MarketingAnalyticsActorsQuery(
                    source=MarketingAnalyticsTableQuery(dateRange=DateRange(date_from="-7d"), properties=[]),
                    conversionGoalId="purchases",
                    breakdown=MarketingAnalyticsActorsBreakdown(value="winter-sale", source="google"),
                )
            ),
        )
        with self.assertRaises(UserAccessControlError):
            runner.run(execution_mode=mode, user=self.user)

    @time_machine.travel("2023-02-01T12:00:00Z", tick=False)
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

    @parameterized.expand([("fresh", False), ("stale", True)])
    @time_machine.travel(datetime.now(UTC), tick=False)
    def test_precomputed_people_only_schedule_refresh_when_stale(self, _name: str, stale: bool) -> None:
        person = create_person(team=self.team, distinct_ids=["precomputed-buyer"])
        self._session_and_conversion("precomputed-buyer", "winter-sale", "google")
        flush_persons_and_events()
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
            "products.marketing_analytics.backend.hogql_queries.marketing_lazy_precompute.is_background_warming_request",
            return_value=True,
        ):
            assert {row[0]["id"] for row in runner.calculate().results} == {person.uuid}
        assert runner.source_query_runner._precompute_computed_at is not None
        if stale:
            assert (
                PreaggregationJob.objects.filter(team_id=self.team.id).update(
                    expires_at=datetime.now(UTC) - timedelta(minutes=1)
                )
                > 0
            )
        with patch(
            "products.marketing_analytics.backend.tasks.lazy_precompute_revalidation"
            ".revalidate_marketing_analytics_precompute.delay"
        ) as warm:
            for _ in range(2):
                assert {row[0]["id"] for row in runner.calculate().results} == {person.uuid}
        assert warm.call_count == (1 if stale else 0)
        if stale:
            assert warm.call_args.kwargs["query"]["kind"] == "MarketingAnalyticsTableQuery"
