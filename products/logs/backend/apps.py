from django.apps import AppConfig


class LogsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.logs.backend"
    label = "logs"

    def ready(self) -> None:
        # Connect the logs alert / sampling-rule activity-log receivers at app-population, from a
        # dedicated light module. They must not live in the viewset modules: the lazy API router no
        # longer pulls those, and alerts_api transitively imports the whole query-runner layer,
        # which would drag posthog.schema and HogQL into django.setup() for every process type.
        from products.logs.backend import activity_logging  # noqa: F401, PLC0415
