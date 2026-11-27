"""Capture starts the loads of a source's streaming tables, and their own schedules slow down.

A streaming table's schedule asks on every tick whether its buffer holds unread changes. Capture
writes the buffer, so it already knows. With the flag on, each capture run triggers the schedule
of every table whose tick would do work, and that schedule itself runs only at the consumer
heartbeat interval. A triggered run is the schedule's own run: same workflow, same overlap policy,
same gate.

The table's `sync_frequency_interval` does not change. A table is triggered at most once per that
interval, so it loads as often as configured and no more.

A slowed schedule must never be left with nothing triggering it. Three things hold that:
- The schema records the interval its schedule has, and Temporal changes before the record does.
- Capture triggers a table for as long as that record is set, also when it should not be.
- A run restores its own schedule at its start when the table should no longer be slowed.
"""

from __future__ import annotations

import copy
import time
import datetime as dt
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from products.warehouse_sources.backend.temporal.data_imports.cdc import metrics
from products.warehouse_sources.backend.temporal.data_imports.cdc.dispatch import (
    CONSUMER_HEARTBEAT_INTERVAL,
    TickDecision,
    data_driven_load_enabled,
    tick_decision,
)

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
    from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

CDC_LOAD_TRIGGER_FLAG = "warehouse-cdc-load-trigger"

# On the schema's `sync_type_config`: when capture last triggered the table. A run that fails or
# is billing-limited leaves no other trace on the schema.
LOAD_TRIGGERED_AT_KEY = "cdc_load_triggered_at"

# Turning the flag on changes one schedule per streaming table. The cap spreads a large source's
# changes over several capture runs. Giving a table its own cadence back is never capped.
MAX_SCHEDULE_SLOWDOWNS_PER_RUN = 50

# Both steps run inside the capture activity, which must get back to the change stream also when
# Temporal is slow or down. The next capture run picks up a table left out.
RECONCILE_BUDGET_SECONDS = 60.0
TRIGGER_BUDGET_SECONDS = 120.0


def load_trigger_enabled(source: ExternalDataSource) -> bool:
    """Whether capture triggers this source's loads. Needs the tick gate, which keeps a triggered run cheap."""
    from products.warehouse_sources.backend.temporal.data_imports.schema_flags import is_source_flag_enabled

    return is_source_flag_enabled(source, CDC_LOAD_TRIGGER_FLAG) and data_driven_load_enabled(source)


def wanted_schedule_interval(schema: ExternalDataSchema, *, enabled: bool) -> dt.timedelta | None:
    """The interval this table's schedule should run at, or None for its sync frequency.

    Only a streaming table that syncs more often than the heartbeat is slowed down. A snapshot, a
    reset, a table that left CDC and a table at the heartbeat interval or slower keep their own cadence.
    """
    from products.warehouse_sources.backend.temporal.data_imports.cdc.source_manager import serves_buffered_lane

    interval = schema.sync_frequency_interval
    if (
        not enabled
        or not schema.is_cdc
        or not schema.should_sync
        or interval is None
        or interval >= CONSUMER_HEARTBEAT_INTERVAL
        or not serves_buffered_lane(schema)
    ):
        return None
    return CONSUMER_HEARTBEAT_INTERVAL


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
    if wanted == schema.schedule_interval_override:
        return False

    config = dict(schema.sync_type_config or {})
    if wanted is None:
        config.pop(SCHEDULE_INTERVAL_SECONDS_KEY, None)
    else:
        config[SCHEDULE_INTERVAL_SECONDS_KEY] = int(wanted.total_seconds())
    # The schedule is built from the row, so a copy carries the interval it should get.
    target = copy.copy(schema)
    target.sync_type_config = config

    # `keep_paused` leaves a paused schedule paused and `should_sync=True` leaves a running one
    # running, so this never changes whether the schedule fires. The row read here can be stale.
    data_warehouse_api.sync_external_data_job_workflow(target, create=False, should_sync=True, keep_paused=True)
    if wanted is None:
        update_sync_type_config_keys(schema.id, schema.team_id, removes=[SCHEDULE_INTERVAL_SECONDS_KEY])
    else:
        update_sync_type_config_keys(
            schema.id, schema.team_id, updates={SCHEDULE_INTERVAL_SECONDS_KEY: config[SCHEDULE_INTERVAL_SECONDS_KEY]}
        )
    schema.sync_type_config = config
    return True


def restore_own_schedule(schema_id: Any, team_id: int, logger: Any) -> None:
    """Give a table that should no longer be slowed its own cadence back, at the start of its run.

    Capture does the same on every run. This covers what capture cannot see or reach: a table that
    left CDC, and a reset or a flag turned off while capture is down. The run a reset or a new sync
    type starts restores the schedule its later runs depend on. Never raises.
    """
    from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema

    try:
        schema = ExternalDataSchema.objects.select_related("source").filter(id=schema_id, team_id=team_id).first()
        if schema is None or schema.schedule_interval_override is None:
            return
        if reconcile_schedule(schema, enabled=load_trigger_enabled(schema.source)):
            logger.info("cdc_load_trigger_schedule_restored", schema_id=str(schema_id))
    except Exception as e:
        logger.warning("cdc_load_trigger_schedule_restore_failed", schema_id=str(schema_id), error=str(e))


