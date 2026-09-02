"""Celery entrypoints for the daily merged-PR Slack digest.

``send_daily_digests`` is the beat fan-out: once a day it enqueues one ``send_team_digests`` per
team that has unposted merges. That task fetches the team's routing once (see
logic/channel_resolution.py) and then works through its audiences, so a run costs one config read
per connected repository and one Slack channel listing rather than one of each per audience.

The work itself lives in logic/digest_runs.py; these are the wrappers the scheduler calls.
"""

from __future__ import annotations

import structlog
from celery import shared_task

from products.stamphog.backend.logic.digest_runs import (
    pending_audiences_by_team,
    post_team_digests,
    reclaim_stale_pending_runs,
)

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True)
def send_team_digests(team_id: int, audience_keys: list[str]) -> None:
    """Post every listed audience's digest for one team.

    No automatic retry wrapper: each group already handles its own failure paths — a Slack post
    failure unlinks that group's claimed PRs so the next daily run retries them, and a crashed
    worker is swept by ``reclaim_stale_pending_runs``. Layering Celery retries on top would re-post
    a digest Slack already accepted.
    """
    post_team_digests(team_id, audience_keys)


@shared_task(ignore_result=True)
def send_daily_digests() -> None:
    """Beat fan-out: one task per team that has merges nobody has been told about yet.

    Driven by the audiences themselves rather than by a table of configured channels, so an
    audience seen for the first time this morning needs no provisioning step to be routed.
    """
    # Reclaim first, so PRs stranded on a crashed worker's run rejoin today's digest.
    reclaim_stale_pending_runs()

    by_team = pending_audiences_by_team()
    for team_id, audience_keys in by_team.items():
        send_team_digests.delay(team_id=team_id, audience_keys=audience_keys)
    logger.info(
        "stamphog_daily_digests_enqueued",
        team_count=len(by_team),
        audience_count=sum(len(keys) for keys in by_team.values()),
    )
