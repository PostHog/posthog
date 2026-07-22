"""
Contract types for warehouse_sources.

Stable, framework-free frozen dataclasses defining what this product exposes to the
rest of the codebase. No Django/DRF imports — enums are flattened to their ``str``
value, and encrypted or write-only fields (``job_inputs``, credential secrets,
pending-credential ``payload``) are deliberately omitted from the read surface.

These use ``pydantic.dataclasses.dataclass`` rather than the stdlib variant — same
syntax and ``is_dataclass()`` compatibility (so ``DataclassSerializer`` keeps
working), but with runtime validation on construction, so mapper/caller mistakes
surface at the facade boundary instead of as a malformed payload later.

The contract surface starts from currently-consumed fields only (see the Phase 1
demand map). The HogQL system-table model classes cross the boundary as objects via
``facade/hogql.py``, and temporal/source wiring via ``facade/temporal.py`` — not here.
"""

from datetime import datetime, time, timedelta
from typing import Literal
from uuid import UUID

from pydantic.dataclasses import dataclass

# --- Source ---


@dataclass(frozen=True)
class ExternalDataSource:
    """A configured external data source (the connection), read-only projection."""

    id: UUID
    team_id: int
    source_type: str
    status: str | None
    prefix: str | None
    access_method: str
    direct_query_enabled: bool
    created_via: str | None
    created_at: datetime
    updated_at: datetime | None
    # Direct-query capability, derived from source_type + access_method.
    is_direct_query: bool
    is_direct_postgres: bool
    is_direct_mysql: bool
    direct_engine: str | None


# --- Schema ---


@dataclass(frozen=True)
class ExternalDataSchema:
    """A table/stream within a source, read-only projection."""

    id: UUID
    team_id: int
    source_id: UUID | None
    table_id: UUID | None
    name: str
    label: str | None
    status: str | None
    should_sync: bool
    latest_error: str | None
    last_synced_at: datetime | None
    sync_type: str | None
    sync_frequency_interval: timedelta | None
    sync_time_of_day: time | None
    initial_sync_complete: bool
    description: str | None
    created_at: datetime
    updated_at: datetime | None
    # Derived/related, commonly read alongside the schema.
    normalized_name: str
    is_incremental: bool
    is_cdc: bool
    source_type: str | None


# --- Table ---


@dataclass(frozen=True)
class DataWarehouseTable:
    """A queryable warehouse table, read-only projection."""

    id: UUID
    team_id: int
    name: str
    format: str
    url_pattern: str
    queryable_folder: str | None
    columns: dict
    row_count: int | None
    size_in_s3_mib: float | None
    external_data_source_id: UUID | None
    credential_id: UUID | None
    created_at: datetime


# --- Job ---


@dataclass(frozen=True)
class ExternalDataJob:
    """A single sync run, read-only projection (billing/health surface)."""

    id: UUID
    team_id: int
    status: str
    latest_error: str | None
    finished_at: datetime | None
    rows_synced: int
    billable: bool | None
    schema_id: UUID | None
    pipeline_id: UUID | None
    workflow_id: str | None
    workflow_run_id: str | None
    created_at: datetime
    # Derived from the parent source, commonly read alongside the job.
    source_type: str | None
    source_prefix: str | None


# --- Column annotation ---


@dataclass(frozen=True)
class WarehouseColumnAnnotation:
    """A user/AI description attached to a warehouse table column."""

    id: UUID
    team_id: int
    table_id: UUID
    column_name: str
    description: str
    description_source: str
    is_user_edited: bool
    ai_model: str | None
    created_at: datetime
    updated_at: datetime


# --- Credential (read-only metadata; secrets are never exposed) ---


@dataclass(frozen=True)
class DataWarehouseCredential:
    """Read-only credential metadata. Access key/secret are intentionally excluded."""

    id: UUID
    team_id: int
    created_at: datetime


# --- Source health (sync-status rollup) ---

# Resolution order (strictest first): tables_missing > tables_failed > tables_disabled
# > error > never > stale > ok. The tables_* states only arise when the caller supplied
# required schema names; a source that doesn't exist is the caller's "not connected",
# never a value here — health is only computed for real sources.
SyncStatus = Literal[
    "ok",
    "stale",
    "error",
    "never",
    "tables_failed",
    "tables_disabled",
    "tables_missing",
]


@dataclass(frozen=True)
class SchemaHealth:
    """Per-schema sync state inside a source health rollup. When the health call was
    given required schema names, absent names appear with ``present=False``."""

    schema_name: str
    present: bool
    should_sync: bool
    status: str | None
    last_synced_at: datetime | None


@dataclass(frozen=True)
class SourceHealth:
    """The read behind "is my imported data fresh, and if not, why?"."""

    source_id: UUID
    team_id: int
    source_type: str
    prefix: str | None
    created_at: datetime
    sync_status: SyncStatus
    last_completed_sync_at: datetime | None
    # Latest FAILED job's error, only when it is newer than the last completed sync —
    # an error that a later successful sync resolved is not surfaced.
    last_unresolved_error: str | None
    rows_synced_last_24h: int
    rows_synced_last_7d: int
    schemas: list[SchemaHealth]
