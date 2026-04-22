from datetime import datetime, timedelta

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock

from posthog.schema import DatabaseSchemaManagedViewTableKind, IntervalType, RevenueAnalyticsGrossRevenueQuery

from posthog.hogql.database.models import SavedQuery, StringDatabaseField
from posthog.hogql.database.s3_table import DataWarehouseTable as HogQLDataWarehouseTable

from posthog.constants import AvailableFeature
from posthog.rbac.user_access_control import UserAccessControlError

from products.data_warehouse.backend.models import ExternalDataSchema, ExternalDataSource
from products.data_warehouse.backend.types import ExternalDataSourceType
from products.revenue_analytics.backend.hogql_queries.revenue_analytics_query_runner import RevenueAnalyticsQueryRunner
from products.revenue_analytics.backend.views import (
    RevenueAnalyticsChargeView,
    RevenueAnalyticsCustomerView,
    RevenueAnalyticsProductView,
    RevenueAnalyticsRevenueItemView,
    RevenueAnalyticsSubscriptionView,
)
from products.revenue_analytics.backend.views.schemas import SCHEMAS as VIEW_SCHEMAS

try:
    from ee.models.rbac.access_control import AccessControl
except ImportError:
    pass


# This is required because we can't instantiate the base class directly
# since it doesn't implement two abstract methods
class RevenueAnalyticsQueryRunnerImpl(RevenueAnalyticsQueryRunner):
    def _calculate(self):
        raise NotImplementedError()

    def to_query(self):
        raise NotImplementedError()


