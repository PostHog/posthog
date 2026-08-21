"""Celery tasks for the daily merged-PR Slack digest.

``send_daily_digests`` is the beat fan-out: once a day it enqueues one ``send_team_digests`` per
team that has unposted merges. That task fetches the team's routing once (see
logic/channel_resolution.py) and then works through its audiences, so a run costs one registry read
per connected repository and one Slack channel listing rather than one of each per audience.

Each audience claims its unposted merges, splits them by the destination each one routes to,
summarizes each group (LLM with a deterministic fallback), posts it, and links those PRs to the
run. A Slack failure leaves that group's PRs unlinked so the next day retries them.

Nothing about routing is stored. A run records where it posted, which is a historical fact; where
the *next* run posts is decided from the repositories again.
"""

from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime, timedelta
from uuid import UUID

from django.db import InterfaceError, OperationalError, router, transaction
from django.utils import timezone

import structlog
from celery import shared_task

from products.stamphog.backend.facade.enums import DigestRunStatus
from products.stamphog.backend.logic.channel_resolution import (
    Destination,
    RoutingContext,
    RoutingUnavailable,
    build_routing_context,
    resolve_destination,
)
from products.stamphog.backend.logic.digest import pr_key, summarize_merged_prs
from products.stamphog.backend.logic.slack_digest import post_digest
from products.stamphog.backend.models import DigestRun, PullRequestAudience

logger = structlog.get_logger(__name__)

# Only PRs merged within this window are eligible, so an audience that starts routing somewhere
# after a backlog piled up doesn't dump ancient history into its first digest.
DIGEST_LOOKBACK_DAYS = 7

# Per-audience claim ceiling. An unbounded claim grows the LLM prompt, the stored summary, and the
# Slack payload with the burst size — and if either rejects the oversized payload, the failure
# handler unlinks the same PRs and every later run retries the identical oversized batch forever.
# Capping the claim drains a backlog across daily runs instead; each digest renders at most
# MAX_DIGEST_PRS of whatever its own destination group received.
DIGEST_MAX_PRS_PER_RUN = 100

# A PENDING DigestRun older than this had its worker die between claiming its PRs and posting (or
# failing) — reclaim it so those PRs re-enter the next digest instead of being stranded forever.
STALE_PENDING_RUN_MINUTES = 60

# The proof-of-post write is the dedup proof (see _post_group); a transient DB blip there converts
# a Slack-accepted digest into a duplicate re-send, so retry the write a few times first.
_PROOF_OF_POST_WRITE_ATTEMPTS = 3
_PROOF_OF_POST_WRITE_RETRY_SECONDS = 0.2


def _previous_run_slot(now: datetime) -> datetime:
    """The weekday 07:00 UTC digest slot before the current one.

    Monday's run reaches back to Friday's slot (weekends have no slot), so an audience's first
    digest never covers more than one cadence period.
    """
    slot = now.replace(hour=7, minute=0, second=0, microsecond=0)
    if slot > now:
        slot -= timedelta(days=1)
    slot -= timedelta(days=1)
    while slot.weekday() >= 5:
        slot -= timedelta(days=1)
    return slot


def _claim_floor(team_id: int, audience_key: str, now: datetime) -> datetime:
    """How far back this audience's claim reaches.

    An audience that has never posted takes only the natural cadence window — back to the previous
    weekday slot, exactly what it would have received had it been routable one run earlier. Without
    that floor, a team whose channel was only just declared would flood its first digest with the
    whole backlog.

    An established audience keeps the wide DIGEST_LOOKBACK_DAYS floor instead: linkage already
    prevents duplicates there, and the wide floor lets PRs from a failed or missed run be picked up
    for a week before aging out.

    Already-linked audiences are untouched by this floor. Once digest_run is set the claim query
    excludes them, and the reclaim and finalize paths key off digest_run_id rather than merged_at,
    so a posted PR older than the window still finalizes instead of being re-sent.
    """
    if DigestRun.objects.for_team(team_id).filter(audience_key=audience_key).exists():
        return now - timedelta(days=DIGEST_LOOKBACK_DAYS)
    return _previous_run_slot(now)


