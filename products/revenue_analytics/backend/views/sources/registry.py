from products.revenue_analytics.backend.views.core import Builder
from products.revenue_analytics.backend.views.sources.events import BUILDER as EVENTS_BUILDER
from products.revenue_analytics.backend.views.sources.stripe import BUILDER as STRIPE_BUILDER

BUILDERS: dict[str, Builder] = {
    "events": EVENTS_BUILDER,
    "stripe": STRIPE_BUILDER,
}
