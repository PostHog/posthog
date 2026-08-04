"""Which enabled signal sources are watching a product the team doesn't actually use.

Turning a source on is a config decision, and a reasonable one to get wrong: the setup agent
enables what looks plausible, and nothing later says the product behind it has never sent
anything. So a project can sit with Support watching for tickets that will never arrive, and the
inbox stays quiet for a reason nobody can see.

This reads the shared per-product freshness in `posthog.data_freshness` rather than counting
signals, because a source that has emitted nothing is ambiguous — it might be watching a healthy
product with nothing wrong. Whether the underlying product received data at all isn't.

Only PostHog-native sources are judged. A source fed by an external tool (GitHub, Linear,
Zendesk, pganalyze) has its data arrive through a warehouse sync or a webhook, and the freshness
probes don't resolve per-connection, so those are left unjudged rather than guessed at.
"""

from posthog.data_freshness import LOOKBACK_DAYS, get_team_product_freshness
from posthog.models.team.team import Team
from posthog.schema_enums import ProductKey

from products.signals.backend.enums import SignalSourceProduct

__all__ = ["LOOKBACK_DAYS", "PRODUCT_BEHIND_SOURCE", "dormant_source_products"]

# The PostHog product each signal source reads from. Sources absent from this map are never
# reported dormant — either no freshness declaration can answer for them, or they're fed by an
# external tool whose sync this can't see.
PRODUCT_BEHIND_SOURCE: dict[SignalSourceProduct, ProductKey] = {
    SignalSourceProduct.SESSION_REPLAY: ProductKey.SESSION_REPLAY,
    # Scanners watch recordings, so replay going quiet is what strands them too.
    SignalSourceProduct.REPLAY_VISION: ProductKey.SESSION_REPLAY,
    SignalSourceProduct.ERROR_TRACKING: ProductKey.ERROR_TRACKING,
    SignalSourceProduct.LLM_ANALYTICS: ProductKey.LLM_ANALYTICS,
    SignalSourceProduct.LOGS: ProductKey.LOGS,
    SignalSourceProduct.CONVERSATIONS: ProductKey.CONVERSATIONS,
    SignalSourceProduct.ANALYTICS: ProductKey.PRODUCT_ANALYTICS,
}


def dormant_source_products(team: Team) -> set[SignalSourceProduct]:
    """The judgeable source products whose backing product sent nothing in the lookback window.

    Empty when a probe failed: an unreachable store is indistinguishable from an unused product,
    and telling someone to turn off a source that works is worse than saying nothing.
    """
    freshness = get_team_product_freshness(team)
    if freshness.degraded:
        return set()
    return {
        source for source, product in PRODUCT_BEHIND_SOURCE.items() if product not in freshness.last_data_at_by_product
    }
