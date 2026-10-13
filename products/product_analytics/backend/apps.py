from django.apps import AppConfig


class ProductAnalyticsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.product_analytics.backend"
    label = "product_analytics"

    def ready(self) -> None:
        from products.product_analytics.backend import authorization_signals  # noqa: F401, PLC0415
