from posthog.test.base import BaseTest

from products.marketing_analytics.backend.demo import health, warehouse
from products.marketing_analytics.backend.demo.world import CAMPAIGNS, FREE_CHANNELS
from products.warehouse_sources.backend.facade.models import ExternalDataSource


class TestUnconnectedPlatforms(BaseTest):
    def test_unconnected_platforms_get_no_source(self):
        sources = health.create_sources(self.team)
        for platform in health.UNCONNECTED_PLATFORMS:
            assert platform not in sources
        assert sources, "every platform was skipped"

    def test_connect_all_creates_every_source(self):
        sources = health.create_sources(self.team, unconnected=frozenset())
        assert set(sources) == set(health.PLATFORM_STATES)

    def test_reseeding_retires_a_source_a_previous_run_left_behind(self):
        platform = next(iter(health.UNCONNECTED_PLATFORMS))
        health.create_sources(self.team, unconnected=frozenset())
        health.create_sources(self.team)
        assert not ExternalDataSource.objects.filter(team=self.team, source_type=platform, deleted=False).exists()

    def test_reseeding_retires_a_dropped_platform_but_keeps_real_integrations(self):
        # A platform removed from PLATFORM_STATES (moved to organic-only traffic) can still
        # have a live demo source from an earlier run when it was connected. It must be
        # retired, or the diagnostic keeps calling it connected and it never reaches
        # events_only — while a real integration the team owns stays untouched.
        ExternalDataSource.objects.create(
            team=self.team,
            source_id="marketing-demo-pinterestads",
            connection_id="marketing-demo-pinterestads",
            status=ExternalDataSource.Status.COMPLETED,
            source_type="PinterestAds",
            prefix="",
        )
        real = ExternalDataSource.objects.create(
            team=self.team,
            source_id="real-pinterest-integration",
            connection_id="real-pinterest-integration",
            status=ExternalDataSource.Status.COMPLETED,
            source_type="PinterestAds",
            prefix="",
        )
        health.create_sources(self.team)
        live_ids = set(
            ExternalDataSource.objects.filter(team=self.team, source_type="PinterestAds", deleted=False).values_list(
                "id", flat=True
            )
        )
        assert live_ids == {real.id}

    def test_every_unconnected_platform_still_has_traffic(self):
        # No traffic means no events, and no events means no `events_only` — the
        # platform just disappears instead of asking to be connected.
        for platform in health.UNCONNECTED_PLATFORMS:
            assert any(c.platform == platform and c.daily_sessions > 0 for c in CAMPAIGNS), platform

    def test_a_platform_sends_organic_traffic_with_no_source_behind_it(self):
        # The suppressed half of the gate: looks like an unconnected ad account on
        # utm_source, but every event says organic.
        assert any(c.utm_source == "pinterest" and c.utm_medium == "social" for c in FREE_CHANNELS)
        assert "PinterestAds" not in health.PLATFORM_STATES
        assert "PinterestAds" not in warehouse.NATIVE_SPECS

    def test_cost_tables_are_only_built_for_connected_platforms(self):
        sources = health.create_sources(self.team)
        assert not (set(warehouse.NATIVE_SPECS) - set(sources) - health.UNCONNECTED_PLATFORMS)
