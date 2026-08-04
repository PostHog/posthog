from datetime import UTC, datetime

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.data_freshness import TeamProductFreshness, discover_data_sources
from posthog.schema_enums import ProductKey

from products.signals.backend.source_dormancy import PRODUCT_BEHIND_SOURCE, dormant_source_products

_FRESHNESS_PATH = "products.signals.backend.source_dormancy.get_team_product_freshness"

_ALL_JUDGED = set(PRODUCT_BEHIND_SOURCE)


def _freshness(*products: ProductKey, degraded: bool = False) -> TeamProductFreshness:
    seen = datetime(2026, 8, 1, tzinfo=UTC)
    return TeamProductFreshness(last_data_at_by_product=dict.fromkeys(products, seen), degraded=degraded)


class TestSourceDormancy(BaseTest):
    @parameterized.expand(
        [
            # Nothing anywhere: every judged source is flagged, and equality is what proves the
            # external-tool sources (GitHub, Linear, Zendesk, …) are absent rather than merely
            # unasserted.
            ("nothing_at_all", _freshness(), _ALL_JUDGED),
            # Replay covers Replay Vision too, since scanners watch recordings.
            (
                "live_replay_and_errors",
                _freshness(ProductKey.SESSION_REPLAY, ProductKey.ERROR_TRACKING),
                _ALL_JUDGED
                - {
                    p
                    for p, k in PRODUCT_BEHIND_SOURCE.items()
                    if k in (ProductKey.SESSION_REPLAY, ProductKey.ERROR_TRACKING)
                },
            ),
            # An unreachable store looks exactly like an unused product, and telling someone to
            # switch off a source that works is worse than saying nothing.
            ("degraded_probe", _freshness(degraded=True), set()),
        ]
    )
    def test_dormancy(self, _name: str, freshness: TeamProductFreshness, expected: set) -> None:
        with patch(_FRESHNESS_PATH, return_value=freshness):
            assert dormant_source_products(self.team) == expected

    def test_every_mapped_product_is_declared(self) -> None:
        # A product with no `DATA_SOURCES` never appears in the freshness result, so mapping a
        # source onto one would mark it dormant forever. Silence about an unmapped source is safe;
        # this is the direction that isn't.
        declared = {spec.product for spec in discover_data_sources()}
        assert set(PRODUCT_BEHIND_SOURCE.values()) <= declared
