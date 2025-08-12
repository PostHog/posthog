from datetime import datetime, timedelta

from products.revenue_analytics.backend.hogql_queries.revenue_analytics_revenue_query_runner import (
    RevenueAnalyticsQueryRunner,
)
from posthog.schema import RevenueAnalyticsRevenueQuery, IntervalType
from posthog.test.base import APIBaseTest
from posthog.warehouse.models import ExternalDataSource, ExternalDataSchema


# This is required because we can't instantiate the base class directly
# since it doesn't implement two abstract methods
class RevenueAnalyticsQueryRunnerImpl(RevenueAnalyticsQueryRunner):
    def calculate(self):
        raise NotImplementedError()

    def to_query(self):
        raise NotImplementedError()


class TestRevenueAnalyticsQueryRunner(APIBaseTest):
    query = RevenueAnalyticsRevenueQuery(groupBy=[], properties=[], interval=IntervalType.MONTH)
    date = datetime(2025, 1, 1)

    def assertDiff(self, diff: timedelta | None):
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
            source_type=ExternalDataSource.Type.STRIPE,
            revenue_analytics_enabled=True,
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
            source_type=ExternalDataSource.Type.STRIPE,
            revenue_analytics_enabled=True,
        )

        # Create schemas with different sync intervals
        ExternalDataSchema.objects.create(
            team=self.team,
            source=source,
            name="schema_1",
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            last_synced_at=datetime.now(),
            sync_frequency_interval=timedelta(hours=4),  # 4 hours
        )

        ExternalDataSchema.objects.create(
            team=self.team,
            source=source,
            name="schema_2",
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            last_synced_at=datetime.now(),
            sync_frequency_interval=timedelta(hours=8),  # 8 hours
        )

        # Should cache for half of the minimum interval (4 hours / 2 = 2 hours)
        self.assertDiff(timedelta(hours=2))

    def test_cache_target_age_without_sync_intervals(self):
        """Test that when schemas have no sync intervals, we use our default cache target age"""

        # Create a Stripe source with revenue analytics enabled
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="src_test",
            connection_id="conn_test",
            source_type=ExternalDataSource.Type.STRIPE,
            revenue_analytics_enabled=True,
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
            source_type=ExternalDataSource.Type.STRIPE,
            revenue_analytics_enabled=True,
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
            sync_frequency_interval=timedelta(hours=2),  # 2 hours (minimum)
        )

        # Should cache for half of the minimum interval (2 hours / 2 = 1 hour)
        self.assertDiff(timedelta(hours=1))

    def test_cache_target_age_non_stripe_sources_ignored(self):
        """Test that non-Stripe sources are ignored"""

        # Create a non-Stripe source with revenue analytics enabled
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="src_test",
            connection_id="conn_test",
            source_type=ExternalDataSource.Type.POSTGRES,  # Not Stripe
            revenue_analytics_enabled=True,
        )

        # Create a schema for the non-Stripe source
        ExternalDataSchema.objects.create(
            team=self.team,
            source=source,
            name="schema_1",
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            last_synced_at=datetime.now(),
            sync_frequency_interval=timedelta(hours=2),
        )

        # Should use our default cache target age since no Stripe sources
        self.assertDiff(RevenueAnalyticsQueryRunner.DEFAULT_CACHE_TARGET_AGE)

    def test_cache_target_age_revenue_analytics_disabled_ignored(self):
        """Test that sources with revenue_analytics_enabled=False are ignored"""

        # Create a Stripe source with revenue analytics disabled
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="src_test",
            connection_id="conn_test",
            source_type=ExternalDataSource.Type.STRIPE,
            revenue_analytics_enabled=False,  # Disabled
        )

        # Create a schema for the disabled source
        ExternalDataSchema.objects.create(
            team=self.team,
            source=source,
            name="schema_1",
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            last_synced_at=datetime.now(),
            sync_frequency_interval=timedelta(hours=2),
        )

        # Should use our default cache target age since revenue analytics is disabled
        self.assertDiff(RevenueAnalyticsQueryRunner.DEFAULT_CACHE_TARGET_AGE)

    def test_cache_target_age_should_sync_false_ignored(self):
        """Test that schemas with should_sync=False are ignored"""

        # Create a Stripe source with revenue analytics enabled
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="src_test",
            connection_id="conn_test",
            source_type=ExternalDataSource.Type.STRIPE,
            revenue_analytics_enabled=True,
        )

        # Create a schema that shouldn't sync
        ExternalDataSchema.objects.create(
            team=self.team,
            source=source,
            name="schema_1",
            should_sync=False,  # Should not sync
            status=ExternalDataSchema.Status.COMPLETED,
            last_synced_at=datetime.now(),
            sync_frequency_interval=timedelta(hours=2),
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
            source_type=ExternalDataSource.Type.STRIPE,
            revenue_analytics_enabled=True,
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
            sync_frequency_interval=timedelta(hours=4),
        )

        # Should return our small cache target age since it's the first time syncing
        self.assertDiff(RevenueAnalyticsQueryRunner.SMALL_CACHE_TARGET_AGE)

    def test_cache_target_age_complex_scenario(self):
        """Test a complex scenario with multiple schemas and edge cases"""

        # Create a Stripe source with revenue analytics enabled
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="src_test",
            connection_id="conn_test",
            source_type=ExternalDataSource.Type.STRIPE,
            revenue_analytics_enabled=True,
        )

        # Create multiple schemas with different configurations
        ExternalDataSchema.objects.create(
            team=self.team,
            source=source,
            name="schema_1",
            should_sync=True,
            status=ExternalDataSchema.Status.RUNNING,
            last_synced_at=None,  # First-time sync (should take priority)
            sync_frequency_interval=timedelta(hours=8),
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
            sync_frequency_interval=timedelta(hours=2),
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
