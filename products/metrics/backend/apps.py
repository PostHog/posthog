"""Django app configuration for metrics."""

from django.apps import AppConfig


class MetricsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.metrics.backend"
    label = "metrics"

    def ready(self) -> None:
        from products.metrics.backend.dashboard_import import receivers  # noqa: PLC0415 — needs the app registry

        receivers.connect()

        # The alerts platform imports no source, so metrics alerts register their wording and their
        # `source_config` schema with it here, in every process.
        from products.metrics.backend.alerts.registration import register  # noqa: PLC0415

        register()
