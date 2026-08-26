"""Per-scanner Temporal schedule lifecycle helpers."""

import datetime as dt
from typing import Any
from uuid import UUID

from django.conf import settings

import structlog
from pydantic import BaseModel
from temporalio import common
from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
)
from temporalio.common import SearchAttributePair, TypedSearchAttributes
from temporalio.service import RPCError, RPCStatusCode

from posthog.sync import database_sync_to_async
from posthog.temporal.common.client import async_connect
from posthog.temporal.common.schedule import (
    a_create_schedule,
    a_delete_schedule,
    a_pause_schedule,
    a_schedule_exists,
    a_trigger_schedule,
    a_unpause_schedule,
    a_update_schedule,
)
from posthog.temporal.common.search_attributes import (
    POSTHOG_SCHEDULE_FINGERPRINT_KEY,
    POSTHOG_SCHEDULE_TYPE_KEY,
    POSTHOG_TEAM_ID_KEY,
)

from products.replay_vision.backend.fingerprint import SCHEDULE_FINGERPRINT_LENGTH, config_fingerprint
from products.replay_vision.backend.models.replay_scanner import ReplayScanner
from products.replay_vision.backend.temporal.backfill_types import BackfillTickInputs
from products.replay_vision.backend.temporal.constants import (
    BACKFILL_SCANNER_WORKFLOW_NAME,
    BACKFILL_SCHEDULE_TYPE,
    BACKFILL_TICK_EXECUTION_TIMEOUT,
    BACKFILL_TICK_INTERVAL,
    SCANNER_SCHEDULE_INTERVAL,
    SCANNER_SCHEDULE_TYPE,
    SWEEP_SCANNER_WORKFLOW_NAME,
    SWEEP_WORKFLOW_EXECUTION_TIMEOUT,
    backfill_schedule_id,
    scanner_schedule_id,
)
from products.replay_vision.backend.temporal.sweep_types import SweepScannerInputs

logger = structlog.get_logger(__name__)

# Scanner row fields whose change should retrigger the schedule via fingerprint drift.
# `enabled` is *not* in this list: `_load_fingerprint` filters `enabled=True`, so a
# `True → False` transition is handled by the `None`-return-and-delete path, not by drift.
_FINGERPRINT_FIELDS = (
    "scanner_version",
    "sampling_rate",
    "sampling_mode",
    "model",
    "provider",
    "query",
    "scanner_config",
)


def compute_schedule_fingerprint(snapshot: dict[str, Any] | None) -> str:
    # `sort_keys=True` is recursive over dicts but not lists; assumes JSONField list ordering is stable.
    return config_fingerprint(snapshot, length=SCHEDULE_FINGERPRINT_LENGTH)


def compute_schedule_offset(entity_id: UUID, interval: dt.timedelta) -> dt.timedelta:
    """Stagger per-entity schedules across their interval so they don't all fire on the same boundary.

    UUID.int is stable across processes; modulo distributes fires uniformly across the window. Without
    this, sibling schedules tick together and each reads the same in-flight counts before any of them
    has persisted a row.
    """
    interval_s = max(1, int(interval.total_seconds()))
    return dt.timedelta(seconds=entity_id.int % interval_s)


def _build_schedule(scanner_id: UUID, team_id: int) -> Schedule:
    return Schedule(
        action=ScheduleActionStartWorkflow(
            SWEEP_SCANNER_WORKFLOW_NAME,
            SweepScannerInputs(scanner_id=scanner_id, team_id=team_id),
            id=f"{SWEEP_SCANNER_WORKFLOW_NAME}-{scanner_id}",
            task_queue=settings.REPLAY_VISION_TASK_QUEUE,
            execution_timeout=SWEEP_WORKFLOW_EXECUTION_TIMEOUT,
            retry_policy=common.RetryPolicy(maximum_attempts=1),
        ),
        spec=ScheduleSpec(
            intervals=[
                ScheduleIntervalSpec(
                    every=SCANNER_SCHEDULE_INTERVAL,
                    offset=compute_schedule_offset(scanner_id, SCANNER_SCHEDULE_INTERVAL),
                )
            ]
        ),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP, catchup_window=SCANNER_SCHEDULE_INTERVAL),
    )


def _load_fingerprint(scanner_id: UUID) -> str | None:
    """Return the fingerprint for an enabled scanner, or `None` if it is missing or disabled."""
    row = ReplayScanner.objects.filter(pk=scanner_id, enabled=True).values(*_FINGERPRINT_FIELDS).first()
    return compute_schedule_fingerprint(dict(row)) if row else None


def load_enabled_scanner_fingerprints() -> dict[UUID, tuple[int, str]]:
    """Bulk variant for the reconciler: returns `{scanner_id: (team_id, fingerprint)}`."""
    rows = ReplayScanner.objects.filter(enabled=True).values("id", "team_id", *_FINGERPRINT_FIELDS)
    return {
        row["id"]: (row["team_id"], compute_schedule_fingerprint({k: row[k] for k in _FINGERPRINT_FIELDS}))
        for row in rows
    }


