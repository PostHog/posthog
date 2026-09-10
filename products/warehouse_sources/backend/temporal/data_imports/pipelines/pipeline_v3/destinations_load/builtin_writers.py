"""Registering the writers that ship with warehouse sources.

Postgres and Redshift ship here. The other destination types have writers built on batch exports'
clients, parked on `tom/dwh-destination-writers-parked`, and each one lands in its own change
once it has been run against that warehouse. Registering a type whose writer has never
executed is how a customer discovers it does not work.

Registration happens on first use rather than at a bootstrap step, so any entry point into
delivery resolves a writer. Each writer pulls in its vendor driver, so the imports stay inside
the function and a deployment only loads what it writes to.
"""

from __future__ import annotations

from products.warehouse_sources.backend.models.external_data_destination import ExternalDataDestination
from products.warehouse_sources.backend.temporal.data_imports.destinations.registry import register_destination_writer

# Every destination type this deployment can write. Used as the default claim scope, because
# claiming a type with no writer would lease the group and then fail every batch in it.
SUPPORTED_DESTINATION_TYPES: list[str] = [
    str(ExternalDataDestination.Type.POSTGRES),
    str(ExternalDataDestination.Type.REDSHIFT),
]


_registered = False


def ensure_builtin_destination_writers_registered() -> None:
    """Register the built-in writers once, on first use."""
    global _registered
    if _registered:
        return
    register_builtin_destination_writers()
    _registered = True


def register_builtin_destination_writers() -> None:
    from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.writers.postgres import (  # noqa: PLC0415
        PostgresDestinationWriter,
    )
    from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.writers.redshift import (  # noqa: PLC0415
        RedshiftDestinationWriter,
    )

    register_destination_writer(ExternalDataDestination.Type.POSTGRES, PostgresDestinationWriter)
    register_destination_writer(ExternalDataDestination.Type.REDSHIFT, RedshiftDestinationWriter)


def builtin_destination_types() -> list[str]:
    return list(SUPPORTED_DESTINATION_TYPES)
