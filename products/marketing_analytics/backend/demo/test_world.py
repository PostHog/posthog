from django.test import SimpleTestCase

from products.marketing_analytics.backend.demo.world import CAMPAIGNS, FREE_CHANNELS
from products.marketing_analytics.backend.services.native_integrations import lookup_alias

PAID_MEDIUMS = {"cpc", "cpm", "cpv", "cpa", "ppc", "retargeting"}


def _is_paid_medium(medium: str | None) -> bool:
    if not medium:
        return False
    return medium in PAID_MEDIUMS or medium.startswith("paid")


class TestDemoWorldPaidSignals(SimpleTestCase):
    """The paid/organic split the `connect_source` gate reads.

    Both sides have to exist here or the gate is untestable against demo data: it
    suppresses only on positive evidence (mediums tagged, none of them paid).
    """

    def test_some_organic_traffic_carries_an_ad_platform_source_name(self):
        organic_on_ad_alias = [
            c
            for c in FREE_CHANNELS
            if c.utm_source
            and lookup_alias(c.utm_source)
            and c.utm_medium
            and not _is_paid_medium(c.utm_medium)
            and not c.extra_properties
        ]
        assert organic_on_ad_alias, (
            "no free channel looks like an unconnected ad account on utm_source alone, "
            "so nothing exercises suppressing connect_source"
        )

    def test_paid_traffic_is_recognisable_by_medium_or_click_id(self):
        for campaign in CAMPAIGNS:
            if campaign.daily_sessions == 0:  # not_linked: spend with no tagged events
                continue
            assert _is_paid_medium(campaign.utm_medium) or campaign.click_id_property, (
                f"{campaign.name} spends money but carries no paid signal"
            )

    def test_click_ids_use_the_property_name_the_sdk_writes(self):
        # `$gclid` is the person-scoped copy; the event carries the unprefixed one, and
        # that is what every paid-detection query reads.
        for campaign in CAMPAIGNS:
            if campaign.click_id_property:
                assert not campaign.click_id_property.startswith("$"), campaign.name

    def test_a_paid_click_id_exists_without_any_medium(self):
        autotagged = [c for c in FREE_CHANNELS if c.extra_properties.get("gad_source") and not c.utm_medium]
        assert autotagged, "nothing covers paid traffic detectable only by gad_source"

    def test_a_paid_click_id_exists_without_any_utm(self):
        # gad_source above still rides alongside a utm_source, so it never exercises the
        # click-id branch on its own.
        assert [c for c in FREE_CHANNELS if c.click_id_property == "gclid" and not c.utm_source], (
            "nothing covers a paid click whose only evidence is the click id"
        )

    def test_fbclid_exists_without_any_other_paid_signal(self):
        assert [
            c for c in FREE_CHANNELS if c.click_id_property == "fbclid" and not c.utm_source and not c.extra_properties
        ], "nothing covers fbclid as the sole identifier, so excluding it proves nothing"

    def test_a_campaign_exists_with_nothing_naming_its_source(self):
        assert [
            c
            for c in FREE_CHANNELS
            if c.utm_campaign and not c.utm_source and not c.click_id_property and not c.extra_properties
        ], "nothing covers a campaign-only pageview, so the source requirement is untested"
