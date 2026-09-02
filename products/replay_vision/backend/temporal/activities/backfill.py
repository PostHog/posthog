"""Activities for the per-backfill tick workflow: gatekeeping, candidate walk, cursor advance, schedule ops."""

import time
import asyncio
from uuid import UUID

from django.db.models import F
from django.utils import timezone

import structlog
from pydantic import ValidationError
from rest_framework.exceptions import (
    PermissionDenied,
    ValidationError as DRFValidationError,
)
from temporalio import activity
from temporalio.client import Client
from temporalio.exceptions import ApplicationError

from posthog.schema import RecordingsQuery

from posthog.sync import database_sync_to_async
from posthog.temporal.common.client import async_connect
from posthog.temporal.session_replay.rasterize_recording.activities.stuck_counter import read_stuck_session_ids

from products.replay_vision.backend.enqueue_claims import claim_enqueue_slot_prefix
from products.replay_vision.backend.models.replay_observation import ObservationStatus, ReplayObservation
from products.replay_vision.backend.models.replay_scanner import apply_experiment_targeting
from products.replay_vision.backend.models.replay_scanner_backfill import (
    ACTIVE_BACKFILL_STATUSES,
    BackfillStatus,
    ReplayScannerBackfill,
)
from products.replay_vision.backend.queries import excluded_sessions
from products.replay_vision.backend.queries.scanner_candidate_query import (
    BACKFILL_CANDIDATE_QUERY_TYPE,
    BACKFILL_EXCLUDED_SESSIONS_QUERY_TYPE,
    WindowedCandidateQuery,
)
from products.replay_vision.backend.quota import compute_scanner_budget, quota_state
from products.replay_vision.backend.temporal.activities.count_in_flight_applies import (
    count_in_flight,
    count_in_flight_rows,
)
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
    FIND_BACKFILL_CANDIDATES_TIMEOUT,
    backfill_dispatch_budget,
    build_apply_scanner_workflow_id,
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

    quota = quota_state(backfill.team.organization_id)
    if quota.would_exceed(backfill.credits_per_observation):
        # Filtered so a concurrent cancel wins over the pause.
        ReplayScannerBackfill.objects.for_team(inputs.team_id).filter(
            pk=inputs.backfill_id, status=BackfillStatus.RUNNING
        ).update(status=BackfillStatus.PAUSED_QUOTA)
        record_backfill_tick_outcome("paused_quota")
        return PrepareBackfillTickOutput(action=BackfillTickAction.PAUSE)

    scanner_budget = compute_scanner_budget(backfill.scanner) if backfill.scanner.credit_limit is not None else None
    if scanner_budget is not None and scanner_budget.would_exceed(backfill.credits_per_observation):
        # Children would decline at create while the cursor walks past their sessions; the hold lets
        # the backfill resume when the period resets or the limit rises.
        record_backfill_tick_outcome("skipped_scanner_limit")
        return PrepareBackfillTickOutput(action=BackfillTickAction.SKIP)

    in_flight = count_in_flight(inputs.team_id, backfill.scanner_id, backfill_id=backfill.id)
    budget = backfill_dispatch_budget(in_flight["scanner"], in_flight["team"], in_flight["backfill"])
    # Never dispatch more children than the quota can pay for: a child declined at create still advances
    # the cursor past its session. Concurrent spenders can still shrink headroom between this check and
    # creation; that residual loss is bounded by one batch and accepted.
    affordable = quota.affordable_count(backfill.credits_per_observation)
    if affordable is not None:
        budget = min(budget, affordable)
    if scanner_budget is not None:
        # The scanner's own cap bounds the batch the same way the org quota does.
        scanner_affordable = scanner_budget.affordable_count(backfill.credits_per_observation)
        if scanner_affordable is not None:
            budget = min(budget, scanner_affordable)
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
        .select_related("team", "created_by")
        .filter(pk=inputs.backfill_id)
        .first()
    )
    if backfill is None:
        return FindBackfillCandidatesOutput(candidates=[], more_work_below_cursor=False)

    rows = count_in_flight_rows(inputs.team_id, backfill.scanner_id, backfill.id)
    capacity = count_in_flight(inputs.team_id, backfill.scanner_id, backfill.id, rows=rows)
    if backfill_dispatch_budget(capacity["scanner"], capacity["team"], capacity["backfill"]) <= 0:
        # Headroom vanished since the prepare gate; skip the enumeration rather than run the tick's
        # most expensive query only to have every candidate refused by the claim below. Checked
        # against the same caps the claim enforces, sub-cap included, so it can actually fire.
        record_backfill_tick_outcome("throttled")
        return FindBackfillCandidatesOutput(candidates=[], more_work_below_cursor=True)

    snapshot = BackfillScannerSnapshot.load_for_backfill(backfill.id, backfill.scanner_snapshot)
    try:
        query = RecordingsQuery.model_validate({**snapshot.query, "kind": "RecordingsQuery"})
    except ValidationError as exc:
        raise ApplicationError(
            f"ReplayScannerBackfill {inputs.backfill_id} has malformed frozen query: {exc}", non_retryable=True
        ) from exc
    query = apply_experiment_targeting(query, snapshot.experiment_targeting)

    candidate_query = WindowedCandidateQuery(
        team=backfill.team,
        query=query,
        # The exposure filter's access check runs as whoever launched the backfill.
        user=backfill.created_by,
        window_start=backfill.window_start,
        window_end=backfill.window_end,
        query_type=BACKFILL_CANDIDATE_QUERY_TYPE,
        sampling_rate=snapshot.sampling_rate,
        # Same salt as the live sweep, so a sampled scanner backfills the same deterministic bucket it scans live.
        sampling_salt=str(backfill.scanner_id),
        scanner_id=str(backfill.scanner_id),
        sampling_mode=snapshot.sampling_mode,
        cursor_end_time=backfill.cursor_end_time,
        cursor_session_id=backfill.cursor_session_id or None,
        candidate_limit=inputs.candidate_limit,
        skip_negative_blocklists=True,
    )
    started_at = time.monotonic()
    try:
        candidates = candidate_query.run()
    except (PermissionDenied, DRFValidationError) as exc:
        # The exposure filter can't run anymore: the launcher was deleted or lost experiment
        # access, or the experiment can't answer for its exposed population (deleted, back to
        # draft, renamed variant). Cancelling on a condition that might heal is deliberate: a
        # stuck backfill silently counts its unspent credits into the spend projection, while a
        # cancelled one is visible and can be relaunched.
        ReplayScannerBackfill.objects.for_team(inputs.team_id).filter(
            pk=backfill.pk, status__in=ACTIVE_BACKFILL_STATUSES
        ).update(status=BackfillStatus.CANCELLED, finished_at=timezone.now())
        raise ApplicationError(
            f"ReplayScannerBackfill {inputs.backfill_id} cancelled: its exposure filter can't run: {exc}",
            non_retryable=True,
        ) from exc

    # Succeeded only, matching the `$recording_observed` event the creation-time count excludes on.
    # Postgres rather than that count's fail-soft ClickHouse read, whose hiccup would report every session
    # unobserved and turn the retake path below into real re-scans and real charges.
    succeeded_at = dict(
        ReplayObservation.objects.filter(
            team_id=inputs.team_id,
            scanner_id=backfill.scanner_id,
            status=ObservationStatus.SUCCEEDED,
            session_id__in=[c.session_id for c in candidates],
        ).values_list("session_id", "completed_at")
    )
    unobserved = [c for c in candidates if c.session_id not in succeeded_at]
    # After the Postgres filter, so the scan covers only ids that could still be dispatched.
    excluded = excluded_sessions.excluded_session_ids(
        team=backfill.team,
        candidate_query=candidate_query,
        candidates=unobserved,
        query_type=BACKFILL_EXCLUDED_SESSIONS_QUERY_TYPE,
        scanner_id=str(backfill.scanner_id),
        seconds_remaining=FIND_BACKFILL_CANDIDATES_TIMEOUT.total_seconds() - (time.monotonic() - started_at),
    )
    # Same quarantine as the live sweep: a session past the stuck threshold cannot render, and the
    # cursor steps over it exactly like an excluded session.
    stuck = read_stuck_session_ids(inputs.team_id, [c.session_id for c in unobserved])
    dispatchable = [c for c in unobserved if c.session_id not in excluded and c.session_id not in stuck]
    # Only sessions the live sweep reached after this backfill was quoted were in its total, so only those
    # count as work done; earlier successes were already excluded at creation.
    overtaken = {
        session_id
        for session_id, completed in succeeded_at.items()
        if completed is not None and completed > backfill.created_at
    }

    # Claim a slot per dispatchable candidate before the workflow starts its children: a started
    # child is invisible to the row-count caps until it persists its observation, so successive
    # ticks would otherwise all read the same headroom. `create_observation_activity` releases the
    # claim once the row exists, and an unreleased claim expires on its own TTL.
    admitted = claim_enqueue_slot_prefix(
        team_id=inputs.team_id,
        scanner_id=backfill.scanner_id,
        workflow_ids=[build_apply_scanner_workflow_id(backfill.scanner_id, c.session_id) for c in dispatchable],
        team_in_flight_rows=rows["team"],
        scanner_in_flight_rows=rows["scanner"],
        backfill_id=backfill.id,
        backfill_in_flight_rows=rows["backfill"],
        scheduled=True,
    )

    # The cursor may step over an already-observed session, because nothing will ever need doing for
    # it, but never over one the caps held back. Claiming stops at the first refusal, so the admitted
    # set is a prefix of `dispatchable` and everything before it in `candidates` is accounted for.
    truncated_by_caps = admitted < len(dispatchable)
    if truncated_by_caps:
        walked_to = dispatchable[admitted - 1] if admitted else None
    else:
        # An empty batch means the walk drained the window: leave the cursor alone and let the
        # short batch below complete the backfill.
        walked_to = candidates[-1] if candidates else None

    # Everything the cursor passes is accounted for, dispatched or not. Without counting the skipped ones
    # `dispatched_count` could never reach `total_count` on a window this scanner has already partly tried,
    # which strands progress short of complete and leaves phantom credits in the org's projected spend.
    walked_through = candidates.index(walked_to) + 1 if walked_to is not None else 0
    skipped = sum(1 for c in candidates[:walked_through] if c.session_id in overtaken)

    return FindBackfillCandidatesOutput(
        started_from_cursor_end_time=backfill.cursor_end_time,
        started_from_cursor_session_id=backfill.cursor_session_id,
        candidates=[
            CandidateSessionPayload(session_id=c.session_id, session_end=c.session_end) for c in dispatchable[:admitted]
        ],
        skipped_delta=skipped,
        next_cursor_end_time=walked_to.session_end if walked_to else None,
        next_cursor_session_id=walked_to.session_id if walked_to else "",
        # Held-back candidates are still work below the cursor, so a truncated batch must not look
        # like a drained window; that would complete the backfill with sessions left unscanned.
        more_work_below_cursor=len(candidates) == inputs.candidate_limit or truncated_by_caps,
    )


