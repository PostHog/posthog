"""Capture starts the loads of a source's streaming tables, and their own schedules slow down.

A streaming table's schedule asks on every tick whether its buffer holds unread changes. Capture
writes the buffer, so it already knows. With the flag on, each capture run triggers the schedule
of every table whose tick would do work, and that schedule itself runs only at the consumer
heartbeat interval. A triggered run is the schedule's own run: same workflow, same overlap policy,
same gate.

The table's `sync_frequency_interval` does not change. A table is triggered at most once per that
interval, so it loads as often as configured and no more.
"""

from __future__ import annotations

import copy
import datetime as dt
from typing import TYPE_CHECKING, Any

from products.warehouse_sources.backend.temporal.data_imports.cdc import metrics
from products.warehouse_sources.backend.temporal.data_imports.cdc.dispatch import (
    CONSUMER_HEARTBEAT_INTERVAL,
    TickDecision,
    _int_value,
    data_driven_load_enabled,
    tick_decision,
)

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
    from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

CDC_LOAD_TRIGGER_FLAG = "warehouse-cdc-load-trigger"

# Turning the flag on changes one schedule per streaming table. The cap spreads a large source's
# updates over several capture runs, so no run spends its time on schedule calls.
MAX_SCHEDULE_UPDATES_PER_RUN = 50


def load_trigger_enabled(source: ExternalDataSource) -> bool:
    """Whether capture triggers this source's loads. Needs the tick gate, which keeps a triggered run cheap."""
    from products.warehouse_sources.backend.temporal.data_imports.schema_flags import is_source_flag_enabled

    return is_source_flag_enabled(source, CDC_LOAD_TRIGGER_FLAG) and data_driven_load_enabled(source)


def wanted_schedule_interval(schema: ExternalDataSchema, *, enabled: bool) -> dt.timedelta | None:
    """The interval this table's schedule should run at, or None for its sync frequency.

    Only a streaming table that syncs more often than the heartbeat is slowed down. A snapshot, a
    reset and a table at the heartbeat interval or slower keep their own cadence.
    """
    from products.warehouse_sources.backend.temporal.data_imports.cdc.source_manager import serves_buffered_lane

    interval = schema.sync_frequency_interval
    if (
        not enabled
        or not schema.should_sync
        or interval is None
        or interval >= CONSUMER_HEARTBEAT_INTERVAL
        or not serves_buffered_lane(schema)
    ):
        return None
    return CONSUMER_HEARTBEAT_INTERVAL


def applied_schedule_interval(schema: ExternalDataSchema) -> dt.timedelta | None:
    """The slower interval recorded on the schema as applied to its schedule, or None for its sync frequency."""
    from products.warehouse_sources.backend.models.external_data_schema import SCHEDULE_INTERVAL_SECONDS_KEY

    seconds = _int_value(schema.sync_type_config, SCHEDULE_INTERVAL_SECONDS_KEY)
    return dt.timedelta(seconds=seconds) if seconds else None


def reconcile_schedule(schema: ExternalDataSchema, *, enabled: bool) -> bool:
    """Bring the table's schedule to the interval it should run at. Returns whether it changed.

    Temporal is updated before the interval is recorded on the schema. A call that fails between the
    two leaves the record behind the schedule, so the next call repeats the update.
    """
    from products.data_warehouse.backend.facade import api as data_warehouse_api
    from products.warehouse_sources.backend.models.external_data_schema import (
        SCHEDULE_INTERVAL_SECONDS_KEY,
        update_sync_type_config_keys,
    )

    wanted = wanted_schedule_interval(schema, enabled=enabled)
    if wanted == applied_schedule_interval(schema):
        return False

    config = dict(schema.sync_type_config or {})
    if wanted is None:
        config.pop(SCHEDULE_INTERVAL_SECONDS_KEY, None)
    else:
        config[SCHEDULE_INTERVAL_SECONDS_KEY] = int(wanted.total_seconds())
    # The schedule is built from the row, so a copy carries the interval it should get.
    target = copy.copy(schema)
    target.sync_type_config = config

    data_warehouse_api.sync_external_data_job_workflow(
        target, create=False, should_sync=schema.should_sync, keep_paused=True
    )
    schema.sync_type_config = config
    if wanted is None:
        update_sync_type_config_keys(schema.id, schema.team_id, removes=[SCHEDULE_INTERVAL_SECONDS_KEY])
    else:
        update_sync_type_config_keys(
            schema.id, schema.team_id, updates={SCHEDULE_INTERVAL_SECONDS_KEY: config[SCHEDULE_INTERVAL_SECONDS_KEY]}
        )
    return True


