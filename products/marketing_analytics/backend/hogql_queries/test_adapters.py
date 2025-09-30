import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Union

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import Mock, patch

from posthog.schema import DateRange, SourceMap

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.test.utils import pretty_print_in_tests

from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.team.team import DEFAULT_CURRENCY
from posthog.warehouse.models import DataWarehouseTable, ExternalDataSource
from posthog.warehouse.models.credential import DataWarehouseCredential
from posthog.warehouse.test.utils import create_data_warehouse_table_from_csv

from products.marketing_analytics.backend.hogql_queries.adapters.base import (
    ExternalConfig,
    GoogleAdsConfig,
    LinkedinAdsConfig,
    MetaAdsConfig,
    QueryContext,
    RedditAdsConfig,
)
from products.marketing_analytics.backend.hogql_queries.adapters.bigquery import BigQueryAdapter
from products.marketing_analytics.backend.hogql_queries.adapters.google_ads import GoogleAdsAdapter
from products.marketing_analytics.backend.hogql_queries.adapters.linkedin_ads import LinkedinAdsAdapter
from products.marketing_analytics.backend.hogql_queries.adapters.meta_ads import MetaAdsAdapter
from products.marketing_analytics.backend.hogql_queries.adapters.reddit_ads import RedditAdsAdapter
from products.marketing_analytics.backend.hogql_queries.adapters.self_managed import (
    AWSAdapter,
    AzureAdapter,
    CloudflareR2Adapter,
    GoogleCloudAdapter,
)

# Test Constants
TEST_DATE_FROM = "2024-01-01"
TEST_DATE_TO = "2024-12-31"
TEST_BUCKET_BASE = "test_storage_bucket-posthog.marketing_analytics"
EXPECTED_COLUMN_COUNT = 6
EXPECTED_COLUMN_ALIASES = ["campaign", "source", "impressions", "clicks", "cost", "reported_conversion"]


logger = logging.getLogger(__name__)


@dataclass
class TableInfo:
    """Information about a test table created from CSV data."""

    table: DataWarehouseTable
    source: ExternalDataSource
    credential: DataWarehouseCredential
    platform: str
    source_type: str
    cleanup_fn: callable


@dataclass
class DataConfig:
    """Configuration for test data sources."""

    csv_filename: str
    table_name: str
    platform: str
    source_type: str
    bucket_suffix: str
    column_schema: dict[str, dict[str, Union[str, bool]]]


