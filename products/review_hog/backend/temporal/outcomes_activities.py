"""Temporal activities for the periodic finding-outcome sweep.

`discover_outcome_teams_activity` finds which teams have work; `classify_team_outcomes_activity`
does one team's classification, emitting a `reviewhog_finding_outcome` event per finding through a
scoped PostHog client (Celery/Temporal-safe capture, cloud-only). Classification takes minutes, so
like the review activities it declares a `heartbeat_timeout` on dispatch and heartbeats via
`Heartbeater()`; discovery is a single indexed query and needs neither.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from asgiref.sync import sync_to_async
from temporalio import activity

from posthog.models.team.team import Team
from posthog.ph_client import ScopedCapture, ph_scoped_capture
from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.scoped import scoped_temporal
from posthog.temporal.common.utils import close_db_connections

from products.review_hog.backend.reviewer.outcomes.classify import classify_team
from products.review_hog.backend.reviewer.outcomes.discovery import team_ids_with_unclassified_published_reports
from products.review_hog.backend.temporal.outcomes_types import ClassifyTeamOutcomesInputs

logger = logging.getLogger(__name__)


@activity.defn
@scoped_temporal()
@close_db_connections
async def discover_outcome_teams_activity() -> list[int]:
    """Teams with a published, not-yet-classified report to sweep this cycle.

    Takes no input: the sweep has no window to narrow by, so discovery is driven entirely by report
    state (published, PR-bound, not yet stamped emitted).
    """
    return await database_sync_to_async(team_ids_with_unclassified_published_reports, thread_sensitive=False)()


@asynccontextmanager
async def _scoped_capture_off_loop() -> AsyncIterator[ScopedCapture]:
    """`ph_scoped_capture()` with its blocking ends moved off the event loop.

    Leaving the scope calls `Posthog.shutdown()`, which flushes with `timeout_seconds=None` and so
    waits indefinitely — unacceptable inline on the worker's shared loop. The `capture()` calls in
    between are non-blocking enqueues and stay on it.
    """
    scope = ph_scoped_capture()
    capture = await sync_to_async(scope.__enter__, thread_sensitive=False)()
    try:
        yield capture
    finally:
        # The scope's generator has no `except`, so it flushes identically whether or not the
        # exception is handed to it; the caller's exception keeps propagating on its own.
        await sync_to_async(scope.__exit__, thread_sensitive=False)(None, None, None)


@activity.defn
@scoped_temporal()
@close_db_connections
async def classify_team_outcomes_activity(input: ClassifyTeamOutcomesInputs) -> int:
    """Classify one team's merged reports; returns the number of findings classified."""
    team = await database_sync_to_async(Team.objects.get, thread_sensitive=False)(id=input.team_id)
    async with Heartbeater(), _scoped_capture_off_loop() as capture:
        # flush lets the classifier block on delivery before stamping a report done — the stamp
        # must never outrun the event buffer.
        classified = await classify_team(team=team, capture=capture, flush=capture.flush)
    logger.info("Classified %d finding outcomes for team %s", classified, input.team_id)
    return classified
