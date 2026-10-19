"""The hourly sweep that asks Jev to rank each enrolled scanner's recent window.

Runs outside both hot paths on purpose: the feed API is synchronous and must not make model calls,
and the scan pipeline must not carry a judgment that can only slow or fail a paid-for scan. Each
sweep judges only the rows without a cached probability (`judge_scanner_window`, with judged rows
padding the request as context) and merges the results into the Redis cache the feed reads
(`load_watch_ranks`), so coverage of a scanner's window accumulates at a bounded hourly cost
whatever the scanner's volume.

The gates run cheapest-first: region (one settings read), then the per-team flag, then the org's AI
data-processing consent, then per-team indexed observation queries. The observation table has no
cross-team index on (status, created_at), so the sweep never queries it without a team_id.
"""

import random
import asyncio
import threading
from collections import Counter
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from statistics import fmean
from time import monotonic, sleep
from typing import Any
from uuid import UUID

import structlog
import posthoganalytics
from asgiref.sync import sync_to_async
from temporalio import activity

from posthog.dataclasses import frozen
from posthog.models.team import Team
from posthog.temporal.common.heartbeat import Heartbeater

from products.ml_inference.backend.facade import api as decision_api
from products.replay_vision.backend.consent import is_ai_data_processing_approved
from products.replay_vision.backend.jev_watch_feed import (
    JEV_WATCHABLE_MIN,
    WINDOW_CHUNK_SIZE,
    judge_scanner_window,
    load_judged_state,
    load_scanner_watch_ranks,
    refresh_watch_ranks_ttl,
    store_watch_ranks,
    watch_feed_ranker,
)
from products.replay_vision.backend.models.replay_observation import ObservationStatus, ReplayObservation
from products.replay_vision.backend.models.replay_scanner import ReplayScanner
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.jev_watch_rank.constants import (
    JUDGE_CONCURRENCY,
    JUDGE_TOKENS_PER_SECOND,
    MAX_JUDGE_ATTEMPTS,
    MAX_JUDGED_PER_SCANNER,
    MAX_SCANNERS_PER_SWEEP,
    MAX_TEAMS_PER_SWEEP,
    PINNED_TEAM_IDS,
    RATE_LIMIT_GIVE_UP_AFTER,
    RATE_LIMIT_PAUSE,
    SWEEP_ACTIVITY_HEARTBEAT_TIMEOUT,
    SWEEP_TIME_BUDGET,
    WATCH_RANK_WINDOW,
    WINDOW_SCAN_CAP,
)
from products.replay_vision.backend.temporal.jev_watch_rank.metrics import push_sweep_metrics
from products.replay_vision.backend.temporal.jev_watch_rank.types import (
    JevWatchRankSweepInputs,
    JevWatchRankSweepResult,
)
from products.replay_vision.backend.temporal.query_budget import bounded_queries

# The background heartbeat keeps a stalled query's attempt alive for the whole sweep, so each query gets its own
# heartbeat window instead.
_QUERY_BUDGET = SWEEP_ACTIVITY_HEARTBEAT_TIMEOUT

logger = structlog.get_logger(__name__)


def _teams_with_scanners() -> list[int]:
    """Teams that own any scanner. The scanner table is small, so this is the cheap universe to
    flag-check; the huge observation table is only queried per team below, where its indexes hold.

    Pinned teams go first. The rest are shuffled, so when a run stops at the time budget, the teams
    it leaves for the next run change from run to run instead of always being the newest ones.
    """
    with bounded_queries(_QUERY_BUDGET, from_attempt_start=False):
        team_ids = list(
            ReplayScanner.all_origins.values_list("team_id", flat=True)
            .distinct()
            .order_by("team_id")[: MAX_TEAMS_PER_SWEEP + 1]
        )
    others = [team_id for team_id in team_ids if team_id not in PINNED_TEAM_IDS]
    random.shuffle(others)
    return [*PINNED_TEAM_IDS, *others]


def _team_uuids(team_ids: list[int]) -> dict[int, UUID]:
    """The flag keys on the project's uuid, so the sweep looks them up in one query per run."""
    with bounded_queries(_QUERY_BUDGET, from_attempt_start=False):
        return dict(Team.objects.filter(id__in=team_ids).values_list("id", "uuid"))


def _team_scanner_ids(team_id: int, window_start: datetime) -> list[UUID]:
    with bounded_queries(_QUERY_BUDGET, from_attempt_start=False):
        return list(
            ReplayObservation.objects.filter(
                team_id=team_id, status=ObservationStatus.SUCCEEDED, created_at__gte=window_start
            )
            .values_list("scanner_id", flat=True)
            .distinct()
        )


