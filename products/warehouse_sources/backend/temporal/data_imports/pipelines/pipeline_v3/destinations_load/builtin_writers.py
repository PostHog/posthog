"""Registering the writers that ship with warehouse sources.

Called once at consumer start rather than at import time, so importing anything in this
package does not drag in every destination's driver.

Destinations owned by another product register themselves through the same registry from
their own app-ready hook, which is why nothing here is special-cased by the processor.
"""

from __future__ import annotations

from products.warehouse_sources.backend.models.external_data_destination import ExternalDataDestination
from products.warehouse_sources.backend.temporal.data_imports.destinations.registry import register_destination_writer

# Every destination type this deployment can write. Used as the default claim scope, because
# claiming a type with no writer would lease the group and then fail every batch in it.
SUPPORTED_DESTINATION_TYPES = [
    ExternalDataDestination.Type.AZURE_BLOB,
    ExternalDataDestination.Type.BIGQUERY,
    ExternalDataDestination.Type.DATABRICKS,
    ExternalDataDestination.Type.POSTGRES,
    ExternalDataDestination.Type.REDSHIFT,
    ExternalDataDestination.Type.S3,
    ExternalDataDestination.Type.SNOWFLAKE,
]


_registered = False


def ensure_builtin_destination_writers_registered() -> None:
    """Register the built-in writers once, on first use.

    Registration used to happen at consumer start. Tying it to a bootstrap step means any
    other entry point into delivery resolves no writer at all, which fails the batch with
    "no writer registered" rather than anything that points at the cause. Doing it on demand
    keeps the vendor drivers off the import path just the same.
    """
    global _registered
    if _registered:
        return
    register_builtin_destination_writers()
    _registered = True


def register_builtin_destination_writers() -> None:
    # Imported here, not at module scope: each writer pulls in its vendor driver, and a consumer
    # scoped to one destination type should not pay for the other six.
    from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.writers.azure_blob import (  # noqa: PLC0415
        AzureBlobDestinationWriter,
    )
    from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.writers.bigquery import (  # noqa: PLC0415
        BigQueryDestinationWriter,
    )
    from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.writers.databricks import (  # noqa: PLC0415
        DatabricksDestinationWriter,
    )
    from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.writers.postgres import (  # noqa: PLC0415
        PostgresDestinationWriter,
    )
    from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.writers.redshift import (  # noqa: PLC0415
        RedshiftDestinationWriter,
    )
    from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.writers.s3 import (  # noqa: PLC0415
        S3DestinationWriter,
    )
    from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.writers.snowflake import (  # noqa: PLC0415
        SnowflakeDestinationWriter,
    )

    register_destination_writer(ExternalDataDestination.Type.AZURE_BLOB, AzureBlobDestinationWriter)
    register_destination_writer(ExternalDataDestination.Type.BIGQUERY, BigQueryDestinationWriter)
    register_destination_writer(ExternalDataDestination.Type.DATABRICKS, DatabricksDestinationWriter)
    register_destination_writer(ExternalDataDestination.Type.POSTGRES, PostgresDestinationWriter)
    register_destination_writer(ExternalDataDestination.Type.REDSHIFT, RedshiftDestinationWriter)
    register_destination_writer(ExternalDataDestination.Type.S3, S3DestinationWriter)
    register_destination_writer(ExternalDataDestination.Type.SNOWFLAKE, SnowflakeDestinationWriter)


def builtin_destination_types() -> list[str]:
    return list(SUPPORTED_DESTINATION_TYPES)
