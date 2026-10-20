"""Django app configuration for metrics."""

from django.apps import AppConfig


class MetricsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.metrics.backend"
    label = "metrics"

    def ready(self) -> None:
        from products.metrics.backend import task_profiles  # noqa: PLC0415
        from products.metrics.backend.dashboard_import import receivers  # noqa: PLC0415 — needs the app registry
        from products.tasks.backend.facade.profiles import register_task_profiles  # noqa: PLC0415

        register_task_profiles(task_profiles.PROFILES)
        receivers.connect()
