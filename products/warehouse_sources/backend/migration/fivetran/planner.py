"""Turn a Fivetran snapshot into one PostHog proposal per Fivetran connection.

Every difference between what Fivetran did and what PostHog will do becomes a caveat
the user sees. Nothing is dropped silently.
"""

import re
from collections.abc import Callable, Mapping
from typing import Protocol

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.facade.source_config import ReleaseStatus
from products.warehouse_sources.backend.migration.types import (
    ItemProposal,
    PostHogSyncFrequency,
    ProposedDestination,
    ProposedRowFilter,
    ProposedSchema,
    RowFilterOperator,
    ScheduleKind,
    SourceCapabilities,
    VendorConnection,
    VendorDestination,
    VendorRowFilter,
    VendorSchedule,
    VendorSnapshot,
    VendorTable,
    Verdict,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


class SourceMatchLike(Protocol):
    @property
    def source_type(self) -> ExternalDataSourceType: ...
    @property
    def table_aliases(self) -> Mapping[str, str]: ...
    @property
    def config_keys(self) -> Mapping[str, str]: ...
    @property
    def notes(self) -> tuple[str, ...]: ...


class CatalogLookup(Protocol):
    def match_source(self, provider: str, vendor_service: str) -> SourceMatchLike | None: ...
    def match_destination(self, provider: str, vendor_service: str) -> str | None: ...


@frozen
class PlannedItem:
    vendor_connection_id: str
    vendor_service: str
    name: str
    verdict: Verdict
    caveats: tuple[str, ...]
    # None when the connection cannot move to PostHog.
    proposal: ItemProposal | None


_INTERVAL_TO_FREQUENCY: dict[int, PostHogSyncFrequency] = {
    1: "5min",
    5: "5min",
    15: "15min",
    30: "30min",
    60: "1hour",
    120: "1hour",
    180: "1hour",
    360: "6hour",
    480: "6hour",
    720: "12hour",
    1440: "24hour",
}
_FREQUENCY_MINUTES: dict[PostHogSyncFrequency, int] = {
    "5min": 5,
    "15min": 15,
    "30min": 30,
    "1hour": 60,
    "6hour": 360,
    "12hour": 720,
    "24hour": 1440,
}
_DEFAULT_FREQUENCY: PostHogSyncFrequency = "6hour"
_ROW_FILTER_OPERATORS: dict[str, RowFilterOperator] = {
    "EQUALS": "=",
    "NOT_EQUALS": "!=",
    "LESS": "<",
    "LESS_OR_EQUALS": "<=",
    "GREATER": ">",
    "GREATER_OR_EQUALS": ">=",
    "IN": "IN",
}
_UNSUPPORTED_NETWORKING = {"PrivateLink", "ProxyAgent", "UnmanagedProxyAgent"}
_CHANGE_LOG_UPDATE_METHODS = {"WAL_PGOUTPUT", "WAL", "BINLOG", "LOGMINER", "CHANGE_TRACKING", "NATIVE_UPDATE"}


def plan_items(
    snapshot: VendorSnapshot,
    catalog: CatalogLookup,
    capabilities: Callable[[ExternalDataSourceType], SourceCapabilities],
) -> tuple[PlannedItem, ...]:
    destinations = {destination.id: destination for destination in snapshot.destinations}
    return tuple(
        _plan_connection(
            snapshot.provider, connection, destinations.get(connection.destination_id or ""), catalog, capabilities
        )
        for connection in snapshot.connections
    )


def _plan_connection(
    provider: str,
    connection: VendorConnection,
    destination: VendorDestination | None,
    catalog: CatalogLookup,
    capabilities: Callable[[ExternalDataSourceType], SourceCapabilities],
) -> PlannedItem:
    def unsupported(reason: str) -> PlannedItem:
        return PlannedItem(
            vendor_connection_id=connection.id,
            vendor_service=connection.service,
            name=connection.name,
            verdict=Verdict.UNSUPPORTED,
            caveats=(reason,),
            proposal=None,
        )

    match = catalog.match_source(provider, connection.service)
    if match is None:
        return unsupported(f"PostHog has no source for the Fivetran connector `{connection.service}` yet.")
    caps = capabilities(match.source_type)
    if caps.unreleased:
        return unsupported(f"The PostHog {match.source_type} source is not released yet.")

    caveats: list[str] = list(match.notes)
    if caps.release_status == ReleaseStatus.ALPHA:
        caveats.append(f"The PostHog {match.source_type} source is in alpha.")
    if connection.setup_state and connection.setup_state != "connected":
        caveats.append(f"This connection is `{connection.setup_state}` in Fivetran, so check its settings first.")
    if connection.networking_method in _UNSUPPORTED_NETWORKING:
        caveats.append(
            f"Fivetran reaches this source through `{connection.networking_method}`. PostHog connects directly or through an SSH tunnel."
        )
    if connection.config.get("update_method") in _CHANGE_LOG_UPDATE_METHODS:
        caveats.append(
            "Fivetran reads this database from its change log. PostHog starts with standard syncs. "
            "Turn on change data capture in the source settings to read the change log."
        )
    if connection.schema_change_handling == "BLOCK_ALL":
        caveats.append("Fivetran blocks new tables and columns for this connection. PostHog may add new columns.")

    schemas = _plan_tables(connection, match, caps, caveats)
    sync_frequency, sync_time_of_day = _plan_frequency(connection, caveats)

    proposal = ItemProposal(
        source_type=match.source_type,
        prefix=_prefix_for(connection.name),
        prefill={
            posthog_key: connection.config[fivetran_key]
            for fivetran_key, posthog_key in match.config_keys.items()
            if fivetran_key in connection.config
        },
        schemas=schemas,
        sync_frequency=sync_frequency,
        sync_time_of_day=sync_time_of_day,
        destination=_plan_destination(provider, destination, catalog, caveats),
    )
    return PlannedItem(
        vendor_connection_id=connection.id,
        vendor_service=connection.service,
        name=connection.name,
        verdict=Verdict.CAVEATS if caveats else Verdict.AS_IS,
        caveats=tuple(caveats),
        proposal=proposal,
    )


def _plan_tables(
    connection: VendorConnection, match: SourceMatchLike, caps: SourceCapabilities, caveats: list[str]
) -> tuple[ProposedSchema, ...]:
    if not connection.tables_available:
        caveats.append("Fivetran did not return a table list. PostHog will use its default tables.")
        return ()

    schemas: list[ProposedSchema] = []
    for table in connection.tables:
        if not table.enabled:
            continue
        name = _posthog_table_name(table, match, caps)
        if caps.documented_tables is not None and name not in caps.documented_tables:
            caveats.append(f"The Fivetran table `{table.name}` has no PostHog equivalent, so it is left out.")
            continue
        if table.sync_mode == "HISTORY":
            caveats.append(
                f"`{table.name}` keeps history in Fivetran. PostHog keeps only the latest version of each row."
            )
        if any(column.hashed for column in table.columns):
            caveats.append(f"`{table.name}` hashes some columns in Fivetran. PostHog syncs them unhashed.")
        schemas.append(
            ProposedSchema(
                name=name,
                should_sync=True,
                sync_type=None,
                disabled_columns=_plan_disabled_columns(table, caps, caveats),
                row_filters=_plan_row_filters(table, table.row_filter, caps, caveats),
            )
        )
    return tuple(schemas)


def _posthog_table_name(table: VendorTable, match: SourceMatchLike, caps: SourceCapabilities) -> str:
    if caps.documented_tables is None:
        # Database sources: PostHog names tables `schema.table` when no single schema is set.
        return f"{table.schema_name}.{table.name}"
    return match.table_aliases.get(table.name, table.name)


def _plan_disabled_columns(table: VendorTable, caps: SourceCapabilities, caveats: list[str]) -> tuple[str, ...]:
    disabled = tuple(column.name for column in table.columns if not column.enabled)
    if disabled and not caps.supports_column_selection:
        caveats.append(f"`{table.name}` skips some columns in Fivetran. PostHog syncs every column of this table.")
        return ()
    return disabled


def _plan_row_filters(
    table: VendorTable, row_filter: VendorRowFilter | None, caps: SourceCapabilities, caveats: list[str]
) -> tuple[ProposedRowFilter, ...]:
    if row_filter is None:
        return ()
    dropped = f"`{table.name}` has a row filter in Fivetran that PostHog cannot apply. PostHog syncs every row."
    if not caps.supports_row_filters or (row_filter.combinator == "OR" and len(row_filter.clauses) > 1):
        caveats.append(dropped)
        return ()
    filters: list[ProposedRowFilter] = []
    for clause in row_filter.clauses:
        operator = _ROW_FILTER_OPERATORS.get(clause.operator)
        if operator is None or not clause.values:
            caveats.append(dropped)
            return ()
        filters.append(
            ProposedRowFilter(
                column=clause.column,
                operator=operator,
                values=clause.values if operator == "IN" else clause.values[:1],
            )
        )
    return tuple(filters)


def _plan_frequency(connection: VendorConnection, caveats: list[str]) -> tuple[PostHogSyncFrequency, str | None]:
    schedule = connection.schedule
    if connection.paused:
        caveats.append("This connection is paused in Fivetran, so PostHog creates it with syncing off.")
        return "never", None
    if schedule.days_of_week:
        caveats.append("Fivetran syncs this connection on some weekdays only. PostHog syncs every day.")

    if schedule.kind == ScheduleKind.MANUAL:
        caveats.append("This connection syncs only on demand in Fivetran, so PostHog creates it with syncing off.")
        return "never", None
    if schedule.kind == ScheduleKind.TIME_OF_DAY:
        return "24hour", _to_posthog_time(schedule.time_of_day_utc)
    if schedule.kind == ScheduleKind.CRON:
        return _plan_cron(schedule, caveats)

    interval = schedule.interval_minutes
    frequency = _INTERVAL_TO_FREQUENCY.get(interval) if interval is not None else None
    if frequency is None:
        caveats.append(f"PostHog cannot match this Fivetran schedule, so it syncs every {_DEFAULT_FREQUENCY}.")
        return _DEFAULT_FREQUENCY, None
    if interval != _FREQUENCY_MINUTES[frequency]:
        caveats.append(f"Fivetran syncs every {interval} minutes. PostHog will sync every {frequency}.")
    time_of_day = _to_posthog_time(schedule.time_of_day_utc) if frequency == "24hour" else None
    return frequency, time_of_day


def _plan_cron(schedule: VendorSchedule, caveats: list[str]) -> tuple[PostHogSyncFrequency, str | None]:
    caveats.append(f"Fivetran uses the cron schedule `{schedule.cron}`. PostHog uses the nearest fixed interval.")
    fields = (schedule.cron or "").split()
    if len(fields) != 5:
        return _DEFAULT_FREQUENCY, None
    minute, hour = fields[0], fields[1]
    step = re.fullmatch(r"\*/(\d+)", hour)
    if step:
        return _nearest_frequency(int(step.group(1)) * 60), None
    if hour == "*":
        minute_step = re.fullmatch(r"\*/(\d+)", minute)
        return _nearest_frequency(int(minute_step.group(1)) if minute_step else 60), None
    if hour.isdigit() and minute.isdigit():
        # The cron hour is in the destination's time zone, so the time of day is left to the user.
        return "24hour", None
    return _DEFAULT_FREQUENCY, None


def _nearest_frequency(minutes: int) -> PostHogSyncFrequency:
    return min(_FREQUENCY_MINUTES, key=lambda frequency: abs(_FREQUENCY_MINUTES[frequency] - minutes))


def _to_posthog_time(time_of_day: str | None) -> str | None:
    return f"{time_of_day}:00" if time_of_day else None


def _plan_destination(
    provider: str, destination: VendorDestination | None, catalog: CatalogLookup, caveats: list[str]
) -> ProposedDestination | None:
    if destination is None:
        return None
    destination_type = catalog.match_destination(provider, destination.service)
    if destination_type is None:
        caveats.append(
            f"PostHog cannot write to the Fivetran destination `{destination.service}`. The data lands in the PostHog warehouse."
        )
        return None
    caveats.append(
        f"The data can land in your {destination_type} warehouse. Use a different schema than Fivetran while both run."
    )
    return ProposedDestination(type=destination_type, config=destination.config)


def _prefix_for(connection_name: str) -> str:
    prefix = re.sub(r"[^a-z0-9_]+", "_", connection_name.lower()).strip("_")
    if prefix and prefix[0].isdigit():
        prefix = f"_{prefix}"
    return prefix
