from collections.abc import Mapping
from typing import Any

from products.warehouse_sources.backend.migration.fivetran.client import FivetranAPIError, FivetranClient
from products.warehouse_sources.backend.migration.secrets import strip_secrets
from products.warehouse_sources.backend.migration.types import (
    MigrationProvider,
    ScheduleKind,
    VendorColumn,
    VendorConnection,
    VendorDestination,
    VendorRowFilter,
    VendorRowFilterClause,
    VendorSchedule,
    VendorSnapshot,
    VendorTable,
)

_ALL_DAYS = 7
_WEEKDAYS = ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY")


def fetch_snapshot(client: FivetranClient) -> VendorSnapshot:
    account = client.get_account_info()

    destinations: list[VendorDestination] = []
    utc_offsets: dict[str, int] = {}
    for group in client.list_groups():
        try:
            raw_destination = client.get_destination(group["id"])
        except FivetranAPIError as error:
            if error.status_code != 404:
                raise
            continue  # A group can exist before its destination is set up.
        destinations.append(parse_destination(raw_destination, name=group.get("name") or group["id"]))
        utc_offsets[group["id"]] = _parse_offset(raw_destination.get("time_zone_offset"))

    connections: list[VendorConnection] = []
    for listed in client.list_connections():
        raw_connection = client.get_connection(listed["id"])
        schema_config: dict[str, Any] | None
        try:
            schema_config = client.get_schema_config(listed["id"])
        except FivetranAPIError as error:
            # Some connectors (Magic Folder, unfinished setups) have no schema config. Any other
            # failure must stop the crawl, or the plan would drop the user's table selection.
            if error.status_code != 404:
                raise
            schema_config = None
        offset = utc_offsets.get(raw_connection.get("group_id") or "", 0)
        connections.append(parse_connection(raw_connection, schema_config, utc_offset_hours=offset))

    return VendorSnapshot(
        provider=MigrationProvider.FIVETRAN,
        account_id=str(account.get("account_id") or ""),
        account_name=account.get("account_name"),
        destinations=tuple(destinations),
        connections=tuple(connections),
    )


def parse_destination(raw: Mapping[str, Any], *, name: str) -> VendorDestination:
    return VendorDestination(
        id=raw["id"],
        name=name,
        service=raw.get("service") or "",
        region=raw.get("region"),
        config=strip_secrets(raw.get("config") or {}),
    )


def parse_connection(
    raw: Mapping[str, Any], schema_config: Mapping[str, Any] | None, *, utc_offset_hours: int
) -> VendorConnection:
    return VendorConnection(
        id=raw["id"],
        service=raw.get("service") or "",
        name=raw.get("schema") or raw["id"],
        destination_id=raw.get("group_id"),
        paused=bool(raw.get("paused")),
        schedule=_parse_schedule(raw, utc_offset_hours),
        setup_state=(raw.get("status") or {}).get("setup_state"),
        succeeded_at=raw.get("succeeded_at"),
        networking_method=raw.get("networking_method"),
        config=strip_secrets(raw.get("config") or {}),
        schema_change_handling=(schema_config or {}).get("schema_change_handling"),
        tables_available=schema_config is not None,
        tables=_parse_tables(schema_config or {}),
    )


def _parse_schedule(raw: Mapping[str, Any], utc_offset_hours: int) -> VendorSchedule:
    if raw.get("schedule_type") == "manual":
        return VendorSchedule(kind=ScheduleKind.MANUAL)

    schedule = raw.get("schedule") or {}
    schedule_type = schedule.get("schedule_type")
    days = tuple(schedule.get("days_of_week") or ())
    if len(days) == _ALL_DAYS:
        days = ()

    if schedule_type == "MANUAL":
        return VendorSchedule(kind=ScheduleKind.MANUAL)
    if schedule_type == "CRON":
        return VendorSchedule(kind=ScheduleKind.CRON, cron=schedule.get("cron"))
    if schedule_type == "TIME_OF_DAY":
        # Fivetran reads this time in the destination's UTC offset.
        time_of_day_utc, day_shift = _shift_to_utc(schedule.get("time_of_day"), utc_offset_hours)
        return VendorSchedule(
            kind=ScheduleKind.TIME_OF_DAY,
            time_of_day_utc=time_of_day_utc,
            days_of_week=_shift_days(days, day_shift),
        )

    interval = schedule.get("interval") or raw.get("sync_frequency")
    interval_minutes = int(interval) if interval is not None else None
    return VendorSchedule(
        kind=ScheduleKind.INTERVAL,
        interval_minutes=interval_minutes,
        # `daily_sync_time` is already UTC.
        time_of_day_utc=raw.get("daily_sync_time") if interval_minutes == 1440 else None,
        days_of_week=days,
    )


def _parse_offset(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _shift_to_utc(local_time: str | None, utc_offset_hours: int) -> tuple[str | None, int]:
    """Return the UTC time and how many days the shift crossed (-1, 0 or 1)."""
    if not local_time:
        return None, 0
    hours, minutes = local_time.split(":")[:2]
    utc_hours = int(hours) - utc_offset_hours
    return f"{utc_hours % 24:02d}:{int(minutes):02d}", utc_hours // 24


def _shift_days(days: tuple[str, ...], day_shift: int) -> tuple[str, ...]:
    if not day_shift:
        return days
    return tuple(
        _WEEKDAYS[(_WEEKDAYS.index(day.upper()) + day_shift) % len(_WEEKDAYS)] if day.upper() in _WEEKDAYS else day
        for day in days
    )


def _parse_tables(schema_config: Mapping[str, Any]) -> tuple[VendorTable, ...]:
    tables: list[VendorTable] = []
    for schema_name, schema in (schema_config.get("schemas") or {}).items():
        schema_enabled = bool(schema.get("enabled", True))
        for table_name, table in (schema.get("tables") or {}).items():
            tables.append(
                VendorTable(
                    schema_name=schema_name,
                    name=table_name,
                    enabled=schema_enabled and bool(table.get("enabled", True)),
                    sync_mode=table.get("sync_mode"),
                    columns=tuple(
                        VendorColumn(
                            name=column_name,
                            enabled=bool(column.get("enabled", True)),
                            hashed=bool(column.get("hashed", False)),
                            is_primary_key=bool(column.get("is_primary_key", False)),
                        )
                        for column_name, column in (table.get("columns") or {}).items()
                    ),
                    row_filter=_parse_row_filter(table.get("row_filter")),
                )
            )
    return tuple(tables)


def _parse_row_filter(raw: Mapping[str, Any] | None) -> VendorRowFilter | None:
    if not raw or not raw.get("column_clauses"):
        return None
    return VendorRowFilter(
        combinator="OR" if raw.get("operator") == "OR" else "AND",
        clauses=tuple(
            VendorRowFilterClause(
                column=clause.get("column") or "",
                operator=clause.get("operator") or "",
                values=tuple(str(value) for value in clause.get("values") or ()),
            )
            for clause in raw["column_clauses"]
        ),
    )