class TestRevenueAnalyticsQueryRunner(APIBaseTest):
    query = RevenueAnalyticsGrossRevenueQuery(breakdown=[], properties=[], interval=IntervalType.MONTH)
    date = datetime(2025, 1, 1)

    def assertDiff(self, diff: timedelta):
        runner = RevenueAnalyticsQueryRunnerImpl(team=self.team, query=self.query)
        self.assertEqual(runner.cache_target_age(self.date), self.date + diff)

    def test_cache_target_age_without_last_refresh(self):
        """Test that when there is no last refresh, we return None"""
        runner = RevenueAnalyticsQueryRunnerImpl(team=self.team, query=self.query)
        self.assertEqual(runner.cache_target_age(None), None)

    def test_cache_target_age_without_sources(self):
        """Test that when there are no sources, we use our default cache target age"""
        self.assertDiff(RevenueAnalyticsQueryRunner.DEFAULT_CACHE_TARGET_AGE)

    def test_cache_target_age_first_time_sync(self):
        """Test that first-time sync (RUNNING status with no last_synced_at) returns 1 minute cache"""

        # Create a Stripe source with revenue analytics enabled
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="src_test",
            connection_id="conn_test",
            source_type=ExternalDataSourceType.STRIPE,
        )

        # Create a schema that's running but has never synced
        ExternalDataSchema.objects.create(
            team=self.team,
            source=source,
            name="test_schema",
            should_sync=True,
            status=ExternalDataSchema.Status.RUNNING,
            last_synced_at=None,  # Never synced before
        )

        self.assertDiff(RevenueAnalyticsQueryRunner.SMALL_CACHE_TARGET_AGE)

    def test_cache_target_age_with_sync_intervals(self):
        """Test that when schemas have sync intervals, we cache for half the minimum interval"""

        # Create a Stripe source with revenue analytics enabled
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="src_test",
            connection_id="conn_test",
            source_type=ExternalDataSourceType.STRIPE,
        )

        # Create schemas with different sync intervals
        ExternalDataSchema.objects.create(
            team=self.team,
            source=source,
            name="schema_1",
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            last_synced_at=datetime.now(),
            sync_frequency_interval=timedelta(hours=6),  # 6 hours
        )

        ExternalDataSchema.objects.create(
            team=self.team,
            source=source,
            name="schema_2",
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            last_synced_at=datetime.now(),
            sync_frequency_interval=timedelta(hours=12),  # 12 hours
        )

        # Should cache for half of the minimum interval (6 hours / 2 = 3 hours)
        self.assertDiff(timedelta(hours=3))

    def test_cache_target_age_without_sync_intervals(self):
        """Test that when schemas have no sync intervals, we use our default cache target age"""

        # Create a Stripe source with revenue analytics enabled
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="src_test",
            connection_id="conn_test",
            source_type=ExternalDataSourceType.STRIPE,
        )

        # Create schemas without sync intervals
        ExternalDataSchema.objects.create(
            team=self.team,
            source=source,
            name="schema_1",
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            last_synced_at=datetime.now(),
            sync_frequency_interval=None,  # No interval
        )

        ExternalDataSchema.objects.create(
            team=self.team,
            source=source,
            name="schema_2",
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            last_synced_at=datetime.now(),
            sync_frequency_interval=None,  # No interval
        )

        self.assertDiff(RevenueAnalyticsQueryRunner.DEFAULT_CACHE_TARGET_AGE)

    def test_cache_target_age_mixed_sync_intervals(self):
        """Test that when some schemas have intervals and others don't, we use the minimum"""

        # Create a Stripe source with revenue analytics enabled
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="src_test",
            connection_id="conn_test",
            source_type=ExternalDataSourceType.STRIPE,
        )

        # Create schemas with mixed sync intervals
        ExternalDataSchema.objects.create(
            team=self.team,
            source=source,
            name="schema_1",
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            last_synced_at=datetime.now(),
            sync_frequency_interval=timedelta(hours=6),  # 6 hours
        )

        ExternalDataSchema.objects.create(
            team=self.team,
            source=source,
            name="schema_2",
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            last_synced_at=datetime.now(),
            sync_frequency_interval=None,  # No interval
        )

        ExternalDataSchema.objects.create(
            team=self.team,
            source=source,
            name="schema_3",
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            last_synced_at=datetime.now(),
            sync_frequency_interval=timedelta(hours=1),  # 1 hour (minimum)
        )

        # Should cache for half of the minimum interval (1 hour / 2 = 0.5 hour)
        self.assertDiff(timedelta(minutes=30))

    def test_cache_target_age_non_stripe_sources_ignored(self):
        """Test that non-Stripe sources are ignored"""

        # Create a non-Stripe source with revenue analytics enabled
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="src_test",
            connection_id="conn_test",
            source_type=ExternalDataSourceType.POSTGRES,  # Not Stripe
        )

        # Create a schema for the non-Stripe source
        ExternalDataSchema.objects.create(
            team=self.team,
            source=source,
            name="schema_1",
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            last_synced_at=datetime.now(),
            sync_frequency_interval=timedelta(hours=1),
        )

        # Should use our default cache target age since no Stripe sources
        self.assertDiff(RevenueAnalyticsQueryRunner.DEFAULT_CACHE_TARGET_AGE)

    def test_cache_target_age_should_sync_false_ignored(self):
        """Test that schemas with should_sync=False are ignored"""

        # Create a Stripe source with revenue analytics enabled
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="src_test",
            connection_id="conn_test",
            source_type=ExternalDataSourceType.STRIPE,
        )

        # Create a schema that shouldn't sync
        ExternalDataSchema.objects.create(
            team=self.team,
            source=source,
            name="schema_1",
            should_sync=False,  # Should not sync
            status=ExternalDataSchema.Status.COMPLETED,
            last_synced_at=datetime.now(),
            sync_frequency_interval=timedelta(hours=1),
        )

        # Should use our default cache target age since schema shouldn't sync
        self.assertDiff(RevenueAnalyticsQueryRunner.DEFAULT_CACHE_TARGET_AGE)

    def test_cache_target_age_first_time_sync_priority(self):
        """Test that first-time sync takes priority over sync intervals"""

        # Create a Stripe source with revenue analytics enabled
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="src_test",
            connection_id="conn_test",
            source_type=ExternalDataSourceType.STRIPE,
        )

        # Create a schema that's running but has never synced (first-time sync)
        ExternalDataSchema.objects.create(
            team=self.team,
            source=source,
            name="schema_1",
            should_sync=True,
            status=ExternalDataSchema.Status.RUNNING,
            last_synced_at=None,  # Never synced before
        )

        # Create another schema with sync interval
        ExternalDataSchema.objects.create(
            team=self.team,
            source=source,
            name="schema_2",
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            last_synced_at=datetime.now(),
            sync_frequency_interval=timedelta(hours=6),
        )

        # Should return our small cache target age since it's the first time syncing
        self.assertDiff(RevenueAnalyticsQueryRunner.SMALL_CACHE_TARGET_AGE)

    def test_cache_target_age_complex_scenario(self):
        """Test a complex scenario with multiple schemas and edge cases"""

        # Create a Stripe source with revenue analytics enabled (default)
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="src_test",
            connection_id="conn_test",
            source_type=ExternalDataSourceType.STRIPE,
        )

        # Create multiple schemas with different configurations
        ExternalDataSchema.objects.create(
            team=self.team,
            source=source,
            name="schema_1",
            should_sync=True,
            status=ExternalDataSchema.Status.RUNNING,
            last_synced_at=None,  # First-time sync (should take priority)
            sync_frequency_interval=timedelta(hours=12),
        )

        ExternalDataSchema.objects.create(
            team=self.team,
            source=source,
            name="schema_2",
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            last_synced_at=datetime.now(),
            sync_frequency_interval=timedelta(hours=6),
        )

        ExternalDataSchema.objects.create(
            team=self.team,
            source=source,
            name="schema_3",
            should_sync=False,  # Should be ignored
            status=ExternalDataSchema.Status.COMPLETED,
            last_synced_at=datetime.now(),
            sync_frequency_interval=timedelta(hours=1),
        )

        ExternalDataSchema.objects.create(
            team=self.team,
            source=source,
            name="schema_4",
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            last_synced_at=datetime.now(),
            sync_frequency_interval=None,  # Should be ignored for interval calculation
        )

        # Should return our small cache target age since it's the first time syncing
        self.assertDiff(RevenueAnalyticsQueryRunner.SMALL_CACHE_TARGET_AGE)

    def test_validate_query_runner_access(self):
        """Test that the query runner can access the query runner"""
        runner = RevenueAnalyticsQueryRunnerImpl(team=self.team, query=self.query)
        self.assertTrue(runner.validate_query_runner_access(self.user))

    def test_validate_query_runner_access_without_access(self):
        """Test that the query runner cannot access the query runner without view access control"""
        AccessControl.objects.create(team=self.team, resource="revenue_analytics", access_level="none")
        self.organization.available_product_features.append({"key": AvailableFeature.ADVANCED_PERMISSIONS})  # type: ignore[union-attr]
        self.organization.save()

        runner = RevenueAnalyticsQueryRunnerImpl(team=self.team, query=self.query)
        self.assertRaises(UserAccessControlError, runner.validate_query_runner_access, self.user)


