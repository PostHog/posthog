from importlib import import_module

from django.apps import AppConfig


class ErrorTrackingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.error_tracking.backend"
    label = "error_tracking"

    def ready(self) -> None:
        import_module("products.error_tracking.backend.signals")
