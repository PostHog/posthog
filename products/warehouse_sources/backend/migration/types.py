"""Vendor-neutral shapes for importing a Fivetran (later Airbyte) account into PostHog.

A `VendorSnapshot` is what we read from the vendor, with every secret already removed.
An `ItemProposal` is what we plan to create in PostHog for one vendor connection.
"""

from collections.abc import Mapping
from dataclasses import field
from enum import StrEnum
from typing import Any, Literal

from pydantic import TypeAdapter

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.facade.source_config import ReleaseStatus
from products.warehouse_sources.backend.types import ExternalDataSchemaSyncType, ExternalDataSourceType


class MigrationProvider(StrEnum):
    FIVETRAN = "fivetran"


class ScheduleKind(StrEnum):
    INTERVAL = "interval"
    TIME_OF_DAY = "time_of_day"
    CRON = "cron"
    MANUAL = "manual"


@frozen
class VendorSchedule:
    kind: ScheduleKind
    interval_minutes: int | None = None
    # "HH:MM", already converted to UTC.
    time_of_day_utc: str | None = None
    cron: str | None = None
    # Empty means every day.
    days_of_week: tuple[str, ...] = ()


@frozen
class VendorColumn:
    name: str
    enabled: bool
    hashed: bool
    is_primary_key: bool


@frozen
class VendorRowFilterClause:
    column: str
    operator: str
    values: tuple[str, ...]


@frozen
class VendorRowFilter:
    combinator: Literal["AND", "OR"]
    clauses: tuple[VendorRowFilterClause, ...]


@frozen
class VendorTable:
    schema_name: str
    name: str
    enabled: bool
    sync_mode: str | None
    # Fivetran returns only the columns a user changed from the table default.
    columns: tuple[VendorColumn, ...]
    row_filter: VendorRowFilter | None


@frozen
class VendorDestination:
    id: str
    name: str
    service: str
    region: str | None
    config: Mapping[str, Any]


@frozen
class VendorConnection:
    id: str
    service: str
    # Fivetran's connection name, which is also the schema name in the destination.
    name: str
    destination_id: str | None
    paused: bool
    schedule: VendorSchedule
    setup_state: str | None
    succeeded_at: str | None
    networking_method: str | None
    config: Mapping[str, Any]
    schema_change_handling: str | None
    # False when the vendor would not return a table selection for this connection.
    tables_available: bool
    tables: tuple[VendorTable, ...]


@frozen
class VendorSnapshot:
    provider: MigrationProvider
    account_id: str
    account_name: str | None
    destinations: tuple[VendorDestination, ...]
    connections: tuple[VendorConnection, ...]

    def to_json(self) -> dict[str, Any]:
        return _SNAPSHOT_ADAPTER.dump_python(self, mode="json")

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "VendorSnapshot":
        return _SNAPSHOT_ADAPTER.validate_python(data)


PostHogSyncFrequency = Literal["5min", "15min", "30min", "1hour", "6hour", "12hour", "24hour", "7day", "30day"]


class Verdict(StrEnum):
    AS_IS = "as_is"
    CAVEATS = "caveats"
    UNSUPPORTED = "unsupported"


RowFilterOperator = Literal[">", ">=", "<", "<=", "=", "!=", "IN", "NOT IN"]


@frozen
class ProposedRowFilter:
    column: str
    operator: RowFilterOperator
    # One value, or several for IN and NOT IN.
    values: tuple[str, ...]


@frozen
class ProposedSchema:
    name: str
    should_sync: bool
    # None means the PostHog default for the table.
    sync_type: ExternalDataSchemaSyncType | None
    disabled_columns: tuple[str, ...] = ()
    row_filters: tuple[ProposedRowFilter, ...] = ()
    # Names to try, in order, when the source does not discover a table called `name`.
    alternative_names: tuple[str, ...] = ()
    # The Fivetran table this plan comes from, which apply's table overrides refer to.
    vendor_table: str | None = None


@frozen
class TablePair:
    vendor_table: str
    posthog_table: str


@frozen
class ProposedDestination:
    # An `ExternalDataDestination.Type` value.
    type: str
    config: Mapping[str, Any]


@frozen
class ItemProposal:
    source_type: ExternalDataSourceType
    prefix: str
    # Non-secret source config, keyed by PostHog payload field name.
    prefill: Mapping[str, Any]
    # None means Fivetran gave no table list, so PostHog uses its default tables.
    # An empty tuple means no Fivetran table moves over, so every table starts off.
    schemas: tuple[ProposedSchema, ...] | None
    sync_frequency: PostHogSyncFrequency
    # "HH:MM:SS" UTC.
    sync_time_of_day: str | None
    destination: ProposedDestination | None
    # The connection is paused or manual in Fivetran, so every table starts with syncing off.
    start_paused: bool = False
    # Tables a naming rule paired, which the user should confirm.
    inferred_tables: tuple[TablePair, ...] = ()
    # Fivetran tables with no PostHog table. The user can map one to a PostHog table at apply.
    unmatched_tables: tuple[str, ...] = ()
    # The source's PostHog tables that no Fivetran table maps to, to choose from for the unmatched ones.
    unused_posthog_tables: tuple[str, ...] = ()

    def to_json(self) -> dict[str, Any]:
        return _PROPOSAL_ADAPTER.dump_python(self, mode="json")

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "ItemProposal":
        return _PROPOSAL_ADAPTER.validate_python(data)


@frozen
class SourceCapabilities:
    release_status: ReleaseStatus | None
    unreleased: bool
    supports_column_selection: bool
    supports_row_filters: bool
    # Table name to the only columns a row filter on it may use. A table not here accepts any column.
    row_filter_columns: Mapping[str, frozenset[str]] = field(default_factory=dict)
    # Config fields that hold a group of settings behind an on/off switch, like `ssh_tunnel`.
    toggle_groups: frozenset[str] = frozenset()
    # Feature flags a team needs before it can create this source.
    feature_flags: frozenset[str] = frozenset()


_SNAPSHOT_ADAPTER: TypeAdapter[VendorSnapshot] = TypeAdapter(VendorSnapshot)
_PROPOSAL_ADAPTER: TypeAdapter[ItemProposal] = TypeAdapter(ItemProposal)
