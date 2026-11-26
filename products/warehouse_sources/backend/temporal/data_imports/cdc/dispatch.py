"""Which buffered changes a streaming table's consumer has not loaded yet.

Each extraction run that writes a table's buffer adds one to the table's generation, after every
file of that run is in S3. The consumer stamps its job with the generation it read before it listed
the buffer. A completed run whose stamp reaches the current generation therefore listed after every
counted file existed, so it read them all. The comparison uses no clock, so skew between pods
cannot make a file look consumed.

A run that dies after a write and before it counts leaves the write open. The table then owes a
load until a later run that completes counts the write.

With the flag on, a scheduled consumer tick of a table that owes nothing stands down before it takes
the pipeline lock or writes a job row. The table's schedule keeps its cadence, so a table with changes
still loads on its next tick.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Mapping
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
    from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

CDC_DATA_DRIVEN_LOAD_FLAG = "warehouse-cdc-data-driven-load"

# A quiet table still gets a full consumer run this often. That run does the repairs an empty tick
# does: it retires orphaned companion jobs, deletes consumed files, retries post-import steps, and
# gives the buffer-expiry check a recent listing. It must stay far below BUFFER_FILE_RETENTION, or
# the expiry check re-snapshots tables that only went quiet.
CONSUMER_HEARTBEAT_INTERVAL = dt.timedelta(hours=6)

# On the schema's `sync_type_config`.
BUFFER_GENERATION_KEY = "cdc_buffer_generation"
BUFFER_WRITE_OPEN_KEY = "cdc_buffer_write_open"
BUFFER_GENERATION_LOADED_KEY = "cdc_buffer_generation_loaded"

# On the consumer's job, beside the listing stamp.
BUFFER_GENERATION_SEEN_KEY = "cdc_buffer_generation_seen"


class TickDecision(StrEnum):
    STOOD_DOWN = "stood_down"
    OWED = "owed"
    HEARTBEAT = "heartbeat"


def _int_value(config: Mapping[str, Any] | None, key: str) -> int | None:
    value = (config or {}).get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        return None
    return value


def buffer_generation(config: Mapping[str, Any] | None) -> int:
    return _int_value(config, BUFFER_GENERATION_KEY) or 0


def known_loaded(config: Mapping[str, Any] | None) -> bool:
    """Whether the schema's own settings prove every counted write loaded, with no job read."""
    loaded = _int_value(config, BUFFER_GENERATION_LOADED_KEY)
    return not (config or {}).get(BUFFER_WRITE_OPEN_KEY) and loaded is not None and loaded >= buffer_generation(config)


def owes_load(config: Mapping[str, Any] | None, proven_generation: Callable[[], int | None]) -> bool:
    """Whether the buffer may hold changes no completed consumer run has read.

    ``proven_generation`` returns the generation the newest completed listing saw, or None when
    there is no such listing. It is called only when the settings alone cannot settle the answer.
    """
    if (config or {}).get(BUFFER_WRITE_OPEN_KEY):
        return True
    if known_loaded(config):
        return False
    seen = proven_generation()
    return seen is None or seen < buffer_generation(config)


def open_buffer_write(config: dict[str, Any]) -> None:
    """Mark the buffer as written but not counted yet. Set before the first file of a run is written."""
    config[BUFFER_WRITE_OPEN_KEY] = True


def close_buffer_write(config: dict[str, Any], *, wrote: bool) -> None:
    """Count every write made so far.

    Called only by a run that completed, after its last write. An open write is counted even when
    this run wrote nothing, because it belongs to an earlier run. That assumes the earlier run is
    over. An attempt that outlives its heartbeat timeout can still write after its retry counted,
    and nothing then counts that file. The consumer's periodic full run reads it.
    """
    was_open = bool(config.pop(BUFFER_WRITE_OPEN_KEY, False))
    if wrote or was_open:
        config[BUFFER_GENERATION_KEY] = buffer_generation(config) + 1


def data_driven_load_enabled(source: ExternalDataSource) -> bool:
    from products.warehouse_sources.backend.temporal.data_imports.schema_flags import is_source_flag_enabled

    return is_source_flag_enabled(source, CDC_DATA_DRIVEN_LOAD_FLAG)


