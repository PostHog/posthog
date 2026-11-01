"""Turn a Fivetran snapshot into one PostHog proposal per Fivetran connection.

Every difference between what Fivetran did and what PostHog will do becomes a caveat
the user sees. Nothing is dropped silently.
"""

import re
import dataclasses
from collections import Counter
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from typing import Any, Protocol

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
    TablePair,
    VendorConnection,
    VendorDestination,
    VendorSchedule,
    VendorSnapshot,
    VendorTable,
    Verdict,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


class PostHogTablesLike(Protocol):
    @property
    def names(self) -> frozenset[str]: ...
    # False when the source also syncs tables it discovers in the user's account.
    @property
    def complete(self) -> bool: ...


class TableMatchLike(Protocol):
    @property
    def vendor_table(self) -> str: ...
    @property
    def posthog_table(self) -> str | None: ...
    # "exact", "inferred", or None when nothing matched.
    @property
    def confidence(self) -> str | None: ...


class CatalogLookup(Protocol):
    """The connector catalog: which PostHog source, tables and settings a vendor connection maps to."""

    def match_source(self, provider: str, vendor_service: str) -> ExternalDataSourceType | None: ...
    def match_destination(self, provider: str, vendor_service: str) -> str | None: ...
    # None when the user defines the tables, as in a database.
    def posthog_tables(self, source_type: ExternalDataSourceType) -> PostHogTablesLike | None: ...
    def match_tables(
        self, provider: str, vendor_tables: Iterable[str], posthog_table_names: Collection[str]
    ) -> Sequence[TableMatchLike]: ...
    # Keys are PostHog payload paths, where a dot is a nested field.
    def prefill_config(
        self, provider: str, source_type: ExternalDataSourceType, vendor_config: Mapping[str, Any]
    ) -> Mapping[str, Any]: ...


@frozen
class _PlannedTables:
    # None means Fivetran gave no table list.
    schemas: tuple[ProposedSchema, ...] | None
    inferred: tuple[TablePair, ...] = ()
    unmatched: tuple[str, ...] = ()
    unused: tuple[str, ...] = ()


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
    *,
    flag_enabled: Callable[[str], bool],
) -> tuple[PlannedItem, ...]:
    """`flag_enabled` tells whether the team has a feature flag, for sources that only some teams can create."""
    destinations = {destination.id: destination for destination in snapshot.destinations}
    items = [
        _plan_connection(
            snapshot.provider,
            connection,
            destinations.get(connection.destination_id or ""),
            catalog,
            capabilities,
            flag_enabled,
        )
        for connection in snapshot.connections
    ]
    return _with_unique_prefixes(items)


def _with_unique_prefixes(items: list[PlannedItem]) -> tuple[PlannedItem, ...]:
    # Fivetran names are unique only within a destination, but a PostHog prefix must be unique per source type.
    taken = {(item.proposal.source_type, item.proposal.prefix) for item in items if item.proposal is not None}
    used: set[tuple[ExternalDataSourceType, str]] = set()
    unique: list[PlannedItem] = []
    for item in items:
        proposal = item.proposal
        if proposal is not None:
            key = (proposal.source_type, proposal.prefix)
            if key in used:
                count = 2
                while (proposal.source_type, f"{proposal.prefix}_{count}") in taken | used:
                    count += 1
                prefix = f"{proposal.prefix}_{count}"
                used.add((proposal.source_type, prefix))
                item = dataclasses.replace(
                    item,
                    verdict=Verdict.CAVEATS,
                    caveats=(
                        *item.caveats,
                        f"Another connection already uses the prefix `{proposal.prefix}`, so this one uses `{prefix}`.",
                    ),
                    proposal=dataclasses.replace(proposal, prefix=prefix),
                )
            else:
                used.add(key)
        unique.append(item)
    return tuple(unique)


