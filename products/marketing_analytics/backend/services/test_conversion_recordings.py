from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events
from unittest.mock import patch

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.schema import (
    AttributionMode,
    CompareFilter,
    DateRange,
    MarketingAnalyticsDrillDownLevel,
    MarketingAnalyticsTableQuery,
)

from posthog.clickhouse.client.execute import sync_execute, validated_client_query_id
from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded
from posthog.clickhouse.preaggregation.marketing_conversions_sql import TRUNCATE_MARKETING_CONVERSIONS_TABLE_SQL
from posthog.clickhouse.preaggregation.marketing_touchpoints_sql import TRUNCATE_MARKETING_TOUCHPOINTS_TABLE_SQL
from posthog.clickhouse.query_tagging import get_query_tag_value, tags_context

from products.actions.backend.models.action import Action
from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import LazyComputationResult
from products.analytics_platform.backend.models.preaggregation_job import PreaggregationJob
from products.marketing_analytics.backend.hogql_queries.errors import MarketingPrecomputeNotReady
from products.marketing_analytics.backend.hogql_queries.marketing_analytics_table_query_runner import (
    MarketingAnalyticsTableQueryRunner,
)
from products.marketing_analytics.backend.services.conversion_recordings import ConversionRecordingsQuery
from products.warehouse_sources.backend.facade.testing import create_data_warehouse_table_from_csv