def _gate_applies(schema: ExternalDataSchema) -> bool:
    """Whether a tick of this table may stand down at all, before the flag and the buffer are consulted.

    Never for a snapshot, a reset, a sync someone asked for, or a table whose last run did not complete.
    Those keep the behavior from before the gate, including a retry on every tick.

    An ad-hoc run paused the schedule, and only its completed job unpauses it, so standing it down
    would leave the schedule paused for good.
    """
    from products.warehouse_sources.backend.temporal.data_imports.cdc.snapshot_lane import CDC_RESET_PENDING_KEY
    from products.warehouse_sources.backend.temporal.data_imports.cdc.source_manager import serves_buffered_lane

    config = schema.sync_type_config or {}
    return (
        serves_buffered_lane(schema)
        and schema.status == schema.Status.COMPLETED
        and not schema.reset_pipeline
        and not schema.manual_run_requested
        and not schema.manual_sync_pending
        and CDC_RESET_PENDING_KEY not in config
        and "admin_unpause_schedule_after_run" not in config
    )


def _heartbeat_due(schema: ExternalDataSchema, now: dt.datetime) -> bool:
    last_full_run = schema.last_full_run
    return last_full_run is None or now - last_full_run >= CONSUMER_HEARTBEAT_INTERVAL


def proven_quiet(schema: ExternalDataSchema, now: dt.datetime) -> bool:
    """Whether a scheduled tick of this table would stand down, judged from the schema row alone.

    A table whose full runs stopped arriving is not quiet: its consumer schedule may be gone, and the
    stalled-schedule sweep has to see it.
    """
    return _gate_applies(schema) and known_loaded(schema.sync_type_config) and not _heartbeat_due(schema, now)


def consumer_tick_stands_down(schema_id: Any, team_id: int, logger: Any) -> bool:
    """Whether this scheduled consumer tick stands down because its table owes no load.

    False on any error: going ahead runs the tick as it ran before the gate existed.
    """
    from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
    from products.warehouse_sources.backend.temporal.data_imports.cdc import metrics

    try:
        schema = ExternalDataSchema.objects.select_related("source").filter(id=schema_id, team_id=team_id).first()
        decision = consumer_tick_decision(schema, dt.datetime.now(dt.UTC)) if schema is not None else None
    except Exception as e:
        logger.warning("cdc_consumer_tick_gate_failed", schema_id=str(schema_id), error=str(e))
        return False
    if schema is None or decision is None:
        return False
    metrics.get_consumer_tick_gate_metric(team_id, str(schema.source_id), decision.value).add(1)
    logger.info("cdc_consumer_tick_gate", schema_id=str(schema_id), decision=decision.value)
    return decision == TickDecision.STOOD_DOWN


def consumer_tick_decision(schema: ExternalDataSchema, now: dt.datetime) -> TickDecision | None:
    """What a scheduled consumer tick of a streaming CDC table does. None means the gate does not apply.

    A tick that stands down after a job read records the generation it proved loaded on the schema.
    """
    from products.warehouse_sources.backend.models.external_data_schema import update_sync_type_config_keys
    from products.warehouse_sources.backend.temporal.data_imports.cdc.source_manager import read_completed_listing_proof

    if not _gate_applies(schema) or not data_driven_load_enabled(schema.source):
        return None

    config = schema.sync_type_config or {}

    def proven_generation() -> int | None:
        proof = read_completed_listing_proof(schema)
        return proof.generation_seen if proof is not None else None

    if owes_load(config, proven_generation):
        return TickDecision.OWED
    if _heartbeat_due(schema, now):
        return TickDecision.HEARTBEAT

    if not known_loaded(config):
        # Read before the lock. A write extraction counts after this read stays above what is recorded.
        generation = buffer_generation(config)

        def _record_loaded(fresh: dict[str, Any]) -> None:
            fresh[BUFFER_GENERATION_LOADED_KEY] = max(generation, _int_value(fresh, BUFFER_GENERATION_LOADED_KEY) or 0)

        update_sync_type_config_keys(schema.id, schema.team_id, mutate=_record_loaded)
    return TickDecision.STOOD_DOWN
