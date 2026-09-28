"""Django app configuration for tracing."""

from django.apps import AppConfig


class TracingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.tracing.backend"
    label = "tracing"

    def ready(self) -> None:
        # Connect the retention-rule activity-log receiver at app-population, from a dedicated light
        # module, so it is wired in every process type and not only where the viewset is imported.
        from products.tracing.backend import activity_logging  # noqa: F401, PLC0415
