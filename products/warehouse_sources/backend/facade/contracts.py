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

from collections.abc import Sequence
from dataclasses import field
from datetime import datetime, time, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic.dataclasses import dataclass

from posthog.dataclasses import frozen
from posthog.integrations import IntegrationUsage

from products.warehouse_sources.backend.facade.types import WarehouseColumnAnnotationDescriptionSource

# The request flag that confirms an edit of credentials that other sources or products also use.
UPDATE_SHARED_CREDENTIALS_PARAM = "update_shared_credentials"

# The `job_inputs` key of a source API edit that points the source at another credentials row. The API
# moves the value to the source's `credentials_integration_id` column. The store never saves it in `job_inputs`.
CREDENTIALS_REFERENCE_INPUT_KEY = "credentials_integration_id"

# The `IntegrationUsage.type` of a warehouse source that uses an integration row.
WAREHOUSE_SOURCE_USAGE_TYPE = "warehouse_source"
# A source whose inputs do not decode, so it may use the row. It blocks a delete of the row only.
UNREADABLE_WAREHOUSE_SOURCE_USAGE_TYPE = "unreadable_warehouse_source"
# The `IntegrationUsage.type` of a warehouse destination that writes through an integration row.
WAREHOUSE_DESTINATION_USAGE_TYPE = "warehouse_destination"


class SharedCredentialsError(Exception):
    """An edit would change a credentials row that other sources or products also use.

    `usages` holds the other users, as the integrations SDK reports them. The API returns them in a
    409 response, and the request can confirm with `update_shared_credentials`.
    """

    def __init__(self, integration_id: int, usages: Sequence[IntegrationUsage]) -> None:
        super().__init__(f"Integration {integration_id} is also used by {len(usages)} other objects")
        self.integration_id = integration_id
        self.usages = tuple(usages)


class UnusableCredentialsReferenceError(ValueError):
    """An edit points a source at a credentials row that the source cannot use: a row of another team,
    another kind or another auth type, or a row that no warehouse source made."""


class SharedCredentialsEdit(StrEnum):
    """What a write of a source's inputs does when other sources or products also use its credentials row."""

    # The default of internal writes. The row is the only storage of the credentials, so a change to a shared row
    # raises `SharedCredentialsError` as with REFUSE. A skipped write would lose the change.
    SKIP = "skip"
    # Raise `SharedCredentialsError`, so the API can ask the person for a confirmation.
    REFUSE = "refuse"
    # The person confirmed the edit: write the shared row.
    CONFIRMED = "confirmed"


class LegacyHistoryTableError(Exception):
    """An incremental schema's history table uses the legacy `_cdc` naming.

    Incremental history writes with deltalite's history upsert, which needs the month-partitioned layout of a
    `_history` table. A legacy table is unpartitioned, so an incremental sync cannot write it.
    """


class UnsupportedSyncTypeError(ValueError):
    """The stored sync type is not a mode PostHog can run."""


HISTORY_ACCESS_RULES_NOT_ALLOWED_MESSAGE = (
    "You need to be able to manage access to this table and its history table to copy its access rules."
)


class HistoryAccessRulesNotAllowedError(Exception):
    """The user may not set the access rules of a table or of its history table."""


class NoHistoryTableError(Exception):
    """The table has no registered history table."""


class HistoryTableDropRefusedError(Exception):
    """A history table can't be dropped now. The message says why and can be shown to the user."""


class UnreadableSourceInputsError(ValueError):
    """A source's stored inputs do not decode to a mapping. The message never holds the value, because the
    value can hold credentials."""


# Set in `job_inputs` when the store has moved the connection fields of a source to its credentials row and
# removed them from `job_inputs`. The value is the time of the strip, as an ISO 8601 string.
CONNECTION_FIELDS_STRIPPED_KEY = "connection_fields_stripped_at"
# Keeps a stripped typed-in source typed-in when, without its connection fields, it would read as OAuth (Slack).
CONNECTION_FIELDS_STRIPPED_TYPED_IN_KEY = "connection_fields_stripped_typed_in"
STRIPPED_STORE_KEYS: frozenset[str] = frozenset(
    {CONNECTION_FIELDS_STRIPPED_KEY, CONNECTION_FIELDS_STRIPPED_TYPED_IN_KEY}
)
DEAD_CREDENTIALS_CLEARED_KEY = "dead_credentials_cleared_at"

SOURCE_CREDENTIALS_MISSING_ERROR = "The credentials of this source are missing or cannot be read"


