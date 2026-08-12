"""Adapts this product's revenue-analytics views into data_modeling's ``ProvidedView`` shape.

Registered with data_modeling at AppConfig.ready() (see apps.py) so data_modeling can sync this
product's managed views without importing this product's views/orchestrator directly.
"""

from posthog.models.team import Team

from products.data_modeling.backend.facade.managed_viewset_hooks import ProvidedView
from products.revenue_analytics.backend.views.orchestrator import build_all_revenue_analytics_views


def get_provided_views(team: Team) -> list[ProvidedView]:
    """Reuses build_all_revenue_analytics_views() from Database.create_for logic.

    For each source (events + external data sources), creates 6 views: customer, charge,
    subscription, revenue_item, product, mrr.
    """
    return [
        ProvidedView(name=view.name, query=view.query, fields=view.fields, materialized=True)
        for view in build_all_revenue_analytics_views(team)
    ]
