"""Activities for the per-backfill tick workflow: gatekeeping, candidate walk, cursor advance, schedule ops."""

import asyncio
from uuid import UUID

from django.db.models import F
from django.utils import timezone

import structlog
from pydantic import ValidationError
from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.schema import RecordingsQuery

from posthog.sync import database_sync_to_async
from posthog.temporal.common.client import async_connect

from products.replay_vision.backend.models.replay_scanner_backfill import (
    ACTIVE_BACKFILL_STATUSES,
    BackfillStatus,
    ReplayScannerBackfill,
)
from products.replay_vision.backend.queries.scanner_candidate_query import BackfillCandidateQuery
from products.replay_vision.backend.quota import compute_quota_snapshot
from products.replay_vision.backend.temporal.activities.count_in_flight_applies import count_in_flight
from products.replay_vision.backend.temporal.backfill_types import (
    AdvanceBackfillCursorInputs,
    AdvanceBackfillCursorOutput,
    BackfillScheduleOpInputs,
    BackfillTickAction,
    BackfillTickInputs,
    FindBackfillCandidatesInputs,
    FindBackfillCandidatesOutput,
    PrepareBackfillTickOutput,
)
from products.replay_vision.backend.temporal.constants import (
    BACKFILL_SCHEDULE_ID_PREFIX,
    BACKFILL_SCHEDULE_TYPE,
    backfill_dispatch_budget,
)
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.metrics import record_backfill_tick_outcome
from products.replay_vision.backend.temporal.schedule import (
    a_delete_backfill_schedule,
    a_pause_backfill_schedule,
    a_upsert_backfill_schedule,
)
from products.replay_vision.backend.temporal.snapshots import BackfillScannerSnapshot
from products.replay_vision.backend.temporal.sweep_types import CandidateSessionPayload

logger = structlog.get_logger(__name__)


def _load_backfill(backfill_id: UUID, team_id: int) -> ReplayScannerBackfill | None:
    return (
        ReplayScannerBackfill.objects.for_team(team_id).select_related("scanner", "team").filter(pk=backfill_id).first()
    )


@activity.defn
@track_activity()
def prepare_backfill_tick_activity(inputs: BackfillTickInputs) -> PrepareBackfillTickOutput:
    """Decide what this tick does: dispatch a bounded batch, skip, pause on quota, or finish."""
    backfill = _load_backfill(inputs.backfill_id, inputs.team_id)
    if backfill is None or backfill.status in (BackfillStatus.COMPLETED, BackfillStatus.CANCELLED):
        record_backfill_tick_outcome("finished")
        return PrepareBackfillTickOutput(action=BackfillTickAction.FINISHED)
    if backfill.status == BackfillStatus.PAUSED_QUOTA:
        # A fire raced the pause; keep the schedule (paused) so an explicit resume can restart it.
        record_backfill_tick_outcome("skipped_paused")
        return PrepareBackfillTickOutput(action=BackfillTickAction.SKIP)
    if not backfill.scanner.enabled:
        # Disabling a scanner holds its backfill without a status change; re-enabling resumes on the next tick.
        record_backfill_tick_outcome("skipped_scanner_disabled")
        return PrepareBackfillTickOutput(action=BackfillTickAction.SKIP)

    if compute_quota_snapshot(backfill.team.organization_id).would_exceed(backfill.credits_per_observation):
        # Filtered so a concurrent cancel wins over the pause.
        ReplayScannerBackfill.objects.for_team(inputs.team_id).filter(
            pk=inputs.backfill_id, status=BackfillStatus.RUNNING
        ).update(status=BackfillStatus.PAUSED_QUOTA)
        record_backfill_tick_outcome("paused_quota")
        return PrepareBackfillTickOutput(action=BackfillTickAction.PAUSE)

    in_flight = count_in_flight(inputs.team_id, backfill.scanner_id, backfill_id=backfill.id)
    budget = backfill_dispatch_budget(in_flight["scanner"], in_flight["team"], in_flight["backfill"])
    if budget <= 0:
        record_backfill_tick_outcome("throttled")
        return PrepareBackfillTickOutput(action=BackfillTickAction.SKIP)
    record_backfill_tick_outcome("dispatch")
    return PrepareBackfillTickOutput(action=BackfillTickAction.DISPATCH, dispatch_budget=budget)


