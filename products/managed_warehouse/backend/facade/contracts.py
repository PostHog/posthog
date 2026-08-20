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

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from posthog.dataclasses import frozen

__all__ = [
    "CPUnavailableError",
    "DuckgresQueryServerConfig",
    "DuckgresStoredBucketConfig",
    "DuckgresStoredServerConfig",
    "DuckLakeCatalogConnectionConfig",
    "DuckLakeCompiledQuery",
    "DuckLakeQueryResult",
    "DuckLakeS3Secret",
    "DuckLakeTableResult",
    "DucklingTables",
    "ManagedWarehouseBackfillState",
    "ManagedWarehousePostgresConnection",
    "ManagedWarehouseProvisionStatus",
    "ManagedWarehouseSourceAuth",
    "ManagedWarehouseSourceJobRecord",
    "ManagedWarehouseSourceJobStatus",
    "ManagedWarehouseSourceJobUpdate",
    "ManagedWarehouseSourceJobWorkflow",
    "ManagedWarehouseTableNames",
    "ManagedWarehouseTeamMembership",
    "ServiceCredential",
    "ServiceCredentialConnect",
    "ServiceCredentialUnavailable",
]


class CPUnavailableError(RuntimeError):
    pass


@frozen
class ServiceCredentialConnect:
    """Where to dial for a minted service credential, returned by the CP on
    every successful mint (see duckgres/CLAUDE.md "Service Credentials").

    The host is the TLS-pinned per-org ingress (``<org-id>.dw.us.postwh.com``);
    the caller's network resolves it (AWS PrivateLink for dagster) — duckgres
    is never in the resolution path. Carrying these on the credential is what
    lets service-credential connections stop reading host/port/database from
    the stored ``DuckgresServer`` row.
    """

    host: str
    port: int
    database: str
    sslmode: str


@dataclass(frozen=True)
class ServiceCredential:
    """An org-scoped per-credential grant minted by the duckgres control
    plane, for one run's new duckgres connections (RDS-IAM pattern:
    short-lived, scoped, disposable — see duckgres/CLAUDE.md "Service
    Credentials").

    Each mint creates its own server-side grant row, so minting never
    disturbs sessions created by other mints. ``principal`` is audit metadata
    and does not select an existing grant. ``credential_id`` is the
    CP-generated identifier (``svc_<24 random hex>``); it is not a secret and
    may be logged. Callers retain it to refresh the credential they minted.
    Every successful mint and refresh includes ``credential_secret``.

    ``connect`` carries the CP-issued dial target for the credential and is
    REQUIRED on every successful mint — a mint response without it is an
    older CP than the contract and must be rejected at mint time.
    """

    credential_id: str
    # repr=False: a dataclass repr lands credentials into any traceback,
    # pytest assertion diff, or log line that stringifies the object.
    credential_secret: str = field(repr=False)
    expires_at: datetime
    connect: ServiceCredentialConnect


class ServiceCredentialUnavailable(RuntimeError):
    """The control plane couldn't issue a service credential (unreachable,
    org/team not provisioned, or a 5xx). Callers decide whether to fall back
    to the stored server login or fail the run."""


@frozen
class ManagedWarehousePostgresConnection:
    host: str
    port: int
    database: str
    username: str
    password: str = field(repr=False)
    sslmode: str


@frozen
class ManagedWarehouseSourceAuth:
    """Non-secret source fields needed to choose managed warehouse authentication."""

    prefix: str | None
    system_managed: bool
    credential_kind: str | None
    lifecycle_generation: int | None


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
    password: str = field(repr=False)


@dataclass(frozen=True, kw_only=True)
class DuckLakeCatalogConnectionConfig:
    """Stored DuckLake metadata-store connection details for a managed warehouse."""

    host: str
    port: int
    database: str
    username: str | None
    password: str | None = field(repr=False)


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


@frozen
class DucklingTables:
    """The per-team events/persons duckling table names the backfill writes to."""

    events_table: str
    persons_table: str


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


class ManagedWarehouseSourceJobWorkflow(StrEnum):
    COPY = "copy"
    REGISTER = "register"


class ManagedWarehouseSourceJobStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    STALE = "stale"


@dataclass(frozen=True, kw_only=True)
class ManagedWarehouseSourceJobUpdate:
    team_id: int
    schema_ids: list[UUID]
    source_job_id: str
    attempt_id: str
    workflow_type: ManagedWarehouseSourceJobWorkflow
    status: ManagedWarehouseSourceJobStatus
    started_at: datetime
    finished_at: datetime | None = None
    latest_error: str | None = None
    workflow_id: str | None = None
    workflow_run_id: str | None = None


@dataclass(frozen=True, kw_only=True)
class ManagedWarehouseSourceJobRecord:
    id: UUID
    team_id: int
    environment_id: int
    schema_id: UUID
    source_job_id: str
    attempt_id: str
    workflow_type: ManagedWarehouseSourceJobWorkflow
    status: ManagedWarehouseSourceJobStatus
    started_at: datetime
    finished_at: datetime | None
    latest_error: str | None
    workflow_id: str | None
    workflow_run_id: str | None
    last_completed_at: datetime | None = None


@dataclass(frozen=True, kw_only=True)
class DuckLakeS3Secret:
    """One temporary DuckDB S3 secret, scoped to a single self-managed table's object path."""

    name: str
    key_id: str = field(repr=False)
    secret: str = field(repr=False)
    region: str
    scope: str
    use_ssl: bool
    url_style: str
    endpoint: str | None = None


@dataclass(frozen=True, kw_only=True)
class DuckLakeCompiledQuery:
    """A HogQL query compiled to DuckDB SQL, with the secrets its self-managed tables need.

    ``s3_secrets`` covers only the self-managed tables the compiled schema still exposed after
    warehouse access control, so a caller cannot install credentials for a table its query was
    not allowed to read.
    """

    sql: str
    values: dict[str, Any]
    hogql: str
    s3_secrets: tuple[DuckLakeS3Secret, ...] = ()


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
