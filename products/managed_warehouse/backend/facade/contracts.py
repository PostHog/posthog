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

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal, Protocol
from uuid import UUID

from posthog.dataclasses import frozen

__all__ = [
    "ControlPlaneRejectedError",
    "InvalidLoginTeamError",
    "LoginKind",
    "LoginMode",
    "LoginNotFoundError",
    "ProtectedLoginError",
    "WarehouseLogin",
    "WarehouseLoginCredential",
    "ConsoleSettings",
    "ControlPlaneNotConfiguredError",
    "ControlPlaneUnavailableError",
    "ControlPlaneUpstreamError",
    "QueryHistoryPage",
    "QueryHistoryRow",
    "QueryNotFoundError",
    "QueryCostEstimate",
    "QueryCostTable",
    "QueryCostWarning",
    "StorageOverview",
    "StorageTableUsage",
    "UsageBreakdownRow",
    "UsageBudget",
    "UsageComputeSummary",
    "UsageDailyPoint",
    "UsageStorageSummary",
    "UsageSummary",
    "WarehouseNotFoundError",
    "CPUnavailableError",
    "DuckLakeBackfillCatalog",
    "DuckLakeDayReplacement",
    "DuckLakeTableLayoutError",
    "DuckLakeTableReplacement",
    "HoglakeBackfillCatalog",
    "TrinoBackend",
    "DuckgresConnectionRefused",
    "DuckgresOrganizationUnavailable",
    "DuckgresQueryServerConfig",
    "DuckgresServerSummary",
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
    "ManagedWarehouseTrinoConnection",
    "ManagedWarehouseTrinoConnectionUnavailable",
    "ProvisionedWarehouseLogin",
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
    "ServiceCredentialTrinoConnect",
    "ServiceCredentialUnavailable",
    "StaffActionOutcome",
    "StaffProvisionPreview",
    "TrinoCompiledQuery",
    "TrinoExpansionMode",
]


class CPUnavailableError(RuntimeError):
    pass


class DuckgresConnectionRefused(Exception):
    """duckgres refused the connection because of its hostname, so no retry can succeed."""


class DuckgresOrganizationUnavailable(DuckgresConnectionRefused):
    """duckgres has no organization for the managed warehouse hostname of the connection."""


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


@frozen
class ServiceCredentialTrinoConnect:
    host: str
    port: int
    catalog: str
    username: str
    http_scheme: Literal["https"]


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
    trino_connect: ServiceCredentialTrinoConnect | None = None


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
class ManagedWarehouseTrinoConnection:
    """A minted Trino connection snapshot; use the connection context manager for refresh."""

    host: str
    port: int
    catalog: str
    username: str
    password: str = field(repr=False)
    credential_id: str
    expires_at: datetime


class ManagedWarehouseTrinoConnectionUnavailable(RuntimeError):
    pass


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
class ControlPlaneStorage:
    """The bucket and data path of a managed warehouse, both from one control-plane status."""

    bucket: str
    # `s3://<bucket>/`, or `s3://<bucket>/<prefix>/` for a warehouse under a prefix of a shared bucket.
    data_path: str


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
    groups_table: str | None = None


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


@frozen(kw_only=True)
class ManagedWarehouseTarget:
    """The endpoint an organization's managed warehouse answers on, for the host guard.

    `host` is the control plane's own host string, so a comparison against it is a comparison
    against the value the ingress was provisioned for rather than anything derived locally.
    `ports` is the listener set this organization's sources may reach, which keeps a Postgres
    source off the gateway listener and a Trino source off the pgwire one.

    The guard compares a source's host, port and resolved addresses against this to decide
    whether the private-address check applies. It is not a connection; it is an authorization
    decision.
    """

    host: str
    ports: frozenset[int]

    def accepts(self, host: str, port: int | None, addresses: list[str] | None, ingress_ips: tuple[str, ...]) -> bool:
        """Whether this target authorizes a dial to `host` on `port` at `addresses`.

        Every condition is required, and a missing one denies. `addresses` must be non-empty
        because an empty set is a failed lookup, not an approved destination, and it must be a
        subset of `ingress_ips` so a record that points elsewhere is refused. The caller supplies
        the ingress set because a contract cannot read settings without importing Django.

        Both hostnames are compared in their normalized form, so a control-plane host that comes
        back with a capital letter or a root-zone trailing dot still matches the name the guard
        normalized.
        """
        if _normalize_host(host) != _normalize_host(self.host):
            return False
        if port is None or port not in self.ports:
            return False
        if not addresses or not ingress_ips:
            return False
        allowed = {_canonical_ip(ip) for ip in ingress_ips}
        return all(_canonical_ip(address) in allowed for address in addresses)


def _normalize_host(host: str) -> str:
    """Lowercase a hostname and drop one root-zone trailing dot, as the guard does."""
    return host.lower().strip().rstrip(".")