def restore_own_schedule(schema: ExternalDataSchema, logger: Any) -> None:
    """Give a table that should no longer be slowed its own cadence back, at the start of its run.

    Capture does the same on every run. This covers a table that leaves streaming, or a flag turned
    off, while capture is down: the run a reset starts restores the schedule its retries depend on.
    """
    if applied_schedule_interval(schema) is None:
        return
    try:
        if reconcile_schedule(schema, enabled=load_trigger_enabled(schema.source)):
            logger.info("cdc_load_trigger_schedule_restored", schema_id=str(schema.id))
    except Exception as e:
        logger.warning("cdc_load_trigger_schedule_restore_failed", schema_id=str(schema.id), error=str(e))


def _due(schema: ExternalDataSchema, now: dt.datetime, capture_interval: dt.timedelta) -> bool:
    """Whether the table's sync frequency has passed since its last run, completed or failed.

    Capture runs at the fastest table's frequency, so a table at that frequency is always due. The
    half-interval tolerance keeps a slower table on its cadence when a capture run ends a little early.
    """
    interval = schema.sync_frequency_interval
    if interval is None or interval <= capture_interval:
        return True
    attempts = [at for at in (schema.last_full_run, schema.failure_streak_last_failed_at) if at is not None]
    return not attempts or now - max(attempts) >= interval - capture_interval / 2


def tables_to_trigger(
    schemas: list[ExternalDataSchema], now: dt.datetime, capture_interval: dt.timedelta
) -> list[ExternalDataSchema]:
    """The slowed-down tables whose scheduled tick would do work now."""
    return [
        schema
        for schema in schemas
        if wanted_schedule_interval(schema, enabled=True) is not None
        and tick_decision(schema, now) != TickDecision.STOOD_DOWN
        and _due(schema, now, capture_interval)
    ]


def trigger_loads(source: ExternalDataSource, logger: Any, *, enabled: bool) -> None:
    """Reconcile the schedules of a source's CDC tables, then trigger the ones with work.

    A trigger starts a run even on a paused schedule, so a paused one is skipped. A trigger that
    fails, or lands while a run is open, leaves the table owing its load, and the next capture run
    triggers it again.
    """
    from products.data_warehouse.backend.facade import api as data_warehouse_api
    from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema

    schemas = list(
        ExternalDataSchema.objects.select_related("source")
        .filter(source=source, team_id=source.team_id, sync_type=ExternalDataSchema.SyncType.CDC)
        .exclude(deleted=True)
    )
    updates = 0
    for schema in schemas:
        if updates >= MAX_SCHEDULE_UPDATES_PER_RUN:
            break
        try:
            updates += reconcile_schedule(schema, enabled=enabled)
        except Exception as e:
            logger.warning("cdc_load_trigger_reconcile_failed", schema_id=str(schema.id), error=str(e))
    if not enabled:
        return

    capture_interval = data_warehouse_api.cdc_min_interval(
        schema.sync_frequency_interval for schema in schemas if schema.should_sync
    )
    for schema in tables_to_trigger(schemas, dt.datetime.now(dt.UTC), capture_interval):
        try:
            if data_warehouse_api.is_external_data_schedule_paused(str(schema.id)):
                outcome = "paused"
            else:
                data_warehouse_api.trigger_external_data_workflow(schema)
                outcome = "triggered"
        except Exception as e:
            outcome = "failed"
            logger.warning("cdc_load_trigger_failed", schema_id=str(schema.id), error=str(e))
        metrics.get_load_trigger_metric(source.team_id, str(source.id), outcome).add(1)
