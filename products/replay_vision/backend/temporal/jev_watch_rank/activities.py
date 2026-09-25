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

import asyncio
from contextlib import suppress
from datetime import UTC, datetime
from statistics import fmean
from time import monotonic
from typing import Any
from uuid import UUID

import structlog
import posthoganalytics
from asgiref.sync import sync_to_async
from temporalio import activity

from posthog.temporal.common.heartbeat import Heartbeater

from products.ml_inference.backend.facade import api as decision_api
from products.replay_vision.backend.consent import is_ai_data_processing_approved
from products.replay_vision.backend.jev_watch_feed import (
    WINDOW_CHUNK_SIZE,
    judge_scanner_window,
    load_watch_ranks,
    refresh_watch_ranks_ttl,
    store_watch_ranks,
    watch_feed_ranker,
)
from products.replay_vision.backend.models.replay_observation import ObservationStatus, ReplayObservation
from products.replay_vision.backend.models.replay_scanner import ReplayScanner
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.jev_watch_rank.constants import (
    MAX_JUDGED_PER_SCANNER,
    MAX_SCANNERS_PER_SWEEP,
    MAX_TEAMS_PER_SWEEP,
    SWEEP_TIME_BUDGET,
    WATCH_RANK_WINDOW,
    WINDOW_SCAN_CAP,
)
from products.replay_vision.backend.temporal.jev_watch_rank.types import (
    JevWatchRankSweepInputs,
    JevWatchRankSweepResult,
)

logger = structlog.get_logger(__name__)


def _teams_with_scanners() -> list[int]:
    """Teams that own any scanner. The scanner table is small, so this is the cheap universe to
    flag-check; the huge observation table is only queried per team below, where its indexes hold."""
    return list(ReplayScanner.all_origins.values_list("team_id", flat=True).distinct()[: MAX_TEAMS_PER_SWEEP + 1])


def _team_scanner_ids(team_id: int, window_start: datetime) -> list[UUID]:
    return list(
        ReplayObservation.objects.filter(
            team_id=team_id, status=ObservationStatus.SUCCEEDED, created_at__gte=window_start
        )
        .values_list("scanner_id", flat=True)
        .distinct()
    )


def _scanner_window_ids(team_id: int, scanner_id: UUID, window_start: datetime) -> list[UUID]:
    """Newest first, ids only: cheap enough to list the whole capped window every sweep, so the
    sweep can tell which rows still lack a judgment and which cached entries left the window."""
    return list(
        ReplayObservation.objects.filter(
            team_id=team_id,
            scanner_id=scanner_id,
            status=ObservationStatus.SUCCEEDED,
            created_at__gte=window_start,
        )
        .order_by("-created_at")
        .values_list("id", flat=True)[:WINDOW_SCAN_CAP]
    )


def _rows_by_id(team_id: int, ids: list[UUID]) -> list[dict[str, Any]]:
    rows = ReplayObservation.objects.filter(team_id=team_id, id__in=ids).values("id", "scanner_result")
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