@time_machine.travel("2026-09-20T12:00:00Z", tick=False)
class TestConversionRecordings(ClickhouseTestMixin, APIBaseTest):
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
        for index, (person, campaign) in enumerate(
            [("alex", "winter-sale"), ("sam", "winter-sale"), ("other", "other-sale")], start=1
        ):
            _create_person(team=self.team, distinct_ids=[person], properties={"email": f"{person}@example.com"})
            _create_event(
                team=self.team,
                distinct_id=person,
                event="$pageview",
                timestamp="2026-09-16T10:00:00Z",
                properties={
                    "utm_campaign": campaign,
                    "utm_source": "google",
                    "utm_medium": "cpc",
                    "$session_id": f"01994530-9000-7000-8000-00000000001{index}",
                },
            )
            for hour in [11, 12]:
                _create_event(
                    team=self.team,
                    distinct_id=person,
                    event="purchase",
                    timestamp=f"2026-09-16T{hour}:00:00Z",
                    properties={"$session_id": f"01994530-9000-7000-8000-00000000000{index}"},
                )
        flush_persons_and_events()

    @parameterized.expand(
        [
            (MarketingAnalyticsDrillDownLevel.CAMPAIGN, "winter-sale", "google", 2),
            (MarketingAnalyticsDrillDownLevel.SOURCE, "google", "", 3),
            (MarketingAnalyticsDrillDownLevel.MEDIUM, "cpc", "", 3),
        ]
    )
    def test_sessions_match_the_table_attribution(
        self, level: MarketingAnalyticsDrillDownLevel, group: str, source: str, count: int
    ) -> None:
        self.source.drillDownLevel = level
        self.source.select = None
        table = MarketingAnalyticsTableQueryRunner(query=self.source, team=self.team, user=self.user).calculate()
        self.assertTrue(table.results)
        result = ConversionRecordingsQuery(query=self.source, team=self.team, user=self.user).sessions(
            "purchase", group, source, None, None, 50
        )
        self.assertEqual(
            result["session_ids"], [f"01994530-9000-7000-8000-00000000000{i}" for i in range(1, count + 1)]
        )
        self.assertFalse(result["has_more"])
        self.assertFalse(result["preparing"])

    def test_endpoint_pagination_and_exact_row_keys(self) -> None:
        _create_person(team=self.team, distinct_ids=["pat"], properties={"email": "pat@example.com"})
        _create_event(
            team=self.team,
            distinct_id="pat",
            event="$pageview",
            timestamp="2026-09-16T10:00:00Z",
            properties={"utm_campaign": "winter-sale ", "utm_source": "google", "utm_medium": "cpc"},
        )
        _create_event(
            team=self.team,
            distinct_id="pat",
            event="purchase",
            timestamp="2026-09-16T11:00:00Z",
            properties={"$session_id": "01994530-9000-7000-8000-000000000004"},
        )
        flush_persons_and_events()
        url = f"/api/projects/{self.team.pk}/marketing_analytics/conversion_recordings/"
        payload = {
            "client_query_id": "01994530-9000-7000-8000-000000000021",
            "source": self.source.model_dump(mode="json"),
            "goal_id": "purchase",
            "group": "winter-sale",
            "source_name": "google",
            "limit": 1,
        }
        query_ids: list[str | None] = []

        def capture_query_id() -> str | None:
            query_ids.append(get_query_tag_value("client_query_id"))
            return validated_client_query_id()

        with (
            tags_context(product=None, feature=None, client_query_id=None),
            patch("posthog.clickhouse.client.execute.DEBUG", True),
            patch("posthog.clickhouse.client.execute.TEST", False),
            patch("posthog.clickhouse.client.execute.validated_client_query_id", side_effect=capture_query_id),
        ):
            first = self.client.post(url, payload, format="json")
        self.assertEqual(first.status_code, 200, first.content)
        self.assertIn(payload["client_query_id"], query_ids)
        self.assertTrue(first.json()["has_more"])
        second = self.client.post(url, {**payload, "after": first.json()["session_ids"][-1]}, format="json")
        self.assertEqual(second.status_code, 200, second.content)
        self.assertFalse(second.json()["has_more"])
        self.assertNotEqual(first.json()["session_ids"][0], second.json()["session_ids"][0])
        exhausted = self.client.post(url, {**payload, "after": second.json()["session_ids"][-1]}, format="json")
        self.assertEqual(exhausted.json()["session_ids"], [])
        self.assertFalse(exhausted.json()["has_more"])
        padded = self.client.post(url, {**payload, "group": "winter-sale ", "limit": 50}, format="json")
        self.assertEqual(padded.json()["session_ids"], ["01994530-9000-7000-8000-000000000004"])
        invalid_requests: list[dict[str, object]] = [
            {"source": {"kind": "ActorsQuery"}},
            {"goal_id": "removed-goal"},
            {"source": {**self.source.model_dump(mode="json"), "drillDownLevel": "ad"}},
        ]
        for invalid_fields in invalid_requests:
            with self.subTest(invalid_fields=invalid_fields):
                invalid = self.client.post(url, {**payload, **invalid_fields}, format="json")
                self.assertEqual(invalid.status_code, 400)
        for limiter in ("get_app_org_rate_limiter", "get_api_team_rate_limiter"):
            with self.subTest(limiter=limiter), patch(f"products.marketing_analytics.backend.api.{limiter}") as mock:
                mock.return_value.run.side_effect = ConcurrencyLimitExceeded("internal limiter detail")
                throttled = self.client.post(url, payload, format="json")
                self.assertEqual(throttled.status_code, 429)
                self.assertNotIn("internal limiter detail", throttled.json()["detail"])

    def test_campaign_mapping_and_missing_row(self) -> None:
        config = self.team.marketing_analytics_config
        config.campaign_name_mappings = {"GoogleAds": {"Winter campaign": ["winter-sale"]}}
        config.save()
        for group, campaign_id, expected in [
            ("Winter campaign", None, 2),
            ("winter-sale", None, 0),
            ("Winter campaign", "another-campaign-id", 0),
        ]:
            result = ConversionRecordingsQuery(query=self.source, team=self.team, user=self.user).sessions(
                "purchase", group, "google", campaign_id, None, 50
            )
            self.assertEqual(len(result["session_ids"]), expected)

        config.campaign_field_preferences = {"GoogleAds": {"match_field": "campaign_id"}}
        config.campaign_name_mappings = {"GoogleAds": {"mapped-id": ["winter-sale"]}}
        config.save()
        for compare, campaign_id, expected in [
            (False, None, 0),
            (False, "", 0),
            (False, "-", 0),
            (False, "mapped-id", 2),
            (True, None, 2),
            (True, "mapped-id", 2),
        ]:
            with self.subTest(compare=compare, campaign_id=campaign_id):
                self.source.compareFilter = CompareFilter(compare=compare)
                result = ConversionRecordingsQuery(query=self.source, team=self.team, user=self.user).sessions(
                    "purchase", "winter-sale", "google", campaign_id, None, 50
                )
                self.assertEqual(len(result["session_ids"]), expected)

    def test_cold_precompute_is_retryable(self) -> None:
        runner = ConversionRecordingsQuery(query=self.source, team=self.team, user=self.user)
        with (
            patch.object(runner, "sessions_query", side_effect=MarketingPrecomputeNotReady("purchase")),
            patch("products.marketing_analytics.backend.services.conversion_recordings.handle_not_ready") as warm,
        ):
            self.assertEqual(
                runner.sessions("purchase", "winter-sale", "google", None, None, 50),
                {"session_ids": [], "has_more": False, "preparing": True},
            )
            warm.assert_called_once_with(team=self.team, query=self.source)
        result = runner.sessions("purchase", "winter-sale", "google", None, None, 50)
        self.assertEqual(len(result["session_ids"]), 2)
        self.assertFalse(result["preparing"])

    def test_precomputed_session_metadata_does_not_split_the_table_conversion(self) -> None:
        job_ids = [uuid4(), uuid4()]
        person_id = uuid4()
        session_ids = ["01994530-9000-7000-8000-000000000051", "01994530-9000-7000-8000-000000000052"]
        self.addCleanup(sync_execute, TRUNCATE_MARKETING_CONVERSIONS_TABLE_SQL())
        sync_execute(
            "INSERT INTO sharded_marketing_conversions_preaggregated "
            "(team_id, job_id, person_id, conversion_timestamp, conversion_math_value, session_id, "
            "campaign_name, source_name, computed_at, expires_at) VALUES",
            [
                (
                    self.team.pk,
                    job_id,
                    person_id,
                    datetime(2026, 9, 16, 11, tzinfo=UTC),
                    1,
                    session_ids[index],
                    "winter-sale",
                    "google",
                    datetime(2026, 9, 20, index, tzinfo=UTC),
                    datetime(2100, 1, 1, tzinfo=UTC),
                )
                for index, job_id in enumerate(job_ids)
            ],
        )
        table_runner = MarketingAnalyticsTableQueryRunner(query=self.source, team=self.team, user=self.user)
        table_runner.config.conversion_goal_precomputation_enabled = True
        recordings_runner = ConversionRecordingsQuery(query=self.source, team=self.team, user=self.user)
        recordings_runner.config.conversion_goal_precomputation_enabled = True
        with patch(
            "products.marketing_analytics.backend.hogql_queries.conversion_goal_processor.marketing_ensure_precomputed",
            return_value=LazyComputationResult(ready=True, job_ids=job_ids),
        ):
            table = table_runner.calculate()
            assert table.columns is not None
            self.assertEqual(len(table.results), 1)
            self.assertEqual(table.results[0][table.columns.index("Purchases")].value, 1)
            result = recordings_runner.sessions("purchase", "winter-sale", "google", None, None, 50)
        self.assertEqual(result["session_ids"], [session_ids[1]])

    @parameterized.expand(
        [
            (False, AttributionMode.LAST_TOUCH, 7),
            (True, AttributionMode.LAST_TOUCH, 7),
            (False, AttributionMode.LINEAR, 7),
            (True, AttributionMode.LINEAR, 7),
            (False, AttributionMode.LAST_TOUCH, 0),
            (False, AttributionMode.LAST_TOUCH, 7, True),
            (True, AttributionMode.LAST_TOUCH, 7, True),
        ]
    )
    def test_returns_conversion_sessions_not_other_sessions_of_the_same_person(
        self, precompute: bool, mode: AttributionMode, window_days: int, action_goal: bool = False
    ) -> None:
        if precompute:
            sync_execute(TRUNCATE_MARKETING_TOUCHPOINTS_TABLE_SQL())
            sync_execute(TRUNCATE_MARKETING_CONVERSIONS_TABLE_SQL())
            PreaggregationJob.objects.all().delete()
            self.addCleanup(sync_execute, TRUNCATE_MARKETING_TOUCHPOINTS_TABLE_SQL())
            self.addCleanup(sync_execute, TRUNCATE_MARKETING_CONVERSIONS_TABLE_SQL())
        if action_goal:
            action = Action.objects.create(team=self.team, name="Purchases", steps_json=[{"event": "purchase"}])
            config = self.team.marketing_analytics_config
            config.conversion_goals[0].update(kind="ActionsNode", id=action.id)
            config.conversion_goals[0].pop("event")
            config.save()
        for hour, properties in [
            (13, {}),
            (14, {"$session_id": "00000000-0000-0000-0000-000000000000"}),
            (
                15,
                {
                    "$session_id": "01994530-9000-7000-8000-000000000006",
                    **({"utm_campaign": "later-sale", "utm_source": "google"} if window_days == 0 else {}),
                },
            ),
        ]:
            _create_event(
                team=self.team,
                distinct_id="alex",
                event="purchase",
                timestamp=f"2026-09-16T{hour}:00:00Z",
                properties=properties,
            )
        _create_event(
            team=self.team,
            distinct_id="alex",
            event="$pageview",
            timestamp="2026-09-16T14:30:00Z",
            properties={
                "$session_id": "01994530-9000-7000-8000-000000000008",
                "utm_campaign": "later-sale",
                "utm_source": "google",
            },
        )
        _create_event(
            team=self.team,
            distinct_id="alex",
            event="purchase",
            timestamp="2026-09-01T10:00:00Z",
            properties={
                "$session_id": "01994530-9000-7000-8000-000000000007",
                "utm_campaign": "later-sale",
                "utm_source": "google",
            },
        )
        flush_persons_and_events()
        runner = ConversionRecordingsQuery(query=self.source, team=self.team, user=self.user)
        runner.config.conversion_goal_precomputation_enabled = precompute
        runner.config.attribution_mode = mode
        runner.config.attribution_window_days = window_days
        with (
            patch(
                "products.marketing_analytics.backend.hogql_queries.marketing_lazy_precompute.is_background_warming_request",
                return_value=True,
            ),
            patch(
                "products.analytics_platform.backend.lazy_computation.lazy_computation_executor._get_ch_expires_at",
                return_value=datetime(2100, 1, 1, tzinfo=UTC),
            ),
        ):
            result = runner.sessions("purchase", "later-sale", "google", None, None, 50)
        self.assertEqual(
            result, {"session_ids": ["01994530-9000-7000-8000-000000000006"], "has_more": False, "preparing": False}
        )


