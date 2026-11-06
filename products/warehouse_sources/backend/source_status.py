"""Effective sync status of a source, derived from the states of its schemas.

The stored `ExternalDataSource.status` column is not kept current as schemas sync, so a source
whose schemas all completed can still read `Running`. Every reader that reports a source's
status uses `effective_source_status`, so the source list, the source detail and the scout
project profile agree about the same source.
"""

from collections.abc import Iterable
from typing import Protocol

from products.warehouse_sources.backend.facade.types import ExternalDataSchemaStatus

BILLING_LIMITS_STATUS = "Billing limits"
BILLING_LIMITS_TOO_LOW_STATUS = "Billing limits too low"


class SchemaSyncState(Protocol):
    @property
    def status(self) -> str | None: ...

    @property
    def should_sync(self) -> bool: ...


def effective_source_status(active_schemas: Iterable[SchemaSyncState], *, fallback: str) -> str:
    """Roll the states of a source's active schemas up into one source status.

    `active_schemas` are the non-deleted schemas that sync or carry an error. Only a schema that
    still syncs can make the source fail: a disabled schema can keep an old error. `fallback` is
    the stored source status, used only when no schema has a known state.
    """
    schemas = list(active_schemas)
    syncing = [schema for schema in schemas if schema.should_sync]

    if any(schema.status == ExternalDataSchemaStatus.FAILED for schema in syncing):
        return ExternalDataSchemaStatus.FAILED
    if any(schema.status == ExternalDataSchemaStatus.BILLING_LIMIT_REACHED for schema in syncing):
        return BILLING_LIMITS_STATUS
    if any(schema.status == ExternalDataSchemaStatus.BILLING_LIMIT_TOO_LOW for schema in syncing):
        return BILLING_LIMITS_TOO_LOW_STATUS
    if any(schema.status == ExternalDataSchemaStatus.PAUSED for schema in schemas):
        return ExternalDataSchemaStatus.PAUSED
    if any(schema.status == ExternalDataSchemaStatus.RUNNING for schema in schemas):
        return ExternalDataSchemaStatus.RUNNING
    if any(schema.status == ExternalDataSchemaStatus.COMPLETED for schema in schemas):
        return ExternalDataSchemaStatus.COMPLETED
    return fallback
