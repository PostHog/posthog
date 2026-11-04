"""Django app configuration for warehouse_sources."""

from django.apps import AppConfig


class WarehouseSourcesConfig(AppConfig):
    name = "products.warehouse_sources.backend"
    label = "warehouse_sources"

    def ready(self) -> None:
        # Connect the external-data-source / -schema activity-log receivers at app-population. The
        # lazy API router does not import the viewset modules, so a process that never builds the
        # router (notably the Temporal data import workflows, which mutate these models heavily)
        # would otherwise drop audit logs. They live in a light activity_logging module because both
        # viewsets pull in dlt via the data-import chain.
        from products.warehouse_sources.backend import activity_logging  # noqa: F401, PLC0415

        # The alerts platform imports no source, so warehouse alerts register their wording and
        # their `source_config` schema with it here, in every process.
        from products.warehouse_sources.backend.sync_alerts.registration import register  # noqa: PLC0415

        register()

        # Source kinds have no generated accessor. Callers reach their rows through `IntegrationManager.source(kind)`.
        # The SDK imports the Integration model, which needs the app registry.
        from posthog.integrations import AuthType, register_source_kinds  # noqa: PLC0415

        from products.warehouse_sources.backend.facade.credential_auth_types import (  # noqa: PLC0415
            CREDENTIAL_AUTH_TYPES,
        )

        register_source_kinds({kind: AuthType(auth_type) for kind, auth_type in CREDENTIAL_AUTH_TYPES.items()})