async def _judge_watch_ranks(inputs: JevWatchRankSweepInputs) -> JevWatchRankSweepResult:
    if not decision_api.decisions_available_here():
        return JevWatchRankSweepResult(decisions_unavailable=True)
    deadline = monotonic() + SWEEP_TIME_BUDGET.total_seconds()
    window_start = datetime.now(UTC) - WATCH_RANK_WINDOW
    team_ids = await sync_to_async(_teams_with_scanners)()

    teams_enrolled = 0
    teams_without_consent = 0
    scanners_judged = 0
    scanners_skipped_unchanged = 0
    observations_judged = 0
    failed_chunks = 0
    input_tokens = 0
    estimated_cost = 0.0
    scanners_seen = 0
    hit_scanner_cap = False
    hit_time_budget = False
    for team_id in team_ids[:MAX_TEAMS_PER_SWEEP]:
        if monotonic() > deadline:
            hit_time_budget = True
            break
        mode = await asyncio.to_thread(watch_feed_ranker, team_id)
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
            if monotonic() > deadline:
                hit_time_budget = True
                break
            if scanners_seen >= MAX_SCANNERS_PER_SWEEP:
                hit_scanner_cap = True
                break
            scanners_seen += 1
            window_ids = await sync_to_async(_scanner_window_ids)(team_id, scanner_id, window_start)
            if not window_ids:
                continue
            # Judgments accumulate: each sweep judges only the rows without a cached probability,
            # newest first, and cached entries whose rows left the window are pruned. Coverage
            # therefore grows across sweeps at MAX_JUDGED_PER_SCANNER per hour whatever the
            # scanner's volume, and a fully judged window costs nothing.
            cached = await asyncio.to_thread(load_watch_ranks, team_id, [scanner_id])
            kept = {str(row_id): cached[str(row_id)] for row_id in window_ids if str(row_id) in cached}
            unjudged_ids = [row_id for row_id in window_ids if str(row_id) not in cached][:MAX_JUDGED_PER_SCANNER]
            if not unjudged_ids:
                await asyncio.to_thread(refresh_watch_ranks_ttl, team_id, scanner_id)
                scanners_skipped_unchanged += 1
                continue
            judged_context_ids = [row_id for row_id in window_ids if str(row_id) in kept][:WINDOW_CHUNK_SIZE]
            rows = await sync_to_async(_rows_by_id)(team_id, unjudged_ids)
            context_rows = await sync_to_async(_rows_by_id)(team_id, judged_context_ids)
            judgment = await asyncio.to_thread(judge_scanner_window, team_id, scanner_id, rows, context_rows)
            merged = {
                **kept,
                **dict.fromkeys(judgment.skipped_no_prose, 0.0),
                **judgment.probabilities,
            }
            if merged:
                await asyncio.to_thread(store_watch_ranks, team_id, scanner_id, merged, judgment.model)
            scanners_judged += 1
            observations_judged += len(judgment.probabilities)
            failed_chunks += judgment.failed_chunks
            input_tokens += judgment.input_tokens
            estimated_cost += judgment.estimated_cost_usd
            with suppress(Exception):
                posthoganalytics.capture(
                    event="replay_vision_jev_watch_rank_judged",
                    distinct_id=f"team-{team_id}",
                    properties={
                        "scanner_id": str(scanner_id),
                        "mode": mode,
                        "window_rows": len(rows),
                        "observations_judged": len(judgment.probabilities),
                        "mean_watchability": (
                            fmean(judgment.probabilities.values()) if judgment.probabilities else None
                        ),
                        "chunks": judgment.chunks,
                        "failed_chunks": judgment.failed_chunks,
                        "jev_model": judgment.model,
                        "input_tokens": judgment.input_tokens,
                        "estimated_cost_usd": judgment.estimated_cost_usd,
                    },
                )
        if hit_scanner_cap:
            break

    result = JevWatchRankSweepResult(
        teams_seen=min(len(team_ids), MAX_TEAMS_PER_SWEEP),
        teams_enrolled=teams_enrolled,
        teams_without_consent=teams_without_consent,
        scanners_judged=scanners_judged,
        scanners_skipped_unchanged=scanners_skipped_unchanged,
        observations_judged=observations_judged,
        failed_chunks=failed_chunks,
        input_tokens=input_tokens,
        estimated_cost_usd=estimated_cost,
        hit_team_cap=len(team_ids) > MAX_TEAMS_PER_SWEEP,
        hit_scanner_cap=hit_scanner_cap,
        hit_time_budget=hit_time_budget,
    )
    logger.info(
        "replay_vision.jev_watch_rank.cycle_complete",
        teams_seen=result.teams_seen,
        teams_enrolled=result.teams_enrolled,
        teams_without_consent=result.teams_without_consent,
        scanners_judged=result.scanners_judged,
        scanners_skipped_unchanged=result.scanners_skipped_unchanged,
        observations_judged=result.observations_judged,
        failed_chunks=result.failed_chunks,
        input_tokens=result.input_tokens,
        hit_team_cap=result.hit_team_cap,
        hit_scanner_cap=result.hit_scanner_cap,
        hit_time_budget=result.hit_time_budget,
    )
    return result
