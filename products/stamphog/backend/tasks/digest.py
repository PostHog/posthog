"""Celery tasks for the daily merged-PR Slack digest.

``send_daily_digests`` is the beat fan-out: once a day it enqueues one ``send_digest_for_channel``
per enabled channel, then discovers audiences that have merged PRs but no channel yet and enqueues
``provision_and_send_digest`` for each — that's what turns an unannounced GitHub team into a live
Slack channel the first time one of its PRs merges. Each channel task gathers that audience's
unposted merged PRs, summarizes them (LLM with a deterministic fallback), posts to Slack, and links
the PRs to the run. A Slack failure leaves the PRs unlinked so the next day retries them.
"""

from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

import structlog
from celery import shared_task

from products.stamphog.backend.facade.enums import DigestRunStatus
from products.stamphog.backend.logic.channel_resolution import auto_provision_channel
from products.stamphog.backend.logic.digest import summarize_merged_prs
from products.stamphog.backend.logic.slack_digest import post_digest
from products.stamphog.backend.models import DigestChannel, DigestRun, MergedPullRequest

logger = structlog.get_logger(__name__)

# Only PRs merged within this window are eligible, so a channel enabled after a backlog piled up
# doesn't dump ancient history into its first digest.
DIGEST_LOOKBACK_DAYS = 7


@shared_task(ignore_result=True)
def send_digest_for_channel(digest_channel_id: str, team_id: int) -> None:
    """Build and post the digest for one channel, then link the included PRs to the run."""
    channel = DigestChannel.objects.for_team(team_id).filter(id=digest_channel_id).first()
    if channel is None or not channel.enabled:
        logger.info("stamphog_digest_channel_missing_or_disabled", digest_channel_id=digest_channel_id)
        return

    since = timezone.now() - timedelta(days=DIGEST_LOOKBACK_DAYS)
    prs = list(
        MergedPullRequest.objects.for_team(team_id)
        .filter(audience_key=channel.audience_key, digest_run__isnull=True, merged_at__gte=since)
        .select_related("repo_config")
        .order_by("merged_at")
    )
    if not prs:
        logger.info("stamphog_digest_no_prs", audience_key=channel.audience_key, team_id=team_id)
        return

    run = DigestRun.objects.for_team(team_id).create(
        team_id=team_id,
        digest_channel=channel,
        status=DigestRunStatus.PENDING,
    )

    summary = summarize_merged_prs(prs)
    try:
        message_ts = post_digest(team_id, channel, summary)
    except Exception as e:
        # PRs stay unlinked (digest_run is NULL) so tomorrow's run retries them.
        logger.exception("stamphog_digest_post_failed", digest_channel_id=digest_channel_id, error=str(e))
        DigestRun.objects.for_team(team_id).filter(id=run.id).update(
            status=DigestRunStatus.FAILED, summary=summary.to_dict(), error=str(e)
        )
        return

    now = timezone.now()
    with transaction.atomic():
        DigestRun.objects.for_team(team_id).filter(id=run.id).update(
            status=DigestRunStatus.COMPLETED,
            pr_count=len(prs),
            summary=summary.to_dict(),
            slack_message_ts=message_ts or "",
            posted_at=now,
        )
        MergedPullRequest.objects.for_team(team_id).filter(id__in=[pr.id for pr in prs]).update(digest_run=run)
        DigestChannel.objects.for_team(team_id).filter(id=channel.id).update(last_digest_at=now)

    logger.info("stamphog_digest_posted", digest_channel_id=digest_channel_id, pr_count=len(prs), run_id=str(run.id))


@shared_task(ignore_result=True)
def provision_and_send_digest(team_id: int, audience_key: str) -> None:
    """Auto-provision a Slack channel for a newly-seen audience, then send its first digest.

    A no-op when ``auto_provision_channel`` finds no Slack name match (see
    logic/channel_resolution.py) — the audience's merged PRs just wait for a human to create a
    channel manually.
    """
    channel = auto_provision_channel(team_id, audience_key)
    if channel is None:
        return
    send_digest_for_channel(digest_channel_id=str(channel.id), team_id=team_id)


@shared_task(ignore_result=True)
def send_daily_digests() -> None:
    """Beat fan-out: enqueue one per-channel digest task for every enabled channel, then discover
    and provision channels for any audience that doesn't have one yet.

    unscoped(): cross-team beat fan-out reads every team's enabled channels; each enqueued task is
    team-scoped via for_team.
    """
    channels = DigestChannel.objects.unscoped().filter(enabled=True).values_list("id", "team_id")
    count = 0
    for channel_id, team_id in channels.iterator():
        send_digest_for_channel.delay(digest_channel_id=str(channel_id), team_id=team_id)
        count += 1
    logger.info("stamphog_daily_digests_enqueued", channel_count=count)

    since = timezone.now() - timedelta(days=DIGEST_LOOKBACK_DAYS)
    # unscoped(): cross-team beat fan-out discovers every team's unprovisioned audiences in one
    # pass; provision_and_send_digest re-scopes to (team_id, audience_key) via for_team internally.
    candidate_audiences = (
        MergedPullRequest.objects.unscoped()
        .filter(digest_run__isnull=True, merged_at__gte=since)
        .exclude(audience_key__startswith="repo:")
        .values_list("team_id", "audience_key")
        .distinct()
    )
    # unscoped(): an existing row — including one a human disabled — must suppress
    # auto-provisioning regardless of team, so the exclusion set also needs a cross-team read.
    already_has_channel = set(DigestChannel.objects.unscoped().values_list("team_id", "audience_key"))

    provisioned_count = 0
    for team_id, audience_key in candidate_audiences:
        if (team_id, audience_key) in already_has_channel:
            continue
        provision_and_send_digest.delay(team_id=team_id, audience_key=audience_key)
        provisioned_count += 1
    logger.info("stamphog_daily_digests_provisioning_enqueued", audience_count=provisioned_count)