def _plan_connection(
    provider: str,
    connection: VendorConnection,
    destination: VendorDestination | None,
    catalog: CatalogLookup,
    capabilities: Callable[[ExternalDataSourceType], SourceCapabilities],
    flag_enabled: Callable[[str], bool],
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

    source_type = catalog.match_source(provider, connection.service)
    if source_type is None:
        return unsupported(f"PostHog has no source for the Fivetran connector `{connection.service}` yet.")
    caps = capabilities(source_type)
    if caps.unreleased:
        return unsupported(f"The PostHog {source_type} source is not released yet.")
    if not all(flag_enabled(flag) for flag in caps.feature_flags):
        return unsupported(f"The PostHog {source_type} source is not available to this project yet.")

    caveats: list[str] = []
    if caps.release_status == ReleaseStatus.ALPHA:
        caveats.append(f"The PostHog {source_type} source is in alpha.")
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

    tables = _plan_tables(provider, connection, source_type, catalog, caps, caveats)
    sync_frequency, sync_time_of_day = _plan_frequency(connection, caveats)
    start_paused = _plan_paused(connection, caveats)

    proposal = ItemProposal(
        source_type=source_type,
        prefix=_prefix_for(connection.name),
        prefill=_plan_prefill(catalog.prefill_config(provider, source_type, connection.config), caps),
        schemas=tables.schemas,
        inferred_tables=tables.inferred,
        unmatched_tables=tables.unmatched,
        unused_posthog_tables=tables.unused,
        sync_frequency=sync_frequency,
        sync_time_of_day=sync_time_of_day,
        destination=_plan_destination(provider, destination, catalog, caveats),
        start_paused=start_paused,
    )
    return PlannedItem(
        vendor_connection_id=connection.id,
        vendor_service=connection.service,
        name=connection.name,
        verdict=Verdict.CAVEATS if caveats else Verdict.AS_IS,
        caveats=tuple(caveats),
        proposal=proposal,
    )


def _plan_prefill(flat_config: Mapping[str, Any], caps: SourceCapabilities) -> dict[str, Any]:
    """Nest the catalog's prefill into the source payload. A dot in a PostHog key is a nested field."""
    prefill: dict[str, Any] = {}
    for posthog_key, value in flat_config.items():
        *parents, leaf = posthog_key.split(".")
        target = prefill
        for parent in parents:
            target = target.setdefault(parent, {})
        target[leaf] = value
    for group in caps.toggle_groups & prefill.keys():
        # A group's settings only apply when its switch is on.
        prefill[group]["enabled"] = True
    return prefill


def _plan_tables(
    provider: str,
    connection: VendorConnection,
    source_type: ExternalDataSourceType,
    catalog: CatalogLookup,
    caps: SourceCapabilities,
    caveats: list[str],
) -> _PlannedTables:
    if not connection.tables_available or not connection.tables:
        caveats.append("Fivetran did not return a table list. PostHog will use its default tables.")
        return _PlannedTables(schemas=None)

    enabled = [table for table in connection.tables if table.enabled]
    known = catalog.posthog_tables(source_type)
    matches = (
        {match.vendor_table: match for match in catalog.match_tables(provider, [t.name for t in enabled], known.names)}
        if known is not None
        else {}
    )
    schemas: list[ProposedSchema] = []
    inferred: list[TablePair] = []
    unmatched: list[str] = []
    for table in enabled:
        vendor_table, is_inferred = table.name, False
        alternative_names: tuple[str, ...] = ()
        if known is None:
            # The user defines the tables. Databases name them `schema.table` when no single schema
            # is set, other sources use the bare name, so apply tries both.
            vendor_table, alternative_names = f"{table.schema_name}.{table.name}", (table.name,)
            name = vendor_table
        elif (match := matches.get(table.name)) is not None and match.posthog_table is not None:
            name, is_inferred = match.posthog_table, match.confidence == "inferred"
        elif known.complete:
            unmatched.append(table.name)
            continue
        else:
            # The source can discover more tables than it lists, so apply checks this one by name.
            name = table.name
        if any(schema.name == name for schema in schemas):
            caveats.append(f"The Fivetran table `{table.name}` lands in the same PostHog table as another one.")
            if known is not None:
                # Listed, so the user can pick this table over the other one, or map it elsewhere.
                unmatched.append(table.name)
            continue
        if is_inferred:
            inferred.append(TablePair(vendor_table=table.name, posthog_table=name))
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
                row_filters=_plan_row_filters(table, name, caps, caveats),
                alternative_names=alternative_names,
                vendor_table=vendor_table,
            )
        )
    if inferred:
        pairs = ", ".join(f"`{pair.vendor_table}` as `{pair.posthog_table}`" for pair in inferred)
        caveats.append(f"PostHog paired some tables by a naming rule: {pairs}. Confirm them before applying.")
    if unmatched:
        names = ", ".join(f"`{name}`" for name in unmatched)
        caveats.append(f"These Fivetran tables are not planned, because no free PostHog table matched them: {names}.")
    if not schemas:
        caveats.append("No Fivetran table of this connection moves to PostHog, so every table starts with syncing off.")
    # Only needed to place the unmatched tables, so the payload stays small otherwise.
    unused = sorted(known.names - {schema.name for schema in schemas}) if known is not None and unmatched else []
    return _PlannedTables(
        schemas=_without_shared_alternative_names(schemas, caveats),
        inferred=tuple(inferred),
        unmatched=tuple(unmatched),
        unused=tuple(unused),
    )


