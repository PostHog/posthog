from datetime import UTC, datetime

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from posthog.data_freshness import TeamProductFreshness
from posthog.schema_enums import ProductKey

from products.signals.backend.enums import SignalSourceProduct
from products.signals.backend.source_dormancy import dormant_source_products

_FRESHNESS_PATH = "products.signals.backend.source_dormancy.get_team_product_freshness"


def _freshness(*products: ProductKey, degraded: bool = False) -> TeamProductFreshness:
    seen = datetime(2026, 8, 1, tzinfo=UTC)
    return TeamProductFreshness(last_data_at_by_product=dict.fromkeys(products, seen), degraded=degraded)


class TestSourceDormancy(APIBaseTest):
    def test_products_with_data_are_not_dormant(self):
        with patch(_FRESHNESS_PATH, return_value=_freshness(ProductKey.ERROR_TRACKING, ProductKey.SESSION_REPLAY)):
            dormant = dormant_source_products(self.team)

        assert SignalSourceProduct.ERROR_TRACKING not in dormant
        assert SignalSourceProduct.SESSION_REPLAY not in dormant
        # Replay Vision reads recordings, so live replay keeps it out too.
        assert SignalSourceProduct.REPLAY_VISION not in dormant
        # The case this exists for: support enabled on a project that has never used it.
        assert SignalSourceProduct.CONVERSATIONS in dormant

    def test_external_tool_sources_are_never_judged(self):
        # Their data arrives via a warehouse sync or webhook that the freshness probes don't
        # resolve per connection, so silence about them is the honest answer.
        with patch(_FRESHNESS_PATH, return_value=_freshness()):
            dormant = dormant_source_products(self.team)

        for source in (SignalSourceProduct.GITHUB, SignalSourceProduct.LINEAR, SignalSourceProduct.ZENDESK):
            assert source not in dormant

    def test_degraded_probe_reports_nothing(self):
        # An unreachable store looks exactly like an unused product. Telling someone to switch off
        # a source that works is worse than saying nothing at all.
        with patch(_FRESHNESS_PATH, return_value=_freshness(degraded=True)):
            assert dormant_source_products(self.team) == set()
