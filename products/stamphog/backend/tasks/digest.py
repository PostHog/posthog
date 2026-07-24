"""Celery tasks for the daily merged-PR Slack digest.

``send_daily_digests`` is the beat fan-out: once a day it enqueues one ``send_digest_for_channel``
per enabled channel, then discovers audiences that have merged PRs but no channel yet and enqueues
``provision_and_send_digest`` for each — that's what turns an unannounced GitHub team into a live
Slack channel the first time one of its PRs merges. Each channel task gathers that audience's
unposted merged PRs, summarizes them (LLM with a deterministic fallback), posts to Slack, and links
the PRs to the run. A Slack failure leaves the PRs unlinked so the next day retries them.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta

from django.db import InterfaceError, OperationalError, router, transaction
from django.utils import timezone

import structlog
from celery import shared_task

from products.stamphog.backend.facade.enums import DigestRunStatus
from products.stamphog.backend.logic.channel_resolution import auto_provision_channel
from products.stamphog.backend.logic.digest import summarize_merged_prs
from products.stamphog.backend.logic.slack_digest import post_digest
from products.stamphog.backend.models import DigestChannel, DigestRun, PullRequest

logger = structlog.get_logger(__name__)

# Only PRs merged within this window are eligible, so a channel enabled after a backlog piled up
# doesn't dump ancient history into its first digest.
DIGEST_LOOKBACK_DAYS = 7

# Per-run claim ceiling. An unbounded claim grows the LLM prompt, the stored summary, and the Slack
# payload with the burst size — and if either rejects the oversized payload, the failure handler
# unlinks the same PRs and every later run retries the identical oversized batch forever. Capping the
# claim drains a backlog across daily runs instead; Slack rendering caps at 40 sections regardless.
DIGEST_MAX_PRS_PER_RUN = 100

# A PENDING DigestRun older than this had its worker die between claiming its PRs and posting (or
# failing) — reclaim it so those PRs re-enter the next digest instead of being stranded forever.
STALE_PENDING_RUN_MINUTES = 60

# The proof-of-post write is the dedup proof (see send_digest_for_channel); a transient DB blip there
# converts a Slack-accepted digest into a duplicate re-send, so retry the write a few times first.
_PROOF_OF_POST_WRITE_ATTEMPTS = 3
_PROOF_OF_POST_WRITE_RETRY_SECONDS = 0.2


def _previous_run_slot(now: datetime) -> datetime:
    """The weekday 07:00 UTC digest slot before the current one.

    Monday's run reaches back to Friday's slot (weekends have no slot), so a channel's first
    digest never covers more than one cadence period.
    """
    slot = now.replace(hour=7, minute=0, second=0, microsecond=0)
    if slot > now:
        slot -= timedelta(days=1)
    slot -= timedelta(days=1)
    while slot.weekday() >= 5:
        slot -= timedelta(days=1)
    return slot


@shared_task(ignore_result=True)
def send_digest_for_channel(digest_channel_id: str, team_id: int) -> None:
    """Build and post the digest for one channel, then link the included PRs to the run.

    No automatic retry wrapper: the body already handles its own failure paths — a Slack post
    failure unlinks the claimed PRs so the next daily run retries them, and a crashed worker is
    swept by ``_reclaim_stale_pending_runs``. Layering Celery retries on top would re-post a digest
    Slack already accepted. Still a ``shared_task`` so ``send_daily_digests`` can ``.delay`` it, and
    ``provision_and_send_digest`` calls it synchronously (a task is a plain callable too).
    """
    # Writer pin: this gate decides an outward side effect (a Slack post). A channel disabled or
    # deleted just before the task runs may not have replicated to the product-DB reader yet, and a
    # stale enabled=True read here would post a digest the user opted out of.
    channel = (
        DigestChannel.objects.for_team(team_id)
        .using(router.db_for_write(DigestChannel))
        .filter(id=digest_channel_id)
        .first()
    )
    if channel is None or not channel.enabled:
        logger.info("stamphog_digest_channel_missing_or_disabled", digest_channel_id=digest_channel_id)
        return

    # Bound the claim by a merged_at floor: audience_key + digest_run__isnull=True marks a PR
    # digest-eligible-and-not-yet-posted, but without a floor a channel created (or re-enabled, or
    # auto-provisioned) long after merges started being captured would claim the whole backlog and
    # flood its first digest. A channel's FIRST digest covers only the natural cadence window — back
    # to the previous weekday slot, exactly what it would have received had it existed one run
    # earlier. An established channel keeps the wide DIGEST_LOOKBACK_DAYS floor instead: linkage
    # already prevents duplicates there, and the wide floor lets PRs from a failed or missed run be
    # picked up for a week before aging out.
    # Already-linked PRs are untouched by this floor: once digest_run is set this query excludes
    # them, and the reclaim/finalize paths key off digest_run_id (not merged_at), so a posted PR
    # older than the window still finalizes instead of being re-sent.
    #
    # Claim the candidate PRs before posting: two concurrent runs for the same channel would
    # otherwise both read the same unlinked PRs and both post to Slack. select_for_update locks
    # the unlinked rows, the run is created, and the PRs are linked to it — all committed before
    # the Slack post. A second worker then blocks on the lock, re-reads, finds nothing unlinked,
    # and returns without posting. of=("self",) keeps the lock off the joined repo_config rows.
    #
    # Bind every atomic block below to the model's routed DB (stamphog_db_writer when the product DB is
    # configured, else default) — a bare atomic() opens on the default connection, so the
    # select_for_update lock and writes would run outside any transaction on the product DB.
    now = timezone.now()
    if DigestRun.objects.for_team(team_id).filter(digest_channel=channel).exists():
        claim_floor = now - timedelta(days=DIGEST_LOOKBACK_DAYS)
    else:
        claim_floor = _previous_run_slot(now)
    write_db = router.db_for_write(PullRequest)
    with transaction.atomic(using=write_db):
        prs = list(
            PullRequest.objects.for_team(team_id)
            .filter(audience_key=channel.audience_key, digest_run__isnull=True, merged_at__gte=claim_floor)
            .select_for_update(of=("self",))
            .select_related("repo_config")
            .order_by("merged_at")[:DIGEST_MAX_PRS_PER_RUN]
        )
        if not prs:
            logger.info("stamphog_digest_no_prs", audience_key=channel.audience_key, team_id=team_id)
            return

        run = DigestRun.objects.for_team(team_id).create(
            team_id=team_id,
            digest_channel=channel,
            status=DigestRunStatus.PENDING,
        )
        PullRequest.objects.for_team(team_id).filter(id__in=[pr.id for pr in prs]).update(digest_run=run)

    summary = summarize_merged_prs(prs)
    try:
        message_ts = post_digest(team_id, channel, summary)
    except Exception as e:
        # Unlink the claimed PRs (digest_run back to NULL) so the next run retries them — the retry
        # query filters digest_run__isnull=True, so leaving them linked to a FAILED run would hide
        # them forever. Unlinking keeps "Slack failure -> PRs stay retryable" intact.
        logger.exception("stamphog_digest_post_failed", digest_channel_id=digest_channel_id, error=str(e))
        with transaction.atomic(using=write_db):
            DigestRun.objects.for_team(team_id).filter(id=run.id).update(
                status=DigestRunStatus.FAILED, summary=summary.to_dict(), error=str(e)
            )
            PullRequest.objects.for_team(team_id).filter(id__in=[pr.id for pr in prs]).update(digest_run=None)
        return

    # Proof-of-post, written immediately after Slack accepted the message and before the fuller COMPLETED
    # write below. If the worker dies in between, the reclaim sweeper sees a non-empty slack_message_ts,
    # knows this run already posted, and finalizes it instead of unlinking + re-sending its PRs to Slack.
    # The metadata rides along so a reclaim-finalized run keeps its real pr_count/summary, not zeros.
    # This single write is the only thing standing between a Slack-accepted message and a duplicate
    # re-send, so a transient DB blip here (not a Slack failure) must not be taken at face value: retry
    # it a few times before letting the exception propagate.
    for attempt in range(_PROOF_OF_POST_WRITE_ATTEMPTS):
        try:
            DigestRun.objects.for_team(team_id).filter(id=run.id).update(
                slack_message_ts=message_ts or "posted",
                pr_count=len(prs),
                summary=summary.to_dict(),
            )
            break
        except (OperationalError, InterfaceError):
            # Only the transient connectivity classes: retrying an IntegrityError/ProgrammingError
            # burns the attempts on a deterministic failure and delays the real traceback.
            if attempt == _PROOF_OF_POST_WRITE_ATTEMPTS - 1:
                raise
            time.sleep(_PROOF_OF_POST_WRITE_RETRY_SECONDS)

    now = timezone.now()
    with transaction.atomic(using=write_db):
        DigestRun.objects.for_team(team_id).filter(id=run.id).update(
            status=DigestRunStatus.COMPLETED,
            pr_count=len(prs),
            summary=summary.to_dict(),
            slack_message_ts=message_ts or "",
            posted_at=now,
        )
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


def _reclaim_stale_pending_runs() -> None:
    """Fail stale PENDING DigestRuns and unlink their PRs so the next digest retries them.

    ``send_digest_for_channel`` claims its PRs (links them to a PENDING run) before posting to Slack.
    If that worker dies before the post succeeds or its failure handler unlinks, the PRs stay attached
    to a PENDING run forever — the digest query filters ``digest_run__isnull=True``, so they'd never be
    sent. A run still PENDING well past when any post should have finished is such a casualty; reclaim
    it. unscoped(): cross-team beat sweep, re-scoped per run's own team for the writes.
    """
    cutoff = timezone.now() - timedelta(minutes=STALE_PENDING_RUN_MINUTES)
    stale = DigestRun.objects.unscoped().filter(status=DigestRunStatus.PENDING, created_at__lt=cutoff)
    # Bind the per-run atomic block to the model's routed DB (see send_digest_for_channel) so the
    # reclaim writes commit on the product DB rather than the default connection.
    write_db = router.db_for_write(DigestRun)
    reclaimed = finalized = 0
    for run_id, team_id, channel_id in stale.values_list("id", "team_id", "digest_channel_id").iterator():
        with transaction.atomic(using=write_db):
            # Lock and RE-READ inside the transaction: the iterator's snapshot is stale by the time
            # this branch runs, and a slow worker may have recorded slack_message_ts (or finished
            # outright) in between. Deciding from the old snapshot would unlink an already-posted
            # digest's PRs and re-send them on the next run.
            current = (
                DigestRun.objects.for_team(team_id)
                .select_for_update()
                .filter(id=run_id, status=DigestRunStatus.PENDING)
                .values_list("slack_message_ts", flat=True)
                .first()
            )
            if current is None:
                continue  # the worker finished (or another sweeper won) while we iterated
            slack_ts = current
            if slack_ts:
                # It already posted to Slack (the COMPLETED write just never landed). Finalize the run and
                # KEEP its PRs linked, so the next digest doesn't re-send PRs Slack already received.
                # pr_count/summary were persisted with the proof-of-post; only the terminal bits are left.
                now = timezone.now()
                DigestRun.objects.for_team(team_id).filter(id=run_id).update(
                    status=DigestRunStatus.COMPLETED, posted_at=now
                )
                DigestChannel.objects.for_team(team_id).filter(id=channel_id).update(last_digest_at=now)
                finalized += 1
            else:
                # Never posted — unlink the PRs so the next run retries them.
                PullRequest.objects.for_team(team_id).filter(digest_run_id=run_id).update(digest_run=None)
                DigestRun.objects.for_team(team_id).filter(id=run_id).update(
                    status=DigestRunStatus.FAILED, error="Reclaimed: worker lost before the digest posted."
                )
                reclaimed += 1
    if reclaimed or finalized:
        logger.info("stamphog_digest_reclaimed_stale_pending_runs", reclaimed=reclaimed, finalized=finalized)


@shared_task(ignore_result=True)
def send_daily_digests() -> None:
    """Beat fan-out: enqueue one per-channel digest task for every enabled channel, then discover
    and provision channels for any audience that doesn't have one yet.

    unscoped(): cross-team beat fan-out reads every team's enabled channels; each enqueued task is
    team-scoped via for_team.
    """
    # Reclaim first, so PRs stranded on a crashed worker's run rejoin today's digest.
    _reclaim_stale_pending_runs()

    channels = DigestChannel.objects.unscoped().filter(enabled=True).values_list("id", "team_id")
    count = 0
    for channel_id, team_id in channels.iterator():
        send_digest_for_channel.delay(digest_channel_id=str(channel_id), team_id=team_id)
        count += 1
    logger.info("stamphog_daily_digests_enqueued", channel_count=count)

    since = timezone.now() - timedelta(days=DIGEST_LOOKBACK_DAYS)
    # unscoped(): cross-team beat fan-out discovers every team's unprovisioned audiences in one
    # pass; provision_and_send_digest re-scopes to (team_id, audience_key) via for_team internally.
    # "repo:" audiences are included too now — a repo with a declared digest channel (policy.yml) resolves
    # them via logic/channel_resolution.py instead of a plain Slack name match.
    candidate_audiences = (
        PullRequest.objects.unscoped()
        .filter(digest_run__isnull=True, merged_at__gte=since)
        .exclude(audience_key="")
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