@activity.defn
@track_activity()
def find_backfill_candidates_activity(inputs: FindBackfillCandidatesInputs) -> FindBackfillCandidatesOutput:
    backfill = (
        ReplayScannerBackfill.objects.for_team(inputs.team_id)
        .select_related("team")
        .filter(pk=inputs.backfill_id)
        .first()
    )
    if backfill is None:
        return FindBackfillCandidatesOutput(candidates=[], saturated=False)

    snapshot = BackfillScannerSnapshot.load_for_backfill(backfill.id, backfill.scanner_snapshot)
    try:
        query = RecordingsQuery.model_validate({**snapshot.query, "kind": "RecordingsQuery"})
    except ValidationError as exc:
        raise ApplicationError(
            f"ReplayScannerBackfill {inputs.backfill_id} has malformed frozen query: {exc}", non_retryable=True
        ) from exc

    candidates = BackfillCandidateQuery(
        team=backfill.team,
        query=query,
        window_start=backfill.window_start,
        window_end=backfill.window_end,
        sampling_rate=snapshot.sampling_rate,
        # Same salt as the live sweep, so a sampled scanner backfills the same deterministic bucket it scans live.
        sampling_salt=str(backfill.scanner_id),
        sampling_mode=snapshot.sampling_mode,
        cursor_end_time=backfill.cursor_end_time,
        cursor_session_id=backfill.cursor_session_id or None,
        candidate_limit=inputs.candidate_limit,
    ).run()

    return FindBackfillCandidatesOutput(
        candidates=[CandidateSessionPayload(session_id=c.session_id, session_end=c.session_end) for c in candidates],
        saturated=len(candidates) == inputs.candidate_limit,
    )


@activity.defn
@track_activity()
def advance_backfill_cursor_activity(inputs: AdvanceBackfillCursorInputs) -> AdvanceBackfillCursorOutput:
    """Advance the descending cursor and dispatch count; a short batch completes the backfill.

    Filtered to RUNNING rows so a concurrent cancel or pause wins over the advance.
    """
    updates: dict[str, object] = {"dispatched_count": F("dispatched_count") + inputs.dispatched_delta}
    if inputs.new_cursor_end_time is not None:
        updates["cursor_end_time"] = inputs.new_cursor_end_time
        updates["cursor_session_id"] = inputs.new_cursor_session_id
    if inputs.exhausted:
        updates["status"] = BackfillStatus.COMPLETED
        updates["finished_at"] = timezone.now()
    updated = (
        ReplayScannerBackfill.objects.for_team(inputs.team_id)
        .filter(pk=inputs.backfill_id, status=BackfillStatus.RUNNING)
        .update(**updates)
    )
    finished = inputs.exhausted and updated > 0
    if finished:
        record_backfill_tick_outcome("completed")
    return AdvanceBackfillCursorOutput(finished=finished)


@activity.defn
@track_activity()
async def pause_backfill_schedule_activity(inputs: BackfillScheduleOpInputs) -> None:
    await a_pause_backfill_schedule(inputs.backfill_id, note="monthly quota exhausted")


@activity.defn
@track_activity()
async def delete_backfill_schedule_activity(inputs: BackfillScheduleOpInputs) -> None:
    await a_delete_backfill_schedule(inputs.backfill_id)


def _active_backfills_by_id() -> dict[UUID, tuple[int, UUID]]:
    """`{backfill_id: (team_id, scanner_id)}` for every non-terminal backfill."""
    rows = ReplayScannerBackfill.objects.unscoped().filter(status__in=ACTIVE_BACKFILL_STATUSES)
    return {
        row_id: (team_id, scanner_id) for row_id, team_id, scanner_id in rows.values_list("id", "team_id", "scanner_id")
    }


@activity.defn
@track_activity()
async def reap_backfill_schedules_activity() -> None:
    """Converge per-backfill schedules with the table: delete schedules whose row is terminal or gone
    (crash between terminal-mark and schedule-delete), recreate schedules a running row lost."""
    client = await async_connect()
    active = await database_sync_to_async(_active_backfills_by_id)()
    prefix = f"{BACKFILL_SCHEDULE_ID_PREFIX}-"
    seen: set[UUID] = set()
    fixes = []
    async for listing in await client.list_schedules(query=f'PostHogScheduleType = "{BACKFILL_SCHEDULE_TYPE}"'):
        if not listing.id.startswith(prefix):
            continue
        try:
            backfill_id = UUID(listing.id[len(prefix) :])
        except ValueError:
            logger.warning("replay_vision.backfill_reaper.unparseable_schedule_id", schedule_id=listing.id)
            continue
        seen.add(backfill_id)
        if backfill_id not in active:
            logger.info("replay_vision.backfill_reaper.deleting_stale", backfill_id=str(backfill_id))
            fixes.append(a_delete_backfill_schedule(backfill_id, client))
    for backfill_id, (team_id, scanner_id) in active.items():
        if backfill_id not in seen:
            logger.info("replay_vision.backfill_reaper.recreating_missing", backfill_id=str(backfill_id))
            fixes.append(a_upsert_backfill_schedule(backfill_id, team_id, scanner_id, client))
    if fixes:
        await asyncio.gather(*fixes)
