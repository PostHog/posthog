from typing import TYPE_CHECKING

from django.apps import AppConfig

# Light re-export modules (no heavy deps), safe to import on the startup path.
from products.data_modeling.backend.facade.managed_viewset_hooks import ProvidedView, register_expected_views_provider
from products.warehouse_sources.backend.facade.hooks import register_engineering_analytics_view_sync
from products.warehouse_sources.backend.facade.types import DataWarehouseManagedViewSetKind

if TYPE_CHECKING:
    from posthog.models.team import Team

    from products.warehouse_sources.backend.facade.models import ExternalDataSchema, ExternalDataSource


def _sync_views(schema: "ExternalDataSchema", source: "ExternalDataSource") -> None:
    from products.engineering_analytics.backend.warehouse_view_sync import (  # noqa: PLC0415 - keeps data_modeling + the read layer off the startup path
        sync_engineering_analytics_views,
    )

    sync_engineering_analytics_views(schema, source)


def _provided_views(team: "Team") -> list[ProvidedView]:
    from products.engineering_analytics.backend.warehouse_view_provider import (  # noqa: PLC0415 - keeps the read layer off the startup path
        get_provided_views,
    )

    return get_provided_views(team)


class EngineeringAnalyticsConfig(AppConfig):
    name = "products.engineering_analytics.backend"
    label = "engineering_analytics"

    def ready(self) -> None:
        # The data-import pipeline and data_modeling call this product through these hooks, because
        # importing it from either would be a dependency cycle.
        register_engineering_analytics_view_sync(_sync_views)
        register_expected_views_provider(DataWarehouseManagedViewSetKind.ENGINEERING_ANALYTICS, _provided_views)