class SourceCredentialsMissingError(UnreadableSourceInputsError):
    """The credentials row or the reference column that a source needs is missing or unreadable. `job_inputs` is
    never a copy of the credentials, so the user must enter the credentials again or reconnect the account."""

    def __init__(self) -> None:
        super().__init__(
            f"{SOURCE_CREDENTIALS_MISSING_ERROR}. Enter the credentials of the source again, or reconnect its "
            "account, then enable the sync again."
        )


class UndecryptedConfigError(ValueError):
    """Raised when a config value reaches conversion still Fernet-encrypted.

    Upstream decryption of the stored job inputs failed (e.g. the key that wrote them is no
    longer in the keychain), so the raw token would otherwise crash the field converter with an
    opaque, secret-leaking error such as ``invalid literal for int() with base 10: 'gAAAAA...'``.
    """


class ConfigValueError(ValueError):
    """Raised when a config field's value can't be converted to its declared type.

    A converter (e.g. ``int``) failing on user-supplied input would otherwise crash with an
    opaque, value-leaking builtin error such as ``invalid literal for int() with base 10: 'lakjsd'``.
    We name the field but never its value, so nothing a user typed reaches logs or error tracking.
    """


@dataclass(frozen=True)
class HistoryTableRef:
    """A table's history table, as the table's access dialog shows it."""

    id: UUID
    # The name the history table is queried by in HogQL.
    name: str
    user_can_manage_access: bool


@dataclass(frozen=True)
class SyncedWarehouseTable:
    table_id: UUID
    name: str


@dataclass(frozen=True)
class RevenueViewSyncInput:
    team_id: int
    source_id: UUID
    source_type: str
    schema_name: str


@dataclass(frozen=True)
class PersonPropertySyncProgress:
    """One produced chunk's counts for one person-property source."""

    team_id: int
    binding_kind: str
    binding_id: str
    source_id: str
    job_id: str | None
    trigger: str
    rows_read: int
    changed: int
    existing: int
    produced: int
    skipped_missing_person: int


@dataclass(frozen=True)
class RevenueSourceTable:
    id: UUID
    name: str


@dataclass(frozen=True)
class RevenueSourceSchema:
    name: str
    table: RevenueSourceTable | None


@dataclass(frozen=True)
class RevenueSource:
    id: UUID
    source_type: str
    prefix: str | None
    enabled: bool
    include_invoiceless_charges: bool
    schemas: tuple[RevenueSourceSchema, ...]


@dataclass(frozen=True)
class RevenueSourceSettings:
    id: UUID
    source_type: str
    prefix: str | None
    deleted: bool
    enabled: bool


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


@dataclass(frozen=True)
class ExternalDataSourceHealth:
    """A source's sync health: how it is configured, plus its newest completed run and error.

    `status` alone conflates "sync in progress" with "never succeeded", so a consumer needs
    `last_run_at` to tell a healthy source from one that has never synced.
    """

    source_type: str
    status: str | None
    prefix: str | None
    created_at: datetime
    last_run_at: datetime | None
    latest_error: str | None


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


@dataclass(frozen=True, kw_only=True)
class ImportedSchemaSnapshot:
    schema_id: UUID
    queryable_folder: str | None


@dataclass(frozen=True)
class DuckLakeImportedTable:
    logical_table_names: tuple[str, ...]
    physical_table_name: str


@dataclass(frozen=True)
class TableSourceLocation:
    """Where a synced table is administered: the source and schema its detail page hangs off."""

    source_id: UUID
    schema_id: UUID


@dataclass(frozen=True)
class TableNames:
    """The two names one warehouse table answers to.

    ``row_name`` is what the table row stores and a listing shows. ``queryable_key`` is what a
    query writes, which for a source table is the dotted form. They are equal for a direct-access
    source and for a table with no source.
    """

    row_name: str
    queryable_key: str


@dataclass(frozen=True)
class TableAwaitingFirstSync:
    """A table that a synced schema will create, but whose first sync has not created yet.

    ``names`` holds the names a query can write for it once it exists.
    ``first_sync_failed`` is true when the latest sync attempt failed.
    """

    names: TableNames
    first_sync_failed: bool


WAREHOUSE_OBJECT_TABLE = "table"
WAREHOUSE_OBJECT_VIEW = "view"


