import json
import dataclasses
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from pydantic import TypeAdapter, ValidationError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.facade.contracts import (
    MigrationConnectionUpload,
    WarehouseMigrationUploadTooLargeError,
)
from products.warehouse_sources.backend.migration import catalog
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
# Connection config keys the planner reads whatever the source.
_PLANNED_CONFIG_KEYS = frozenset({"update_method"})
_WEEKDAYS = ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY")


class SnapshotStoppedError(Exception):
    """`keep_going` returned false, so the read stopped before the next connection."""


def fetch_snapshot(client: FivetranClient, *, keep_going: Callable[[], bool] | None = None) -> VendorSnapshot:
    account = client.get_account_info()

    destinations: list[VendorDestination] = []
    for group in client.list_groups():
        try:
            raw_destination = client.get_destination(group["id"])
        except FivetranAPIError as error:
            if error.status_code != 404:
                raise
            continue  # A group can exist before its destination is set up.
        destinations.append(parse_destination(raw_destination, name=group.get("name") or group["id"]))
    utc_offsets = {destination.id: destination.utc_offset_hours for destination in destinations}

    connections: list[VendorConnection] = []
    for listed in client.list_connections():
        # A large account takes many requests, so a caller that no longer wants the result can stop it here.
        if keep_going is not None and not keep_going():
            raise SnapshotStoppedError()
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


@frozen
class UploadedSnapshot:
    snapshot: VendorSnapshot
    connection_ids: tuple[str, ...]
    errors: tuple[str, ...]


MAX_UPLOADED_CONNECTION_BYTES = 1_000_000
# Every upload loads, checks and rewrites the whole stored snapshot in one web worker, so the cap bounds that work.
# A larger account migrates with an API key, and the crawl reads it outside the web worker.
MAX_UPLOADED_SNAPSHOT_BYTES = 10_000_000
_ITEM_COLUMN_MAX_LENGTH = 400
# Fivetran responses nest a few levels. A deeper upload would make the recursive parsers below overflow the stack.
_MAX_UPLOAD_DEPTH = 64
# The parsers trust the vendor's field types. An agent upload can carry any JSON, so it is checked after parsing.
_DESTINATION_ADAPTER: TypeAdapter[VendorDestination] = TypeAdapter(VendorDestination)
_CONNECTION_ADAPTER: TypeAdapter[VendorConnection] = TypeAdapter(VendorConnection)
# OverflowError comes from `int()` on a JSON number too large for a float, such as `1e309`.
_READ_ERRORS = (KeyError, TypeError, ValueError, AttributeError, OverflowError)


def merge_upload(
    previous: VendorSnapshot | None,
    *,
    account: Mapping[str, Any] | None,
    destinations: Sequence[Mapping[str, Any]],
    connections: Sequence[MigrationConnectionUpload],
) -> UploadedSnapshot:
    """Add Fivetran read responses that an agent uploaded to the snapshot of earlier uploads.

    Secrets are removed exactly as in a crawl. A new destination or connection replaces the stored one with its id.
    Raises `WarehouseMigrationUploadTooLargeError` when the merged snapshot is over `MAX_UPLOADED_SNAPSHOT_BYTES`.
    """
    errors: list[str] = []
    stored_destinations = {destination.id: destination for destination in previous.destinations} if previous else {}
    for index, raw in enumerate(destinations):
        raw = _unwrap(raw)
        label = f"Destination {index} ({_label_id(raw)})"
        if problem := _upload_problem(raw):
            errors.append(f"{label}: {problem}")
            continue
        try:
            destination = _DESTINATION_ADAPTER.validate_python(
                dataclasses.asdict(parse_destination(raw, name=raw.get("name") or raw["id"]))
            )
        except _READ_ERRORS as error:
            errors.append(f"{label}: {_read_error(error)}")
            continue
        stored_destinations[destination.id] = destination

    utc_offsets = {destination.id: destination.utc_offset_hours for destination in stored_destinations.values()}
    stored_connections = {connection.id: connection for connection in previous.connections} if previous else {}
    connection_ids: list[str] = []
    for index, upload in enumerate(connections):
        raw = _unwrap(upload.connection)
        label = f"Connection {index} ({_label_id(raw)})"
        schema_config = _unwrap(upload.schema_config) if upload.schema_config is not None else None
        if problem := _upload_problem([raw, schema_config]):
            errors.append(f"{label}: {problem}")
            continue
        try:
            parsed = parse_connection(
                raw, schema_config, utc_offset_hours=utc_offsets.get(raw.get("group_id") or "", 0)
            )
            connection = _CONNECTION_ADAPTER.validate_python(dataclasses.asdict(parsed))
        except _READ_ERRORS as error:
            errors.append(f"{label}: {_read_error(error)}")
            continue
        if max(len(connection.id), len(connection.service), len(connection.name)) > _ITEM_COLUMN_MAX_LENGTH:
            errors.append(
                f"{label}: its id, service or schema name is longer than {_ITEM_COLUMN_MAX_LENGTH} characters."
            )
            continue
        stored_connections[connection.id] = connection
        connection_ids.append(connection.id)

    account_info: Mapping[str, Any] = {}
    if account is not None:
        if problem := _upload_problem(_unwrap(account)):
            errors.append(f"Account: {problem}")
        else:
            account_info = _unwrap(account)
    account_name = _text(account_info.get("account_name"))
    snapshot = VendorSnapshot(
        provider=MigrationProvider.FIVETRAN,
        account_id=_text(account_info.get("account_id")) or (previous.account_id if previous else ""),
        account_name=account_name[:_ITEM_COLUMN_MAX_LENGTH]
        if account_name
        else (previous.account_name if previous else None),
        destinations=tuple(stored_destinations.values()),
        connections=tuple(stored_connections.values()),
    )
    if _json_longer_than(snapshot.to_json(), MAX_UPLOADED_SNAPSHOT_BYTES):
        raise WarehouseMigrationUploadTooLargeError()
    return UploadedSnapshot(
        snapshot=snapshot, connection_ids=tuple(dict.fromkeys(connection_ids)), errors=tuple(errors)
    )