def _finalize_empty_run(team_id: int, run_id: str, audience_ids: list[UUID], summary_dict: dict) -> None:
    """The model kept nothing, so release the claim rather than consume it.

    The summarizer reads contributor-authored text, so a single injected or degenerate answer must
    not be the last word on a whole batch. Genuinely irrelevant PRs are re-evaluated tomorrow and
    age out of the claim floor on their own.
    """
    with transaction.atomic(using=router.db_for_write(DigestRun)):
        DigestRun.objects.for_team(team_id).filter(id=run_id).update(
            status=DigestRunStatus.COMPLETED, summary=summary_dict, posted_at=timezone.now()
        )
        PullRequestAudience.objects.for_team(team_id).filter(id__in=audience_ids).update(digest_run=None)


def _write_proof_of_post(team_id: int, run_id: str, message_ts: str | None, pr_count: int, summary_dict: dict) -> None:
    """Record that Slack accepted the message, before the fuller COMPLETED write.

    If the worker dies in between, the reclaim sweeper sees a non-empty slack_message_ts, knows this
    run already posted, and finalizes it instead of unlinking and re-sending its PRs to Slack. The
    metadata rides along so a reclaim-finalized run keeps its real pr_count and summary, not zeros.

    This single write is the only thing standing between a Slack-accepted message and a duplicate
    re-send, so a transient DB blip here (not a Slack failure) must not be taken at face value.
    """
    for attempt in range(_PROOF_OF_POST_WRITE_ATTEMPTS):
        try:
            DigestRun.objects.for_team(team_id).filter(id=run_id).update(
                slack_message_ts=message_ts or "posted", pr_count=pr_count, summary=summary_dict
            )
            return
        except (OperationalError, InterfaceError):
            # Only the transient connectivity classes: retrying an IntegrityError/ProgrammingError
            # burns the attempts on a deterministic failure and delays the real traceback.
            if attempt == _PROOF_OF_POST_WRITE_ATTEMPTS - 1:
                raise
            time.sleep(_PROOF_OF_POST_WRITE_RETRY_SECONDS)


def _post_group(
    team_id: int,
    run: DigestRun,
    destination: Destination,
    audiences: list[PullRequestAudience],
    slack_integration_id: int,
) -> None:
    """Summarize one destination's share of a claim and post it. Runs outside the claim transaction."""
    prs = [audience.pull_request for audience in audiences]
    audience_ids = [audience.id for audience in audiences]
    summary = summarize_merged_prs(prs, audiences)
    write_db = router.db_for_write(PullRequestAudience)

    if not summary.prs:
        logger.info("stamphog_digest_nothing_relevant", run_id=str(run.id), pr_count=len(prs))
        _finalize_empty_run(team_id, str(run.id), audience_ids, summary.to_dict())
        return

    try:
        message_ts = post_digest(team_id, slack_integration_id, destination, summary)
    except Exception as e:
        # Unlink the claimed audiences (digest_run back to NULL) so the next run retries them — the
        # retry query filters digest_run__isnull=True, so leaving them linked to a FAILED run would
        # hide them forever. Only for THIS group: another destination's rows are separate.
        logger.exception("stamphog_digest_post_failed", run_id=str(run.id), error=str(e))
        with transaction.atomic(using=write_db):
            DigestRun.objects.for_team(team_id).filter(id=run.id).update(
                status=DigestRunStatus.FAILED, summary=summary.to_dict(), error=str(e)
            )
            PullRequestAudience.objects.for_team(team_id).filter(id__in=audience_ids).update(digest_run=None)
        return

    _write_proof_of_post(team_id, str(run.id), message_ts, len(prs), summary.to_dict())

    with transaction.atomic(using=write_db):
        DigestRun.objects.for_team(team_id).filter(id=run.id).update(
            status=DigestRunStatus.COMPLETED,
            pr_count=len(prs),
            summary=summary.to_dict(),
            slack_message_ts=message_ts or "",
            posted_at=timezone.now(),
        )
        # Release the PRs the digest kept but had no room for, so the next run posts them. Every
        # other claimed PR stays linked: the model saw it and left it out, which is a decision and
        # not a backlog. Runs after the proof-of-post write, so a crash here loses a day for those
        # PRs rather than re-sending the whole digest.
        if summary.deferred_prs:
            deferred = set(summary.deferred_prs)
            PullRequestAudience.objects.for_team(team_id).filter(
                id__in=[
                    a.id
                    for a in audiences
                    if pr_key(a.pull_request.repo_config.repository, a.pull_request.pr_number) in deferred
                ]
            ).update(digest_run=None)

    logger.info(
        "stamphog_digest_posted",
        run_id=str(run.id),
        audience_key=run.audience_key,
        slack_channel_id=destination.channel_id,
        pr_count=len(prs),
    )