DUMMY_FIELDS = {"id": StringDatabaseField(name="id")}


def _make_saved_query(name: str, metadata: dict | None = None) -> SavedQuery:
    return SavedQuery(
        id="test-id",
        name=name,
        query="SELECT 1",
        fields=DUMMY_FIELDS,
        metadata={"managed_viewset_kind": "revenue_analytics"} if metadata is None else metadata,
    )


def _make_materialized_table(name: str) -> HogQLDataWarehouseTable:
    return HogQLDataWarehouseTable(
        name=name,
        url="s3://bucket/path",
        format="DeltaS3Wrapper",
        fields=DUMMY_FIELDS,
        table_id="test-table-id",
    )


VIEW_SUFFIX_TO_CLASS = [
    ("charge_revenue_view", RevenueAnalyticsChargeView),
    ("customer_revenue_view", RevenueAnalyticsCustomerView),
    ("product_revenue_view", RevenueAnalyticsProductView),
    ("revenue_item_revenue_view", RevenueAnalyticsRevenueItemView),
    ("subscription_revenue_view", RevenueAnalyticsSubscriptionView),
]


class TestTableToRevenueAnalyticsBaseView:
    @pytest.mark.parametrize(
        "suffix,expected_class",
        VIEW_SUFFIX_TO_CLASS,
    )
    @pytest.mark.parametrize(
        "factory,expected_query,expected_id",
        [
            (_make_saved_query, "SELECT 1", "test-id"),
            (_make_materialized_table, "", "test-table-id"),
        ],
        ids=["saved_query", "materialized_table"],
    )
    def test_resolves_correct_view_class(self, suffix, expected_class, factory, expected_query, expected_id):
        table = factory(f"revenue_analytics.stripe.{suffix}")
        result = RevenueAnalyticsQueryRunner.table_to_revenue_analytics_base_view(table)

        assert isinstance(result, expected_class)
        assert result.name == f"revenue_analytics.stripe.{suffix}"
        assert result.query == expected_query
        assert result.id == expected_id

    def test_events_view_sets_event_name(self):
        saved_query = _make_saved_query("revenue_analytics.events.purchase.charge_events_revenue_view")
        result = RevenueAnalyticsQueryRunner.table_to_revenue_analytics_base_view(saved_query)
        assert isinstance(result, RevenueAnalyticsChargeView)
        assert result.event_name == "purchase"

    def test_source_view_has_no_event_name(self):
        saved_query = _make_saved_query("revenue_analytics.stripe.charge_revenue_view")
        result = RevenueAnalyticsQueryRunner.table_to_revenue_analytics_base_view(saved_query)
        assert result.event_name is None

    def test_raises_for_unknown_suffix(self):
        saved_query = _make_saved_query("revenue_analytics.stripe.unknown_view")
        with pytest.raises(ValueError, match="not a revenue analytics view"):
            RevenueAnalyticsQueryRunner.table_to_revenue_analytics_base_view(saved_query)


