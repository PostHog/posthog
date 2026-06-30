from typing import Optional, cast

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils.timezone import now

from posthog.models import SharingConfiguration
from posthog.models.signals import mute_selected_signals

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.product_analytics.backend.models.insight import Insight
from products.product_analytics.backend.models.insight_caching_state import InsightCachingState

filters = {
    "events": [{"id": "$pageview"}],
    "properties": [{"key": "$browser", "value": "Mac OS X"}],
}

filters2 = {
    **filters,
    "events": [{"id": "$pageleave"}],
}


class TestInsightCachingState(BaseTest):
    def test_insight_creation_updating_deletion(self):
        insight = Insight.objects.create(team=self.team, filters=filters)

        initial_caching_state = self.get_caching_state()
        assert initial_caching_state is not None
        assert initial_caching_state.insight.pk == insight.pk
        assert initial_caching_state.dashboard_tile is None
        assert isinstance(initial_caching_state.cache_key, str)

        insight.filters = filters2
        insight.save()

        updated_caching_state = self.get_caching_state()
        assert updated_caching_state is not None
        assert updated_caching_state.pk == initial_caching_state.pk
        assert updated_caching_state.cache_key != initial_caching_state.cache_key
        assert updated_caching_state.updated_at != initial_caching_state.updated_at

        insight.delete()

        assert self.get_caching_state() is None

    def test_dashboard_tile_creation_updating_deletion(self):
        with mute_selected_signals():
            dashboard = Dashboard.objects.create(team=self.team)
            insight = Insight.objects.create(team=self.team, filters=filters)

        dashboard_tile = DashboardTile.objects.create(dashboard=dashboard, insight=insight)

        initial_caching_state = self.get_caching_state()
        assert initial_caching_state is not None
        assert initial_caching_state.insight.pk == insight.pk
        assert cast(DashboardTile, initial_caching_state.dashboard_tile).pk == dashboard_tile.pk
        assert isinstance(initial_caching_state.cache_key, str)

        with mute_selected_signals():
            insight.filters = filters2
            insight.save()

        dashboard_tile.color = "red"
        dashboard_tile.save()

        updated_caching_state = self.get_caching_state()
        assert updated_caching_state is not None
        assert updated_caching_state.pk == initial_caching_state.pk
        assert updated_caching_state.cache_key != initial_caching_state.cache_key
        assert updated_caching_state.updated_at != initial_caching_state.updated_at

        dashboard_tile.delete()

        assert self.get_caching_state() is None

    def test_dashboard_tile_save_signal_does_not_query_dashboard_table(self):
        with mute_selected_signals():
            dashboard = Dashboard.objects.create(team=self.team)
            insight = Insight.objects.create(team=self.team, filters=filters)
            tile = DashboardTile.objects.create(dashboard=dashboard, insight=insight)

        # Re-fetch so the dashboard relation is not already cached on the instance; the
        # post_save signal must read the denormalized team_id rather than dereferencing
        # instance.dashboard, which would issue an extra SELECT on the dashboard table.
        tile = DashboardTile.objects.get(pk=tile.pk)
        tile.color = "red"

        # Stub the downstream sync task so the only work captured is save() + the signal
        # itself (the task legitimately reads dashboard.deleted, which is out of scope here).
        with patch(
            "products.product_analytics.backend.models.insight_caching_state._queue_sync_insight_caching_state"
        ) as queue_mock:
            with CaptureQueriesContext(connection) as ctx:
                tile.save(update_fields=["color"])

        queue_mock.assert_called_once_with(self.team.pk, dashboard_tile_id=tile.pk)
        # Quoted to distinguish the dashboard table from posthog_dashboardtile.
        assert not any('"posthog_dashboard"' in query["sql"] for query in ctx.captured_queries)

    def test_sharing_configuration_insight(self):
        with mute_selected_signals():
            insight = Insight.objects.create(team=self.team, filters=filters)

        SharingConfiguration.objects.create(team=self.team, insight=insight, enabled=True)

        assert self.get_caching_state() is not None

    def test_dashboard(self):
        dashboard = Dashboard.objects.create(team=self.team)
        insight = Insight.objects.create(team=self.team, filters=filters)
        dashboard_tile = DashboardTile.objects.create(dashboard=dashboard, insight=insight)

        initial_caching_state = dashboard_tile.caching_state
        assert initial_caching_state is not None

        dashboard.filters = {"date_from": "-24h"}
        dashboard.save()

        new_caching_state = InsightCachingState.objects.get(dashboard_tile=dashboard_tile)
        assert new_caching_state.pk == initial_caching_state.pk
        assert new_caching_state.cache_key != initial_caching_state.cache_key
        assert new_caching_state.updated_at != initial_caching_state.updated_at

    def test_dashboard_updating_last_accessed_at_does_not_sync(self):
        with mute_selected_signals():
            dashboard = Dashboard.objects.create(team=self.team)
            insight = Insight.objects.create(team=self.team, filters=filters)
            DashboardTile.objects.create(dashboard=dashboard, insight=insight)

        dashboard.last_accessed_at = now()
        dashboard.save(update_fields=["last_accessed_at"])

        assert self.get_caching_state() is None

    def get_caching_state(self) -> Optional[InsightCachingState]:
        query_set = InsightCachingState.objects.filter(team_id=self.team.pk)
        assert len(query_set) in (0, 1)
        return query_set.first()