def _canonical_ip(value: str) -> str:
    """Compare addresses as numbers, so an IPv4-mapped IPv6 form matches its IPv4 spelling."""
    import ipaddress  # noqa: PLC0415

    try:
        parsed = ipaddress.ip_address(value.strip().strip("[]"))
    except ValueError:
        return value
    if isinstance(parsed, ipaddress.IPv6Address) and parsed.ipv4_mapped is not None:
        return str(parsed.ipv4_mapped)
    return str(parsed)


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


@frozen
class TrinoCompiledQuery:
    """A HogQL query compiled to Trino SQL with named parameter bindings."""

    sql: str
    values: dict[str, Any]
    hogql: str | None = None
    needs_row_type_probe: bool = True
    """Whether the build must read the output types: an output column may hold a ROW with anonymous fields or a boolean.

    False only when every output column resolved to a type without a tuple, a boolean or an unknown part.
    """


@frozen
class TrinoIncrementalWrite:
    """How a Trino model build tracks an incremental view.

    With ``since`` set, the build reads only rows at or after it and merges them into the existing
    table on ``unique_key``. Without it, the build replaces the table. Both report the highest
    ``incremental_key`` written, so a full build seeds the next incremental one.
    """

    incremental_key: str
    unique_key: tuple[str, ...]
    since: Any = None


@frozen
class StoredColumnType:
    """The ClickHouse type stored for one output column of a saved query.

    A Trino build matches these types, so models that read the table see the same column types
    on both engines.
    """

    name: str
    clickhouse_type: str


class TrinoExpansionMode(StrEnum):
    PURE = "pure"
    DJANGO = "django"


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


@frozen
class DuckLakeTableResult:
    schema_name: str
    table_name: str
    row_count: int
    file_size_bytes: int = 0
    file_size_delta_bytes: int = 0
    # Highest incremental key written, for builds that track one. None when no rows were written.
    watermark: Any = None
    merged: bool = False


@frozen
class DuckLakeDayReplacement:
    """The rows of one UTC day of `column`, which a backfill export of that day replaces."""

    column: str
    day: date


@frozen
class DuckLakeTableReplacement:
    """All rows of the table, which a full backfill export replaces."""


class DuckLakeTableLayoutError(ValueError):
    """The table's column types differ from the backfill export, so add_files refuses the export's files."""


# The connector behind an organization's managed Trino catalog. The backend is fixed when the warehouse is created.
TrinoBackend = Literal["ducklake", "hoglake"]


class DuckLakeBackfillCatalog(Protocol):
    """The DuckLake statements a backfill runs in the organization's Trino catalog."""

    def ensure_table(
        self, table: str, columns: Mapping[str, str], *, drop_first: bool, create_if_missing: bool, validate: bool
    ) -> None: ...

    def replace_table(self, table: str, columns: Mapping[str, str]) -> None: ...

    def validate_file_count(self, files: Sequence[str]) -> None: ...

    def register_files(
        self,
        table: str,
        files: Sequence[str],
        *,
        import_id: str,
        replacement: DuckLakeDayReplacement | DuckLakeTableReplacement | None,
    ) -> int: ...

    def delete_rows(self, table: str, replacement: DuckLakeDayReplacement | DuckLakeTableReplacement) -> None: ...


@frozen
class DuckgresServerSummary:
    """An organization's warehouse server as staff see it in PostHog Admin. No credentials."""

    server_id: UUID
    host: str
    bucket: str | None
    internal_testing: bool
    deprovisioned: bool


@frozen
class ProvisionedWarehouseLogin:
    """The root login of a newly provisioned warehouse. The control plane returns the password only once."""

    host: str
    port: int
    database: str
    username: str
    # Empty when the control plane returned no password.
    password: str = field(repr=False)


@frozen
class StaffActionOutcome:
    ok: bool
    status_code: int
    message: str
    login: ProvisionedWarehouseLogin | None = None


@frozen
class StaffProvisionPreview:
    """What provisioning would set up, for staff to confirm. `problem` says why it cannot run."""

    team_name: str
    host: str
    problem: str | None = None


@frozen
class ViewTranslationSummary:
    """An organization's view translation jobs as staff see them in PostHog Admin."""

    latest_status: str
    total_count: int
    compiled_count: int
    failed_count: int
    stale_count: int
    # True while a job is pending or running. An organization runs one job at a time.
    active: bool
    # The latest job, when it has failed or stale views to retry. None otherwise.
    retry_job_id: UUID | None


class HoglakeBackfillCatalog(Protocol):
    """The hoglake statements of one team's backfill, run in the organization's Trino catalog."""

    def ensure_table(
        self, table: str, columns: Mapping[str, str], *, drop_first: bool, create_if_missing: bool, validate: bool
    ) -> None: ...

    def replace_table(self, table: str, columns: Mapping[str, str]) -> None: ...

    def register_export(
        self,
        table: str,
        *,
        location: str,
        file_prefix: str,
        import_id: str,
        expected_rows: int,
        replacement: DuckLakeDayReplacement | DuckLakeTableReplacement | None,
    ) -> int: ...


