"""Django app configuration for warehouse_sources."""

from django.apps import AppConfig


class WarehouseSourcesConfig(AppConfig):
    name = "products.warehouse_sources.backend"
    label = "warehouse_sources"

    def ready(self) -> None:
        # Connect the external-data-source / -schema activity-log receivers at app-population. They
        # used to wire in as an import side effect of the viewset modules; the lazy API router no
        # longer pulls that, so a process that never builds the router (notably the Temporal data
        # import workflows, which mutate these models heavily) would drop audit logs. They live in a
        # light activity_logging module because both viewsets pull in dlt via the data-import chain.
        from products.warehouse_sources.backend import activity_logging  # noqa: F401, PLC0415
