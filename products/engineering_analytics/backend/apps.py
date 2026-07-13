"""Django app configuration for engineering_analytics."""

from django.apps import AppConfig

# Light re-export module (no heavy deps) — safe to import on the startup path.
from products.warehouse_sources.backend.facade.hooks import register_engineering_analytics_view_sync


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