class ControlPlaneNotConfiguredError(RuntimeError):
    """The deployment has no managed warehouse control plane to ask."""


class WarehouseNotFoundError(LookupError):
    """The control plane has no warehouse for the organization."""


class ControlPlaneUnavailableError(RuntimeError):
    """The control plane or its catalog answered 503, so a retry later may succeed."""


class ControlPlaneUpstreamError(RuntimeError):
    """The control plane failed, timed out, or answered something unusable."""


class QueryNotFoundError(LookupError):
    """The query is unknown to Trino, or it already finished."""


@frozen
class UsageComputeSummary:
    billable_bytes: int
    failed_billable_bytes: int
    logical_bytes: int
    queries: int
    free_bytes: int
    estimated_cost_usd: Decimal


@frozen
class UsageStorageSummary:
    gib_months: Decimal
    average_bytes: int
    free_gib_months: Decimal
    estimated_cost_usd: Decimal


@frozen
class UsageDailyPoint:
    date: date
    billable_bytes: int
    queries: int
    storage_average_bytes: int


@frozen
class UsageBreakdownRow:
    key: str
    label: str
    queries: int
    billable_bytes: int
    estimated_cost_share_usd: Decimal


@frozen
class UsageBudget:
    monthly_budget_usd: Decimal | None
    share_used: Decimal | None


@frozen
class UsageSummary:
    """One UTC calendar month of managed warehouse usage and its estimated spend."""

    period_start: date
    # Exclusive: the first day of the next month.
    period_end: date
    compute: UsageComputeSummary
    storage: UsageStorageSummary
    total_estimated_cost_usd: Decimal
    forecast_total_usd: Decimal | None
    daily: tuple[UsageDailyPoint, ...]
    breakdown: tuple[UsageBreakdownRow, ...]
    budget: UsageBudget


@frozen
class QueryHistoryRow:
    id: int
    query_id: str
    principal: str
    principal_label: str
    team_id: int | None
    source: str
    source_label: str
    state: str
    error_code: str | None
    error_type: str | None
    created_at: str | None
    completed_at: str | None
    elapsed_ms: int | None
    queued_ms: int | None
    logical_bytes_scanned: int
    billable: bool
    billable_bytes: int
    cpu_seconds: float | None
    # None when the viewer cannot access the project the query ran for.
    query: str | None
    # Marginal price of the row's billable bytes. The monthly free tier is not applied per row.
    estimated_cost_usd: Decimal


@frozen
class QueryHistoryPage:
    queries: tuple[QueryHistoryRow, ...]
    # Opaque keyset cursor for the next page. None on the last page.
    next_cursor: str | None


@frozen
class StorageTableUsage:
    schema: str
    table: str
    data_bytes: int
    delete_bytes: int
    file_count: int
    row_count: int
    last_modified_at: str | None


@frozen
class StorageOverview:
    tables: tuple[StorageTableUsage, ...]
    total_bytes: int
    pending_deletion_files: int
    read_at: str | None
    # Opaque control plane status. None when the control plane could not report it.
    maintenance: dict[str, Any] | None


@frozen
class ConsoleSettings:
    max_scan_bytes_per_query: int | None
    monthly_budget_usd: Decimal | None


class ControlPlaneRejectedError(RuntimeError):
    """The control plane refused the request as invalid. The message is safe to show."""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class LoginNotFoundError(LookupError):
    """The warehouse has no login with that name."""


class ProtectedLoginError(ValueError):
    """The root login cannot be disabled, deleted or rotated from the console."""


class InvalidLoginTeamError(ValueError):
    """The project does not belong to the organization."""


LoginKind = Literal["root", "project_reader", "project_user", "other"]
LoginMode = Literal["reader", "user"]


@frozen
class WarehouseLogin:
    """A Trino login of the warehouse, with its last 30 days of activity."""

    username: str
    kind: LoginKind
    team_id: int | None
    scope_label: str
    disabled: bool
    created_at: str | None
    updated_at: str | None
    queries_30d: int
    billable_bytes_30d: int


@frozen
class WarehouseLoginCredential:
    """A login with its new password. The password is shown once and never stored in PostHog."""

    login: WarehouseLogin
    password: str = field(repr=False)


QueryCostWarning = Literal["no_filter_on_large_table", "exceeds_cap", "size_unknown"]


@frozen
class QueryCostTable:
    catalog: str
    schema: str
    table: str
    # Stored data bytes of the table, or None when the storage listing has no matching table.
    size_bytes: int | None
    # Whether the query constrains at least one column of the table.
    has_filter: bool


@frozen
class QueryCostEstimate:
    """An upper bound on what a SQL editor query can scan, before it runs."""

    tables: tuple[QueryCostTable, ...]
    upper_bound_bytes: int | None
    # Marginal compute price of the upper bound. The monthly free tier is not applied.
    estimated_cost_usd: Decimal | None
    cap_bytes: int | None
    exceeds_cap: bool
    # False when any table has an unknown size, so the upper bound undercounts.
    complete: bool
    warnings: tuple[QueryCostWarning, ...]