def _claim_and_partition(
    team_id: int, audience_key: str, context: RoutingContext
) -> list[tuple[DigestRun, Destination, list[PullRequestAudience]]]:
    """Lock this audience's unposted merges, split them by destination, and open one run per group.

    Claiming before posting is what stops two concurrent runs for one audience from both posting.
    ``select_for_update`` locks the unlinked rows, the runs are created, and the PRs are linked to
    them — all committed before any Slack call. A second worker then blocks on the lock, re-reads,
    finds nothing unlinked, and returns without posting. ``of=("self",)`` keeps the lock off the
    joined pull_request and repo_config rows.

    Splitting happens here rather than at capture time because the destination is derived from
    config that can change between the merge and the digest. A row whose merges route nowhere is
    left unlinked, so a declaration added later picks it up instead of losing it.

    Every atomic block is bound to the model's routed DB (stamphog_db_writer when the product DB is
    configured, else default). A bare atomic() opens on the default connection, so the
    select_for_update lock and the writes would run outside any transaction on the product DB.
    """
    now = timezone.now()
    claim_floor = _claim_floor(team_id, audience_key, now)
    write_db = router.db_for_write(PullRequestAudience)
    opened: list[tuple[DigestRun, Destination, list[PullRequestAudience]]] = []

    with transaction.atomic(using=write_db):
        audiences = list(
            PullRequestAudience.objects.for_team(team_id)
            .filter(
                audience_key=audience_key,
                digest_run__isnull=True,
                pull_request__merged_at__gte=claim_floor,
            )
            .select_for_update(of=("self",))
            .select_related("pull_request", "pull_request__repo_config")
            .order_by("pull_request__merged_at")[:DIGEST_MAX_PRS_PER_RUN]
        )
        if not audiences:
            return []

        by_destination: dict[Destination, list[PullRequestAudience]] = defaultdict(list)
        for audience in audiences:
            destination = resolve_destination(context, audience_key, audience.pull_request.repo_config.repository)
            if destination is not None:
                by_destination[destination].append(audience)

        if not by_destination:
            logger.info("stamphog_digest_no_destination", team_id=team_id, audience_key=audience_key)
            return []

        for destination, group in by_destination.items():
            run = DigestRun.objects.for_team(team_id).create(
                team_id=team_id,
                audience_key=audience_key,
                slack_channel_id=destination.channel_id,
                slack_channel_name=destination.channel_name,
                resolution_source=destination.source,
                status=DigestRunStatus.PENDING,
            )
            PullRequestAudience.objects.for_team(team_id).filter(id__in=[a.id for a in group]).update(digest_run=run)
            opened.append((run, destination, group))

    return opened