class TestRevenueSubqueries:
    def _mock_database(self, view_names: list[str], tables: dict[str, object]) -> MagicMock:
        db = MagicMock()
        db.get_view_names.return_value = view_names
        db.get_table.side_effect = lambda name: tables[name]
        return db

    def test_yields_revenue_analytics_base_view_directly(self):
        view = RevenueAnalyticsRevenueItemView(
            id="old-view",
            name="stripe.prefix.revenue_item_revenue_view",
            query="SELECT 1",
            fields=DUMMY_FIELDS,
            prefix="stripe.prefix",
        )
        db = self._mock_database(
            ["stripe.prefix.revenue_item_revenue_view"],
            {"stripe.prefix.revenue_item_revenue_view": view},
        )
        schema = VIEW_SCHEMAS[DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_REVENUE_ITEM]
        results = list(RevenueAnalyticsQueryRunner.revenue_subqueries(schema, db))

        assert len(results) == 1
        assert results[0] is view

    def test_yields_view_from_saved_query(self):
        saved_query = _make_saved_query("revenue_analytics.stripe.revenue_item_revenue_view")
        db = self._mock_database(
            ["revenue_analytics.stripe.revenue_item_revenue_view"],
            {"revenue_analytics.stripe.revenue_item_revenue_view": saved_query},
        )
        schema = VIEW_SCHEMAS[DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_REVENUE_ITEM]
        results = list(RevenueAnalyticsQueryRunner.revenue_subqueries(schema, db))

        assert len(results) == 1
        assert isinstance(results[0], RevenueAnalyticsRevenueItemView)

    def test_yields_view_from_materialized_table(self):
        table = _make_materialized_table("revenue_analytics.stripe.revenue_item_revenue_view")
        db = self._mock_database(
            ["revenue_analytics.stripe.revenue_item_revenue_view"],
            {"revenue_analytics.stripe.revenue_item_revenue_view": table},
        )
        schema = VIEW_SCHEMAS[DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_REVENUE_ITEM]
        results = list(RevenueAnalyticsQueryRunner.revenue_subqueries(schema, db))

        assert len(results) == 1
        assert isinstance(results[0], RevenueAnalyticsRevenueItemView)

    def test_skips_saved_query_without_managed_viewset_metadata(self):
        saved_query = _make_saved_query(
            "revenue_analytics.stripe.revenue_item_revenue_view",
            metadata={},
        )
        db = self._mock_database(
            ["revenue_analytics.stripe.revenue_item_revenue_view"],
            {"revenue_analytics.stripe.revenue_item_revenue_view": saved_query},
        )
        schema = VIEW_SCHEMAS[DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_REVENUE_ITEM]
        results = list(RevenueAnalyticsQueryRunner.revenue_subqueries(schema, db))

        assert len(results) == 0

    def test_skips_views_with_non_matching_suffix(self):
        saved_query = _make_saved_query("revenue_analytics.stripe.customer_revenue_view")
        db = self._mock_database(
            ["revenue_analytics.stripe.customer_revenue_view"],
            {"revenue_analytics.stripe.customer_revenue_view": saved_query},
        )
        schema = VIEW_SCHEMAS[DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_REVENUE_ITEM]
        results = list(RevenueAnalyticsQueryRunner.revenue_subqueries(schema, db))

        assert len(results) == 0

    def test_yields_multiple_views(self):
        source_view = _make_saved_query("revenue_analytics.stripe_1.revenue_item_revenue_view")
        materialized_view = _make_materialized_table("revenue_analytics.stripe_2.revenue_item_revenue_view")
        db = self._mock_database(
            [
                "revenue_analytics.stripe_1.revenue_item_revenue_view",
                "revenue_analytics.stripe_2.revenue_item_revenue_view",
            ],
            {
                "revenue_analytics.stripe_1.revenue_item_revenue_view": source_view,
                "revenue_analytics.stripe_2.revenue_item_revenue_view": materialized_view,
            },
        )
        schema = VIEW_SCHEMAS[DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_REVENUE_ITEM]
        results = list(RevenueAnalyticsQueryRunner.revenue_subqueries(schema, db))

        assert len(results) == 2
        assert all(isinstance(r, RevenueAnalyticsRevenueItemView) for r in results)