class TestMarketingAnalyticsAdapters(ClickhouseTestMixin, BaseTest):
    """
    Production-ready test suite for Marketing Analytics Adapters.

    This test suite covers:
    - Adapter validation (error conditions and success cases)
    - SQL query generation with snapshot testing
    - Real data execution with CSV-backed tables
    - UNION compatibility across different adapters
    - Error handling and edge cases

    Test Structure:
    - Unit tests for individual adapter validation
    - Integration tests for query generation
    - End-to-end tests with real data execution
    - Performance and compatibility tests
    """

    maxDiff = None
    CLASS_DATA_LEVEL_SETUP = False

    @classmethod
    def setUpClass(cls):
        """Set up test data configurations."""
        super().setUpClass()
        cls.test_data_configs = {
            "bigquery": DataConfig(
                csv_filename="test/external/bigquery.csv",
                table_name="bigquery_marketing_table",
                platform="Facebook Ads",
                source_type="BigQuery",
                bucket_suffix="bigquery",
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
            "google_campaign": DataConfig(
                csv_filename="test/google_ads/campaign.csv",
                table_name="google_ads_campaign_table",
                platform="Google Ads",
                source_type="GoogleAds",
                bucket_suffix="google_campaign",
                column_schema={
                    "campaign_id": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "campaign_name": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "campaign_status": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                },
            ),
            "google_stats": DataConfig(
                csv_filename="test/google_ads/campaign_stats.csv",
                table_name="google_ads_stats_table",
                platform="Google Ads",
                source_type="GoogleAds",
                bucket_suffix="google_stats",
                column_schema={
                    "campaign_id": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "segments_date": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "metrics_clicks": {"hogql": "FloatDatabaseField", "clickhouse": "Float64", "schema_valid": True},
                    "metrics_cost_micros": {
                        "hogql": "FloatDatabaseField",
                        "clickhouse": "Float64",
                        "schema_valid": True,
                    },
                    "metrics_impressions": {
                        "hogql": "FloatDatabaseField",
                        "clickhouse": "Float64",
                        "schema_valid": True,
                    },
                    "metrics_conversions": {
                        "hogql": "FloatDatabaseField",
                        "clickhouse": "Float64",
                        "schema_valid": True,
                    },
                },
            ),
            "linkedin_campaigns": DataConfig(
                csv_filename="test/linkedin_ads/campaigns.csv",
                table_name="linkedin_campaigns_table",
                platform="LinkedIn Ads",
                source_type="LinkedinAds",
                bucket_suffix="linkedin_campaigns",
                column_schema={
                    "id": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "name": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "type": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "locale": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "status": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "account": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "version": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "cost_type": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "unit_cost": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "account_id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "schema_valid": True},
                    "created_time": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "daily_budget": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "run_schedule": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "campaign_group": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "campaign_group_id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "schema_valid": True},
                    "last_modified_time": {
                        "hogql": "StringDatabaseField",
                        "clickhouse": "String",
                        "schema_valid": True,
                    },
                    "targeting_criteria": {
                        "hogql": "StringDatabaseField",
                        "clickhouse": "String",
                        "schema_valid": True,
                    },
                    "change_audit_stamps": {
                        "hogql": "StringDatabaseField",
                        "clickhouse": "String",
                        "schema_valid": True,
                    },
                },
            ),
            "linkedin_stats": DataConfig(
                csv_filename="test/linkedin_ads/campaign_stats.csv",
                table_name="linkedin_campaign_stats_table",
                platform="LinkedIn Ads",
                source_type="LinkedinAds",
                bucket_suffix="linkedin_stats",
                column_schema={
                    "clicks": {"hogql": "FloatDatabaseField", "clickhouse": "Float64", "schema_valid": True},
                    "follows": {"hogql": "FloatDatabaseField", "clickhouse": "Float64", "schema_valid": True},
                    "date_end": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "date_range": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "date_start": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "campaign_id": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "cost_in_usd": {"hogql": "FloatDatabaseField", "clickhouse": "Float64", "schema_valid": True},
                    "impressions": {"hogql": "FloatDatabaseField", "clickhouse": "Float64", "schema_valid": True},
                    "video_views": {"hogql": "FloatDatabaseField", "clickhouse": "Float64", "schema_valid": True},
                    "pivot_values": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "one_click_leads": {"hogql": "FloatDatabaseField", "clickhouse": "Float64", "schema_valid": True},
                    "total_engagements": {"hogql": "FloatDatabaseField", "clickhouse": "Float64", "schema_valid": True},
                    "video_completions": {"hogql": "FloatDatabaseField", "clickhouse": "Float64", "schema_valid": True},
                    "landing_page_clicks": {
                        "hogql": "FloatDatabaseField",
                        "clickhouse": "Float64",
                        "schema_valid": True,
                    },
                    "external_website_conversions": {
                        "hogql": "FloatDatabaseField",
                        "clickhouse": "Float64",
                        "schema_valid": True,
                    },
                },
            ),
            "reddit_campaign": DataConfig(
                csv_filename="test/reddit/campaigns.csv",
                table_name="reddit_campaigns_table",
                platform="Reddit Ads",
                source_type="RedditAds",
                bucket_suffix="reddit_campaign",
                column_schema={
                    "id": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "name": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "app_id": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "goal_type": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "objective": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "spend_cap": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "created_at": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "goal_value": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "modified_at": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "ad_account_id": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "age_restriction": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "effective_status": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "configured_status": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "skadnetwork_metadata": {
                        "hogql": "StringDatabaseField",
                        "clickhouse": "String",
                        "schema_valid": True,
                    },
                    "funding_instrument_id": {
                        "hogql": "StringDatabaseField",
                        "clickhouse": "String",
                        "schema_valid": True,
                    },
                    "special_ad_categories": {
                        "hogql": "StringDatabaseField",
                        "clickhouse": "String",
                        "schema_valid": True,
                    },
                },
            ),
            "reddit_stats": DataConfig(
                csv_filename="test/reddit/campaign_report.csv",
                table_name="reddit_campaign_report_table",
                platform="Reddit Ads",
                source_type="RedditAds",
                bucket_suffix="reddit_stats",
                column_schema={
                    "cpc": {"hogql": "FloatDatabaseField", "clickhouse": "Float64", "schema_valid": True},
                    "ctr": {"hogql": "FloatDatabaseField", "clickhouse": "Float64", "schema_valid": True},
                    "date": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "ecpm": {"hogql": "FloatDatabaseField", "clickhouse": "Float64", "schema_valid": True},
                    "hour": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "reach": {"hogql": "FloatDatabaseField", "clickhouse": "Float64", "schema_valid": True},
                    "spend": {"hogql": "FloatDatabaseField", "clickhouse": "Float64", "schema_valid": True},
                    "clicks": {"hogql": "FloatDatabaseField", "clickhouse": "Float64", "schema_valid": True},
                    "currency": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "frequency": {"hogql": "FloatDatabaseField", "clickhouse": "Float64", "schema_valid": True},
                    "campaign_id": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "impressions": {"hogql": "FloatDatabaseField", "clickhouse": "Float64", "schema_valid": True},
                    "video_started": {"hogql": "FloatDatabaseField", "clickhouse": "Float64", "schema_valid": True},
                    "conversion_roas": {"hogql": "FloatDatabaseField", "clickhouse": "Float64", "schema_valid": True},
                    "video_view_rate": {"hogql": "FloatDatabaseField", "clickhouse": "Float64", "schema_valid": True},
                    "app_install_revenue": {
                        "hogql": "FloatDatabaseField",
                        "clickhouse": "Float64",
                        "schema_valid": True,
                    },
                    "key_conversion_rate": {
                        "hogql": "FloatDatabaseField",
                        "clickhouse": "Float64",
                        "schema_valid": True,
                    },
                    "video_completion_rate": {
                        "hogql": "FloatDatabaseField",
                        "clickhouse": "Float64",
                        "schema_valid": True,
                    },
                    "app_install_roas_double": {
                        "hogql": "FloatDatabaseField",
                        "clickhouse": "Float64",
                        "schema_valid": True,
                    },
                    "conversion_sign_up_views": {
                        "hogql": "FloatDatabaseField",
                        "clickhouse": "Float64",
                        "schema_valid": True,
                    },
                    "video_watched_25_percent": {
                        "hogql": "FloatDatabaseField",
                        "clickhouse": "Float64",
                        "schema_valid": True,
                    },
                    "video_watched_50_percent": {
                        "hogql": "FloatDatabaseField",
                        "clickhouse": "Float64",
                        "schema_valid": True,
                    },
                    "video_watched_75_percent": {
                        "hogql": "FloatDatabaseField",
                        "clickhouse": "Float64",
                        "schema_valid": True,
                    },
                    "app_install_install_count": {
                        "hogql": "FloatDatabaseField",
                        "clickhouse": "Float64",
                        "schema_valid": True,
                    },
                    "video_watched_100_percent": {
                        "hogql": "FloatDatabaseField",
                        "clickhouse": "Float64",
                        "schema_valid": True,
                    },
                    "app_install_purchase_count": {
                        "hogql": "FloatDatabaseField",
                        "clickhouse": "Float64",
                        "schema_valid": True,
                    },
                    "key_conversion_total_count": {
                        "hogql": "FloatDatabaseField",
                        "clickhouse": "Float64",
                        "schema_valid": True,
                    },
                    "video_viewable_impressions": {
                        "hogql": "FloatDatabaseField",
                        "clickhouse": "Float64",
                        "schema_valid": True,
                    },
                    "conversion_signup_total_value": {
                        "hogql": "FloatDatabaseField",
                        "clickhouse": "Float64",
                        "schema_valid": True,
                    },
                    "conversion_purchase_total_items": {
                        "hogql": "FloatDatabaseField",
                        "clickhouse": "Float64",
                        "schema_valid": True,
                    },
                    "conversion_purchase_total_value": {
                        "hogql": "FloatDatabaseField",
                        "clickhouse": "Float64",
                        "schema_valid": True,
                    },
                },
            ),
            "s3": DataConfig(
                csv_filename="test/self_managed/s3.csv",
                table_name="s3_marketing_table",
                platform="TikTok",
                source_type="AWS",
                bucket_suffix="s3",
                column_schema={
                    "campaign2": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "spend2": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "date2": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "impressions2": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "clicks2": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "source2": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                },
            ),
            "gcs": DataConfig(
                csv_filename="test/self_managed/gcs.csv",
                table_name="gcs_marketing_table",
                platform="LinkedIn",
                source_type="google_cloud",
                bucket_suffix="gcs",
                column_schema={
                    "campaign3": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "spend3": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "date3": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "impressions3": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "clicks3": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "source3": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                },
            ),
            "meta_campaigns": DataConfig(
                csv_filename="test/meta_ads/campaigns.csv",
                table_name="metaads_campaigns",
                platform="Meta Ads",
                source_type="MetaAds",
                bucket_suffix="meta_campaigns",
                column_schema={
                    "id": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "account_id": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "name": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "status": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "effective_status": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "configured_status": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "objective": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "buying_type": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "budget_remaining": {"hogql": "FloatDatabaseField", "clickhouse": "Float64", "schema_valid": True},
                    "start_time": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "stop_time": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "created_time": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "updated_time": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "special_ad_categories": {
                        "hogql": "StringDatabaseField",
                        "clickhouse": "String",
                        "schema_valid": True,
                    },
                },
            ),
            "meta_campaign_stats": DataConfig(
                csv_filename="test/meta_ads/campaign_stats.csv",
                table_name="metaads_campaign_stats",
                platform="Meta Ads",
                source_type="MetaAds",
                bucket_suffix="meta_campaign_stats",
                column_schema={
                    "account_id": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "campaign_id": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "date_start": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "date_stop": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "impressions": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "schema_valid": True},
                    "clicks": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "schema_valid": True},
                    "unique_clicks": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "schema_valid": True},
                    "reach": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "schema_valid": True},
                    "frequency": {"hogql": "FloatDatabaseField", "clickhouse": "Float64", "schema_valid": True},
                    "spend": {"hogql": "FloatDatabaseField", "clickhouse": "Float64", "schema_valid": True},
                    "cpm": {"hogql": "FloatDatabaseField", "clickhouse": "Float64", "schema_valid": True},
                    "cpc": {"hogql": "FloatDatabaseField", "clickhouse": "Float64", "schema_valid": True},
                    "ctr": {"hogql": "FloatDatabaseField", "clickhouse": "Float64", "schema_valid": True},
                    "cpp": {"hogql": "FloatDatabaseField", "clickhouse": "Float64", "schema_valid": True},
                    "unique_ctr": {"hogql": "FloatDatabaseField", "clickhouse": "Float64", "schema_valid": True},
                    "cost_per_unique_click": {
                        "hogql": "FloatDatabaseField",
                        "clickhouse": "Float64",
                        "schema_valid": True,
                    },
                    "actions": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                    "cost_per_action_type": {
                        "hogql": "StringDatabaseField",
                        "clickhouse": "String",
                        "schema_valid": True,
                    },
                },
            ),
        }

    def setUp(self):
        """Set up test context and minimal required data."""
        super().setUp()
        self.context = self._create_test_context()
        self.test_tables: dict[str, TableInfo] = {}
        self._cleanup_functions: list[callable] = []

    def tearDown(self):
        """Clean up all test resources."""
        for cleanup_fn in self._cleanup_functions:
            try:
                cleanup_fn()
            except Exception as e:
                logger.warning(f"Failed to cleanup test resource: {e}")
        self._cleanup_functions.clear()
        self.test_tables.clear()
        super().tearDown()

    def _create_test_context(self) -> QueryContext:
        """Create a standard test context."""
        date_range_obj = DateRange(date_from=TEST_DATE_FROM, date_to=TEST_DATE_TO)
        date_range = QueryDateRange(
            date_range=date_range_obj,
            team=self.team,
            interval=None,
            now=datetime.now(),
        )
        return QueryContext(
            date_range=date_range,
            team=self.team,
            base_currency=DEFAULT_CURRENCY,
        )

    def _setup_csv_table(self, table_key: str) -> TableInfo:
        """
        Set up a single CSV-backed table for testing.

        Args:
            table_key: Key from test_data_configs

        Returns:
            TableInfo with table details

        Raises:
            AssertionError: If CSV file doesn't exist
            ValueError: If table_key is invalid
        """
        if table_key not in self.test_data_configs:
            raise ValueError(f"Invalid table key: {table_key}")

        if table_key in self.test_tables:
            return self.test_tables[table_key]

        config = self.test_data_configs[table_key]
        csv_path = Path(__file__).parent / config.csv_filename

        if not csv_path.exists():
            raise AssertionError(f"CSV file must exist at {csv_path}")

        columns = config.column_schema
        logger.info(f"Setting up table {config.table_name} with columns: {list(columns.keys())}")

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

        self.test_tables[table_key] = table_info
        self._cleanup_functions.append(cleanup_fn)

        logger.info(f"Created table {config.table_name} with {len(csv_df)} rows")
        return table_info

    def _create_mock_table(self, name: str, source_type: str) -> Mock:
        """Create a mock table with consistent structure."""
        table = Mock(spec=DataWarehouseTable)
        table.name = name
        table.external_data_source = Mock(spec=ExternalDataSource)
        table.external_data_source.source_type = source_type

        return table

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
            "reported_conversion": "conversions",
        }
        defaults.update(overrides)

        source_map = Mock(spec=SourceMap)
        for key, value in defaults.items():
            setattr(source_map, key, value)
        return source_map

    def _execute_and_snapshot(self, query: ast.SelectQuery | ast.SelectSetQuery) -> str:
        """Convert AST to HogQL and create snapshot."""
        query_string = query.to_hogql()
        return pretty_print_in_tests(query_string, self.team.pk)

    def _validate_query_structure(self, query: ast.SelectQuery, adapter_name: str):
        """Validate that a query has the expected structure."""
        assert query is not None, f"{adapter_name} failed to generate query"
        assert isinstance(query, ast.SelectQuery), f"{adapter_name} should return SelectQuery"
        assert len(query.select) == EXPECTED_COLUMN_COUNT, f"{adapter_name} should have {EXPECTED_COLUMN_COUNT} columns"

        actual_aliases = [col.alias for col in query.select if hasattr(col, "alias")]
        assert actual_aliases == EXPECTED_COLUMN_ALIASES, f"{adapter_name} has incorrect column aliases"

    def _execute_query_and_validate(self, query: ast.SelectQuery | ast.SelectSetQuery) -> list[tuple]:
        """Execute a query and return results with basic validation."""
        hogql_query = query.to_hogql()
        result = execute_hogql_query(hogql_query, self.team)

        assert result is not None, "Query execution should not return None"
        assert result.results is not None, "Query results should not be None"
        assert len(result.columns) == EXPECTED_COLUMN_COUNT, f"Should have {EXPECTED_COLUMN_COUNT} columns"

        return result.results

    # ================================================================
    # VALIDATION TESTS
    # ================================================================

    def test_adapter_validation_missing_required_fields(self):
        """Test that adapter validation fails when required fields are missing."""
        table = self._create_mock_table("test_table", "BigQuery")
        source_map = self._create_source_map(
            campaign="",
            source="",
            date="",
        )

        config = ExternalConfig(
            table=table,
            source_map=source_map,
            source_type="BigQuery",
            source_id="test_validation",
            schema_name="marketing_schema",
        )

        adapter = BigQueryAdapter(config=config, context=self.context)
        result = adapter.validate()

        assert not result.is_valid, "Validation should fail with missing required fields"
        assert len(result.errors) >= 3, "Should have at least 3 validation errors"
        assert all(
            "Missing required field" in error for error in result.errors
        ), "All errors should be about missing fields"

    def test_adapter_validation_success(self):
        """Test that adapter validation succeeds with all required fields."""
        table = self._create_mock_table("test_table", "BigQuery")
        source_map = self._create_source_map()

        config = ExternalConfig(
            table=table,
            source_map=source_map,
            source_type="BigQuery",
            source_id="test_validation_success",
            schema_name="marketing_schema",
        )

        adapter = BigQueryAdapter(config=config, context=self.context)
        result = adapter.validate()

        assert result.is_valid, f"Validation should succeed: {result.errors}"
        assert len(result.errors) == 0, "Should have no validation errors"

    def test_adapter_validation_with_optional_fields(self):
        """Test adapter validation with missing optional fields."""
        table = self._create_mock_table("test_table", "BigQuery")
        source_map = self._create_source_map(
            campaign="campaign_id",
            source="source_name",
            date="report_date",
            impressions=None,
            clicks=None,
            currency=None,
        )

        config = ExternalConfig(
            table=table,
            source_map=source_map,
            source_type="BigQuery",
            source_id="test_optional_fields",
            schema_name="marketing_schema",
        )

        adapter = BigQueryAdapter(config=config, context=self.context)
        result = adapter.validate()

        assert result.is_valid, "Validation should succeed with optional fields missing"

    def test_bigquery_adapter_validation_consistency(self):
        """Test BigQuery adapter validation consistency."""
        table = self._create_mock_table("test_table", "BigQuery")
        source_map = self._create_source_map()

        config = ExternalConfig(
            table=table,
            source_map=source_map,
            source_type="BigQuery",
            source_id="test_consistency",
            schema_name="marketing_schema",
        )

        adapter = BigQueryAdapter(config=config, context=self.context)
        result = adapter.validate()

        assert result.is_valid, "BigQueryAdapter validation should succeed"
        assert isinstance(result.errors, list), "BigQueryAdapter should return list of errors"

    def test_aws_adapter_validation_consistency(self):
        """Test AWS adapter validation consistency."""
        table = self._create_mock_table("test_table", "aws")
        source_map = self._create_source_map()

        config = ExternalConfig(
            table=table,
            source_map=source_map,
            source_type="aws",
            source_id="test_consistency",
            schema_name="marketing_schema",
        )

        adapter = AWSAdapter(config=config, context=self.context)
        result = adapter.validate()

        assert result.is_valid, "AWSAdapter validation should succeed"
        assert isinstance(result.errors, list), "AWSAdapter should return list of errors"

    def test_google_cloud_adapter_validation_consistency(self):
        """Test Google Cloud adapter validation consistency."""
        table = self._create_mock_table("test_table", "google_cloud")
        source_map = self._create_source_map()

        config = ExternalConfig(
            table=table,
            source_map=source_map,
            source_type="google_cloud",
            source_id="test_consistency",
            schema_name="marketing_schema",
        )

        adapter = GoogleCloudAdapter(config=config, context=self.context)
        result = adapter.validate()

        assert result.is_valid, "GoogleCloudAdapter validation should succeed"
        assert isinstance(result.errors, list), "GoogleCloudAdapter should return list of errors"

    def test_linkedin_ads_adapter_validation_consistency(self):
        """Test LinkedIn Ads adapter validation consistency."""
        campaign_table = self._create_mock_table("linkedin_campaigns_table", "linkedin_ads")
        stats_table = self._create_mock_table("linkedin_campaign_stats_table", "linkedin_ads")

        config = LinkedinAdsConfig(
            campaign_table=campaign_table,
            stats_table=stats_table,
            source_type="linkedin_ads",
            source_id="test_consistency",
        )

        adapter = LinkedinAdsAdapter(config=config, context=self.context)
        result = adapter.validate()

        assert result.is_valid, "LinkedinAdsAdapter validation should succeed"
        assert isinstance(result.errors, list), "LinkedinAdsAdapter should return list of errors"

    def test_reddit_ads_adapter_validation_consistency(self):
        """Test Reddit Ads adapter validation consistency."""
        campaign_table = self._create_mock_table("reddit_campaigns_table", "RedditAds")
        stats_table = self._create_mock_table("reddit_campaign_report_table", "RedditAds")

        config = RedditAdsConfig(
            campaign_table=campaign_table,
            stats_table=stats_table,
            source_type="RedditAds",
            source_id="test_consistency",
        )

        adapter = RedditAdsAdapter(config=config, context=self.context)
        result = adapter.validate()

        assert result.is_valid, "RedditAdsAdapter validation should succeed"
        assert isinstance(result.errors, list), "RedditAdsAdapter should return list of errors"

    def test_meta_ads_adapter_validation_consistency(self):
        """Test Meta Ads adapter validation consistency."""
        campaign_table = self._create_mock_table("metaads_campaigns", "MetaAds")
        stats_table = self._create_mock_table("metaads_campaign_stats", "MetaAds")

        config = MetaAdsConfig(
            campaign_table=campaign_table,
            stats_table=stats_table,
            source_type="MetaAds",
            source_id="test_consistency",
        )

        adapter = MetaAdsAdapter(config=config, context=self.context)
        result = adapter.validate()

        assert result.is_valid, "MetaAdsAdapter validation should succeed"
        assert isinstance(result.errors, list), "MetaAdsAdapter should return list of errors"

    # ================================================================
    # QUERY GENERATION TESTS
    # ================================================================

    def test_facebook_ads_query_generation(self):
        """Test Facebook Ads (BigQuery) adapter query generation."""
        table = self._create_mock_table("facebook_table", "BigQuery")
        source_map = self._create_source_map(
            campaign="campaign_name",
            source="'Facebook'",
            cost="spend_usd",
            date="report_date",
            impressions="impressions",
            clicks="clicks",
            currency="'USD'",
        )

        config = ExternalConfig(
            table=table,
            source_map=source_map,
            source_type="BigQuery",
            source_id="facebook_ads",
            schema_name="marketing_analytics",
        )

        adapter = BigQueryAdapter(config=config, context=self.context)
        query = adapter.build_query()

        assert query is not None, "BigQueryAdapter should generate a query"
        self._validate_query_structure(query, "BigQueryAdapter")
        assert self._execute_and_snapshot(query) == self.snapshot

    def test_google_ads_query_generation(self):
        """Test Google Ads adapter query generation with JOIN."""
        campaign_table = self._create_mock_table("google_campaign", "GoogleAds")
        stats_table = self._create_mock_table("google_stats", "GoogleAds")

        config = GoogleAdsConfig(
            campaign_table=campaign_table,
            stats_table=stats_table,
            source_type="GoogleAds",
            source_id="google_ads",
        )

        adapter = GoogleAdsAdapter(config=config, context=self.context)
        query = adapter.build_query()

        assert query is not None, "GoogleAdsAdapter should generate a query"
        self._validate_query_structure(query, "GoogleAdsAdapter")
        assert self._execute_and_snapshot(query) == self.snapshot

    def test_reddit_ads_query_generation(self):
        """Test Reddit Ads adapter query generation with JOIN."""
        campaign_table = self._create_mock_table("reddit_campaign", "RedditAds")
        stats_table = self._create_mock_table("reddit_stats", "RedditAds")

        config = RedditAdsConfig(
            campaign_table=campaign_table,
            stats_table=stats_table,
            source_type="RedditAds",
            source_id="reddit_ads",
        )

        adapter = RedditAdsAdapter(config=config, context=self.context)
        query = adapter.build_query()

        assert query is not None, "RedditAdsAdapter should generate a query"
        self._validate_query_structure(query, "RedditAdsAdapter")
        assert self._execute_and_snapshot(query) == self.snapshot

    def test_meta_ads_query_generation(self):
        """Test Meta Ads adapter query generation with JOIN."""
        campaign_table = self._create_mock_table("meta_campaigns", "MetaAds")
        stats_table = self._create_mock_table("meta_campaign_stats", "MetaAds")

        config = MetaAdsConfig(
            campaign_table=campaign_table,
            stats_table=stats_table,
            source_type="MetaAds",
            source_id="meta_ads",
        )

        adapter = MetaAdsAdapter(config=config, context=self.context)
        query = adapter.build_query()

        assert query is not None, "MetaAdsAdapter should generate a query"
        self._validate_query_structure(query, "MetaAdsAdapter")
        assert self._execute_and_snapshot(query) == self.snapshot

    def test_tiktok_ads_query_generation(self):
        """Test TikTok Ads (AWS) adapter query generation."""
        table = self._create_mock_table("tiktok_table", "aws")
        source_map = self._create_source_map(
            campaign="campaign_name",
            source="'TikTok'",
            cost="spend",
            date="report_date",
            impressions="impressions",
            clicks="clicks",
            currency="'USD'",
        )

        config = ExternalConfig(
            table=table,
            source_map=source_map,
            source_type="aws",
            source_id="tiktok_ads",
            schema_name="marketing_data",
        )

        adapter = AWSAdapter(config=config, context=self.context)
        query = adapter.build_query()

        assert query is not None, "AWSAdapter should generate a query"
        self._validate_query_structure(query, "AWSAdapter")
        assert self._execute_and_snapshot(query) == self.snapshot

    def test_linkedin_ads_query_generation(self):
        """Test LinkedIn Ads adapter query generation."""
        campaign_table = self._create_mock_table("linkedin_campaigns", "LinkedinAds")
        stats_table = self._create_mock_table("linkedin_stats", "LinkedinAds")

        config = LinkedinAdsConfig(
            campaign_table=campaign_table,
            stats_table=stats_table,
            source_type="LinkedinAds",
            source_id="linkedin_ads",
        )

        adapter = LinkedinAdsAdapter(config=config, context=self.context)
        query = adapter.build_query()

        assert query is not None, "LinkedinAdsAdapter should generate a query"
        self._validate_query_structure(query, "LinkedinAdsAdapter")
        assert self._execute_and_snapshot(query) == self.snapshot

    def test_azure_adapter_query_generation(self):
        """Test Azure adapter query generation."""
        table = self._create_mock_table("azure_table", "azure")
        source_map = self._create_source_map(
            campaign="campaign_name",
            source="'Azure'",
            cost="spend",
            date="report_date",
            impressions="impressions",
            clicks="clicks",
            currency="'USD'",
        )

        config = ExternalConfig(
            table=table,
            source_map=source_map,
            source_type="azure",
            source_id="azure_ads",
            schema_name="marketing_data",
        )

        adapter = AzureAdapter(config=config, context=self.context)
        query = adapter.build_query()

        assert query is not None, "AzureAdapter should generate a query"
        self._validate_query_structure(query, "AzureAdapter")
        assert self._execute_and_snapshot(query) == self.snapshot

    def test_cloudflare_r2_adapter_query_generation(self):
        """Test Cloudflare R2 adapter query generation."""
        table = self._create_mock_table("cloudflare_table", "cloudflare_r2")
        source_map = self._create_source_map(
            campaign="campaign_name",
            source="'Cloudflare'",
            cost="spend",
            date="report_date",
            impressions="impressions",
            clicks="clicks",
            currency="'USD'",
        )

        config = ExternalConfig(
            table=table,
            source_map=source_map,
            source_type="cloudflare_r2",
            source_id="cloudflare_ads",
            schema_name="marketing_data",
        )

        adapter = CloudflareR2Adapter(config=config, context=self.context)
        query = adapter.build_query()

        assert query is not None, "CloudflareR2Adapter should generate a query"
        self._validate_query_structure(query, "CloudflareR2Adapter")
        assert self._execute_and_snapshot(query) == self.snapshot

    def test_union_query_compatibility(self):
        """Test that different adapters generate UNION-compatible queries."""
        configs = [
            (
                BigQueryAdapter,
                ExternalConfig(
                    table=self._create_mock_table("facebook_table", "BigQuery"),
                    source_map=self._create_source_map(campaign="campaign_id", source="'Facebook'"),
                    source_type="BigQuery",
                    source_id="facebook",
                    schema_name="marketing",
                ),
            ),
            (
                AWSAdapter,
                ExternalConfig(
                    table=self._create_mock_table("tiktok_table", "aws"),
                    source_map=self._create_source_map(campaign="campaign_name", source="'TikTok'"),
                    source_type="aws",
                    source_id="tiktok",
                    schema_name="marketing",
                ),
            ),
        ]

        queries = []
        for adapter_class, config in configs:
            adapter = adapter_class(config=config, context=self.context)
            query = adapter.build_query()
            assert query is not None, f"{adapter_class.__name__} should generate a query"
            self._validate_query_structure(query, adapter_class.__name__)
            queries.append(query)

        union_query_set = ast.SelectSetQuery.create_from_queries(queries, "UNION ALL")
        union_query = ast.SelectQuery(
            select=[
                ast.Alias(alias="campaign", expr=ast.Field(chain=["campaign"])),
                ast.Alias(alias="source", expr=ast.Field(chain=["source"])),
                ast.Alias(alias="impressions", expr=ast.Field(chain=["impressions"])),
                ast.Alias(alias="clicks", expr=ast.Field(chain=["clicks"])),
                ast.Alias(alias="cost", expr=ast.Field(chain=["cost"])),
            ],
            select_from=ast.JoinExpr(table=union_query_set, alias="all_marketing_data"),
        )

        assert self._execute_and_snapshot(union_query) == self.snapshot

    def test_currency_conversion_handling(self):
        """Test that currency conversion is properly handled in queries."""
        table = self._create_mock_table("currency_test_table", "BigQuery")
        source_map = self._create_source_map(
            campaign="campaign_name",
            source="'Facebook'",
            cost="spend_amount",
            currency="spend_currency",
        )

        config = ExternalConfig(
            table=table,
            source_map=source_map,
            source_type="BigQuery",
            source_id="currency_test",
            schema_name="marketing_schema",
        )

        adapter = BigQueryAdapter(config=config, context=self.context)
        query = adapter.build_query()

        assert query is not None, "BigQueryAdapter should generate a query"
        self._validate_query_structure(query, "BigQueryAdapter")

        cost_select = next((col for col in query.select if hasattr(col, "alias") and col.alias == "cost"), None)
        assert cost_select is not None, "Cost column should exist"
        assert isinstance(cost_select, ast.Alias), "Cost column should be an Alias"

        cost_expr = cost_select.expr
        assert isinstance(cost_expr, ast.Call), "Cost should be a function call"
        assert cost_expr.name == "toFloat", "Cost should be converted to float"

        assert self._execute_and_snapshot(query) == self.snapshot

    # ================================================================
    # INTEGRATION TESTS WITH REAL DATA
    # ================================================================

    def test_bigquery_adapter_with_real_data(self):
        """Test BigQuery adapter with real CSV data."""
        table_info = self._setup_csv_table("bigquery")

        source_map = Mock(spec=SourceMap)
        source_map.campaign = "campaign1"
        source_map.source = None
        source_map.cost = "spend1"
        source_map.date = "date1"
        source_map.impressions = "impressions1"
        source_map.clicks = "clicks1"
        source_map.currency = None
        source_map.reported_conversion = "conversions1"

        config = ExternalConfig(
            table=table_info.table,
            source_map=source_map,
            source_type="BigQuery",
            source_id="facebook_ads",
            schema_name="marketing",
        )

        adapter = BigQueryAdapter(config=config, context=self.context)
        query = adapter.build_query()

        assert query is not None, "BigQueryAdapter should generate a query"
        results = self._execute_query_and_validate(query)

        total_cost = sum(float(row[4] or 0) for row in results)
        total_impressions = sum(int(row[2] or 0) for row in results)
        total_clicks = sum(int(row[3] or 0) for row in results)

        assert len(results) == 14, "Expected 14 campaigns from BigQuery CSV"
        assert abs(total_cost - 18.66) < 0.01, f"Expected cost $18.66, got ${total_cost}"
        assert total_impressions == 1676, f"Expected 1676 impressions, got {total_impressions}"
        assert total_clicks == 12, f"Expected 12 clicks, got {total_clicks}"

        sources = [row[1] for row in results]
        assert all(source == "Unknown Source" for source in sources), "All sources should be 'Unknown Source'"

    def test_google_ads_adapter_with_real_data(self):
        """Test Google Ads adapter with real CSV data (JOIN operation)."""
        campaign_info = self._setup_csv_table("google_campaign")
        stats_info = self._setup_csv_table("google_stats")

        config = GoogleAdsConfig(
            campaign_table=campaign_info.table,
            stats_table=stats_info.table,
            source_type="GoogleAds",
            source_id="google_ads",
        )

        adapter = GoogleAdsAdapter(config=config, context=self.context)

        validation_result = adapter.validate()
        assert validation_result.is_valid, f"Validation failed: {validation_result.errors}"

        query = adapter.build_query()
        assert query is not None, "GoogleAdsAdapter should generate a query"
        results = self._execute_query_and_validate(query)

        total_cost = sum(float(row[4] or 0) for row in results)
        total_impressions = sum(int(row[2] or 0) for row in results)
        total_clicks = sum(int(row[3] or 0) for row in results)

        assert len(results) == 12, "Expected 12 campaigns from Google Ads JOIN"
        assert abs(total_cost - 644.50) < 0.01, f"Expected cost $644.50, got ${total_cost}"
        assert total_impressions == 1687, f"Expected 1687 impressions, got {total_impressions}"
        assert total_clicks == 72, f"Expected 72 clicks, got {total_clicks}"

        sources = [row[1] for row in results]
        assert all(source == "google" for source in sources), "All sources should be 'google'"

    def test_linkedin_ads_adapter_with_real_data(self):
        """Test LinkedIn Ads adapter with real CSV data (JOIN operation)."""
        campaign_info = self._setup_csv_table("linkedin_campaigns")
        stats_info = self._setup_csv_table("linkedin_stats")

        config = LinkedinAdsConfig(
            campaign_table=campaign_info.table,
            stats_table=stats_info.table,
            source_type="LinkedinAds",
            source_id="linkedin_ads",
        )

        adapter = LinkedinAdsAdapter(config=config, context=self.context)

        validation_result = adapter.validate()
        assert validation_result.is_valid, f"Validation failed: {validation_result.errors}"

        query = adapter.build_query()
        assert query is not None, "Expected adapter to build a valid query"
        results = self._execute_query_and_validate(query)

        total_cost = sum(float(row[4] or 0) for row in results)
        total_impressions = sum(int(row[2] or 0) for row in results)
        total_clicks = sum(int(row[3] or 0) for row in results)

        assert len(results) == 5, "Expected 5 campaigns from LinkedIn Ads JOIN"
        assert abs(total_cost - 1600.00) < 0.01, f"Expected cost $1600.00, got ${total_cost}"
        assert total_impressions == 485, f"Expected 485 impressions, got {total_impressions}"
        assert total_clicks == 26, f"Expected 26 clicks, got {total_clicks}"

        sources = [row[1] for row in results]
        assert all(source == "linkedin" for source in sources), "All sources should be 'linkedin'"

    def test_reddit_ads_adapter_with_real_data(self):
        """Test Reddit Ads adapter with real CSV data (JOIN operation)."""
        campaign_info = self._setup_csv_table("reddit_campaign")
        stats_info = self._setup_csv_table("reddit_stats")

        config = RedditAdsConfig(
            campaign_table=campaign_info.table,
            stats_table=stats_info.table,
            source_type="RedditAds",
            source_id="reddit_ads",
        )

        adapter = RedditAdsAdapter(config=config, context=self.context)

        validation_result = adapter.validate()
        assert validation_result.is_valid, f"Validation failed: {validation_result.errors}"

        query = adapter.build_query()
        assert query is not None, "RedditAdsAdapter should generate a query"
        results = self._execute_query_and_validate(query)

        total_cost = sum(float(row[4] or 0) for row in results)
        total_impressions = sum(int(row[2] or 0) for row in results)
        total_clicks = sum(int(row[3] or 0) for row in results)

        assert len(results) == 10, "Expected 10 campaigns from Reddit Ads JOIN"
        assert abs(total_cost - 90.6) < 0.01, f"Expected cost $90.6, got ${total_cost}"
        assert total_impressions == 14299, f"Expected 14299 impressions, got {total_impressions}"
        assert total_clicks == 454, f"Expected 454 clicks, got {total_clicks}"

        sources = [row[1] for row in results]
        assert all(source == "reddit" for source in sources), "All sources should be 'reddit'"

    def test_multi_adapter_union_with_real_data(self):
        """Test UNION query with multiple adapters using real data."""
        bigquery_info = self._setup_csv_table("bigquery")
        s3_info = self._setup_csv_table("s3")

        bigquery_source_map = Mock(spec=SourceMap)
        bigquery_source_map.campaign = "campaign1"
        bigquery_source_map.source = None
        bigquery_source_map.cost = "spend1"
        bigquery_source_map.date = "date1"
        bigquery_source_map.impressions = "impressions1"
        bigquery_source_map.clicks = "clicks1"
        bigquery_source_map.currency = None
        bigquery_source_map.reported_conversion = "conversions1"

        facebook_config = ExternalConfig(
            table=bigquery_info.table,
            source_map=bigquery_source_map,
            source_type="BigQuery",
            source_id="facebook_ads",
            schema_name="marketing_data",
        )

        s3_source_map = Mock(spec=SourceMap)
        s3_source_map.campaign = "campaign2"
        s3_source_map.source = None
        s3_source_map.cost = "spend2"
        s3_source_map.date = "date2"
        s3_source_map.impressions = "impressions2"
        s3_source_map.clicks = "clicks2"
        s3_source_map.currency = None
        s3_source_map.reported_conversion = None

        tiktok_config = ExternalConfig(
            table=s3_info.table,
            source_map=s3_source_map,
            source_type="aws",
            source_id="tiktok_ads",
            schema_name="marketing_data",
        )

        facebook_adapter = BigQueryAdapter(config=facebook_config, context=self.context)
        tiktok_adapter = AWSAdapter(config=tiktok_config, context=self.context)

        facebook_query = facebook_adapter.build_query()
        tiktok_query = tiktok_adapter.build_query()

        union_query = ast.SelectSetQuery.create_from_queries([facebook_query, tiktok_query], "UNION ALL")
        results = self._execute_query_and_validate(union_query)

        total_cost = sum(float(row[4] or 0) for row in results)
        total_impressions = sum(int(row[2] or 0) for row in results)
        total_clicks = sum(int(row[3] or 0) for row in results)

        assert len(results) == 28, "Expected 28 campaigns from union (BigQuery: 14 + S3: 14)"
        assert abs(total_cost - 127.17) < 0.01, f"Expected cost $127.17 (combined sources), got ${total_cost}"
        assert total_impressions == 2219, f"Expected 2219 impressions (combined), got {total_impressions}"
        assert total_clicks == 136, f"Expected 136 clicks (combined), got {total_clicks}"

    # ================================================================
    # ERROR HANDLING TESTS
    # ================================================================

    def test_adapter_error_handling(self):
        """Test that adapters handle errors gracefully."""
        table = self._create_mock_table("error_table", "BigQuery")
        source_map = self._create_source_map()

        config = ExternalConfig(
            table=table,
            source_map=source_map,
            source_type="BigQuery",
            source_id="error_test",
            schema_name="marketing_schema",
        )

        adapter = BigQueryAdapter(config=config, context=self.context)

        with patch.object(adapter, "_get_campaign_name_field", side_effect=Exception("Test error")):
            query = adapter.build_query()
            assert query is None, "Should return None on error instead of raising"

    def test_validation_error_handling(self):
        """Test validation error handling with various error conditions."""
        table = self._create_mock_table("validation_error_table", "BigQuery")

        config = ExternalConfig(
            table=table,
            source_map=None,
            source_type="BigQuery",
            source_id="validation_error",
            schema_name="marketing_schema",
        )

        adapter = BigQueryAdapter(config=config, context=self.context)

        result = adapter.validate()
        assert hasattr(result, "is_valid"), "Should return ValidationResult object"
        assert not result.is_valid, "Should return invalid result for None source_map"

    def test_missing_csv_files_handling(self):
        """Test behavior when CSV files are missing."""
        old_configs = self.test_data_configs.copy()
        self.test_data_configs["nonexistent_table"] = DataConfig(
            csv_filename="test/nonexistent/missing.csv",
            table_name="nonexistent_table",
            platform="Test",
            source_type="Test",
            bucket_suffix="test",
            column_schema={"test_col": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True}},
        )

        try:
            with pytest.raises(AssertionError, match="CSV file must exist"):
                self._setup_csv_table("nonexistent_table")
        finally:
            self.test_data_configs = old_configs

    # ================================================================
    # PERFORMANCE TESTS
    # ================================================================

    def test_adapter_performance_with_large_queries(self):
        """Test adapter performance with complex queries."""
        table = self._create_mock_table("performance_table", "BigQuery")
        source_map = self._create_source_map()

        config = ExternalConfig(
            table=table,
            source_map=source_map,
            source_type="BigQuery",
            source_id="performance_test",
            schema_name="marketing_schema",
        )

        adapter = BigQueryAdapter(config=config, context=self.context)

        import time

        start_time = time.time()
        query = adapter.build_query()
        generation_time = time.time() - start_time

        assert query is not None, "Query should be generated"
        assert generation_time < 1.0, f"Query generation took too long: {generation_time}s"

    def test_memory_usage_with_multiple_adapters(self):
        """Test memory usage when creating multiple adapters."""
        adapters = []
        for i in range(10):
            table = self._create_mock_table(f"memory_test_table_{i}", "BigQuery")
            source_map = self._create_source_map()
            config = ExternalConfig(
                table=table,
                source_map=source_map,
                source_type="BigQuery",
                source_id=f"memory_test_{i}",
                schema_name="marketing_schema",
            )
            adapter = BigQueryAdapter(config=config, context=self.context)
            adapters.append(adapter)

        for adapter in adapters:
            result = adapter.validate()
            assert result.is_valid, "All adapters should validate successfully"

        adapters.clear()