@dataclass(frozen=True)
class WarehouseObjectRef:
    """Which warehouse object a queryable name resolves to, for a caller that must record identity.

    ``kind`` is ``WAREHOUSE_OBJECT_TABLE`` or ``WAREHOUSE_OBJECT_VIEW``, since a name reaches either
    a warehouse table or a saved query and the two are stored apart.
    """

    kind: str
    id: UUID


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
class TableLevelDescription:
    """What a warehouse table represents. `source` is null for text from the source schema."""

    text: str
    source: WarehouseColumnAnnotationDescriptionSource | None


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


# --- Column statistics ---


@dataclass(frozen=True)
class ColumnStatistics:
    """The per-column data profile core reads when describing a warehouse table.

    Narrower than the model on purpose: this carries only what schema description consumes.
    Row counts, provenance and the Delta version stay product-side.
    """

    table_id: UUID
    column_name: str
    null_fraction: float | None
    min_value: str | None
    max_value: str | None


# --- Credential (read-only metadata; secrets are never exposed) ---


@dataclass(frozen=True)
class DataWarehouseCredential:
    """Read-only credential metadata. Access key/secret are intentionally excluded."""

    id: UUID
    team_id: int
    created_at: datetime


@dataclass(frozen=True)
class GitHubSourceCredential:
    """How a GitHub source authenticates to the repositories it syncs.

    Exactly one field is set. This is the one contract that carries a secret, because a consumer
    that has to read the same repository the source reads cannot do it without the token. ``repr``
    omits the token so it cannot reach a log line or a traceback frame.
    """

    integration_id: int | None = None
    personal_access_token: str | None = field(default=None, repr=False)


# --- File upload sources ---


class FileUploadSourceError(Exception):
    """A request a file upload source can't carry out. The message is for the user."""


class UnreadableUploadError(FileUploadSourceError):
    """ClickHouse couldn't read the uploaded file's columns, or its CSV quoting."""


@dataclass(frozen=True)
class UploadedFileRef:
    """An upload that `upload_file` stored, as the client names it. The team always comes from the request."""

    upload_id: str
    filename: str
    file_format: str


@dataclass(frozen=True)
class UploadReadSettings:
    """What PostHog learned about an uploaded file when it read the file in place."""

    columns: dict[str, Any]
    allow_double_quotes: bool | None = None


class WarehouseMigrationKeyRejectedError(ValueError):
    """The vendor refused the API key."""


class WarehouseMigrationVendorUnreachableError(ValueError):
    """The vendor API could not be reached to check the API key."""


class WarehouseMigrationBusyError(ValueError):
    """The migration is already reading the vendor account."""


class WarehouseMigrationUploadedError(ValueError):
    """An agent uploaded this migration, so PostHog has no vendor key to read the account again."""


class WarehouseMigrationUploadTooLargeError(ValueError):
    """The uploaded migration would grow past the size PostHog stores for an upload."""


class WarehouseMigrationHasVendorKeyError(ValueError):
    """PostHog reads this migration's vendor account with an API key, so it takes no uploads."""


class WarehouseMigrationItemClaimedError(ValueError):
    """An apply has already claimed or finished this migration item."""


class WarehouseMigrationEmptySourceError(ValueError):
    """An earlier apply left a source with no tables behind. The message says how to recover."""


class WarehouseMigrationTableOverrideError(ValueError):
    """The table overrides do not fit the item's plan. The message says why."""


@dataclass(frozen=True)
class MigrationTableOverride:
    """Map one Fivetran table to a PostHog table at apply, or drop it with `posthog_table=None`."""

    vendor_table: str
    posthog_table: str | None


class WarehouseMigrationUnknownItemsError(ValueError):
    """Some item ids are not items of the migration."""

    def __init__(self, item_ids: list[UUID]) -> None:
        super().__init__(f"Not items of this migration: {', '.join(str(item_id) for item_id in item_ids)}.")
        self.item_ids = item_ids


@dataclass(frozen=True)
class WarehouseMigrationBulkSkip:
    skipped_item_ids: list[UUID]
    # Items an apply claimed or finished, which a skip never overwrites.
    not_skipped_item_ids: list[UUID]


@dataclass(frozen=True)
class WarehouseMigrationItemCounts:
    as_is: int
    caveats: int
    unsupported: int
    applied: int
    skipped: int


@dataclass(frozen=True)
class WarehouseMigration:
    """One import of a vendor account. The vendor key never leaves the product."""

    id: UUID
    provider: str
    status: str
    account_name: str
    crawled_at: datetime | None
    latest_error: str
    created_at: datetime
    item_counts: WarehouseMigrationItemCounts
    has_vendor_key: bool


@dataclass(frozen=True)
class WarehouseMigrationCreator:
    first_name: str
    email: str