def _scanner_window(team_id: int, scanner_id: UUID, window_start: datetime) -> dict[UUID, datetime]:
    """Newest first, without prose: cheap enough to list the whole capped window every sweep, so the
    sweep can tell which rows still lack a judgment and which cached entries left the window."""
    with bounded_queries(_QUERY_BUDGET, from_attempt_start=False):
        return dict(
            ReplayObservation.objects.filter(
                team_id=team_id,
                scanner_id=scanner_id,
                status=ObservationStatus.SUCCEEDED,
                created_at__gte=window_start,
            )
            .order_by("-created_at")
            .values_list("id", "created_at")[:WINDOW_SCAN_CAP]
        )


def _rows_by_id(team_id: int, ids: list[UUID]) -> list[dict[str, Any]]:
    with bounded_queries(_QUERY_BUDGET, from_attempt_start=False):
        rows = list(ReplayObservation.objects.filter(team_id=team_id, id__in=ids).values("id", "scanner_result"))
    by_id = {row["id"]: dict(row) for row in rows}
    # `id__in` loses the caller's newest-first order.
    return [by_id[row_id] for row_id in ids if row_id in by_id]


@activity.defn(name="replay_vision_judge_watch_ranks_activity")
@track_activity()
async def judge_watch_ranks_activity(inputs: JevWatchRankSweepInputs) -> JevWatchRankSweepResult:
    """Judges every enrolled scanner's window. Per-scanner failures counted, never raised."""
    # Continuous background heartbeats — a slow Jev fan-out otherwise outlives the heartbeat timeout.
    async with Heartbeater(factor=4):
        return await _judge_watch_ranks(inputs)


@frozen
class _ScannerOutcome:
    """What one scanner's turn in the sweep did, summed into the sweep result."""

    judged: bool = False
    skipped_unchanged: bool = False
    # The scanner waited past the time budget and was left for the next run.
    out_of_time: bool = False
    # The organization revoked AI data-processing consent while the scanner waited for its turn.
    consent_revoked: bool = False
    # The gateway rate-limited the scanner's requests.
    rate_limited: bool = False
    # The run had been rate-limited RATE_LIMIT_GIVE_UP_AFTER turns in a row, so the scanner waits for
    # the next run.
    backed_off: bool = False
    observations_judged: int = 0
    observations_given_up: int = 0
    cache_errors: int = 0
    failed_chunks: int = 0
    input_tokens: int = 0
    estimated_cost_usd: float = 0.0
    estimated_prompt_tokens: int = 0
    failed_reason_chunks: int = 0
    inspected: bool = False
    window_capped: bool = False
    pending_observations: int = 0
    oldest_pending_age_seconds: float = 0.0


class _TokenPacer:
    """Spreads the run's Jev requests across the hour at a steady token rate.

    Thread-safe, because judging runs in worker threads. wait() reserves the next free slot, sized
    by the request's tokens, and sleeps until it; the first request in an idle run never waits."""

    def __init__(self, tokens_per_second: float) -> None:
        self._seconds_per_token = 1.0 / tokens_per_second
        self._lock = threading.Lock()
        self._next_start = monotonic()
        self.waited_seconds = 0.0

    def wait(self, tokens: int) -> None:
        with self._lock:
            now = monotonic()
            start = max(now, self._next_start)
            self._next_start = start + tokens * self._seconds_per_token
            waiting = start - now
            self.waited_seconds += waiting
        if waiting > 0:
            sleep(waiting)