@shared_task(ignore_result=True)
def send_team_digests(team_id: int, audience_keys: list[str]) -> None:
    """Post every listed audience's digest for one team.

    No automatic retry wrapper: each group already handles its own failure paths — a Slack post
    failure unlinks that group's claimed PRs so the next daily run retries them, and a crashed
    worker is swept by ``_reclaim_stale_pending_runs``. Layering Celery retries on top would
    re-post a digest Slack already accepted.

    One audience failing must not take the rest of the team's morning with it, so each is wrapped.
    A routing failure is different and stops everything: routing is derived rather than stored, so
    a half-read registry does not degrade, it silently reroutes.
    """
    try:
        context = build_routing_context(team_id)
    except RoutingUnavailable as e:
        logger.warning("stamphog_digest_routing_unavailable", team_id=team_id, error=str(e))
        return
    if context is None:
        return

    for audience_key in audience_keys:
        try:
            for run, destination, group in _claim_and_partition(team_id, audience_key, context):
                _post_group(team_id, run, destination, group, context.slack_integration_id)
        except Exception:
            logger.exception("stamphog_digest_audience_failed", team_id=team_id, audience_key=audience_key)


def _reclaim_stale_pending_runs() -> None:
    """Fail stale PENDING DigestRuns and unlink their PRs so the next digest retries them.

    A run claims its PRs before posting to Slack. If that worker dies before the post succeeds or
    its failure handler unlinks, the PRs stay attached to a PENDING run forever — the digest query
    filters ``digest_run__isnull=True``, so they'd never be sent. A run still PENDING well past when
    any post should have finished is such a casualty; reclaim it. unscoped(): cross-team beat sweep,
    re-scoped per run's own team for the writes.
    """
    cutoff = timezone.now() - timedelta(minutes=STALE_PENDING_RUN_MINUTES)
    stale = DigestRun.objects.unscoped().filter(status=DigestRunStatus.PENDING, created_at__lt=cutoff)
    write_db = router.db_for_write(DigestRun)
    reclaimed = finalized = 0
    for run_id, team_id in stale.values_list("id", "team_id").iterator():
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
            if current:
                # It already posted to Slack (the COMPLETED write just never landed). Finalize the
                # run and KEEP its PRs linked, so the next digest doesn't re-send PRs Slack already
                # received. pr_count/summary were persisted with the proof-of-post; only the
                # terminal bits are left.
                DigestRun.objects.for_team(team_id).filter(id=run_id).update(
                    status=DigestRunStatus.COMPLETED, posted_at=timezone.now()
                )
                finalized += 1
            else:
                # Never posted — unlink the audiences so the next run retries them.
                PullRequestAudience.objects.for_team(team_id).filter(digest_run_id=run_id).update(digest_run=None)
                DigestRun.objects.for_team(team_id).filter(id=run_id).update(
                    status=DigestRunStatus.FAILED, error="Reclaimed: worker lost before the digest posted."
                )
                reclaimed += 1
    if reclaimed or finalized:
        logger.info("stamphog_digest_reclaimed_stale_pending_runs", reclaimed=reclaimed, finalized=finalized)


@shared_task(ignore_result=True)
def send_daily_digests() -> None:
    """Beat fan-out: one task per team that has merges nobody has been told about yet.

    Driven by the audiences themselves rather than by a table of configured channels, so an
    audience seen for the first time this morning needs no provisioning step to be routed.

    unscoped(): cross-team beat fan-out reads every team's pending audiences; each enqueued task is
    team-scoped via for_team.
    """
    # Reclaim first, so PRs stranded on a crashed worker's run rejoin today's digest.
    _reclaim_stale_pending_runs()

    since = timezone.now() - timedelta(days=DIGEST_LOOKBACK_DAYS)
    pending = (
        PullRequestAudience.objects.unscoped()
        .filter(digest_run__isnull=True, pull_request__merged_at__gte=since)
        .values_list("team_id", "audience_key")
        .distinct()
    )
    by_team: dict[int, list[str]] = defaultdict(list)
    for team_id, audience_key in pending:
        by_team[team_id].append(audience_key)

    for team_id, audience_keys in by_team.items():
        send_team_digests.delay(team_id=team_id, audience_keys=sorted(audience_keys))
    logger.info(
        "stamphog_daily_digests_enqueued",
        team_count=len(by_team),
        audience_count=sum(len(keys) for keys in by_team.values()),
    )