def _upload_problem(value: Any) -> str | None:
    """Why one uploaded entry cannot be read at all, checked before anything recurses into it."""
    pending = [(value, 1)]
    while pending:
        item, depth = pending.pop()
        if depth > _MAX_UPLOAD_DEPTH:
            return f"it nests deeper than {_MAX_UPLOAD_DEPTH} levels, so it is not a Fivetran response."
        if isinstance(item, Mapping):
            pending.extend((key, depth) for key in item.keys())
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
        # Postgres stores no NUL character and no lone UTF-16 surrogate such as `"\ud800"`.
        elif isinstance(item, str) and not _storable(item):
            return "it holds a NUL character or a broken Unicode character, so it is not a Fivetran response."
    if _json_longer_than(value, MAX_UPLOADED_CONNECTION_BYTES):
        return "larger than 1 MB, so it cannot be uploaded. Migrate this account with an API key."
    return None


def _json_longer_than(value: Any, limit: int) -> bool:
    """Encodes only up to `limit`. Parsing repeats a schema name in each of its tables, so the full text can be far
    larger than the upload."""
    length = 0
    for chunk in json.JSONEncoder().iterencode(value):
        length += len(chunk)
        if length > limit:
            return True
    return False


def _storable(text: str) -> bool:
    if "\x00" in text:
        return False
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _label_id(raw: Mapping[str, Any]) -> str:
    value = raw.get("id")
    if value is None:
        return "no id"
    # Never stringified, because an uploaded id can nest deep enough to overflow `repr`.
    return value[:100] if isinstance(value, str) else "no valid id"


def _unwrap(raw: Mapping[str, Any]) -> Mapping[str, Any]:
    """Fivetran wraps every response as `{"code": ..., "data": {...}}`."""
    data = raw.get("data")
    return data if "code" in raw and isinstance(data, Mapping) else raw


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _read_error(error: Exception) -> str:
    if isinstance(error, KeyError):
        return f"the field `{error.args[0]}` is missing. Upload the Fivetran response unchanged."
    if isinstance(error, ValidationError):
        field = ".".join(str(part) for part in error.errors()[0]["loc"])
        return f"the field `{field}` has the wrong type. Upload the Fivetran response unchanged."
    return "this is not a Fivetran response PostHog can read. Upload the Fivetran response unchanged."


def parse_destination(raw: Mapping[str, Any], *, name: str) -> VendorDestination:
    return VendorDestination(
        id=raw["id"],
        name=name,
        service=raw.get("service") or "",
        region=raw.get("region"),
        config=_kept_destination_config(raw.get("service") or "", raw.get("config") or {}),
        utc_offset_hours=_parse_offset(raw.get("time_zone_offset")),
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
        config=_kept_config(raw.get("service") or "", raw.get("config") or {}),
        schema_change_handling=(schema_config or {}).get("schema_change_handling"),
        tables_available=schema_config is not None,
        tables=_parse_tables(schema_config or {}),
    )


def _kept_config(service: str, config: Mapping[str, Any]) -> dict[str, Any]:
    """Only the keys the plan uses. Fivetran marks secrets per connector, so no name rule alone can find them all."""
    # The planner matches and logs the source again, so this lookup stays quiet.
    source_type = catalog.match_source(MigrationProvider.FIVETRAN, service, log_unmatched=False)
    used = _PLANNED_CONFIG_KEYS | (
        catalog.prefill_vendor_keys(MigrationProvider.FIVETRAN, source_type) if source_type else frozenset()
    )
    return strip_secrets({key: value for key, value in config.items() if key in used})


def _kept_destination_config(service: str, config: Mapping[str, Any]) -> dict[str, Any]:
    used = catalog.destination_vendor_keys(MigrationProvider.FIVETRAN, service)
    return strip_secrets({key: value for key, value in config.items() if key in used})


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
        # Without its own zone, Fivetran runs the expression in the destination's UTC offset.
        time_zone = schedule.get("time_zone") or f"UTC{utc_offset_hours:+03d}:00"
        return VendorSchedule(kind=ScheduleKind.CRON, cron=schedule.get("cron"), time_zone=time_zone)
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
