"""Activities for the per-backfill tick workflow: gatekeeping, candidate walk, cursor advance, schedule ops."""

import asyncio
from uuid import UUID

from django.db.models import F
from django.utils import timezone

import structlog
from pydantic import ValidationError
from temporalio import activity
from temporalio.client import Client
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
        ReplayScannerBackfill.objects.for_team(team_id)
        .select_related("scanner", "team__organization")
        .filter(pk=backfill_id)
        .first()
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
        # Re-pause rather than skip: a recreated or racing schedule would otherwise fire every minute forever.
        record_backfill_tick_outcome("skipped_paused")
        return PrepareBackfillTickOutput(action=BackfillTickAction.PAUSE)
    if not backfill.team.organization.is_ai_data_processing_approved:
        # Children would decline at create while the cursor walks past their sessions; hold instead.
        record_backfill_tick_outcome("skipped_no_consent")
        return PrepareBackfillTickOutput(action=BackfillTickAction.SKIP)
    if not backfill.scanner.enabled:
        # Disabling a scanner holds its backfill without a status change; re-enabling resumes on the next tick.
        record_backfill_tick_outcome("skipped_scanner_disabled")
        return PrepareBackfillTickOutput(action=BackfillTickAction.SKIP)

    quota = compute_quota_snapshot(backfill.team.organization_id)
    if quota.would_exceed(backfill.credits_per_observation):
        # Filtered so a concurrent cancel wins over the pause.
        ReplayScannerBackfill.objects.for_team(inputs.team_id).filter(
            pk=inputs.backfill_id, status=BackfillStatus.RUNNING
        ).update(status=BackfillStatus.PAUSED_QUOTA)
        record_backfill_tick_outcome("paused_quota")
        return PrepareBackfillTickOutput(action=BackfillTickAction.PAUSE)

    in_flight = count_in_flight(inputs.team_id, backfill.scanner_id, backfill_id=backfill.id)
    budget = backfill_dispatch_budget(in_flight["scanner"], in_flight["team"], in_flight["backfill"])
    if quota.remaining is not None:
        # Never dispatch more children than the quota can pay for: a child declined at create still
        # advances the cursor past its session. Concurrent spenders can still shrink headroom between
        # this check and creation; that residual loss is bounded by one batch and accepted.
        budget = min(budget, quota.remaining // backfill.credits_per_observation)
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


def _active_backfills_by_id() -> dict[UUID, tuple[int, UUID, str]]:
    """`{backfill_id: (team_id, scanner_id, status)}` for every non-terminal backfill."""
    rows = ReplayScannerBackfill.objects.unscoped().filter(status__in=ACTIVE_BACKFILL_STATUSES)
    return {
        row_id: (team_id, scanner_id, row_status)
        for row_id, team_id, scanner_id, row_status in rows.values_list("id", "team_id", "scanner_id", "status")
    }


async def _recreate_schedule(
    backfill_id: UUID, team_id: int, scanner_id: UUID, row_status: str, client: Client
) -> None:
    await a_upsert_backfill_schedule(backfill_id, team_id, scanner_id, client)
    # A quota-paused backfill's schedule comes back paused; only an explicit user resume unpauses it.
    if row_status == BackfillStatus.PAUSED_QUOTA:
        await a_pause_backfill_schedule(backfill_id, note="monthly quota exhausted", client=client)


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
    for backfill_id, (team_id, scanner_id, row_status) in active.items():
        if backfill_id not in seen:
            logger.info("replay_vision.backfill_reaper.recreating_missing", backfill_id=str(backfill_id))
            fixes.append(_recreate_schedule(backfill_id, team_id, scanner_id, row_status, client))
    if fixes:
        await asyncio.gather(*fixes)