def _triggered_at(schema: ExternalDataSchema) -> dt.datetime | None:
    raw = (schema.sync_type_config or {}).get(LOAD_TRIGGERED_AT_KEY)
    try:
        stamped = dt.datetime.fromisoformat(raw) if isinstance(raw, str) else None
    except ValueError:
        return None
    return stamped if stamped is not None and stamped.tzinfo is not None else None


def _due(schema: ExternalDataSchema, now: dt.datetime, capture_interval: dt.timedelta) -> bool:
    """Whether the table's sync frequency has passed since capture last triggered it.

    The tolerance of half a capture interval keeps a table on its cadence when a capture run ends a
    little early. It still spaces out two triggers of one long capture run.
    """
    interval = schema.sync_frequency_interval
    triggered_at = _triggered_at(schema)
    return interval is None or triggered_at is None or now - triggered_at >= interval - capture_interval / 2


def tables_to_trigger(
    schemas: list[ExternalDataSchema], now: dt.datetime, capture_interval: dt.timedelta, *, enabled: bool
) -> list[ExternalDataSchema]:
    """The tables on a slowed schedule, or about to get one, whose scheduled tick would do work now."""
    return [
        schema
        for schema in schemas
        if schema.should_sync
        and (
            schema.schedule_interval_override is not None
            or wanted_schedule_interval(schema, enabled=enabled) is not None
        )
        # Before the decision, which can read the table's jobs.
        and _due(schema, now, capture_interval)
        and tick_decision(schema, now) != TickDecision.STOOD_DOWN
    ]


def _reconcile_all(
    schemas: list[ExternalDataSchema], logger: Any, *, enabled: bool, heartbeat: Callable[[], None] | None
) -> None:
    """Restores first and without a cap: a table waiting for its own cadence back has no other tick."""
    pending = [s for s in schemas if wanted_schedule_interval(s, enabled=enabled) != s.schedule_interval_override]
    restores = [s for s in pending if s.schedule_interval_override is not None]
    # A failed slowdown counts too, so a Temporal outage costs a bounded number of calls per run.
    slowdowns = [s for s in pending if s.schedule_interval_override is None][:MAX_SCHEDULE_SLOWDOWNS_PER_RUN]
    started = time.monotonic()
    for schema in [*restores, *slowdowns]:
        if time.monotonic() - started >= RECONCILE_BUDGET_SECONDS:
            logger.warning("cdc_load_trigger_reconcile_budget_spent", pending=len(pending))
            break
        if heartbeat is not None:
            heartbeat()
        try:
            reconcile_schedule(schema, enabled=enabled)
        except Exception as e:
            logger.warning("cdc_load_trigger_reconcile_failed", schema_id=str(schema.id), error=str(e))


def trigger_loads(
    source: ExternalDataSource, logger: Any, *, enabled: bool, heartbeat: Callable[[], None] | None = None
) -> None:
    """Reconcile the schedules of a source's tables, then trigger the ones with work.

    A trigger starts a run even on a paused schedule, so a paused one is skipped. A trigger that
    fails, lands while a run is open, or does not fit the time budget leaves the table owing its
    load, and the next capture run triggers it again.
    """
    from django.db.models import Q

    import temporalio.service

    from posthog.temporal.common.client import sync_connect
    from posthog.temporal.common.schedule import describe_schedule, trigger_schedule

    from products.data_warehouse.backend.facade import api as data_warehouse_api
    from products.warehouse_sources.backend.models.external_data_schema import (
        SCHEDULE_INTERVAL_SECONDS_KEY,
        ExternalDataSchema,
        update_sync_type_config_keys,
    )

    schemas = list(
        ExternalDataSchema.objects.select_related("source")
        .filter(source=source, team_id=source.team_id)
        .filter(
            Q(sync_type=ExternalDataSchema.SyncType.CDC) | Q(sync_type_config__has_key=SCHEDULE_INTERVAL_SECONDS_KEY)
        )
        .exclude(deleted=True)
    )
    _reconcile_all(schemas, logger, enabled=enabled, heartbeat=heartbeat)

    now = dt.datetime.now(dt.UTC)
    capture_interval = data_warehouse_api.cdc_min_interval(
        schema.sync_frequency_interval for schema in schemas if schema.should_sync and schema.is_cdc
    )
    to_trigger = tables_to_trigger(schemas, now, capture_interval, enabled=enabled)
    if not to_trigger:
        return

    temporal = sync_connect()
    started = time.monotonic()
    for schema in to_trigger:
        if time.monotonic() - started >= TRIGGER_BUDGET_SECONDS:
            logger.warning("cdc_load_trigger_budget_spent", tables=len(to_trigger))
            break
        if heartbeat is not None:
            heartbeat()
        try:
            if describe_schedule(temporal, str(schema.id)).schedule.state.paused:
                outcome = "paused"
            else:
                trigger_schedule(temporal, schedule_id=str(schema.id))
                outcome = "triggered"
                update_sync_type_config_keys(
                    schema.id, schema.team_id, updates={LOAD_TRIGGERED_AT_KEY: now.isoformat()}
                )
        except temporalio.service.RPCError as e:
            outcome = "missing" if e.status == temporalio.service.RPCStatusCode.NOT_FOUND else "failed"
            logger.warning("cdc_load_trigger_failed", schema_id=str(schema.id), error=str(e))
        except Exception as e:
            outcome = "failed"
            logger.warning("cdc_load_trigger_failed", schema_id=str(schema.id), error=str(e))
        metrics.get_load_trigger_metric(source.team_id, str(source.id), outcome).add(1)
