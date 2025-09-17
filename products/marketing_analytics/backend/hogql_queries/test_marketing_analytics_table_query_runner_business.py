from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Union

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import Mock

from posthog.schema import (
    BaseMathType,
    ConversionGoalFilter2,
    DateRange,
    MarketingAnalyticsTableQuery,
    MarketingAnalyticsTableQueryResponse,
    NodeKind,
    SourceMap,
)

from posthog.hogql.errors import QueryError
from posthog.hogql.test.utils import pretty_print_in_tests

from posthog.models import Action
from posthog.models.team.team import Team
from posthog.warehouse.models import DataWarehouseTable, ExternalDataSource
from posthog.warehouse.models.credential import DataWarehouseCredential
from posthog.warehouse.test.utils import create_data_warehouse_table_from_csv

from products.marketing_analytics.backend.hogql_queries.marketing_analytics_table_query_runner import (
    MarketingAnalyticsTableQueryRunner,
)

TEST_DATE_FROM = "2024-01-01"
TEST_DATE_TO = "2024-12-31"
TEST_BUCKET_BASE = "test_storage_bucket-posthog.marketing_analytics"
DEFAULT_LIMIT = 100

FACEBOOK_SOURCE_MAP = {
    "campaign": "campaign1",
    "source": "source1",
    "cost": "spend1",
    "date": "date1",
    "impressions": "impressions1",
    "clicks": "clicks1",
    "currency": "USD",
    "reported_conversion": "conversions1",
}

TIKTOK_SOURCE_MAP = {
    "campaign": "campaign2",
    "source": "source2",
    "cost": "spend2",
    "date": "date2",
    "impressions": "impressions2",
    "clicks": "clicks2",
    "currency": "USD",
    "reported_conversion": None,
}

LINKEDIN_SOURCE_MAP = {
    "campaign": "campaign3",
    "source": "source3",
    "cost": "spend3",
    "date": "date3",
    "impressions": "impressions3",
    "clicks": "clicks3",
    "currency": "USD",
    "reported_conversion": None,
}


def get_default_query_runner(query: MarketingAnalyticsTableQuery, team: Team) -> MarketingAnalyticsTableQueryRunner:
    return MarketingAnalyticsTableQueryRunner(
        query=query,
        team=team,
        timings=None,
        modifiers=None,
        limit_context=None,
    )


@dataclass
class TableInfo:
    table: DataWarehouseTable
    source: ExternalDataSource
    credential: DataWarehouseCredential
    platform: str
    source_type: str
    cleanup_fn: Callable


@dataclass
class DataConfig:
    csv_filename: str
    table_name: str
    platform: str
    source_type: str
    bucket_suffix: str
    column_schema: dict[str, dict[str, Union[str, bool]]]


def _create_action(team, name: str = "test_action") -> Action:
    return Action.objects.create(
        team=team,
        name=name,
        steps_json=[{"event": "test_event"}],
    )