async def upsert_interval_schedule(
    client: Client,
    *,
    schedule_id: str,
    workflow_name: str,
    workflow_id: str,
    inputs: BaseModel,
    interval: dt.timedelta,
    execution_timeout: dt.timedelta,
    search_attributes: TypedSearchAttributes | None = None,
    offset: dt.timedelta | None = None,
) -> None:
    """Create or update a singleton interval schedule with SKIP overlap; first creation triggers immediately."""
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            workflow_name,
            inputs,
            id=workflow_id,
            task_queue=settings.REPLAY_VISION_TASK_QUEUE,
            execution_timeout=execution_timeout,
            retry_policy=common.RetryPolicy(maximum_attempts=1),
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=interval, offset=offset)]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP, catchup_window=interval),
    )
    if await a_schedule_exists(client, schedule_id):
        await a_update_schedule(client, schedule_id, schedule, search_attributes=search_attributes)
        return
    try:
        await a_create_schedule(
            client, schedule_id, schedule, trigger_immediately=True, search_attributes=search_attributes
        )
    except RPCError as e:
        if e.status != RPCStatusCode.ALREADY_EXISTS:
            raise
        # Concurrent upsert beat us to create; treat as update.
        await a_update_schedule(client, schedule_id, schedule, search_attributes=search_attributes)


async def a_upsert_scanner_schedule(scanner_id: UUID, team_id: int) -> None:
    """Reflect current scanner state in Temporal: upsert when enabled, delete otherwise."""
    fingerprint = await database_sync_to_async(_load_fingerprint)(scanner_id)
    if fingerprint is None:
        # Row is missing or disabled — drop any stale schedule rather than leave it firing.
        logger.info("replay_vision.upsert_schedule.removing_stale", scanner_id=str(scanner_id))
        await a_delete_scanner_schedule(scanner_id)
        return

    client = await async_connect()
    schedule_id = scanner_schedule_id(scanner_id)
    schedule = _build_schedule(scanner_id, team_id)
    search_attributes = TypedSearchAttributes(
        search_attributes=[
            SearchAttributePair(key=POSTHOG_TEAM_ID_KEY, value=team_id),
            SearchAttributePair(key=POSTHOG_SCHEDULE_TYPE_KEY, value=SCANNER_SCHEDULE_TYPE),
            SearchAttributePair(key=POSTHOG_SCHEDULE_FINGERPRINT_KEY, value=fingerprint),
        ]
    )

    if await a_schedule_exists(client, schedule_id):
        await a_update_schedule(client, schedule_id, schedule, search_attributes=search_attributes)
        return
    try:
        await a_create_schedule(
            client, schedule_id, schedule, trigger_immediately=True, search_attributes=search_attributes
        )
    except RPCError as e:
        if e.status != RPCStatusCode.ALREADY_EXISTS:
            raise
        # Concurrent upsert beat us to create; treat as update.
        await a_update_schedule(client, schedule_id, schedule, search_attributes=search_attributes)


async def a_upsert_backfill_schedule(
    backfill_id: UUID, team_id: int, scanner_id: UUID, client: Client | None = None
) -> None:
    """Create (or repair) the per-backfill tick schedule; first creation triggers immediately."""
    client = client or await async_connect()
    await upsert_interval_schedule(
        client,
        schedule_id=backfill_schedule_id(backfill_id),
        workflow_name=BACKFILL_SCANNER_WORKFLOW_NAME,
        workflow_id=f"{BACKFILL_SCANNER_WORKFLOW_NAME}-{backfill_id}",
        inputs=BackfillTickInputs(backfill_id=backfill_id, team_id=team_id, scanner_id=scanner_id),
        interval=BACKFILL_TICK_INTERVAL,
        execution_timeout=BACKFILL_TICK_EXECUTION_TIMEOUT,
        # Without this every backfill in the fleet ticks on the same minute boundary.
        offset=compute_schedule_offset(backfill_id, BACKFILL_TICK_INTERVAL),
        search_attributes=TypedSearchAttributes(
            search_attributes=[
                SearchAttributePair(key=POSTHOG_TEAM_ID_KEY, value=team_id),
                SearchAttributePair(key=POSTHOG_SCHEDULE_TYPE_KEY, value=BACKFILL_SCHEDULE_TYPE),
            ]
        ),
    )


async def _a_delete_schedule_idempotent(schedule_id: str, log_event: str, client: Client | None = None) -> None:
    """Delete directly and swallow the NOT_FOUND race; other RPC failures propagate."""
    client = client or await async_connect()
    try:
        await a_delete_schedule(client, schedule_id)
    except RPCError as e:
        if e.status != RPCStatusCode.NOT_FOUND:
            raise
        logger.info(log_event, schedule_id=schedule_id)


async def a_delete_backfill_schedule(backfill_id: UUID, client: Client | None = None) -> None:
    await _a_delete_schedule_idempotent(
        backfill_schedule_id(backfill_id), "replay_vision.delete_backfill_schedule.already_gone", client
    )


async def a_pause_backfill_schedule(backfill_id: UUID, note: str, client: Client | None = None) -> None:
    """Idempotent — pausing a missing schedule is a no-op."""
    client = client or await async_connect()
    try:
        await a_pause_schedule(client, backfill_schedule_id(backfill_id), note=note)
    except RPCError as e:
        if e.status != RPCStatusCode.NOT_FOUND:
            raise


async def a_resume_backfill_schedule(backfill_id: UUID, team_id: int, scanner_id: UUID) -> None:
    """Unpause the tick schedule and fire a tick right away so a resume feels immediate.

    A lost schedule is recreated instead of failing the resume (creation triggers immediately).
    """
    client = await async_connect()
    schedule_id = backfill_schedule_id(backfill_id)
    try:
        await a_unpause_schedule(client, schedule_id, note="user resume")
    except RPCError as e:
        if e.status != RPCStatusCode.NOT_FOUND:
            raise
        await a_upsert_backfill_schedule(backfill_id, team_id, scanner_id, client)
        return
    await a_trigger_schedule(client, schedule_id)


async def a_delete_scanner_schedule(scanner_id: UUID) -> None:
    await _a_delete_schedule_idempotent(scanner_schedule_id(scanner_id), "replay_vision.delete_schedule.already_gone")
