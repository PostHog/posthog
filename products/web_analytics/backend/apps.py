from django.apps import AppConfig


class WebAnalyticsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.web_analytics.backend"
    label = "web_analytics"

    def ready(self) -> None:
        from products.web_analytics.backend import (
            heatmap_history_expiry,  # noqa: F401, PLC0415 — registers model receivers
        )
