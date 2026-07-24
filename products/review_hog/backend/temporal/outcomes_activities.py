"""Temporal activities for the periodic finding-outcome sweep.

`discover_outcome_teams_activity` finds which teams have work; `classify_team_outcomes_activity`
does one team's classification, emitting a `reviewhog_finding_outcome` event per finding through a
scoped PostHog client (Celery/Temporal-safe capture, cloud-only).
"""

import logging
from datetime import timedelta

from django.utils import timezone

from temporalio import activity

from posthog.models.team.team import Team
from posthog.ph_client import ph_scoped_capture
from posthog.sync import database_sync_to_async
from posthog.temporal.common.scoped import scoped_temporal
from posthog.temporal.common.utils import close_db_connections

from products.review_hog.backend.reviewer.outcomes.classify import classify_team
from products.review_hog.backend.reviewer.outcomes.discovery import team_ids_with_unclassified_published_reports
from products.review_hog.backend.temporal.outcomes_types import (
    ClassifyFindingOutcomesInputs,
    ClassifyTeamOutcomesInputs,
)

logger = logging.getLogger(__name__)


@activity.defn
@scoped_temporal()
@close_db_connections
async def discover_outcome_teams_activity(input: ClassifyFindingOutcomesInputs) -> list[int]:
    """Teams with a published, not-yet-classified report to sweep this cycle."""
    return await database_sync_to_async(team_ids_with_unclassified_published_reports, thread_sensitive=False)()


@activity.defn
@scoped_temporal()
@close_db_connections
async def classify_team_outcomes_activity(input: ClassifyTeamOutcomesInputs) -> int:
    """Classify one team's merged reports; returns the number of findings classified."""
    team = await database_sync_to_async(Team.objects.get, thread_sensitive=False)(id=input.team_id)
    since = timezone.now() - timedelta(days=input.lookback_days)
    with ph_scoped_capture() as capture:
        # flush lets the classifier block on delivery before stamping a report done — the stamp
        # must never outrun the event buffer.
        classified = await classify_team(team=team, since=since, capture=capture, flush=capture.flush)
    logger.info("Classified %d finding outcomes for team %s", classified, input.team_id)
    return classified
