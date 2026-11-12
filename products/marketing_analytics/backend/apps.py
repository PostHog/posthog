from django.apps import AppConfig


class MarketingAnalyticsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.marketing_analytics.backend"
    label = "marketing_analytics"

    def ready(self) -> None:
        # Resolutions are written from the API, but the audit log must connect in every process, so it lives in a
        # light module that does not pull the viewset import graph into django.setup().
        from products.marketing_analytics.backend import activity_logging  # noqa: F401, PLC0415
