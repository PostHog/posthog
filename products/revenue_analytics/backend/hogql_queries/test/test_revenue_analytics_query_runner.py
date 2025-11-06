from datetime import datetime, timedelta

from posthog.test.base import APIBaseTest

from posthog.schema import IntervalType, RevenueAnalyticsGrossRevenueQuery

from posthog.constants import AvailableFeature
from posthog.rbac.user_access_control import UserAccessControlError

from products.data_warehouse.backend.models import ExternalDataSchema, ExternalDataSource
from products.data_warehouse.backend.types import ExternalDataSourceType
from products.revenue_analytics.backend.hogql_queries.revenue_analytics_query_runner import RevenueAnalyticsQueryRunner

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
