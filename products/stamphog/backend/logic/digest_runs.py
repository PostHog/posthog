"""Claim merged PRs into digest runs, post them, and sweep the runs that died mid-flight.

One audience claims its unposted merges, splits them by the destination each one routes to (see
logic/channel_resolution.py), summarizes each group, posts it, and links those PRs to the run it
opened. A Slack failure leaves that group's PRs unlinked so the next day retries them.

Nothing about routing is stored. A run records where it posted, which is a historical fact; where
the *next* run posts is decided from the repositories again.
"""

from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime, timedelta

from django.db import InterfaceError, OperationalError, router, transaction
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen

from ..facade.enums import DigestRunStatus
from ..models import DigestRun, PullRequestAudience
from .channel_resolution import (
    Destination,
    RoutingContext,
    RoutingUnavailable,
    build_routing_context,
    resolve_destination,
)
from .digest import summarize_merged_prs
from .slack_digest import post_digest_details, post_digest_lead

logger = structlog.get_logger(__name__)

# Only PRs merged within this window are eligible, so an audience that starts routing somewhere
# after a backlog piled up doesn't dump ancient history into its first digest.
DIGEST_LOOKBACK_DAYS = 7

# Per-audience claim ceiling. An unbounded claim grows the LLM prompt, the stored summary, and the
# Slack payload with the burst size — and if either rejects the oversized payload, the failure
# handler unlinks the same PRs and every later run retries the identical oversized batch forever.
# Merges above the ceiling stay unclaimed rather than claimed and dropped, so the next run picks
# them up. This is the one place a merge can still wait for a later digest.
DIGEST_MAX_PRS_PER_RUN = 100

# A PENDING DigestRun older than this had its worker die between claiming its PRs and posting (or
# failing) — reclaim it so those PRs re-enter the next digest instead of being stranded forever.
STALE_PENDING_RUN_MINUTES = 60

# The proof-of-post write is the dedup proof (see _post_group); a transient DB blip there converts
# a Slack-accepted digest into a duplicate re-send, so retry the write a few times first.
_PROOF_OF_POST_WRITE_ATTEMPTS = 3
_PROOF_OF_POST_WRITE_RETRY_SECONDS = 0.2


@frozen
class _ClaimedGroup:
    """One destination's share of a claim, and the run opened to post it."""

    run: DigestRun
    destination: Destination
    audiences: list[PullRequestAudience]


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


def _established_audiences(team_id: int, audience_keys: list[str]) -> set[str]:
    """Which of these audiences have posted before, in one query rather than one per audience."""
    return set(
        DigestRun.objects.for_team(team_id)
        .filter(audience_key__in=audience_keys)
        .values_list("audience_key", flat=True)
        .distinct()
    )


def _claim_floor(audience_key: str, now: datetime, established: set[str]) -> datetime:
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
    if audience_key in established:
        return now - timedelta(days=DIGEST_LOOKBACK_DAYS)
    return _previous_run_slot(now)


def _finalize_empty_run(team_id: int, run_id: str, pr_count: int, summary_dict: dict) -> None:
    """The model kept nothing, so record the decision and leave the claim consumed.

    An empty answer is a judgment like any other, not a failure worth retrying. Releasing the claim
    put the same merges in front of the same prompt the next morning, and the same text produced
    the same answer, so a batch grew instead of draining and merges reached a channel days after
    they landed.

    The prompt injection this once guarded against is handled where it starts instead. The author's
    body never reaches the prompt, and the values that do cannot close their own tag and continue as
    instructions (see logic/digest.py), so one PR's text can no longer answer for the batch around
    it.
    """
    DigestRun.objects.for_team(team_id).filter(id=run_id).update(
        status=DigestRunStatus.COMPLETED,
        pr_count=pr_count,
        summary=summary_dict,
        posted_at=timezone.now(),
    )


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


def _post_group(team_id: int, group: _ClaimedGroup) -> None:
    """Summarize one destination's share of a claim and post it. Runs outside the claim transaction."""
    run, destination, audiences = group.run, group.destination, group.audiences
    prs = [audience.pull_request for audience in audiences]
    audience_ids = [audience.id for audience in audiences]
    summary = summarize_merged_prs(prs, audiences)
    write_db = router.db_for_write(PullRequestAudience)

    if not summary.prs:
        logger.info("stamphog_digest_nothing_relevant", run_id=str(run.id), pr_count=len(prs))
        _finalize_empty_run(team_id, str(run.id), len(prs), summary.to_dict())
        return

    try:
        message_ts = post_digest_lead(team_id, destination, summary)
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

    # The lead is on record now, so the thread reply is safe to attempt. It never raises, and a
    # worker that dies inside it leaves a run the sweeper finalizes rather than one it re-sends.
    post_digest_details(team_id, destination, summary, message_ts)

    # Every claimed merge stays consumed, including the ones the model left out and the ones the
    # rail cut. Each of those got a decision, and a run that hands them back re-summarizes the same
    # merges tomorrow rather than draining them.
    DigestRun.objects.for_team(team_id).filter(id=run.id).update(
        status=DigestRunStatus.COMPLETED,
        pr_count=len(prs),
        summary=summary.to_dict(),
        slack_message_ts=message_ts or "",
        posted_at=timezone.now(),
    )

    logger.info(
        "stamphog_digest_posted",
        run_id=str(run.id),
        audience_key=run.audience_key,
        slack_channel_id=destination.channel_id,
        pr_count=len(prs),
    )