@dataclass(frozen=True)
class WarehouseMigrationItem:
    id: UUID
    migration_id: UUID
    vendor_connection_id: str
    vendor_service: str
    name: str
    verdict: str
    caveats: list[str]
    # The planned PostHog source as stored JSON, or None when the connection cannot move.
    proposal: dict[str, Any] | None
    status: str
    external_data_source_id: UUID | None
    error: str
    # Who prepared the migration, so whoever types a password for this item can see who chose its server.
    created_by: WarehouseMigrationCreator | None = None


@dataclass(frozen=True)
class MigrationConnectionUpload:
    """One vendor connection as the vendor API returned it, secrets included until PostHog removes them."""

    connection: dict[str, Any]
    # None when the vendor has no table list for the connection.
    schema_config: dict[str, Any] | None


@dataclass(frozen=True)
class WarehouseMigrationUpload:
    items: list[WarehouseMigrationItem]
    # One message per uploaded destination or connection that could not be read. Each names it.
    errors: list[str]


@dataclass(frozen=True)
class ClaimedWarehouseMigrationItem:
    """A migration item that one apply request now owns."""

    id: UUID
    caveats: list[str]
    source_type: str
    # The prefix this attempt creates the source with: the caller's override, else the planned one.
    prefix: str | None
    description: str
    sync_frequency: str
    start_paused: bool
    # The stored plan, passed back to `plan_migration_schemas`.
    proposal: dict[str, Any]
    # Set when an earlier attempt already created the source: the claim linked it and applied the item.
    recovered_source_id: UUID | None = None


@dataclass(frozen=True)
class PlannedMigrationSchemas:
    # The `schemas` payload for source creation, one entry per discovered table.
    schemas: list[dict[str, Any]]
    # Planned tables that PostHog did not find or cannot sync with these credentials.
    unavailable: list[str]
    # Planned tables that only sync through a webhook.
    webhook_only: list[str]
    # Discovered tables the plan covers.
    planned: list[str]
    # Planned tables that skip columns PostHog would still read, so they stay off.
    kept_off: list[str]


@dataclass(frozen=True)
class SourceReferencingIntegration:
    id: UUID
    source_type: str
    prefix: str | None
    # The inputs did not decode, so the source may point at the row. The search counts it as a user.
    unreadable: bool = False


@frozen
class StaffSchemaPartitioning:
    enabled: bool | None
    mode: str | None
    format: str | None
    size: int | None
    count: int | None
    # Pinned by staff. Applied on the next reset.
    count_override: int | None
    size_override: int | None
    mode_override: str | None
    keys_override: tuple[str, ...] | None
    keys: tuple[str, ...] | None


@frozen
class StaffSchemaSummary:
    """One schema as staff see it in PostHog Admin."""

    id: UUID
    name: str
    team_id: int
    team_name: str
    source_id: UUID
    source_type: str
    is_cdc: bool
    supports_scheduled_sync: bool
    partitioning: StaffSchemaPartitioning
    available_columns: tuple[str, ...] | None


@frozen
class StaffJobRow:
    id: UUID
    status: str
    created_at: datetime
    finished_at: datetime | None
    rows_synced: int | None
    workflow_id: str | None
    workflow_run_id: str | None
    latest_error: str | None


@frozen
class StaffJobsPage:
    rows: tuple[StaffJobRow, ...]
    number: int
    num_pages: int
    count: int


@frozen
class StaffSourceSummary:
    id: UUID
    source_type: str
    prefix: str | None
    team_id: int
    team_name: str


@frozen
class StaffSchemaRow:
    id: UUID
    name: str
    deleted: bool
    status: str | None
    should_sync: bool
    sync_type: str | None
    sync_frequency_interval: timedelta | None
    last_synced_at: datetime | None
    table_id: UUID | None
    table_name: str | None
    table_row_count: int | None
    latest_error: str | None


@frozen
class StaffSchemasPage:
    rows: tuple[StaffSchemaRow, ...]
    number: int
    num_pages: int
    count: int


@frozen
class RepartitionRequest:
    """Partition settings staff chose. A value left empty keeps the schema's current one where that is allowed."""

    partition_mode: str | None
    partitioning_keys: tuple[str, ...]
    partition_format: str | None
    partition_count: int | None
    partition_size: int | None


@frozen
class StaffActionResult:
    ok: bool
    message: str


@dataclass(frozen=True)
class DestinationReferencingIntegration:
    id: UUID
    name: str
