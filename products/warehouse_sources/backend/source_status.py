"""Rolled-up sync status of a source, derived from its schemas.

`ExternalDataSource.status` is deprecated: it is written once when the source is created and
is not kept current as schemas sync, so a source whose schemas all completed still reads as
`Running`. Every consumer that reports a source's health must roll the schema statuses up
instead, through `derive_source_status`, so the source list, the source detail and the scout
project profile cannot disagree about the same source.
"""

from collections.abc import Sequence

from products.warehouse_sources.backend.facade.contracts import SchemaSyncState
from products.warehouse_sources.backend.types import ExternalDataSchemaStatus

BILLING_LIMITS_STATUS = "Billing limits"
BILLING_LIMITS_TOO_LOW_STATUS = "Billing limits too low"


def derive_source_status(active_schemas: Sequence[SchemaSyncState], *, fallback: str) -> str:
    """Roll the statuses of a source's active schemas up into one source status.

    `active_schemas` are the non-deleted schemas that either sync or carry an error. A negative
    status comes only from a schema the user still syncs: a disabled schema can keep an old error
    and must not drag the source into a failed state. `fallback` is the source's own deprecated
    `status` column, used only when no schema says anything.
    """
    syncing = [schema for schema in active_schemas if schema.should_sync]

    if any(schema.status == ExternalDataSchemaStatus.FAILED for schema in syncing):
        return ExternalDataSchemaStatus.FAILED
    if any(schema.status == ExternalDataSchemaStatus.BILLING_LIMIT_REACHED for schema in syncing):
        return BILLING_LIMITS_STATUS
    if any(schema.status == ExternalDataSchemaStatus.BILLING_LIMIT_TOO_LOW for schema in syncing):
        return BILLING_LIMITS_TOO_LOW_STATUS
    if any(schema.status == ExternalDataSchemaStatus.PAUSED for schema in active_schemas):
        return ExternalDataSchemaStatus.PAUSED
    if any(schema.status == ExternalDataSchemaStatus.RUNNING for schema in active_schemas):
        return ExternalDataSchemaStatus.RUNNING
    if any(schema.status == ExternalDataSchemaStatus.COMPLETED for schema in active_schemas):
        return ExternalDataSchemaStatus.COMPLETED
    return fallback
