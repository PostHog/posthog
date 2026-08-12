"""Adapts this product's warehouse-view contract into data_modeling's ``ProvidedView`` shape.

Registered with data_modeling at AppConfig.ready() (see apps.py) so data_modeling can sync this
product's managed views without importing this product's read layer directly.
"""

from posthog.models.team import Team

from products.data_modeling.backend.facade.managed_viewset_hooks import ProvidedView
from products.engineering_analytics.backend.facade.warehouse_views import get_expected_warehouse_views


def get_provided_views(team: Team) -> list[ProvidedView]:
    """The engineering-analytics warehouse views, adapted for data_modeling's managed-viewset sync.

    Non-materialized: the view is computed at query time so a Depot rate change propagates
    immediately and it never joins the materialization schedule / managed DAG.
    """
    return [
        ProvidedView(name=view.name, query=view.query, fields=view.fields, materialized=False)
        for view in get_expected_warehouse_views(team)
    ]
