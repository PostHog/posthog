from posthog.models.team import Team

from products.data_modeling.backend.facade.managed_viewset_hooks import ProvidedView
from products.engineering_analytics.backend.facade.warehouse_views import get_expected_warehouse_views


def get_provided_views(team: Team) -> list[ProvidedView]:
    return [
        ProvidedView(
            name=view.name,
            query=view.query,
            fields=view.fields,
            materialized=view.materialized,
            sync_frequency=view.sync_frequency,
            incremental_config=view.incremental_config,
        )
        for view in get_expected_warehouse_views(team)
    ]
