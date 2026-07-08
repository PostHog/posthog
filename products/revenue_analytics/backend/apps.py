from django.apps import AppConfig


class RevenueAnalyticsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.revenue_analytics.backend"
    label = "revenue_analytics"

    def ready(self) -> None:
        # Register the warehouse view-sync so the data-import pipeline can trigger it without
        # importing this product (it depends on warehouse_sources). The impl is imported lazily
        # to keep the revenue views/orchestrator off the django.setup() path.
        from products.warehouse_sources.backend.facade.hooks import register_revenue_view_sync

        def _sync_revenue_views(schema: object, source: object) -> None:
            from products.revenue_analytics.backend.warehouse_view_sync import (  # noqa: PLC0415
                sync_revenue_analytics_views,
            )

            sync_revenue_analytics_views(schema, source)  # type: ignore[arg-type]

        register_revenue_view_sync(_sync_revenue_views)
