"""Effective sync status of a source, derived from the states of its schemas.

The stored `ExternalDataSource.status` column is not kept current as schemas sync, so a source
whose schemas all completed can still read `Running`. Every reader that reports a source's
status uses `effective_source_status`, so the source list, the source detail and the scout
project profile agree about the same source. `system.data_warehouse_sources` applies the same
rule in SQL from `SOURCE_STATUS_BY_SCHEMA_STATUS`.
"""

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Protocol

from products.warehouse_sources.backend.facade.types import (
    SOURCE_STATUS_BY_SCHEMA_STATUS,
    SOURCE_STATUS_WITH_NO_ENABLED_SCHEMA,
)

_NEVER = datetime.min.replace(tzinfo=UTC)


class SchemaSyncState(Protocol):
    @property
    def status(self) -> str | None: ...

    @property
    def should_sync(self) -> bool: ...


class SchemaErrorState(SchemaSyncState, Protocol):
    @property
    def latest_error(self) -> str | None: ...

    @property
    def updated_at(self) -> datetime | None: ...


def effective_source_status(schemas: Iterable[SchemaSyncState], *, fallback: str) -> str:
    """Roll the states of a source's non-deleted schemas up into one source status.

    Only an enabled schema counts: a disabled one keeps whatever state it stopped in. A source
    whose schemas are all disabled is paused. `fallback` is the stored source status, used only
    when the source has no schemas or none of its enabled schemas has a known state.
    """
    schemas = list(schemas)
    syncing = [schema for schema in schemas if schema.should_sync]
    if schemas and not syncing:
        return SOURCE_STATUS_WITH_NO_ENABLED_SCHEMA
    for schema_status, source_status in SOURCE_STATUS_BY_SCHEMA_STATUS:
        if any(schema.status == schema_status for schema in syncing):
            return source_status
    return fallback


def latest_source_error(schemas: Iterable[SchemaErrorState]) -> str | None:
    """The newest error among the source's enabled schemas. A disabled schema keeps an old error."""
    with_error = [schema for schema in schemas if schema.should_sync and schema.latest_error]
    if not with_error:
        return None
    return max(with_error, key=lambda schema: schema.updated_at or _NEVER).latest_error