def _claim_and_partition(
    team_id: int, audience_key: str, claim_floor: datetime, context: RoutingContext
) -> list[_ClaimedGroup]:
    """Lock this audience's unposted merges, split them by destination, and open one run per group.

    Claiming before posting is what stops two concurrent runs for one audience from both posting.
    ``select_for_update`` locks the unlinked rows, the runs are created, and the PRs are linked to
    them — all committed before any Slack call. A second worker then blocks on the lock, re-reads,
    finds nothing unlinked, and returns without posting. ``of=("self",)`` keeps the lock off the
    joined pull_request and repo_config rows.

    Splitting happens here rather than at capture time because the destination is derived from
    config that can change between the merge and the digest. A row whose merges route nowhere is
    left unlinked, so a declaration added later picks it up instead of losing it.

    A destination depends only on the audience and the repository a merge came from. Every
    repository therefore resolves before the query, not once per claimed row. This lets the claim
    exclude unroutable repositories in SQL, so the cap applies to rows this run can post.

    A cap applied first selects the same rows every day, if an audience's oldest merges are all
    unroutable. The routable merges behind them are never reached, and they age out unposted.

    The claim reads the repo's digest toggle for the same reason. Capture decides only what gets
    stamped, so a repo switched off after its merges landed would still post them. A toggle read at
    claim time stops the next digest, including merges already captured. Switching the toggle back
    on returns whatever is still inside the claim floor.

    Every atomic block is bound to the model's routed DB (stamphog_db_writer when the product DB is
    configured, else default). A bare atomic() opens on the default connection, so the
    select_for_update lock and the writes would run outside any transaction on the product DB.
    """
    write_db = router.db_for_write(PullRequestAudience)
    opened: list[_ClaimedGroup] = []

    destination_by_repo = {
        repository: destination
        for repository in context.registry_by_repo
        if (destination := resolve_destination(context, audience_key, repository)) is not None
    }
    if not destination_by_repo:
        logger.info("stamphog_digest_no_destination", team_id=team_id, audience_key=audience_key)
        return []

    with transaction.atomic(using=write_db):
        audiences = list(
            PullRequestAudience.objects.for_team(team_id)
            .filter(
                audience_key=audience_key,
                digest_run__isnull=True,
                pull_request__repo_config__digest_enabled=True,
                pull_request__repo_config__repository__in=destination_by_repo,
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
            by_destination[destination_by_repo[audience.pull_request.repo_config.repository]].append(audience)

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
            opened.append(_ClaimedGroup(run=run, destination=destination, audiences=group))

    return opened


def _has_claimable_merges(team_id: int, audience_keys: list[str], floor: datetime) -> bool:
    return (
        PullRequestAudience.objects.for_team(team_id)
        .filter(
            audience_key__in=audience_keys,
            digest_run__isnull=True,
            pull_request__repo_config__digest_enabled=True,
            pull_request__merged_at__gte=floor,
        )
        .exists()
    )


def post_team_digests(team_id: int, audience_keys: list[str]) -> None:
    """Post every listed audience's digest for one team.

    One audience failing must not take the rest of the team's morning with it, so each is wrapped.
    A routing failure is different and stops everything: routing is derived rather than stored, so
    a half-read registry does not degrade, it silently reroutes.
    """
    now = timezone.now()
    established = _established_audiences(team_id, audience_keys)
    floors = {audience_key: _claim_floor(audience_key, now, established) for audience_key in audience_keys}

    # A routing context costs one config read per connected repository, plus a Slack channel
    # listing. Check that there is something to route before paying for it. An audience whose merges
    # route nowhere stays unclaimed on purpose, and it re-enqueues its team every day until those
    # merges age out. "Enqueued but nothing claimable" is therefore the steady state for a team with
    # an ownership gap, not a rare case. The widest floor over-approximates: nothing claimable there
    # means nothing claimable at any narrower per-audience floor.
    if not _has_claimable_merges(team_id, audience_keys, min(floors.values())):
        return

    try:
        context = build_routing_context(team_id)
    except RoutingUnavailable as e:
        logger.warning("stamphog_digest_routing_unavailable", team_id=team_id, error=str(e))
        return
    if context is None:
        return

    for audience_key in audience_keys:
        try:
            for group in _claim_and_partition(team_id, audience_key, floors[audience_key], context):
                _post_group(team_id, group)
        except Exception:
            logger.exception("stamphog_digest_audience_failed", team_id=team_id, audience_key=audience_key)


def reclaim_stale_pending_runs() -> None:
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


def pending_audiences_by_team() -> dict[int, list[str]]:
    """Every audience with merges nobody has been told about yet, grouped by team.

    Repos with the digest switched off are excluded, so a team whose only pending merges came from
    one of them is never enqueued. The claim applies the same filter, which is the gate that counts:
    the toggle can move between this query and the claim.

    unscoped(): cross-team beat sweep; each team's work is re-scoped via for_team downstream.
    """
    since = timezone.now() - timedelta(days=DIGEST_LOOKBACK_DAYS)
    pending = (
        PullRequestAudience.objects.unscoped()
        .filter(
            digest_run__isnull=True,
            pull_request__repo_config__digest_enabled=True,
            pull_request__merged_at__gte=since,
        )
        .values_list("team_id", "audience_key")
        .distinct()
    )
    by_team: dict[int, list[str]] = defaultdict(list)
    for team_id, audience_key in pending:
        by_team[team_id].append(audience_key)
    return {team_id: sorted(audience_keys) for team_id, audience_keys in by_team.items()}