class TestWarehouseConversionRecordings(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self) -> None:
        super().setUp()
        flags = patch(
            "products.marketing_analytics.backend.hogql_queries.marketing_analytics_config.feature_enabled_or_false",
            return_value=False,
        )
        flags.start()
        self.addCleanup(flags.stop)

    def test_warehouse_goal_without_conversion_sessions_is_rejected(self) -> None:
        table, *_rest, cleanup = create_data_warehouse_table_from_csv(
            Path(__file__).parents[1] / "hogql_queries/test/external/warehouse_conversions_empty_utm.csv",
            "conversion_recordings_warehouse",
            {
                "user_id": "String",
                "event_timestamp": "DateTime",
                "campaign_name": "String",
                "source_name": "String",
                "revenue": "Int64",
            },
            "test_storage_bucket-posthog.marketing_analytics.conversion_recordings",
            self.team,
        )
        self.addCleanup(cleanup)
        _create_person(team=self.team, distinct_ids=["dw_user_2"], properties={"email": "dw@example.com"})
        flush_persons_and_events()
        config = self.team.marketing_analytics_config
        config.conversion_goals = [
            {
                "kind": "DataWarehouseNode",
                "id": table.name,
                "table_name": table.name,
                "name": "Warehouse purchases",
                "math": "total",
                "conversion_goal_id": "warehouse",
                "conversion_goal_name": "Warehouse purchases",
                "distinct_id_field": "user_id",
                "id_field": "user_id",
                "timestamp_field": "event_timestamp",
                "schema_map": {
                    "utm_campaign_name": "campaign_name",
                    "utm_source_name": "source_name",
                    "timestamp_field": "event_timestamp",
                },
            }
        ]
        config.save()
        source = MarketingAnalyticsTableQuery(
            properties=[], dateRange=DateRange(date_from="2023-01-01", date_to="2023-01-31")
        )
        with (
            time_machine.travel("2023-02-01T12:00:00Z", tick=False),
            self.assertRaisesMessage(ValidationError, "only available for event and action goals"),
        ):
            ConversionRecordingsQuery(query=source, team=self.team, user=self.user).sessions(
                "warehouse", "summer_sale", "google", None, None, 50
            )
