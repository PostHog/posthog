from posthog.test.base import BaseTest

from products.marketing_analytics.backend.demo import health, warehouse
from products.marketing_analytics.backend.demo.world import CAMPAIGNS, FREE_CHANNELS
from products.marketing_analytics.backend.services.native_integrations import (
    EXTERNAL_SOURCE_TYPE_TO_NATIVE,
    NATIVE_TO_KEY,
    lookup_alias,
)
from products.warehouse_sources.backend.facade.models import ExternalDataSource

PAID_MEDIUMS = frozenset({"cpc", "cpm", "cpv", "cpa", "ppc", "retargeting"})


def _organic_only_platforms_in_fixture() -> frozenset[str]:
    """Sourceless native platforms the free channels name via utm_source, sending no paid traffic.

    Both halves matter. A connected platform never reaches `events_only` however its traffic
    is tagged — Meta and LinkedIn also send organic channels and belong nowhere near this set.
    And one paid channel stops the gate suppressing, which makes it Reddit's case, not
    Pinterest's.
    """
    by_platform: dict[str, list[str | None]] = {}
    for source_type, native in EXTERNAL_SOURCE_TYPE_TO_NATIVE.items():
        if source_type in health.PLATFORM_STATES and source_type not in health.UNCONNECTED_PLATFORMS:
            continue
        key = NATIVE_TO_KEY[native]
        mediums = [c.utm_medium for c in FREE_CHANNELS if lookup_alias(c.utm_source or "") == key]
        if mediums:
            by_platform[source_type] = mediums
    return frozenset(
        source_type
        for source_type, mediums in by_platform.items()
        if all(medium and medium not in PAID_MEDIUMS for medium in mediums)
    )


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

    def test_organic_only_platforms_match_the_channels_the_fixture_actually_sends(self):
        # Derived from the channel list rather than spot-checked, so the constant can't be
        # emptied or fall behind a newly added organic channel — either way the summary's
        # events_only count would go quietly wrong.
        assert health.ORGANIC_ONLY_PLATFORMS == _organic_only_platforms_in_fixture()

    def test_organic_only_platforms_stay_out_of_the_staged_tables(self):
        # Being absent from both is what keeps `--connect-all` from connecting them and
        # erasing the suppressed half of the gate.
        for platform in health.ORGANIC_ONLY_PLATFORMS:
            assert platform not in health.PLATFORM_STATES, platform
            assert platform not in warehouse.NATIVE_SPECS, platform

    def test_organic_only_platforms_are_never_also_staged_as_unconnected(self):
        # Both sets feed the dry-run summary's events_only count; an overlap would
        # double-count and mean a platform is claimed to be organic-only and paid at once.
        assert not (health.ORGANIC_ONLY_PLATFORMS & health.UNCONNECTED_PLATFORMS)

    def test_cost_tables_are_only_built_for_connected_platforms(self):
        sources = health.create_sources(self.team)
        assert not (set(warehouse.NATIVE_SPECS) - set(sources) - health.UNCONNECTED_PLATFORMS)