async def _sweep_scanner(
    team_id: int,
    scanner_id: UUID,
    mode: str,
    window_start: datetime,
    pace: Callable[[int], None],
    stop_after: float,
) -> _ScannerOutcome:
    window = await sync_to_async(_scanner_window)(team_id, scanner_id, window_start)
    window_ids = list(window)
    if not window_ids:
        return _ScannerOutcome(inspected=True)
    # Judgments accumulate: each sweep judges only the rows the judged set does not hold,
    # newest first, and cache entries whose rows left the window are pruned. Coverage
    # therefore grows across sweeps at MAX_JUDGED_PER_SCANNER per hour whatever the
    # scanner's volume, and a fully judged window costs nothing.
    try:
        judged_state = await asyncio.to_thread(load_judged_state, team_id, scanner_id)
        cached = await asyncio.to_thread(load_scanner_watch_ranks, team_id, scanner_id)
    except Exception:
        # A cache the sweep cannot read must not be judged over or written: without the
        # judged set it re-buys rows, and the write would replace entries it never saw.
        logger.exception(
            "Jev watch rank cache unreadable, skipping scanner",
            team_id=team_id,
            scanner_id=str(scanner_id),
        )
        return _ScannerOutcome(cache_errors=1)
    judged = judged_state.ids
    unjudged_ids = [row_id for row_id in window_ids if str(row_id) not in judged][:MAX_JUDGED_PER_SCANNER]
    if not unjudged_ids:
        await asyncio.to_thread(refresh_watch_ranks_ttl, team_id, scanner_id)
        return _ScannerOutcome(skipped_unchanged=True, inspected=True, window_capped=len(window) == WINDOW_SCAN_CAP)
    judged_context_ids = [row_id for row_id in window_ids if str(row_id) in judged][:WINDOW_CHUNK_SIZE]
    rows = await sync_to_async(_rows_by_id)(team_id, unjudged_ids)
    context_rows = await sync_to_async(_rows_by_id)(team_id, judged_context_ids)
    judgment = await asyncio.to_thread(judge_scanner_window, team_id, scanner_id, rows, context_rows, pace, stop_after)
    # Sub-threshold judgments join only the judged set, keeping the watchable key — which
    # the feed loads for every readable scanner on each request — small.
    window_strs = {str(row_id) for row_id in window_ids}
    watchable = {
        **{oid: p for oid, p in cached.probabilities.items() if oid in window_strs},
        **{oid: p for oid, p in judgment.probabilities.items() if p >= JEV_WATCHABLE_MIN},
    }
    reasons = {oid: reason for oid, reason in (cached.reasons | judgment.reasons).items() if oid in watchable}
    # A row whose judgment failed through its own batch (an invalid answer, a gateway
    # refusal the batch caused) retries on later sweeps, but only MAX_JUDGE_ATTEMPTS times: the
    # newest-first pick would otherwise retry a deterministically failing batch every hour
    # and starve older rows. An exhausted row is recorded as judged with no score, so it
    # settles into the filler tier like a prose-less row. An outage charges nothing — its
    # rows stay unjudged and retry free next sweep.
    failed_ids = set(judgment.batch_failed_ids)
    updated_attempts = {oid: judged_state.attempts.get(oid, 0) + 1 for oid in failed_ids}
    exhausted = {oid for oid, count in updated_attempts.items() if count >= MAX_JUDGE_ATTEMPTS}
    attempts = {
        oid: count for oid, count in judged_state.attempts.items() if oid in window_strs and oid not in failed_ids
    } | {oid: count for oid, count in updated_attempts.items() if count < MAX_JUDGE_ATTEMPTS}
    all_judged = (judged & window_strs) | set(judgment.probabilities) | set(judgment.skipped_no_prose) | exhausted
    cache_errors = 0
    if all_judged or attempts:
        try:
            await asyncio.to_thread(
                store_watch_ranks,
                team_id,
                scanner_id,
                all_judged,
                watchable,
                attempts,
                judgment.model,
                reasons,
            )
        except Exception:
            # The batch is re-bought next run, which beats one write failure ending the sweep.
            logger.exception("Jev watch rank cache write failed", team_id=team_id, scanner_id=str(scanner_id))
            cache_errors += 1
    persisted_judged = all_judged if cache_errors == 0 else judged
    pending = [created_at for row_id, created_at in window.items() if str(row_id) not in persisted_judged]
    with suppress(Exception):
        # Sub-threshold scores are cached nowhere, so this event is the only record of the
        # score distribution — it is the data JEV_WATCHABLE_MIN is calibrated from.
        scores = sorted(judgment.probabilities.values())
        top_scored = [
            {"id": oid, "p": round(probability, 3)}
            for oid, probability in sorted(judgment.probabilities.items(), key=lambda entry: entry[1], reverse=True)[:5]
        ]
        posthoganalytics.capture(
            event="replay_vision_jev_watch_rank_judged",
            distinct_id=f"team-{team_id}",
            properties={
                "scanner_id": str(scanner_id),
                "mode": mode,
                "window_rows": len(rows),
                "observations_judged": len(judgment.probabilities),
                "mean_watchability": (fmean(judgment.probabilities.values()) if judgment.probabilities else None),
                "watchable_count": sum(1 for probability in scores if probability >= JEV_WATCHABLE_MIN),
                "watchability_p90": scores[int(0.9 * (len(scores) - 1))] if scores else None,
                "watchability_max": scores[-1] if scores else None,
                "top_scored": top_scored,
                "chunks": judgment.chunks,
                "stopped_early": judgment.stopped_early,
                "failed_chunks": judgment.failed_chunks,
                "chunk_error_types": judgment.chunk_error_types,
                "watch_reasons": dict(Counter(judgment.reasons.values())),
                "failed_reason_chunks": judgment.failed_reason_chunks,
                "rate_limited": judgment.rate_limited,
                "jev_model": judgment.model,
                "input_tokens": judgment.input_tokens,
                "estimated_cost_usd": judgment.estimated_cost_usd,
            },
        )
    return _ScannerOutcome(
        judged=True,
        rate_limited=judgment.rate_limited,
        # A window the deadline cut short surfaces as the time budget being hit, like a turn that
        # never started.
        out_of_time=judgment.stopped_early,
        observations_judged=len(judgment.probabilities),
        observations_given_up=len(exhausted),
        cache_errors=cache_errors,
        failed_chunks=judgment.failed_chunks,
        input_tokens=judgment.input_tokens,
        estimated_cost_usd=judgment.estimated_cost_usd,
        estimated_prompt_tokens=judgment.estimated_prompt_tokens,
        failed_reason_chunks=judgment.failed_reason_chunks,
        inspected=True,
        window_capped=len(window) == WINDOW_SCAN_CAP,
        pending_observations=len(pending),
        oldest_pending_age_seconds=max(0.0, (datetime.now(UTC) - min(pending)).total_seconds()) if pending else 0.0,
    )


