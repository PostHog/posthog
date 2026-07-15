"""Django app configuration for engineering_analytics."""

from typing import TYPE_CHECKING

from django.apps import AppConfig

# Light re-export modules (no heavy deps) — safe to import on the startup path.
from products.data_modeling.backend.facade.managed_viewset_hooks import ProvidedView, register_expected_views_provider
from products.warehouse_sources.backend.facade.hooks import register_engineering_analytics_view_sync
from products.warehouse_sources.backend.facade.types import DataWarehouseManagedViewSetKind

if TYPE_CHECKING:
    from posthog.models.team import Team


class EngineeringAnalyticsConfig(AppConfig):
    name = "products.engineering_analytics.backend"
    label = "engineering_analytics"

    def ready(self) -> None:
        # Register the warehouse view-sync so the data-import pipeline can trigger it without
        # importing this product (it depends on warehouse_sources). The impl is imported lazily to
        # keep the read layer / data_modeling off the django.setup() path.
        def _sync_engineering_analytics_views(schema: object, source: object) -> None:
            from products.engineering_analytics.backend.warehouse_view_sync import (  # noqa: PLC0415 — keeps data_modeling + read layer off the startup path
                sync_engineering_analytics_views,
            )

            sync_engineering_analytics_views(schema, source)  # type: ignore[arg-type]

        register_engineering_analytics_view_sync(_sync_engineering_analytics_views)

        # Register the expected-views provider so data_modeling can sync this product's managed
        # views without importing its read layer. The impl is imported lazily to keep it off the
        # django.setup() path.
        def _get_provided_views(team: "Team") -> list[ProvidedView]:
            from products.engineering_analytics.backend.warehouse_view_provider import (  # noqa: PLC0415 — keeps the read layer off the startup path
                get_provided_views,
            )

            return get_provided_views(team)

        register_expected_views_provider(DataWarehouseManagedViewSetKind.ENGINEERING_ANALYTICS, _get_provided_views)
