"""The hourly sweep that asks Jev to rank each enrolled scanner's recent window.

Runs outside both hot paths on purpose: the feed API is synchronous and must not make model calls,
and the scan pipeline must not carry a judgment that can only slow or fail a paid-for scan. The
sweep judges whole windows (`judge_scanner_window`), so each probability is relative to the
scanner's other recent sessions, and writes them to the Redis cache the feed reads
(`load_watch_ranks`).
"""

import asyncio
from collections import defaultdict
from contextlib import suppress
from datetime import UTC, datetime
from statistics import fmean
from typing import Any
from uuid import UUID

import structlog
import posthoganalytics
from asgiref.sync import sync_to_async
from temporalio import activity

from posthog.temporal.common.heartbeat import Heartbeater

from products.replay_vision.backend.jev_watch_feed import judge_scanner_window, store_watch_ranks, watch_feed_ranker
from products.replay_vision.backend.models.replay_observation import ObservationStatus, ReplayObservation
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.jev_watch_rank.constants import (
    MAX_SCANNERS_PER_SWEEP,
    WATCH_RANK_WINDOW,
    WINDOW_ROWS_CAP,
)
from products.replay_vision.backend.temporal.jev_watch_rank.types import (
    JevWatchRankSweepInputs,
    JevWatchRankSweepResult,
)

logger = structlog.get_logger(__name__)


def _recent_scanner_pairs(window_start: datetime) -> dict[int, list[UUID]]:
    """Scanner ids with recent succeeded observations, grouped by team. Cross-team on purpose: the
    sweep is a global background job, and the per-team flag check below scopes the actual work."""
    pairs = (
        ReplayObservation.objects.filter(status=ObservationStatus.SUCCEEDED, created_at__gte=window_start)
        .values_list("team_id", "scanner_id")
        .distinct()[: MAX_SCANNERS_PER_SWEEP + 1]
    )
    by_team: dict[int, list[UUID]] = defaultdict(list)
    for team_id, scanner_id in pairs:
        by_team[team_id].append(scanner_id)
    return dict(by_team)


def _scanner_window_rows(team_id: int, scanner_id: UUID, window_start: datetime) -> list[dict[str, Any]]:
    rows = (
        ReplayObservation.objects.filter(
            team_id=team_id,
            scanner_id=scanner_id,
            status=ObservationStatus.SUCCEEDED,
            created_at__gte=window_start,
        )
        .order_by("-created_at")
        .values("id", "scanner_result")[:WINDOW_ROWS_CAP]
    )
    # The ORM plugin types `values()` rows as a TypedDict, which is not a `dict[str, Any]`.
    return [dict(row) for row in rows]


@activity.defn(name="replay_vision_judge_watch_ranks_activity")
@track_activity()
async def judge_watch_ranks_activity(inputs: JevWatchRankSweepInputs) -> JevWatchRankSweepResult:
    """Judges every enrolled scanner's window. Per-scanner failures counted, never raised."""
    # Continuous background heartbeats — a slow Jev fan-out otherwise outlives the heartbeat timeout.
    async with Heartbeater(factor=4):
        return await _judge_watch_ranks(inputs)


async def _judge_watch_ranks(inputs: JevWatchRankSweepInputs) -> JevWatchRankSweepResult:
    window_start = datetime.now(UTC) - WATCH_RANK_WINDOW
    by_team = await sync_to_async(_recent_scanner_pairs)(window_start)
    total_pairs = sum(len(scanner_ids) for scanner_ids in by_team.values())

    teams_enrolled = 0
    scanners_judged = 0
    observations_judged = 0
    failed_chunks = 0
    input_tokens = 0
    estimated_cost = 0.0
    for team_id, scanner_ids in by_team.items():
        mode = await asyncio.to_thread(watch_feed_ranker, team_id)
        if mode == "weighted-score":
            continue
        teams_enrolled += 1
        for scanner_id in scanner_ids:
            rows = await sync_to_async(_scanner_window_rows)(team_id, scanner_id, window_start)
            if not rows:
                continue
            judgment = await asyncio.to_thread(judge_scanner_window, team_id, scanner_id, rows)
            if judgment.probabilities:
                await asyncio.to_thread(store_watch_ranks, team_id, scanner_id, judgment)
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

    result = JevWatchRankSweepResult(
        teams_seen=len(by_team),
        teams_enrolled=teams_enrolled,
        scanners_judged=scanners_judged,
        observations_judged=observations_judged,
        failed_chunks=failed_chunks,
        input_tokens=input_tokens,
        estimated_cost_usd=estimated_cost,
        hit_scanner_cap=total_pairs > MAX_SCANNERS_PER_SWEEP,
    )
    logger.info(
        "replay_vision.jev_watch_rank.cycle_complete",
        teams_seen=result.teams_seen,
        teams_enrolled=result.teams_enrolled,
        scanners_judged=result.scanners_judged,
        observations_judged=result.observations_judged,
        failed_chunks=result.failed_chunks,
        input_tokens=result.input_tokens,
        hit_scanner_cap=result.hit_scanner_cap,
    )
    return result