@activity.defn
@track_activity()
def advance_backfill_cursor_activity(inputs: AdvanceBackfillCursorInputs) -> AdvanceBackfillCursorOutput:
    """Advance the descending cursor and dispatch count; a short batch completes the backfill.

    Filtered to RUNNING rows so a concurrent cancel or pause wins over the advance.
    """
    updates: dict[str, object] = {
        "dispatched_count": F("dispatched_count") + inputs.dispatched_delta,
        "skipped_count": F("skipped_count") + inputs.skipped_delta,
    }
    if inputs.new_cursor_end_time is not None:
        updates["cursor_end_time"] = inputs.new_cursor_end_time
        updates["cursor_session_id"] = inputs.new_cursor_session_id
    if inputs.exhausted:
        updates["status"] = BackfillStatus.COMPLETED
        updates["finished_at"] = timezone.now()
    # Matching the starting cursor makes this idempotent: Temporal retries an activity whose result
    # was lost after it committed, and a second blind increment would inflate progress and understate
    # the backfill's remaining credit commitment.
    updated = (
        ReplayScannerBackfill.objects.for_team(inputs.team_id)
        .filter(
            pk=inputs.backfill_id,
            status=BackfillStatus.RUNNING,
            cursor_end_time=inputs.expected_cursor_end_time,
            cursor_session_id=inputs.expected_cursor_session_id,
        )
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
        # The SDK throttles the RPCs, so per-listing is cheap.
        activity.heartbeat({"phase": "listing_schedules", "seen": len(seen)})
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
        activity.heartbeat({"phase": "applying_fixes", "fixes": len(fixes)})
        await asyncio.gather(*fixes)
