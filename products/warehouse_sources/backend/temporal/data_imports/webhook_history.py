"""History tables for webhook syncs: each event becomes a version at its own change time, also when it arrives late.

When a schema keeps history, the webhook read yields every event with the event columns (`webhook_event_columns.py`).
The history lane stages them and writes them once per run, where a late event splits the version that covers its
time and a redelivered event makes no version. The main lane keeps the newest event of each key, and its write never
lets an older event replace a newer row.
"""

import asyncio
import functools
from collections.abc import Sequence
from datetime import UTC, datetime

import pyarrow as pa
import structlog
import pyarrow.compute as pc

from posthog.models.team import Team
from posthog.ph_client import feature_enabled_or_false

from products.warehouse_sources.backend.models.external_data_schema import (
    HISTORY_TRACKED_SINCE_KEY,
    ExternalDataSchema,
    update_sync_type_config_keys,
)
from products.warehouse_sources.backend.temporal.data_imports.cdc.batcher import (
    HISTORY_NAMING,
    HistoryNaming,
    companion_resource_name,
    history_columns,
    reserved_column_collisions,
)
from products.warehouse_sources.backend.temporal.data_imports.cdc.load_resolution import SCD2_APPEND_MODE
from products.warehouse_sources.backend.temporal.data_imports.incremental_history import (
    IncrementalHistoryUnavailableError,
    finalize_history_lane,
    history_lane_naming,
    stage_history_batch,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.common.extract import resolve_primary_keys
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import normalize_column_name
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.consts import PARTITION_KEY
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.history_upsert import (
    EventOrder,
    HistoryFinalizeResult,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table import DeltaTableRef
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import OutputLane, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_event_columns import (
    ARRIVAL_COLUMN,
    EVENT_ID_COLUMN,
    EVENT_RANK_COLUMN,
    EVENT_TIME_COLUMN,
    WEBHOOK_EVENT_COLUMNS,
    WEBHOOK_EVENT_ORDER,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_events import latest_event_per_key

logger = structlog.get_logger(__name__)

WEBHOOK_HISTORY_FLAG = "dwh-webhook-history"
WEBHOOK_EVENT_ORDER_RULES = EventOrder(order_columns=WEBHOOK_EVENT_ORDER, dedupe_column=EVENT_ID_COLUMN)
# The event id of a version seeded from a stored row that has none. Unique per key, so a second seed is a redelivery.
SEED_EVENT_ID = "seed"
_TIME_TYPE = pa.timestamp("us", tz="UTC")
# The time half of `_ph_arrival`, as `webhook_s3._arrival_prefix` writes it.
_ARRIVAL_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
_SEED_BATCH_ROWS = 50_000


def is_webhook_history_enabled_for_team(team: Team) -> bool:
    return feature_enabled_or_false(
        WEBHOOK_HISTORY_FLAG,
        str(team.organization_id),
        groups={"organization": str(team.organization_id)},
        group_properties={"organization": {"id": str(team.organization_id)}},
    )


def reads_webhook_history(schema: ExternalDataSchema) -> bool:
    """Whether this run's webhook read yields every event, for the history lane."""
    return schema.is_webhook and schema.keeps_history and is_webhook_history_enabled_for_team(schema.team)


def attach_webhook_history_lanes(
    schema: ExternalDataSchema,
    source_response: SourceResponse,
    *,
    webhook_history: bool,
    destination_ids: Sequence[str] = (),
) -> None:
    """Add the history lane, and keep the newest event per key on the main lane."""
    if not (schema.is_webhook and schema.keeps_history):
        return
    history_only = schema.cdc_table_mode == "cdc_only"
    if not webhook_history:
        if history_only:
            raise IncrementalHistoryUnavailableError(
                f"{schema.name} keeps only a history table, and history tables for webhook syncs are turned off"
            )
        logger.warning("webhook_history_lane_skipped", schema_id=str(schema.id), reason="flag_off")
        return
    naming = history_lane_naming(schema, source_response, destination_ids, history_only=history_only)
    primary_keys = resolve_primary_keys(schema, source_response) or []
    if HISTORY_TRACKED_SINCE_KEY not in schema.sync_type_config:
        # Turned on since the last run. The first finalize seeds the history table from the main table.
        schema.sync_type_config = update_sync_type_config_keys(
            schema.id,
            schema.team_id,
            mutate=lambda config: config.setdefault(HISTORY_TRACKED_SINCE_KEY, datetime.now(UTC).isoformat()),
        )
    # Only for an event whose arrival has no time, which a listing without `LastModified` leaves.
    run_started = datetime.now(UTC)
    history_lane = OutputLane(
        name=companion_resource_name(schema.name, naming),
        cdc_write_mode=SCD2_APPEND_MODE,
        billable=history_only,
        transform=functools.partial(
            history_events_batch, schema_name=schema.name, naming=naming, fallback_time=run_started
        ),
    )
    if history_only:
        source_response.lanes = [history_lane]
        source_response.name = history_lane.name
    else:
        main_lane = OutputLane(
            name=source_response.name,
            transform=functools.partial(
                newest_events_batch,
                primary_keys=[normalize_column_name(key) for key in primary_keys],
                fallback_time=run_started,
            ),
        )
        source_response.lanes = [main_lane, history_lane]


def _arrival_time(arrival: str | None) -> datetime | None:
    try:
        return datetime.strptime((arrival or "").split("|", 1)[0], _ARRIVAL_TIME_FORMAT).replace(tzinfo=UTC)
    except ValueError:
        return None


def _with_event_times(table: pa.Table, fallback_time: datetime) -> pa.Table:
    """Fill a missing change time from the event's arrival, so every event can be ordered and placed."""
    times: pa.Array | pa.ChunkedArray = pc.cast(table.column(EVENT_TIME_COLUMN), _TIME_TYPE)
    if times.null_count:
        arrivals = table.column(ARRIVAL_COLUMN).to_pylist()
        times = pa.array(
            [
                time if time is not None else _arrival_time(arrival) or fallback_time
                for time, arrival in zip(times.to_pylist(), arrivals)
            ],
            _TIME_TYPE,
        )
    return table.set_column(
        table.schema.get_field_index(EVENT_TIME_COLUMN), pa.field(EVENT_TIME_COLUMN, _TIME_TYPE), times
    )


def _is_event_batch(table: pa.Table) -> bool:
    # A poll, or a reconciliation poll after the events, yields rows without an event id.
    return EVENT_ID_COLUMN in table.column_names and table.column(EVENT_ID_COLUMN).null_count == 0


def newest_events(table: pa.Table, primary_keys: Sequence[str]) -> pa.Table:
    return latest_event_per_key(table, [normalize_column_name(key) for key in primary_keys])


def newest_events_batch(table: pa.Table, *, primary_keys: Sequence[str], fallback_time: datetime) -> pa.Table:
    """The newest event of each key. Polled rows load as before."""
    if not _is_event_batch(table):
        return table
    return newest_events(_with_event_times(table, fallback_time), primary_keys)


def history_events_batch(
    table: pa.Table, *, schema_name: str, naming: HistoryNaming, fallback_time: datetime
) -> pa.Table:
    """Every event as a version that starts at its change time. Polled rows make no version."""
    if EVENT_ID_COLUMN not in table.column_names:
        # A history-only run stages its first batch even when empty, and staging needs `valid_from`.
        return table.slice(0, 0).append_column(pa.field(naming.valid_from, _TIME_TYPE), pa.array([], _TIME_TYPE))
    table = table.filter(pc.is_valid(table.column(EVENT_ID_COLUMN)))
    taken = reserved_column_collisions(table.column_names, history_columns(naming))
    if taken:
        raise IncrementalHistoryUnavailableError(
            f"{schema_name} has source column(s) {taken}, which the history table uses itself. "
            "Stop syncing or rename them, or keep the consolidated table only."
        )
    table = _with_event_times(table, fallback_time)
    return table.append_column(pa.field(naming.valid_from, _TIME_TYPE), table.column(EVENT_TIME_COLUMN))


def main_table_order_columns(schema: ExternalDataSchema, table: pa.Table) -> Sequence[str] | None:
    """The order that keeps an older event out of a webhook main table, for a batch of events. None writes as before."""
    if schema.is_webhook and _is_event_batch(table) and all(name in table.column_names for name in WEBHOOK_EVENT_ORDER):
        return WEBHOOK_EVENT_ORDER
    return None


def seed_rows(rows: pa.Table, tracked_since: datetime, naming: HistoryNaming) -> pa.Table:
    """Main-table rows as the first versions: each starts at its stored change time, else when history began.

    The order columns follow `valid_from`, so the seeded versions sort where they start.
    """
    rows = rows.drop_columns([name for name in rows.column_names if name == PARTITION_KEY])
    count = rows.num_rows
    tracked = pa.scalar(tracked_since, _TIME_TYPE)
    valid_from = (
        pc.cast(rows.column(EVENT_TIME_COLUMN), _TIME_TYPE).fill_null(tracked)
        if EVENT_TIME_COLUMN in rows.column_names
        else pa.repeat(tracked, count)
    )
    event_ids = (
        pc.cast(rows.column(EVENT_ID_COLUMN), pa.string()).fill_null(pa.scalar(SEED_EVENT_ID))
        if EVENT_ID_COLUMN in rows.column_names
        else pa.repeat(pa.scalar(SEED_EVENT_ID), count)
    )
    rows = rows.drop_columns([name for name in rows.column_names if name in WEBHOOK_EVENT_COLUMNS])
    return (
        rows.append_column(pa.field(EVENT_ID_COLUMN, pa.string()), event_ids)
        .append_column(pa.field(EVENT_TIME_COLUMN, _TIME_TYPE), valid_from)
        .append_column(pa.field(EVENT_RANK_COLUMN, pa.int64()), pa.repeat(pa.scalar(0, pa.int64()), count))
        .append_column(pa.field(ARRIVAL_COLUMN, pa.string()), pa.repeat(pa.scalar(""), count))
        .append_column(pa.field(naming.valid_from, _TIME_TYPE), valid_from)
    )


async def _stage_seed(
    table: DeltaTableRef, schema: ExternalDataSchema, primary_keys: Sequence[str], run_uuid: str
) -> None:
    main_table = await DeltaTableRef(resource_name=schema.name, job=table.job, logger=table.logger).get_delta_table()
    if main_table is None:
        return
    stored = schema.sync_type_config.get(HISTORY_TRACKED_SINCE_KEY)
    tracked_since = datetime.fromisoformat(stored) if isinstance(stored, str) else datetime.now(UTC)
    reader = await asyncio.to_thread(
        lambda: (
            main_table.to_pyarrow_dataset()
            # One decoded batch at a time: the seed reads every column of the table, outside the memory governor.
            .scanner(batch_size=_SEED_BATCH_ROWS, batch_readahead=1, fragment_readahead=1, use_threads=False)
            .to_reader()
        )
    )
    batch_index = 0
    while (batch := await asyncio.to_thread(_next_batch, reader)) is not None:
        if batch.num_rows:
            await stage_history_batch(
                table,
                seed_rows(pa.Table.from_batches([batch]), tracked_since, HISTORY_NAMING),
                primary_keys=primary_keys,
                # Its own tag, so the redelivery check of the run's real batches never finds a seed batch.
                run_uuid=f"{run_uuid}-seed",
                batch_index=batch_index,
            )
            batch_index += 1


def _next_batch(reader: pa.RecordBatchReader) -> pa.RecordBatch | None:
    try:
        return reader.read_next_batch()
    except StopIteration:
        return None


async def finalize_run_history(
    table: DeltaTableRef,
    primary_keys: Sequence[str],
    *,
    schema: ExternalDataSchema,
    run_uuid: str,
    batch_index: int,
) -> HistoryFinalizeResult | None:
    """Write a history lane's staged rows. A webhook history table orders them by event and is seeded first."""
    if not schema.is_webhook:
        return await finalize_history_lane(table, primary_keys, run_uuid=run_uuid, batch_index=batch_index)
    if await table.get_delta_table() is None:
        await _stage_seed(table, schema, primary_keys, run_uuid)
    result = await finalize_history_lane(
        table, primary_keys, run_uuid=run_uuid, batch_index=batch_index, event_order=WEBHOOK_EVENT_ORDER_RULES
    )
    if result is not None:
        for outcome, rows in (
            ("late", result.rows_late),
            ("versions_split", result.versions_split),
            ("redelivered", result.rows_redelivered),
            ("order_mismatch", result.rows_order_mismatch),
        ):
            record_webhook_history_rows(schema, outcome, rows)
    return result


def record_webhook_history_rows(schema: ExternalDataSchema, outcome: str, rows: int) -> None:
    """Count rows by outcome. `schema.source` must be loaded already, as the loader prefetches it."""
    from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.metrics import (
        WEBHOOK_HISTORY_ROWS_TOTAL,
    )

    if rows:
        WEBHOOK_HISTORY_ROWS_TOTAL.labels(
            source_type=schema.source.source_type, object_type=schema.name, outcome=outcome
        ).inc(rows)
