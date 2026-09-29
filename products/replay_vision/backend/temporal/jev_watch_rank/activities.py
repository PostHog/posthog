"""The hourly sweep that asks Jev to rank each enrolled scanner's recent window.

Runs outside both hot paths on purpose: the feed API is synchronous and must not make model calls,
and the scan pipeline must not carry a judgment that can only slow or fail a paid-for scan. The
sweep judges whole windows (`judge_scanner_window`), so each probability is relative to the
scanner's other recent sessions, and writes them to the Redis cache the feed reads
(`load_watch_ranks`).

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
    judge_scanner_window,
    refresh_watch_ranks_ttl,
    store_watch_ranks,
    stored_watch_rank_fingerprint,
    watch_feed_ranker,
    window_fingerprint,
)
from products.replay_vision.backend.models.replay_observation import ObservationStatus, ReplayObservation
from products.replay_vision.backend.models.replay_scanner import ReplayScanner
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.jev_watch_rank.constants import (
    MAX_SCANNERS_PER_SWEEP,
    MAX_TEAMS_PER_SWEEP,
    SWEEP_TIME_BUDGET,
    WATCH_RANK_WINDOW,
    WINDOW_ROWS_CAP,
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
            rows = await sync_to_async(_scanner_window_rows)(team_id, scanner_id, window_start)
            if not rows:
                continue
            fingerprint = window_fingerprint(rows)
            if fingerprint == await asyncio.to_thread(stored_watch_rank_fingerprint, team_id, scanner_id):
                # Same window as last run, so keep the cache warm without re-buying the judgments.
                await asyncio.to_thread(refresh_watch_ranks_ttl, team_id, scanner_id)
                scanners_skipped_unchanged += 1
                continue
            judgment = await asyncio.to_thread(judge_scanner_window, team_id, scanner_id, rows)
            if judgment.probabilities:
                await asyncio.to_thread(store_watch_ranks, team_id, scanner_id, judgment, fingerprint)
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