def _without_shared_alternative_names(schemas: list[ProposedSchema], caveats: list[str]) -> tuple[ProposedSchema, ...]:
    # Two tables with one bare name (`public.users`, `analytics.users`) cannot both claim the bare table at apply.
    counts = Counter(name for schema in schemas for name in schema.alternative_names)
    shared = {name for name, count in counts.items() if count > 1}
    for name in sorted(shared):
        caveats.append(
            f"More than one Fivetran schema has a table called `{name}`, so PostHog matches them only by schema and name."
        )
    return tuple(
        dataclasses.replace(
            schema, alternative_names=tuple(name for name in schema.alternative_names if name not in shared)
        )
        if shared.intersection(schema.alternative_names)
        else schema
        for schema in schemas
    )


def _plan_disabled_columns(table: VendorTable, caps: SourceCapabilities, caveats: list[str]) -> tuple[str, ...]:
    disabled = tuple(column.name for column in table.columns if not column.enabled)
    if disabled and not caps.supports_column_selection:
        caveats.append(
            f"`{table.name}` skips some columns in Fivetran. PostHog syncs every column of this table at first. "
            "You can turn columns off after the first sync."
        )
        return ()
    return disabled


def _plan_row_filters(
    table: VendorTable, posthog_name: str, caps: SourceCapabilities, caveats: list[str]
) -> tuple[ProposedRowFilter, ...]:
    row_filter = table.row_filter
    if row_filter is None:
        return ()
    dropped = f"`{table.name}` has a row filter in Fivetran that PostHog cannot apply. PostHog syncs every row."
    if not caps.supports_row_filters or (row_filter.combinator == "OR" and len(row_filter.clauses) > 1):
        caveats.append(dropped)
        return ()
    allowed_columns = caps.row_filter_columns.get(posthog_name)
    filters: list[ProposedRowFilter] = []
    for clause in row_filter.clauses:
        operator = _ROW_FILTER_OPERATORS.get(clause.operator)
        if (
            operator is None
            or not clause.values
            or (operator != "IN" and len(clause.values) > 1)
            or (allowed_columns is not None and clause.column not in allowed_columns)
        ):
            caveats.append(dropped)
            return ()
        filters.append(
            ProposedRowFilter(
                column=clause.column,
                operator=operator,
                values=clause.values,
            )
        )
    return tuple(filters)


def _plan_paused(connection: VendorConnection, caveats: list[str]) -> bool:
    if connection.paused:
        caveats.append("This connection is paused in Fivetran, so PostHog creates it with syncing off.")
        return True
    if connection.schedule.kind == ScheduleKind.MANUAL:
        caveats.append("This connection syncs only on demand in Fivetran, so PostHog creates it with syncing off.")
        return True
    return False


def _plan_frequency(connection: VendorConnection, caveats: list[str]) -> tuple[PostHogSyncFrequency, str | None]:
    schedule = connection.schedule
    if schedule.kind == ScheduleKind.MANUAL:
        return _DEFAULT_FREQUENCY, None
    if schedule.days_of_week:
        caveats.append("Fivetran syncs this connection on some weekdays only. PostHog syncs every day.")
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
    minute, hour, day_of_month, _month, day_of_week = fields
    # One day a month or one day a week. A list or range of days syncs at least daily.
    if re.fullmatch(r"\d+", day_of_month):
        return "30day", None
    if re.fullmatch(r"\w+", day_of_week):
        return "7day", None
    step = re.fullmatch(r"\*/(\d+)", hour)
    if step:
        return _nearest_frequency(int(step.group(1)) * 60), None
    if hour == "*":
        if minute == "*":
            return _nearest_frequency(1), None
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
    return ProposedDestination(type=destination_type, config=destination.config)


def _prefix_for(connection_name: str) -> str:
    prefix = re.sub(r"[^a-z0-9_]+", "_", connection_name.lower()).strip("_")
    if prefix and prefix[0].isdigit():
        # Prefix validation strips underscores before it checks the first character, so `_3pl` fails too.
        prefix = f"source_{prefix}"
    return prefix
