"""
Data and error types that cross the managed_warehouse boundary.

Pure Python — no Django, no DRF, no duckdb — so consumers can import these without
dragging the product's runtime onto their import path. The product's internals import
them from here too, so there is exactly one definition of each.

These stay plain ``dataclass`` rather than ``pydantic.dataclasses.dataclass``: they
carry query results on a hot path, and per-row validation on construction would be a
behavior change, not a contract improvement.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

__all__ = [
    "CPUnavailableError",
    "DuckgresQueryServerConfig",
    "DuckgresStoredBucketConfig",
    "DuckgresStoredServerConfig",
    "DuckLakeCatalogConnectionConfig",
    "DuckLakeQueryResult",
    "DuckLakeTableResult",
    "ManagedWarehouseBackfillState",
    "ManagedWarehouseProvisionStatus",
    "ManagedWarehouseTableNames",
    "ManagedWarehouseTeamMembership",
]


class CPUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True, kw_only=True)
class ManagedWarehouseProvisionStatus:
    """Whether an organization has a stored managed-warehouse connection."""

    provisioned: bool


@dataclass(frozen=True, kw_only=True)
class DuckgresQueryServerConfig:
    """Stored Postgres-wire connection details for an organization's Duckgres server."""

    host: str
    port: int
    flight_port: int
    database: str
    username: str
    password: str


@dataclass(frozen=True, kw_only=True)
class DuckLakeCatalogConnectionConfig:
    """Stored DuckLake metadata-store connection details for a managed warehouse."""

    host: str
    port: int
    database: str
    username: str | None
    password: str | None


@dataclass(frozen=True, kw_only=True)
class DuckgresStoredBucketConfig:
    """Control-plane-owned object-storage location persisted for a managed warehouse."""

    bucket: str
    region: str | None


@dataclass(frozen=True, kw_only=True)
class DuckgresStoredServerConfig:
    """The persisted managed-warehouse configuration available outside the product."""

    organization_id: UUID
    query_server: DuckgresQueryServerConfig
    catalog: DuckLakeCatalogConnectionConfig | None
    bucket: DuckgresStoredBucketConfig | None


@dataclass(frozen=True, kw_only=True)
class ManagedWarehouseTableNames:
    """Resolved per-team table and schema names owned by the control plane."""

    events_table: str
    persons_table: str
    data_imports_schema: str


@dataclass(frozen=True, kw_only=True)
class ManagedWarehouseTeamMembership:
    """A team's managed-warehouse membership as read from the control plane."""

    team_id: int
    organization_id: str
    schema_name: str
    enabled: bool
    backfill_enabled: bool
    table_names: ManagedWarehouseTableNames
    earliest_event_date: date | None


@dataclass(frozen=True, kw_only=True)
class ManagedWarehouseBackfillState:
    """The existing warehouse-status backfill shape, represented at the facade boundary."""

    has_backfill: bool
    table_suffix: str | None


@dataclass
class DuckLakeQueryResult:
    columns: list[str]
    types: list[str]
    results: list[list[Any]]
    sql: str
    hogql: str | None = None
    # connect_ms includes control-plane activation of a cold tenant; query_ms is the query alone.
    connect_ms: float | None = None
    query_ms: float | None = None


@dataclass
class DuckLakeTableResult:
    schema_name: str
    table_name: str
    row_count: int
    file_size_bytes: int = 0
    file_size_delta_bytes: int = 0
