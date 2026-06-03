from django.apps import AppConfig


class LogsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.logs.backend"
    label = "logs"

    def ready(self) -> None:
        # Connect the logs alert / sampling-rule activity-log receivers at app-population. They used
        # to wire in as an import side effect of the viewset modules; the lazy API router no longer
        # pulls that, so a process that never builds the router (celery, temporal, migrate) would
        # drop audit logs on those writes. Both modules are light, so importing them here stays cheap.
        from products.logs.backend import alerts_api, sampling_api  # noqa: F401, PLC0415
