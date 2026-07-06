from uuid import UUID

import structlog
from temporalio import activity

from posthog.sync import database_sync_to_async
from posthog.temporal.common.client import async_connect
from posthog.temporal.common.search_attributes import POSTHOG_SCHEDULE_FINGERPRINT_KEY

from products.replay_vision.backend.temporal.constants import (
    SCANNER_SCHEDULE_ID_PREFIX,
    SCANNER_SCHEDULE_TYPE,
    SWEEP_SCANNER_WORKFLOW_NAME,
)
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.reconciler_types import (
    DeleteScannerScheduleActivityInputs,
    EnabledScannerEntry,
    ScannerScheduleEntry,
    UpsertScannerScheduleActivityInputs,
)
from products.replay_vision.backend.temporal.schedule import (
    a_delete_scanner_schedule,
    a_upsert_scanner_schedule,
    load_enabled_scanner_fingerprints,
)

logger = structlog.get_logger(__name__)


@activity.defn
@track_activity()
async def list_enabled_scanners_activity() -> list[EnabledScannerEntry]:
    """Every enabled ReplayScanner with its current fingerprint."""
    rows = await database_sync_to_async(load_enabled_scanner_fingerprints)()
    return [EnabledScannerEntry(scanner_id=sid, team_id=team_id, fingerprint=fp) for sid, (team_id, fp) in rows.items()]


def _schedule_fingerprint(listing: object) -> str | None:
    # Distinguish missing attribute (Temporal shape change) from unstamped (legacy schedule).
    try:
        attrs = listing.typed_search_attributes  # type: ignore[attr-defined]
    except AttributeError:
        logger.warning(
            "replay_vision.reconciler.listing_missing_search_attributes",
            schedule_id=getattr(listing, "id", "<unknown>"),
        )
        return None
    for pair in attrs:
        if pair.key.name == POSTHOG_SCHEDULE_FINGERPRINT_KEY.name:
            return pair.value
    return None


@activity.defn
@track_activity()
async def list_scanner_schedules_activity() -> list[ScannerScheduleEntry]:
    """Existing per-scanner schedules in Temporal; fingerprint is None for legacy schedules."""
    client = await async_connect()
    prefix = f"{SCANNER_SCHEDULE_ID_PREFIX}-"
    entries: list[ScannerScheduleEntry] = []
    async for listing in await client.list_schedules(query=f'PostHogScheduleType = "{SCANNER_SCHEDULE_TYPE}"'):
        if not listing.id.startswith(prefix):
            continue
        if getattr(getattr(listing.schedule, "action", None), "workflow", None) != SWEEP_SCANNER_WORKFLOW_NAME:
            continue
        try:
            scanner_id = UUID(listing.id[len(prefix) :])
        except ValueError:
            logger.warning("replay_vision.reconciler.unparseable_schedule_id", schedule_id=listing.id)
            continue
        entries.append(ScannerScheduleEntry(scanner_id=scanner_id, fingerprint=_schedule_fingerprint(listing)))
    return entries


@activity.defn
@track_activity()
async def upsert_scanner_schedule_activity(inputs: UpsertScannerScheduleActivityInputs) -> None:
    await a_upsert_scanner_schedule(inputs.scanner_id, inputs.team_id)


@activity.defn
@track_activity()
async def delete_scanner_schedule_activity(inputs: DeleteScannerScheduleActivityInputs) -> None:
    await a_delete_scanner_schedule(inputs.scanner_id)