class TestMarketingAnalyticsTableQueryRunnerBusiness(ClickhouseTestMixin, BaseTest):
    maxDiff = None
    CLASS_DATA_LEVEL_SETUP = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.test_data_configs = {
            "facebook_ads": DataConfig(
                csv_filename="test/external/bigquery.csv",
                table_name="facebook_ads_table",
                platform="Facebook Ads",
                source_type="BigQuery",
                bucket_suffix="facebook",
                column_schema={
                    "campaign1": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "spend1": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "date1": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "impressions1": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "clicks1": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "source1": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "conversions1": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                },
            ),
            "tiktok_ads": DataConfig(
                csv_filename="test/self_managed/s3.csv",
                table_name="tiktok_ads_table",
                platform="TikTok",
                source_type="AWS",
                bucket_suffix="tiktok",
                column_schema={
                    "campaign2": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "spend2": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "date2": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "impressions2": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "clicks2": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "source2": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                },
            ),
            "linkedin_ads": DataConfig(
                csv_filename="test/self_managed/gcs.csv",
                table_name="linkedin_ads_table",
                platform="LinkedIn",
                source_type="google_cloud",
                bucket_suffix="linkedin",
                column_schema={
                    "campaign3": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "spend3": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "date3": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "impressions3": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "clicks3": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "source3": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                },
            ),
        }

    def setUp(self):
        super().setUp()
        self.test_tables: dict[str, TableInfo] = {}
        self._cleanup_functions: list[callable] = []

        config = self.team.marketing_analytics_config
        config.sources_map = {}
        config.conversion_goals = []
        config.save()

    def tearDown(self):
        for cleanup_fn in self._cleanup_functions:
            cleanup_fn()
        self._cleanup_functions.clear()
        self.test_tables.clear()
        super().tearDown()

    def _setup_csv_table(self, table_key: str) -> TableInfo:
        """Set up a single CSV-backed table for testing."""
        if table_key not in self.test_data_configs:
            raise ValueError(f"Invalid table key: {table_key}")

        if table_key in self.test_tables:
            return self.test_tables[table_key]

        config = self.test_data_configs[table_key]
        csv_path = Path(__file__).parent / config.csv_filename

        if not csv_path.exists():
            raise AssertionError(f"CSV file must exist at {csv_path}")

        columns = config.column_schema

        table, source, credential, csv_df, cleanup_fn = create_data_warehouse_table_from_csv(
            csv_path,
            config.table_name,
            columns,
            f"{TEST_BUCKET_BASE}.{config.bucket_suffix}",
            self.team,
        )

        table_info = TableInfo(
            table=table,
            source=source,
            credential=credential,
            platform=config.platform,
            source_type=config.source_type,
            cleanup_fn=cleanup_fn,
        )

        # Configure source types correctly for the factory to recognize them
        if config.platform == "Facebook Ads":
            source.source_type = "BigQuery"
            source.save()
        elif config.platform == "TikTok":
            # Set as BigQuery managed source to avoid S3 credential issues
            source.source_type = "BigQuery"
            source.save()
        elif config.platform == "LinkedIn":
            # Set as BigQuery managed source to avoid S3 credential issues
            source.source_type = "BigQuery"
            source.save()

        self.test_tables[table_key] = table_info
        self._cleanup_functions.append(cleanup_fn)

        return table_info

    def _create_source_map(self, **overrides) -> Mock:
        """Create a mock source map with sensible defaults."""
        defaults = {
            "campaign": "campaign_name",
            "source": "source_name",
            "cost": "spend",
            "date": "date",
            "impressions": "impressions",
            "clicks": "clicks",
            "currency": "currency",
        }
        defaults.update(overrides)

        source_map = Mock(spec=SourceMap)
        for key, value in defaults.items():
            setattr(source_map, key, value)
        return source_map

    def _create_basic_query(self, **overrides) -> MarketingAnalyticsTableQuery:
        """Create a basic marketing analytics query."""
        defaults = {
            "dateRange": DateRange(date_from=TEST_DATE_FROM, date_to=TEST_DATE_TO),
            "limit": DEFAULT_LIMIT,
            "offset": 0,
            "select": None,
            "orderBy": None,
            "draftConversionGoal": None,
            "properties": [],
        }
        defaults.update(overrides)
        return MarketingAnalyticsTableQuery(**defaults)

    def _setup_team_source_configs(self, configs: list[dict[str, Any]]):
        """Set up team marketing analytics source configurations."""
        config = self.team.marketing_analytics_config
        sources_map = {}

        for source_config in configs:
            table_id = str(source_config["table_id"])
            source_map = source_config["source_map"]
            sources_map[table_id] = source_map

        config.sources_map = sources_map
        config.save()

    def _calculate_cpc(self, cost: float, clicks: int) -> float:
        """Calculate Cost Per Click."""
        return cost / clicks if clicks > 0 else 0

    def _calculate_cpm(self, cost: float, impressions: int) -> float:
        """Calculate Cost Per Mille (thousand impressions)."""
        return (cost / impressions) * 1000 if impressions > 0 else 0

    def _calculate_ctr(self, clicks: int, impressions: int) -> float:
        """Calculate Click Through Rate."""
        return (clicks / impressions) * 100 if impressions > 0 else 0

    def test_basic_query_runner_initialization(self):
        query = self._create_basic_query()
        runner = get_default_query_runner(query, self.team)

        assert runner.query == query
        assert runner.team == self.team
        assert runner.query_date_range is not None
        assert runner.paginator is not None

    def test_basic_query_execution_no_sources(self):
        query = self._create_basic_query()
        runner = get_default_query_runner(query, self.team)

        response = runner.calculate()

        assert isinstance(response, MarketingAnalyticsTableQueryResponse)
        assert response.results is not None
        assert len(response.results) == 0
        assert response.hasMore is False

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_facebook_ads_single_source_execution(self):
        """Test Facebook Ads single source execution with real data."""
        facebook_info = self._setup_csv_table("facebook_ads")

        source_configs = [
            {
                "table_id": facebook_info.table.id,
                "source_map": FACEBOOK_SOURCE_MAP,
            }
        ]
        self._setup_team_source_configs(source_configs)

        query = self._create_basic_query()
        runner = get_default_query_runner(query, self.team)

        response = runner.calculate()

        assert isinstance(response, MarketingAnalyticsTableQueryResponse)
        assert response.results is not None
        assert len(response.results) == 5, f"Expected 5 campaigns from CSV, got {len(response.results)}"

        total_cost = sum(float(row[2].value or 0) for row in response.results)
        total_clicks = sum(int(row[3].value or 0) for row in response.results)
        total_impressions = sum(int(row[4].value or 0) for row in response.results)

        assert round(total_cost, 2) == 18.66, f"Expected cost $18.66, got ${total_cost}"
        assert total_impressions == 1676, f"Expected {1676} impressions, got {total_impressions}"
        assert total_clicks == 12, f"Expected {12} clicks, got {total_clicks}"

        overall_cpc = self._calculate_cpc(total_cost, total_clicks)
        overall_cpm = self._calculate_cpm(total_cost, total_impressions)
        overall_ctr = self._calculate_ctr(total_clicks, total_impressions)

        assert round(overall_cpc, 3) == 1.555, f"Expected CPC $1.555, got ${round(overall_cpc, 3)}"
        assert round(overall_cpm, 2) == 11.13, f"Expected CPM $11.13, got ${round(overall_cpm, 2)}"
        assert round(overall_ctr, 3) == 0.716, f"Expected CTR 0.716%, got {round(overall_ctr, 3)}%"

        assert pretty_print_in_tests(response.hogql, self.team.pk) == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_facebook_only_multi_source_execution(self):
        """Test query runner with only Facebook source."""
        facebook_info = self._setup_csv_table("facebook_ads")

        source_configs = [
            {
                "table_id": facebook_info.table.id,
                "source_map": FACEBOOK_SOURCE_MAP,
            }
        ]
        self._setup_team_source_configs(source_configs)

        query = self._create_basic_query()
        runner = get_default_query_runner(query, self.team)

        response = runner.calculate()

        assert isinstance(response, MarketingAnalyticsTableQueryResponse)
        assert response.results is not None
        assert len(response.results) == 5, f"Expected 5 Facebook campaigns, got {len(response.results)}"

        # Verify all results are from Facebook
        sources = [row[1].value for row in response.results]
        assert all(source == "Facebook Ads" for source in sources), f"Expected all Facebook sources, got {sources}"

        total_cost = sum(float(row[2].value or 0) for row in response.results)
        total_clicks = sum(int(row[3].value or 0) for row in response.results)
        total_impressions = sum(int(row[4].value or 0) for row in response.results)

        assert round(total_cost, 2) == 18.66, f"Expected Facebook cost $18.66, got ${total_cost}"
        assert total_impressions == 1676, f"Expected Facebook impressions 1676, got {total_impressions}"
        assert total_clicks == 12, f"Expected Facebook clicks 12, got {total_clicks}"

        assert pretty_print_in_tests(response.hogql, self.team.pk) == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_multi_source_business_metrics_validation(self):
        """Test business metrics validation across multiple sources."""
        facebook_info = self._setup_csv_table("facebook_ads")
        tiktok_info = self._setup_csv_table("tiktok_ads")
        linkedin_info = self._setup_csv_table("linkedin_ads")

        source_configs = [
            {
                "table_id": facebook_info.table.id,
                "source_map": FACEBOOK_SOURCE_MAP,
            },
            {
                "table_id": tiktok_info.table.id,
                "source_map": TIKTOK_SOURCE_MAP,
            },
            {
                "table_id": linkedin_info.table.id,
                "source_map": LINKEDIN_SOURCE_MAP,
            },
        ]
        self._setup_team_source_configs(source_configs)

        query = self._create_basic_query()
        runner = get_default_query_runner(query, self.team)

        response = runner.calculate()
        assert {
            "response": response.results,
            "query": pretty_print_in_tests(response.hogql, self.team.pk),
        } == self.snapshot

    def test_cost_efficiency_analysis(self):
        facebook_info = self._setup_csv_table("facebook_ads")
        tiktok_info = self._setup_csv_table("tiktok_ads")
        linkedin_info = self._setup_csv_table("linkedin_ads")

        source_configs = [
            {
                "table_id": facebook_info.table.id,
                "source_map": FACEBOOK_SOURCE_MAP,
            },
            {
                "table_id": tiktok_info.table.id,
                "source_map": TIKTOK_SOURCE_MAP,
            },
            {
                "table_id": linkedin_info.table.id,
                "source_map": LINKEDIN_SOURCE_MAP,
            },
        ]
        self._setup_team_source_configs(source_configs)

        query = self._create_basic_query(orderBy=[["Total Clicks", "DESC"]])
        runner = get_default_query_runner(query, self.team)

        response = runner.calculate()

        source_efficiency = {}
        for row in response.results:
            source = row[1].value
            cost = float(row[2].value or 0)
            clicks = int(row[3].value or 0)
            impressions = int(row[4].value or 0)

            if source not in source_efficiency:
                source_efficiency[source] = {
                    "campaigns": [],
                    "total_cost": 0,
                    "total_clicks": 0,
                    "total_impressions": 0,
                }

            source_efficiency[source]["campaigns"].append(
                {
                    "campaign": row[0].value,
                    "cost": cost,
                    "clicks": clicks,
                    "impressions": impressions,
                    "cpc": self._calculate_cpc(cost, clicks),
                    "cpm": self._calculate_cpm(cost, impressions),
                    "ctr": self._calculate_ctr(clicks, impressions),
                }
            )

            source_efficiency[source]["total_cost"] += cost
            source_efficiency[source]["total_clicks"] += clicks
            source_efficiency[source]["total_impressions"] += impressions

        for source, data in source_efficiency.items():
            campaigns_with_clicks = [c for c in data["campaigns"] if c["clicks"] > 0]
            if source == "Facebook Ads":
                assert (
                    len(campaigns_with_clicks) == 4
                ), f"Expected 4 Facebook campaigns with clicks, got {len(campaigns_with_clicks)}"
            elif source == "TikTok Ads":
                assert (
                    len(campaigns_with_clicks) == 4
                ), f"Expected 4 TikTok campaigns with clicks, got {len(campaigns_with_clicks)}"
            elif source == "LinkedIn Ads":
                assert (
                    len(campaigns_with_clicks) == 8
                ), f"Expected 8 LinkedIn campaigns with clicks, got {len(campaigns_with_clicks)}"

            best_cpc_campaign = min(campaigns_with_clicks, key=lambda x: x["cpc"])
            worst_cpc_campaign = max(campaigns_with_clicks, key=lambda x: x["cpc"])

            assert best_cpc_campaign["cpc"] <= worst_cpc_campaign["cpc"], f"{source} best CPC should be <= worst CPC"

    def test_zero_cost_campaigns_handling(self):
        tiktok_info = self._setup_csv_table("tiktok_ads")

        source_configs = [
            {
                "table_id": tiktok_info.table.id,
                "source_map": TIKTOK_SOURCE_MAP,
            }
        ]
        self._setup_team_source_configs(source_configs)

        query = self._create_basic_query()
        runner = get_default_query_runner(query, self.team)

        response = runner.calculate()

        zero_cost_campaigns = [row for row in response.results if float(row[2].value or 0) == 0]
        paid_campaigns = [row for row in response.results if float(row[2].value or 0) != 0]

        assert len(zero_cost_campaigns) == 5, f"Expected 5 zero-cost campaigns, got {len(zero_cost_campaigns)}"
        assert len(paid_campaigns) == 4, f"Expected 4 paid campaigns, got {len(paid_campaigns)}"

        # Check total impressions and clicks for zero-cost campaigns
        total_zero_total_impressions = sum(int(row[4].value or 0) for row in zero_cost_campaigns)
        total_zero_total_clicks = sum(int(row[3].value or 0) for row in zero_cost_campaigns)

        assert (
            total_zero_total_impressions == 56
        ), f"Expected 56 total impressions for zero-cost campaigns, got {total_zero_total_impressions}"
        assert (
            total_zero_total_clicks == 0
        ), f"Expected 0 total clicks for zero-cost campaigns, got {total_zero_total_clicks}"

    def test_pagination_basic(self):
        linkedin_info = self._setup_csv_table("linkedin_ads")

        source_configs = [
            {
                "table_id": linkedin_info.table.id,
                "source_map": LINKEDIN_SOURCE_MAP,
            }
        ]
        self._setup_team_source_configs(source_configs)

        query = self._create_basic_query(limit=5, offset=0)
        runner = get_default_query_runner(query, self.team)

        response = runner.calculate()

        assert len(response.results) == 5, "Should return exactly 5 results"
        assert response.hasMore is True, "Should have more results available"
        assert response.limit == 5, "Limit should be 5"
        assert response.offset == 0, "Offset should be 0"

        query_page2 = self._create_basic_query(limit=5, offset=5)
        runner_page2 = MarketingAnalyticsTableQueryRunner(
            query=query_page2,
            team=self.team,
            timings=None,
            modifiers=None,
            limit_context=None,
        )

        response_page2 = runner_page2.calculate()

        assert len(response_page2.results) == 4, "Page 2 should return exactly 4 results"
        assert response_page2.offset == 5, "Page 2 offset should be 5"

        page1_campaigns = [row[0].value for row in response.results]
        page2_campaigns = [row[0].value for row in response_page2.results]

        assert set(page1_campaigns).isdisjoint(
            set(page2_campaigns)
        ), "Page 1 and Page 2 should have different campaigns"

    def test_pagination_edge_cases(self):
        facebook_info = self._setup_csv_table("facebook_ads")

        source_configs = [
            {
                "table_id": facebook_info.table.id,
                "source_map": FACEBOOK_SOURCE_MAP,
            }
        ]
        self._setup_team_source_configs(source_configs)

        query = self._create_basic_query(limit=1000, offset=0)
        runner = get_default_query_runner(query, self.team)

        response = runner.calculate()

        assert len(response.results) == 5, "Should return exactly 5 Facebook campaigns"
        assert response.hasMore is False, "Should not have more results when limit exceeds data"

        query_beyond = self._create_basic_query(limit=10, offset=1000)
        runner_beyond = MarketingAnalyticsTableQueryRunner(
            query=query_beyond,
            team=self.team,
            timings=None,
            modifiers=None,
            limit_context=None,
        )

        response_beyond = runner_beyond.calculate()

        assert len(response_beyond.results) == 0, "Should return empty results when offset exceeds data"
        assert response_beyond.hasMore is False, "Should not have more results when offset exceeds data"

    def test_date_range_filtering(self):
        facebook_info = self._setup_csv_table("facebook_ads")

        source_configs = [
            {
                "table_id": facebook_info.table.id,
                "source_map": FACEBOOK_SOURCE_MAP,
            }
        ]
        self._setup_team_source_configs(source_configs)

        query = self._create_basic_query(dateRange=DateRange(date_from="2024-12-01", date_to="2024-12-31"))
        runner = get_default_query_runner(query, self.team)

        response = runner.calculate()

        assert len(response.results) == 4, "Should have 4 Facebook campaigns in December 2024"

        query_narrow = self._create_basic_query(dateRange=DateRange(date_from="2024-12-15", date_to="2024-12-15"))
        runner_narrow = MarketingAnalyticsTableQueryRunner(
            query=query_narrow,
            team=self.team,
            timings=None,
            modifiers=None,
            limit_context=None,
        )

        response_narrow = runner_narrow.calculate()

        assert len(response_narrow.results) == 1, "Should have exactly 1 campaign from Dec 15"
        actual_campaigns = [row[0].value for row in response_narrow.results]
        expected_campaigns = ["test_brand_campaign"]
        assert any(
            campaign in expected_campaigns for campaign in actual_campaigns
        ), "Should have expected campaigns from Dec 15"

    def test_invalid_table_configuration(self):
        source_configs = [
            {
                "table_id": 99999,
                "source_map": FACEBOOK_SOURCE_MAP,
            }
        ]
        self._setup_team_source_configs(source_configs)

        query = self._create_basic_query()
        runner = get_default_query_runner(query, self.team)

        response = runner.calculate()

        assert isinstance(response, MarketingAnalyticsTableQueryResponse)
        assert response.results is not None
        assert len(response.results) == 0, "Should return empty results for invalid configuration"

    def test_invalid_source_map_configuration(self):
        facebook_info = self._setup_csv_table("facebook_ads")

        source_configs = [
            {
                "table_id": facebook_info.table.id,
                "source_map": {
                    **FACEBOOK_SOURCE_MAP,
                    "campaign": "nonexistent_column",
                },
            }
        ]
        self._setup_team_source_configs(source_configs)

        query = self._create_basic_query()
        runner = get_default_query_runner(query, self.team)

        # This should raise a QueryError because the column doesn't exist
        with pytest.raises(QueryError, match="nonexistent_column"):
            runner.calculate()

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_conversion_goal_basic_setup(self):
        facebook_info = self._setup_csv_table("facebook_ads")

        source_configs = [
            {
                "table_id": facebook_info.table.id,
                "source_map": FACEBOOK_SOURCE_MAP,
            }
        ]
        self._setup_team_source_configs(source_configs)

        test_action = _create_action(self.team, "test_conversion_action")

        conversion_goal = ConversionGoalFilter2(
            kind=NodeKind.ACTIONS_NODE,
            conversion_goal_id="sign_up_goal",
            conversion_goal_name="Sign Up Conversions",
            id=str(test_action.id),
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        query = self._create_basic_query(draftConversionGoal=conversion_goal)
        runner = get_default_query_runner(query, self.team)

        response = runner.calculate()

        assert isinstance(response, MarketingAnalyticsTableQueryResponse)
        assert response.results is not None

        expected_columns = 10
        actual_columns = len(response.columns) if response.columns else 0
        assert (
            actual_columns == expected_columns
        ), f"Expected {expected_columns} columns, got {actual_columns}: {response.columns}"

        assert pretty_print_in_tests(response.hogql, self.team.pk) == self.snapshot

    def test_multiple_conversion_goals(self):
        facebook_info = self._setup_csv_table("facebook_ads")

        source_configs = [
            {
                "table_id": facebook_info.table.id,
                "source_map": FACEBOOK_SOURCE_MAP,
            }
        ]
        self._setup_team_source_configs(source_configs)

        signup_action = _create_action(self.team, "signup_action")
        purchase_action = _create_action(self.team, "purchase_action")

        team_conversion_goals = [
            {
                "name": "Signup Goal",
                "kind": NodeKind.ACTIONS_NODE,
                "conversion_goal_id": "signup_goal",
                "conversion_goal_name": "Signup Goal",
                "id": str(signup_action.id),
                "math": BaseMathType.TOTAL,
                "schema_map": {"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
            },
            {
                "name": "Purchase Goal",
                "kind": NodeKind.ACTIONS_NODE,
                "conversion_goal_id": "purchase_goal",
                "conversion_goal_name": "Purchase Goal",
                "id": str(purchase_action.id),
                "math": BaseMathType.TOTAL,
                "schema_map": {"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
            },
        ]

        config = self.team.marketing_analytics_config
        config.conversion_goals = team_conversion_goals
        config.save()

        query = self._create_basic_query()
        runner = get_default_query_runner(query, self.team)

        response = runner.calculate()

        assert isinstance(response, MarketingAnalyticsTableQueryResponse)
        assert response.results is not None
        assert len(response.columns) == 12, "Should have 12 columns including multiple conversion goal columns"

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_comprehensive_marketing_analytics_basic(self):
        facebook_info = self._setup_csv_table("facebook_ads")

        source_configs = [
            {
                "table_id": facebook_info.table.id,
                "source_map": FACEBOOK_SOURCE_MAP,
            }
        ]

        config = self.team.marketing_analytics_config

        sources_map = {}
        for source_config in source_configs:
            table_id = str(source_config["table_id"])
            source_map = source_config["source_map"]
            sources_map[table_id] = source_map

        config.sources_map = sources_map
        config.save()

        query = MarketingAnalyticsTableQuery(
            dateRange={"date_from": "2024-11-01", "date_to": "2024-11-30"},
            limit=100,
            offset=0,
            orderBy=[["Total Cost", "DESC"]],
            properties=[],
        )

        runner = get_default_query_runner(query, self.team)
        response = runner.calculate()

        assert isinstance(response, MarketingAnalyticsTableQueryResponse)
        assert response.results is not None
        assert len(response.results) == 3, "Should have 3 Facebook campaigns in November 2024"

        sources = [row[1].value for row in response.results]
        assert all(source == "Facebook Ads" for source in sources), "All sources should be Facebook Ads"

        total_cost = sum(float(row[2].value or 0) for row in response.results)
        total_clicks = sum(int(row[3].value or 0) for row in response.results)
        total_impressions = sum(int(row[4].value or 0) for row in response.results)

        assert round(total_cost, 2) == 8.40, f"Expected cost $8.40, got ${total_cost}"
        assert total_clicks == 4, f"Expected 4 clicks, got {total_clicks}"
        assert total_impressions == 546, f"Expected 546 impressions, got {total_impressions}"

        assert pretty_print_in_tests(response.hogql, self.team.pk) == self.snapshot

    def test_query_performance_single_source(self):
        linkedin_info = self._setup_csv_table("linkedin_ads")

        source_configs = [
            {
                "table_id": linkedin_info.table.id,
                "source_map": LINKEDIN_SOURCE_MAP,
            }
        ]
        self._setup_team_source_configs(source_configs)

        query = self._create_basic_query()
        runner = get_default_query_runner(query, self.team)

        response = runner.calculate()

        assert isinstance(response, MarketingAnalyticsTableQueryResponse)
        assert len(response.results) == 9, "Should return exactly 9 LinkedIn campaigns"

    def test_query_performance_multi_source(self):
        facebook_info = self._setup_csv_table("facebook_ads")
        tiktok_info = self._setup_csv_table("tiktok_ads")
        linkedin_info = self._setup_csv_table("linkedin_ads")

        source_configs = [
            {
                "table_id": facebook_info.table.id,
                "source_map": FACEBOOK_SOURCE_MAP,
            },
            {
                "table_id": tiktok_info.table.id,
                "source_map": TIKTOK_SOURCE_MAP,
            },
            {
                "table_id": linkedin_info.table.id,
                "source_map": LINKEDIN_SOURCE_MAP,
            },
        ]
        self._setup_team_source_configs(source_configs)

        query = self._create_basic_query()
        runner = get_default_query_runner(query, self.team)

        response = runner.calculate()

        assert isinstance(response, MarketingAnalyticsTableQueryResponse)
        assert len(response.results) == 23, "Should return exactly 23 total campaigns"


# Standalone parametrized test that works with pytest
@pytest.mark.django_db
@pytest.mark.parametrize(
    "test_name,order_by,expected_sort_reverse",
    [
        ("cost", [["Cost", "DESC"]], True),
        ("clicks", [["Clicks", "DESC"]], True),
        ("impressions", [["Impressions", "DESC"]], True),
        ("campaign", [["Campaign", "ASC"]], False),
    ],
)
def test_campaign_performance_ranking(test_name, order_by, expected_sort_reverse):
    """Test campaign performance ranking with different ordering scenarios using pytest parametrize."""
    # Create test instance to access helper methods
    test_instance = TestMarketingAnalyticsTableQueryRunnerBusiness()
    test_instance.setUpClass()
    test_instance.setUp()

    try:
        facebook_info = test_instance._setup_csv_table("facebook_ads")

        source_configs = [
            {
                "table_id": facebook_info.table.id,
                "source_map": FACEBOOK_SOURCE_MAP,
            }
        ]
        test_instance._setup_team_source_configs(source_configs)

        query = test_instance._create_basic_query(orderBy=order_by)
        runner = get_default_query_runner(query, test_instance.team)

        response = runner.calculate()

        assert len(response.results) == 5, f"Should have 5 Facebook campaigns for {test_name} ordering"

        # Extract values based on test_name
        values: list[float | int | str]
        if test_name == "cost":
            values = [float(row[2].value or 0) for row in response.results]
        elif test_name == "clicks":
            values = [int(row[3].value or 0) for row in response.results]
        elif test_name == "impressions":
            values = [int(row[4].value or 0) for row in response.results]
        elif test_name == "campaign":
            values = [str(row[0].value) for row in response.results]
        else:
            raise ValueError(f"Unknown test_name: {test_name}")

        # Verify ordering
        expected_values = sorted(values, reverse=expected_sort_reverse)
        assert (
            values == expected_values
        ), f"{test_name} should be in {'descending' if expected_sort_reverse else 'ascending'} order. Got {values}, expected {expected_values}"
    finally:
        test_instance.tearDown()
        test_instance.tearDownClass()