async def _judge_watch_ranks(inputs: JevWatchRankSweepInputs) -> JevWatchRankSweepResult:
    if not decision_api.decisions_available_here():
        result = JevWatchRankSweepResult(decisions_unavailable=True)
        await asyncio.to_thread(push_sweep_metrics, result)
        return result
    started = monotonic()
    deadline = started + SWEEP_TIME_BUDGET.total_seconds()
    window_start = datetime.now(UTC) - WATCH_RANK_WINDOW
    team_ids = await sync_to_async(_teams_with_scanners)()
    team_uuids = await sync_to_async(_team_uuids)(team_ids[:MAX_TEAMS_PER_SWEEP])

    # Most of a scanner's turn waits on Jev, so scanners take turns JUDGE_CONCURRENCY at a time. The
    # teams loop only flag-checks and lists scanners, so it runs ahead and queues them.
    turns = asyncio.Semaphore(JUDGE_CONCURRENCY)
    pacer = _TokenPacer(JUDGE_TOKENS_PER_SECOND)

    # Every product's Jev calls share the decision service's capacity. A rate-limited turn pauses new
    # turns for RATE_LIMIT_PAUSE, so the run gives that capacity back instead of retrying into it. Only
    # a run that stays rate-limited leaves its remaining scanners for the next run.
    paused_until = 0.0
    consecutive_rate_limited = 0

    async def take_turn(team_id: int, scanner_id: UUID, mode: str) -> _ScannerOutcome:
        nonlocal paused_until, consecutive_rate_limited
        async with turns:
            pause = min(paused_until, deadline) - monotonic()
            if pause > 0:
                await asyncio.sleep(pause)
            if monotonic() > deadline:
                return _ScannerOutcome(out_of_time=True)
            if consecutive_rate_limited >= RATE_LIMIT_GIVE_UP_AFTER:
                return _ScannerOutcome(backed_off=True)
            # A turn can wait most of the run after its team was queued, so consent is read again
            # here: a revocation in between must stop the prose before it reaches the model.
            if not await sync_to_async(is_ai_data_processing_approved)(team_id):
                return _ScannerOutcome(consent_revoked=True)
            # The deadline passes into the window too: the turn-level check cannot interrupt a
            # scanner already judging, and a paced window of many chunks could otherwise run long
            # past the budget toward the activity timeout.
            outcome = await _sweep_scanner(team_id, scanner_id, mode, window_start, pacer.wait, deadline)
            if outcome.rate_limited:
                consecutive_rate_limited += 1
                paused_until = monotonic() + RATE_LIMIT_PAUSE.total_seconds()
            elif outcome.judged:
                consecutive_rate_limited = 0
            return outcome

    teams_enrolled = 0
    teams_evaluated = 0
    teams_without_consent = 0
    scanners_seen = 0
    hit_scanner_cap = False
    hit_time_budget = False
    queued: list[asyncio.Task[_ScannerOutcome]] = []
    async with asyncio.TaskGroup() as scanner_turns:
        for team_id in team_ids[:MAX_TEAMS_PER_SWEEP]:
            if monotonic() > deadline:
                hit_time_budget = True
                break
            team_uuid = team_uuids.get(team_id)
            if team_uuid is None:
                continue
            mode = await asyncio.to_thread(watch_feed_ranker, team_id, team_uuid)
            teams_evaluated += 1
            if mode == "weighted-score":
                continue
            # The scan prose the sweep sends to the model derives from recordings, so a revoked consent
            # stops the judgments even while the flag stays on.
            if not await sync_to_async(is_ai_data_processing_approved)(team_id):
                teams_without_consent += 1
                continue
            teams_enrolled += 1
            scanner_ids = await sync_to_async(_team_scanner_ids)(team_id, window_start)
            for scanner_id in scanner_ids:
                if scanners_seen >= MAX_SCANNERS_PER_SWEEP:
                    hit_scanner_cap = True
                    break
                scanners_seen += 1
                queued.append(scanner_turns.create_task(take_turn(team_id, scanner_id, mode)))
            if hit_scanner_cap:
                break
    outcomes = [turn.result() for turn in queued]

    result = JevWatchRankSweepResult(
        teams_seen=min(len(team_ids), MAX_TEAMS_PER_SWEEP),
        teams_evaluated=teams_evaluated,
        teams_enrolled=teams_enrolled,
        teams_without_consent=teams_without_consent,
        scanners_consent_revoked=sum(outcome.consent_revoked for outcome in outcomes),
        scanners_judged=sum(outcome.judged for outcome in outcomes),
        scanners_skipped_unchanged=sum(outcome.skipped_unchanged for outcome in outcomes),
        observations_judged=sum(outcome.observations_judged for outcome in outcomes),
        observations_given_up=sum(outcome.observations_given_up for outcome in outcomes),
        cache_errors=sum(outcome.cache_errors for outcome in outcomes),
        failed_chunks=sum(outcome.failed_chunks for outcome in outcomes),
        scanners_rate_limited=sum(outcome.rate_limited for outcome in outcomes),
        scanners_backed_off=sum(outcome.backed_off for outcome in outcomes),
        input_tokens=sum(outcome.input_tokens for outcome in outcomes),
        estimated_cost_usd=sum(outcome.estimated_cost_usd for outcome in outcomes),
        pacing_wait_seconds=round(pacer.waited_seconds, 1),
        hit_team_cap=len(team_ids) > MAX_TEAMS_PER_SWEEP,
        hit_scanner_cap=hit_scanner_cap,
        hit_time_budget=hit_time_budget or any(outcome.out_of_time for outcome in outcomes),
        estimated_prompt_tokens=sum(outcome.estimated_prompt_tokens for outcome in outcomes),
        duration_seconds=monotonic() - started,
        failed_reason_chunks=sum(outcome.failed_reason_chunks for outcome in outcomes),
        scanners_seen=scanners_seen,
        scanners_inspected=sum(outcome.inspected for outcome in outcomes),
        scanners_window_capped=sum(outcome.window_capped for outcome in outcomes),
        pending_observations=sum(outcome.pending_observations for outcome in outcomes),
        oldest_pending_age_seconds=max((outcome.oldest_pending_age_seconds for outcome in outcomes), default=0.0),
        backlog_complete=(
            len(team_ids) <= MAX_TEAMS_PER_SWEEP
            and not hit_scanner_cap
            and not hit_time_budget
            and all(outcome.inspected and not outcome.window_capped for outcome in outcomes)
        ),
    )
    logger.info(
        "replay_vision.jev_watch_rank.cycle_complete",
        teams_seen=result.teams_seen,
        teams_enrolled=result.teams_enrolled,
        teams_without_consent=result.teams_without_consent,
        scanners_consent_revoked=result.scanners_consent_revoked,
        scanners_judged=result.scanners_judged,
        scanners_skipped_unchanged=result.scanners_skipped_unchanged,
        observations_judged=result.observations_judged,
        observations_given_up=result.observations_given_up,
        cache_errors=result.cache_errors,
        failed_chunks=result.failed_chunks,
        scanners_rate_limited=result.scanners_rate_limited,
        scanners_backed_off=result.scanners_backed_off,
        input_tokens=result.input_tokens,
        pacing_wait_seconds=result.pacing_wait_seconds,
        hit_team_cap=result.hit_team_cap,
        hit_scanner_cap=result.hit_scanner_cap,
        hit_time_budget=result.hit_time_budget,
        estimated_prompt_tokens=result.estimated_prompt_tokens,
        pending_observations=result.pending_observations,
        oldest_pending_age_seconds=result.oldest_pending_age_seconds,
        backlog_complete=result.backlog_complete,
    )
    await asyncio.to_thread(push_sweep_metrics, result)
    return result
