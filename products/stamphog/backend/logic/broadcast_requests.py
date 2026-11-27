"""Requests for a person to review a pull request that stamphog did not approve.

A request starts with a manual review request that sets ``allow_broadcast``, or with a pull request link
that a person posts in the repository's Broadcast channel. It follows the pull request until a person or
stamphog approves it, or the pull request merges or closes. ``refresh`` decides
the request's state from the database and GitHub, then posts or edits its Slack card, so every
change to a request goes through one idempotent path.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID

from django.db import IntegrityError, router, transaction
from django.db.models import Q
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen
from posthog.egress.limiter.policies import Priority
from posthog.models import User
from posthog.ph_client import ph_background_capture, ph_scoped_capture

from ..facade.enums import (
    ACTIVE_BROADCAST_REQUEST_STATUSES,
    BroadcastRequestDeliveryKind,
    BroadcastRequestSource,
    BroadcastRequestStatus,
    ReviewRunStatus,
    ReviewVerdict,
)
from ..models import BroadcastRequest, BroadcastRequestDelivery, BroadcastRequestParticipant, PullRequest, ReviewRun
from .broadcast_request_slack import (
    BroadcastRequestCard,
    BroadcastRequestSlackError,
    CardLooker,
    LookClick,
    card_permalink,
    card_workspace,
    find_card_integration,
    ping_lookers,
    post_card,
    update_card,
)
from .github_client import StamphogGitHubClient, expected_app_bot_login
from .merge_approval import retained_at_head
from .rerun_evidence import is_person
from .reviewer import parse_reviewer_output
from .scrubbing import neutralize_active_markdown, scrub_credentials

logger = structlog.get_logger(__name__)

REQUEST_CREATED_EVENT = "stamphog_broadcast_request_created"
CARD_POSTED_EVENT = "stamphog_broadcast_card_posted"
LOOK_CLICKED_EVENT = "stamphog_broadcast_look_clicked"
STATUS_CHANGED_EVENT = "stamphog_broadcast_request_status_changed"

CARD_COUNT_WINDOW = timedelta(days=7)

# The outcomes that send a pull request to people. An ERROR is here because nothing reviews that head again on its own.
# A WAIT is absent because stamphog reviews the head again.
_NOT_APPROVED_VERDICTS = frozenset({ReviewVerdict.REFUSED, ReviewVerdict.ESCALATE, ReviewVerdict.ERROR})


@frozen
class BroadcastRequestAsk:
    """Who asked for people to review a pull request, and from where."""

    requested_by_user_id: int | None
    requested_via: BroadcastRequestSource
    requester_slack_user_id: str = ""
    requester_github_login: str = ""
    note: str = ""


@frozen
class OpenedBroadcastRequest:
    """The active request for a pull request, and whether this ask created it."""

    request: BroadcastRequest
    created: bool


def status_for_run(run: ReviewRun) -> BroadcastRequestStatus:
    """What a request waits for while ``run`` is stamphog's newest review of the request's head.

    Only a verdict that GitHub already has counts, so a run that has not posted one leaves the request
    PENDING. ``stamphog_status_at_head`` never passes a silent run that withheld its verdict.
    """
    if run.status == ReviewRunStatus.FAILED:
        return BroadcastRequestStatus.OPEN if run.may_publish() else BroadcastRequestStatus.PENDING
    if run.status not in (ReviewRunStatus.COMPLETED, ReviewRunStatus.GATED) or run.verdict_posted_at is None:
        return BroadcastRequestStatus.PENDING
    # A gate denial is stored as a GATED WAIT, and stamphog does not review that head again.
    if run.status == ReviewRunStatus.GATED:
        return BroadcastRequestStatus.OPEN
    if run.verdict == ReviewVerdict.APPROVED and run.approval_dismissed_at is None:
        return BroadcastRequestStatus.STAMPHOG_APPROVED
    if run.verdict in _NOT_APPROVED_VERDICTS:
        return BroadcastRequestStatus.OPEN
    return BroadcastRequestStatus.PENDING


def open_broadcast_request(
    pull_request: PullRequest, run: ReviewRun, ask: BroadcastRequestAsk, *, using: str
) -> OpenedBroadcastRequest:
    """Return the pull request's active request, or create one for the head that ``run`` covers.

    Call it inside the transaction that locked ``run``. The run cannot reach a terminal state before
    the request commits, so the finished-review path always sees the request.

    A new request takes its status from ``run``. A request for a head that stamphog already approved
    is created as STAMPHOG_APPROVED, which is final, so it does not block a later request. A repeated
    ask for that head returns the newest request when that request already records this approval.
    """
    active = (
        BroadcastRequest.objects.for_team(pull_request.team_id)
        .using(using)
        .filter(pull_request=pull_request, status__in=ACTIVE_BROADCAST_REQUEST_STATUSES)
    )
    existing = active.first()
    if existing is not None:
        return OpenedBroadcastRequest(request=existing, created=False)
    status = status_for_run(run)
    if status == BroadcastRequestStatus.STAMPHOG_APPROVED:
        latest = (
            BroadcastRequest.objects.for_team(pull_request.team_id)
            .using(using)
            .filter(pull_request=pull_request)
            .order_by("-created_at")
            .first()
        )
        if (
            latest is not None
            and latest.status == BroadcastRequestStatus.STAMPHOG_APPROVED
            and latest.head_sha == run.head_sha
        ):
            return OpenedBroadcastRequest(request=latest, created=False)
    try:
        # The savepoint keeps the outer transaction usable when a concurrent ask wins the unique constraint.
        with transaction.atomic(using=using):
            request = (
                BroadcastRequest.objects.for_team(pull_request.team_id)
                .using(using)
                .create(
                    team_id=pull_request.team_id,
                    pull_request=pull_request,
                    status=status,
                    head_sha=run.head_sha,
                    requested_by_user_id=ask.requested_by_user_id,
                    requested_via=ask.requested_via,
                    requester_slack_user_id=ask.requester_slack_user_id,
                    requester_github_login=ask.requester_github_login,
                    note=ask.note,
                )
            )
    except IntegrityError:
        return OpenedBroadcastRequest(request=active.get(), created=False)
    transaction.on_commit(
        lambda: _capture(
            request,
            REQUEST_CREATED_EVENT,
            {
                "stamphog_broadcast_request_status": str(request.status),
                "stamphog_broadcast_request_has_note": bool(request.note),
            },
        ),
        using=using,
    )
    return OpenedBroadcastRequest(request=request, created=True)


class LinkAskOutcome(StrEnum):
    CREATED = "created"
    # A retry of the task for the post that already opened the active request.
    REPEATED = "repeated"
    ALREADY_ASKED = "already_asked"
    STAMPHOG_APPROVED = "stamphog_approved"


@frozen
class LinkAsk:
    """What a pull request link posted in a Broadcast channel did."""

    outcome: LinkAskOutcome
    request: BroadcastRequest | None = None
    # The link to the card of the request that was already active, or "" when it has no posted card.
    permalink: str = ""


def stamphog_approval_live(reviews: list[dict[str, Any]]) -> bool | None:
    """Whether GitHub still shows an approval by this App. GitHub reports a dismissed review as ``DISMISSED``.

    None when the App slug is not configured, because no review can then be identified as this App's.
    """
    own_login = expected_app_bot_login()
    if own_login is None:
        return None
    return any(
        (review.get("user") or {}).get("login") == own_login and review.get("state") == "APPROVED" for review in reviews
    )


def stamphog_approved_head(pull_request: PullRequest, head_sha: str, *, using: str) -> bool:
    """Whether GitHub shows a standing stamphog approval of ``head_sha``.

    Only the newest verdict at the head that GitHub shows decides, so a withheld verdict never counts.
    A head that approval retention kept counts too, because the earlier approval stands over it.
    """
    runs = ReviewRun.objects.for_team(pull_request.team_id).using(using).filter(pull_request=pull_request)
    published = (
        runs.filter(head_sha=head_sha, verdict_posted_at__isnull=False)
        .exclude(status=ReviewRunStatus.SUPERSEDED)
        .order_by("-created_at")
        .first()
    )
    if published is not None:
        return published.verdict == ReviewVerdict.APPROVED and published.approval_dismissed_at is None
    return runs.filter(retained_at_head(head_sha)).exists()


def earlier_link_ask(
    team_id: int, *, repo_config_id: UUID, pr_number: int, channel_id: str, thread_ts: str, using: str
) -> LinkAsk | None:
    """What a link post gets when the pull request already has an active request, or None when it has none.

    REPEATED when the request belongs to this post, which is a retry of the task.
    """
    existing = (
        BroadcastRequest.objects.for_team(team_id)
        .using(using)
        .filter(
            pull_request__repo_config_id=repo_config_id,
            pull_request__pr_number=pr_number,
            status__in=ACTIVE_BROADCAST_REQUEST_STATUSES,
        )
        .first()
    )
    if existing is None:
        return None
    delivery = (
        BroadcastRequestDelivery.objects.for_team(team_id)
        .using(using)
        .filter(broadcast_request=existing, kind=BroadcastRequestDeliveryKind.SLACK_MESSAGE)
        .first()
    )
    if delivery is not None and (delivery.channel_id, delivery.thread_ts) == (channel_id, thread_ts):
        return LinkAsk(outcome=LinkAskOutcome.REPEATED, request=existing)
    permalink = delivery.permalink if delivery and delivery.state == BroadcastRequestDelivery.State.POSTED else ""
    return LinkAsk(outcome=LinkAskOutcome.ALREADY_ASKED, request=existing, permalink=permalink)


def open_link_request(
    pull_request: PullRequest,
    head_sha: str,
    ask: BroadcastRequestAsk,
    *,
    channel_id: str,
    thread_ts: str,
    stamphog_approval_live: bool,
    using: str,
) -> LinkAsk:
    """Open an OPEN request for a pull request link that a person posted, with its card due in the post's thread.

    No review starts, so the request waits for nobody. It is not opened when the pull request already
    has an active request, or when stamphog already approved ``head_sha``. The delivery row records the
    post before the card exists, so a retry for the same post finds its own request.
    """
    team_id = pull_request.team_id
    deliveries = BroadcastRequestDelivery.objects.for_team(team_id).using(using)
    kind = BroadcastRequestDeliveryKind.SLACK_MESSAGE

    def asked_before() -> LinkAsk | None:
        return earlier_link_ask(
            team_id,
            repo_config_id=pull_request.repo_config_id,
            pr_number=pull_request.pr_number,
            channel_id=channel_id,
            thread_ts=thread_ts,
            using=using,
        )

    earlier = asked_before()
    if earlier is not None:
        return earlier
    # The product DB misses a maintainer dismissing the approval on GitHub, so GitHub must still show it.
    if stamphog_approval_live and stamphog_approved_head(pull_request, head_sha, using=using):
        return LinkAsk(outcome=LinkAskOutcome.STAMPHOG_APPROVED)
    try:
        # The savepoint keeps the outer transaction usable when a concurrent ask wins the unique constraint.
        with transaction.atomic(using=using):
            request = (
                BroadcastRequest.objects.for_team(team_id)
                .using(using)
                .create(
                    team_id=team_id,
                    pull_request=pull_request,
                    status=BroadcastRequestStatus.OPEN,
                    head_sha=head_sha,
                    requested_by_user_id=ask.requested_by_user_id,
                    requested_via=ask.requested_via,
                    requester_slack_user_id=ask.requester_slack_user_id,
                    requester_github_login=ask.requester_github_login,
                    note=ask.note,
                )
            )
            deliveries.create(
                team_id=team_id, broadcast_request=request, kind=kind, channel_id=channel_id, thread_ts=thread_ts
            )
    except IntegrityError:
        concurrent = asked_before()
        if concurrent is None:
            raise
        return concurrent
    transaction.on_commit(
        lambda: _capture(
            request,
            REQUEST_CREATED_EVENT,
            {"stamphog_broadcast_request_status": str(request.status), "stamphog_broadcast_request_has_note": False},
        ),
        using=using,
    )
    return LinkAsk(outcome=LinkAskOutcome.CREATED, request=request)


# The review states that replace a person's earlier review. A COMMENTED review leaves an approval standing.
_DECIDING_REVIEW_STATES = frozenset({"APPROVED", "CHANGES_REQUESTED", "DISMISSED"})
_REVIEWABLE_STATUSES = frozenset({BroadcastRequestStatus.OPEN, BroadcastRequestStatus.PENDING})


def stamphog_status_at_head(
    pull_request: PullRequest, head_sha: str, *, using: str
) -> tuple[BroadcastRequestStatus, ReviewRun | None]:
    """What stamphog's newest review of ``head_sha`` means for a request, and that run.

    No review that still counts means stamphog will not answer this head, for example after a push in
    label mode, so the request opens rather than waiting forever. A silent run counts only once it
    posted its approval. Until then it can show nothing, and no stamphog verdict follows a withheld one.

    "No run" means that no run is coming only once the review path has decided the head. Callers check
    that through ``decided_head_sha`` in ``refresh``, which names the head the review path decided. A
    head that approval retention kept also has no run, because the push skipped the review, and the
    retained approval approves it.
    """
    runs = ReviewRun.objects.for_team(pull_request.team_id).using(using).filter(pull_request=pull_request)
    at_head = runs.filter(head_sha=head_sha).exclude(status=ReviewRunStatus.SUPERSEDED).order_by("-created_at")
    for run in at_head:
        if run.is_silent and run.verdict_posted_at is None:
            continue
        return status_for_run(run), run
    retained = runs.filter(retained_at_head(head_sha)).order_by("-created_at").first()
    if retained is not None:
        return BroadcastRequestStatus.STAMPHOG_APPROVED, retained
    return BroadcastRequestStatus.OPEN, None


def human_approver(reviews: list[dict[str, Any]], head_sha: str, author_login: str) -> str:
    """The login of a person whose standing review approves ``head_sha``, or "".

    Only each person's latest deciding review counts, so a later request for changes or a dismissal
    withdraws an approval. The author, bots and stamphog never count.
    """
    latest: dict[str, Mapping[str, Any]] = {}
    for review in reviews:
        user = review.get("user") or {}
        login = user.get("login") or ""
        if not is_person(login, user.get("type") == "Bot", review.get("author_association")):
            continue
        if login.lower() == author_login.lower() or review.get("state") not in _DECIDING_REVIEW_STATES:
            continue
        latest[login] = review
    for login, standing in latest.items():
        if standing.get("state") == "APPROVED" and standing.get("commit_id") == head_sha:
            return login
    return ""


def _findings(run: ReviewRun | None) -> tuple[str, ...]:
    """Why stamphog did not approve, only from a run whose verdict GitHub already shows."""
    if run is None or run.verdict_posted_at is None or run.verdict == ReviewVerdict.APPROVED:
        return ()
    raw = (run.output or {}).get("reviewer_raw")
    if not isinstance(raw, str) or not raw:
        return ()
    try:
        parsed = parse_reviewer_output(raw)
    except (AttributeError, TypeError, ValueError):
        return ()
    items = parsed.showstoppers or ([parsed.reasoning] if parsed.reasoning else [])
    # The same redaction the GitHub review got, before the card escapes it for Slack.
    return tuple(neutralize_active_markdown(scrub_credentials(item)) for item in items if item.strip())


def _requester_name(request: BroadcastRequest) -> str:
    if request.requester_slack_user_id:
        return ""
    name = ""
    if request.requested_by_user_id is not None:
        name = User.objects.filter(id=request.requested_by_user_id).values_list("first_name", flat=True).first() or ""
    return name or request.requester_github_login


def _same_requester(request: BroadcastRequest) -> Q | None:
    """Requests by the person who made ``request``: any one of its identities matches. None when it has none."""
    match = Q()
    if request.requested_by_user_id is not None:
        match |= Q(broadcast_request__requested_by_user_id=request.requested_by_user_id)
    if request.requester_slack_user_id:
        match |= Q(broadcast_request__requester_slack_user_id=request.requester_slack_user_id)
    if request.requester_github_login:
        # GitHub logins are case-insensitive.
        match |= Q(broadcast_request__requester_github_login__iexact=request.requester_github_login)
    return match or None


def requester_card_count(request: BroadcastRequest, *, at: datetime, using: str) -> int:
    """How many cards the person who made ``request`` caused in the window up to ``at``, its own card included.

    Only posted cards count, because a request that stamphog approved asked nobody to look. Two cards that
    post at the same moment can show the same number, which is accepted for a label.
    """
    match = _same_requester(request)
    if match is None:
        return 1
    earlier = (
        BroadcastRequestDelivery.objects.for_team(request.team_id)
        .using(using)
        .filter(
            match,
            kind=BroadcastRequestDeliveryKind.SLACK_MESSAGE,
            state=BroadcastRequestDelivery.State.POSTED,
            posted_at__gt=at - CARD_COUNT_WINDOW,
        )
        .exclude(broadcast_request_id=request.id)
        .count()
    )
    return earlier + 1


def card_cannot_post(request: BroadcastRequest, *, using: str) -> bool:
    """Whether the card of an open request cannot go out until a person fixes something.

    That is the case when the team has no Slack integration, or when Slack refused an earlier post, for
    example because the channel is gone or the app cannot join it.
    """
    if find_card_integration(request.team_id) is None:
        return True
    return (
        BroadcastRequestDelivery.objects.for_team(request.team_id)
        .using(using)
        .filter(
            broadcast_request_id=request.id,
            kind=BroadcastRequestDeliveryKind.SLACK_MESSAGE,
            state=BroadcastRequestDelivery.State.FAILED,
        )
        .exists()
    )


def _card(
    request: BroadcastRequest,
    pr: Mapping[str, Any],
    *,
    integration_id: int,
    status: BroadcastRequestStatus,
    approved_by_login: str,
    run: ReviewRun | None,
    lookers: list[BroadcastRequestParticipant],
) -> BroadcastRequestCard:
    pull_request = request.pull_request
    return BroadcastRequestCard(
        request_id=str(request.id),
        team_id=request.team_id,
        integration_id=integration_id,
        status=status,
        repository=pull_request.repo_config.repository,
        pr_number=pull_request.pr_number,
        pr_url=pr.get("html_url") or pull_request.pr_url,
        title=pr.get("title") or pull_request.title,
        additions=int(pr.get("additions") or 0),
        deletions=int(pr.get("deletions") or 0),
        changed_files=int(pr.get("changed_files") or 0),
        requested_on_github=(
            *(reviewer.get("login") or "" for reviewer in pr.get("requested_reviewers") or []),
            *(team.get("slug") or "" for team in pr.get("requested_teams") or []),
        ),
        findings=_findings(run) if status in (BroadcastRequestStatus.OPEN, BroadcastRequestStatus.APPROVED) else (),
        stamphog_failed=run is not None
        and run.status == ReviewRunStatus.FAILED
        and status == BroadcastRequestStatus.OPEN,
        note=request.note,
        requester_slack_user_id=request.requester_slack_user_id,
        requester_name=_requester_name(request),
        lookers=tuple(CardLooker(slack_user_id=p.slack_user_id, display_name=p.display_name) for p in lookers),
        approved_by_login=approved_by_login,
        requester_card_count=request.requester_card_count,
        from_link_post=request.requested_via == BroadcastRequestSource.SLACK_LINK,
    )


@frozen
class _NextState:
    status: BroadcastRequestStatus
    approved_by_login: str
    # Stamphog's newest review of the head, for its findings. None for a final request.
    run: ReviewRun | None


def _next_state(
    request: BroadcastRequest,
    client: StamphogGitHubClient,
    pr: Mapping[str, Any],
    *,
    decided_head_sha: str,
    using: str,
) -> _NextState | None:
    """The request's next state, or None while the review path has not yet decided a new head."""
    if request.status not in ACTIVE_BROADCAST_REQUEST_STATUSES:
        return _NextState(
            status=BroadcastRequestStatus(request.status), approved_by_login=request.approved_by_login, run=None
        )
    if pr.get("merged") or pr.get("merged_at"):
        return _NextState(status=BroadcastRequestStatus.MERGED, approved_by_login=request.approved_by_login, run=None)
    if pr.get("state") == "closed":
        return _NextState(status=BroadcastRequestStatus.CLOSED, approved_by_login=request.approved_by_login, run=None)
    pull_request = request.pull_request
    head_sha = pr["head"]["sha"]
    status, run = stamphog_status_at_head(pull_request, head_sha, using=using)
    if request.requested_via == BroadcastRequestSource.SLACK_LINK:
        # The person asked people directly, so nobody waits for stamphog. A review that has not decided yet
        # neither holds the card back nor shows on it. Only its approval changes the request.
        if status == BroadcastRequestStatus.PENDING:
            status, run = BroadcastRequestStatus.OPEN, None
    # Other GitHub deliveries for a push, such as review_requested, can refresh before the review path creates
    # the new head's run. That missing run does not mean that no review is coming, so the request waits.
    elif (
        run is None
        and status == BroadcastRequestStatus.OPEN
        and head_sha != request.head_sha
        and head_sha != decided_head_sha
    ):
        return None
    reviews = client.get_pr_reviews(pull_request.repo_config.repository, pull_request.pr_number)
    if status == BroadcastRequestStatus.STAMPHOG_APPROVED:
        # The product DB misses a maintainer dismissing the approval on GitHub, so GitHub must still show it.
        # Without the App slug nothing can be checked, so the DB record stands, as it does for a new approval.
        if stamphog_approval_live(reviews) is not False:
            return _NextState(status=status, approved_by_login="", run=run)
        status, run = BroadcastRequestStatus.OPEN, None
    author = (pr.get("user") or {}).get("login") or pull_request.author_login
    approver = human_approver(reviews, head_sha, author)
    if approver:
        return _NextState(status=BroadcastRequestStatus.APPROVED, approved_by_login=approver, run=run)
    return _NextState(status=status, approved_by_login="", run=run)


def _capture(request: BroadcastRequest, event: str, properties: dict[str, Any], *, background: bool = False) -> None:
    repo_config = request.pull_request.repo_config
    all_properties = {
        "stamphog_repo": repo_config.repository,
        "stamphog_team_id": request.team_id,
        "stamphog_broadcast_request_id": str(request.id),
        "stamphog_broadcast_request_via": request.requested_via,
        **properties,
    }
    try:
        if background:
            ph_background_capture()(distinct_id=repo_config.repository, event=event, properties=all_properties)
            return
        with ph_scoped_capture() as capture:
            capture(distinct_id=repo_config.repository, event=event, properties=all_properties)
    except Exception:
        logger.exception("stamphog_broadcast_request_capture_failed", broadcast_request_id=str(request.id))


def _capture_status_change(
    request: BroadcastRequest,
    delivery: BroadcastRequestDelivery | None,
    old: BroadcastRequestStatus,
    new: BroadcastRequestStatus,
    *,
    using: str,
) -> None:
    """Record how a request with a posted card ended, or moved, so the data shows whether a card got a review."""
    if delivery is None or delivery.state != BroadcastRequestDelivery.State.POSTED or delivery.posted_at is None:
        return
    properties = {
        "stamphog_broadcast_request_old_status": old.value,
        "stamphog_broadcast_request_new_status": new.value,
        "stamphog_broadcast_request_seconds_since_card": int((timezone.now() - delivery.posted_at).total_seconds()),
    }
    # After the commit, so a refresh that rolls back and retries records the change once.
    transaction.on_commit(lambda: _capture(request, STATUS_CHANGED_EVENT, properties), using=using)


def _post_once(request: BroadcastRequest, card: BroadcastRequestCard, head_sha: str, *, using: str) -> None:
    """Post the card unless another refresh already did. The delivery row lock makes a retry wait and then skip."""
    repo_config = request.pull_request.repo_config
    kind = BroadcastRequestDeliveryKind.SLACK_MESSAGE
    deliveries = BroadcastRequestDelivery.objects.for_team(request.team_id).using(using)
    with transaction.atomic(using=using):
        deliveries.get_or_create(team_id=request.team_id, broadcast_request=request, kind=kind)
        delivery = deliveries.select_for_update().get(broadcast_request=request, kind=kind)
        if delivery.state == BroadcastRequestDelivery.State.POSTED:
            return
        # A card in a thread belongs to the post that asked. Once Broadcast moves to another channel, that
        # post is not there.
        if delivery.thread_ts and delivery.channel_id != repo_config.broadcast_slack_channel_id:
            logger.info("stamphog_broadcast_request_thread_in_another_channel", broadcast_request_id=str(request.id))
            return
        posted_at = timezone.now()
        card_count = requester_card_count(request, at=posted_at, using=using)
        card = dataclasses.replace(card, requester_card_count=card_count)
        # When Slack accepts the post and the commit then fails, the retry posts one more card. That is accepted,
        # because recording the post before Slack accepts it could leave a card that never posts.
        try:
            ts = post_card(
                card,
                repo_config.broadcast_slack_channel_id,
                repo_config.broadcast_slack_channel_name,
                thread_ts=delivery.thread_ts,
            )
        except BroadcastRequestSlackError as e:
            # A missing integration, a channel the app cannot join, or a Slack refusal such as a revoked token needs a
            # person, so a retry would fail the same way. The next refresh tries again.
            logger.warning(
                "stamphog_broadcast_request_post_refused", broadcast_request_id=str(request.id), error=str(e)
            )
            delivery.state = BroadcastRequestDelivery.State.FAILED
            delivery.save(update_fields=["state", "updated_at"])
            return
        delivery.integration_id = card.integration_id
        delivery.channel_id = repo_config.broadcast_slack_channel_id
        delivery.message_ts = ts
        delivery.state = BroadcastRequestDelivery.State.POSTED
        delivery.posted_at = posted_at
        delivery.save(
            update_fields=[
                "integration_id",
                "channel_id",
                "message_ts",
                "state",
                "posted_at",
                "updated_at",
            ]
        )
        # The people who look later see the card at this head, so only a later head pings them. Later edits show
        # the count the card went out with.
        BroadcastRequest.objects.for_team(request.team_id).using(using).filter(id=request.id).update(
            pinged_head_sha=head_sha, requester_card_count=card_count, updated_at=timezone.now()
        )
        channel_id = delivery.channel_id
        transaction.on_commit(
            lambda: _record_permalink(request.team_id, delivery.id, card, channel_id, ts, using=using), using=using
        )
    _capture(request, CARD_POSTED_EVENT, {"stamphog_broadcast_request_status": card.status.value})


def _record_permalink(
    team_id: int, delivery_id: UUID, card: BroadcastRequestCard, channel_id: str, ts: str, *, using: str
) -> None:
    permalink = card_permalink(card, channel_id, ts)
    if not permalink:
        return
    BroadcastRequestDelivery.objects.for_team(team_id).using(using).filter(id=delivery_id, permalink="").update(
        permalink=permalink, updated_at=timezone.now()
    )


def _post_if_open(
    request: BroadcastRequest,
    pr: Mapping[str, Any],
    state: _NextState,
    lookers: list[BroadcastRequestParticipant],
    head_sha: str,
    *,
    using: str,
) -> None:
    if state.status != BroadcastRequestStatus.OPEN:
        return
    repo_config = request.pull_request.repo_config
    if not repo_config.broadcast_enabled or not repo_config.broadcast_slack_channel_id:
        logger.info("stamphog_broadcast_request_not_configured", broadcast_request_id=str(request.id))
        return
    integration_id = find_card_integration(request.team_id)
    if integration_id is None:
        logger.warning("stamphog_broadcast_request_no_slack_integration", broadcast_request_id=str(request.id))
        return
    card = _card(
        request,
        pr,
        integration_id=integration_id,
        status=state.status,
        approved_by_login=state.approved_by_login,
        run=state.run,
        lookers=lookers,
    )
    _post_once(request, card, head_sha, using=using)


def refresh(team_id: int, broadcast_request_id: str, *, decided_head_sha: str = "") -> None:
    """Recompute one Broadcast request from the database and GitHub, then post or edit its Slack card.

    Idempotent: a retry, or a second refresh for the same state, posts nothing new. Every read that
    decides a post is pinned to the writer.

    ``decided_head_sha`` is set only by the refresh that the review path queues after it created the run
    for the pull request's head or skipped that head, and it names the head the review path decided.
    Only that refresh, and only while the live head is still that head, may read a new head with no run
    as a head that stamphog will not review. Any other refresh leaves the request unchanged until then.

    Refreshes of one request run one at a time under the request's row lock, which is held across the
    GitHub reads and the Slack call. Without it, a refresh that read GitHub before a push or a merge
    could write its older state, or edit the card to it, after a newer refresh finished.
    """
    db = router.db_for_write(BroadcastRequest)
    with transaction.atomic(using=db):
        request = (
            BroadcastRequest.objects.for_team(team_id)
            .using(db)
            .select_related("pull_request__repo_config")
            # Only the request row: a lock on the pull request row would block the review path's upsert.
            # NO KEY UPDATE does not block the FOR KEY SHARE lock of a participant insert, so a click
            # does not wait for the GitHub and Slack calls of a refresh.
            .select_for_update(no_key=True, of=("self",))
            .filter(id=broadcast_request_id)
            .first()
        )
        if request is None:
            return
        _refresh_locked(request, decided_head_sha=decided_head_sha, using=db)


def _refresh_locked(request: BroadcastRequest, *, decided_head_sha: str, using: str) -> None:
    team_id = request.team_id
    pull_request = request.pull_request
    repo_config = pull_request.repo_config
    # These reads are not review writes, so they leave the CRITICAL reserve to verdicts and dismissals.
    # NORMAL and not BATCH, because a person who clicked waits on them, and a shed refresh only retries.
    client = StamphogGitHubClient(repo_config.installation_id, lane=Priority.NORMAL)
    pr = client.get_pr(repo_config.repository, pull_request.pr_number)
    head_sha = pr["head"]["sha"]
    state = _next_state(request, client, pr, decided_head_sha=decided_head_sha, using=using)
    if state is None:
        return

    delivery = (
        BroadcastRequestDelivery.objects.for_team(team_id)
        .using(using)
        .filter(broadcast_request=request, kind=BroadcastRequestDeliveryKind.SLACK_MESSAGE)
        .first()
    )
    if request.status in ACTIVE_BROADCAST_REQUEST_STATUSES:
        BroadcastRequest.objects.for_team(team_id).using(using).filter(id=request.id).update(
            status=state.status, head_sha=head_sha, approved_by_login=state.approved_by_login, updated_at=timezone.now()
        )
        if state.status != request.status:
            _capture_status_change(request, delivery, BroadcastRequestStatus(request.status), state.status, using=using)
    lookers = list(
        BroadcastRequestParticipant.objects.for_team(team_id)
        .using(using)
        .filter(broadcast_request=request, looking=True)
        .order_by("created_at")
    )

    if delivery is None or delivery.state != BroadcastRequestDelivery.State.POSTED or delivery.integration_id is None:
        _post_if_open(request, pr, state, lookers, head_sha, using=using)
        return
    # Turning Broadcast off, or moving it to another channel, stops PR data from reaching the old card's audience.
    if not repo_config.broadcast_enabled or repo_config.broadcast_slack_channel_id != delivery.channel_id:
        logger.info("stamphog_broadcast_request_card_frozen", broadcast_request_id=str(request.id))
        return

    card = _card(
        request,
        pr,
        integration_id=delivery.integration_id,
        status=state.status,
        approved_by_login=state.approved_by_login,
        run=state.run,
        lookers=lookers,
    )
    try:
        update_card(card, delivery.channel_id, delivery.message_ts)
    except BroadcastRequestSlackError as e:
        logger.warning("stamphog_broadcast_request_update_refused", broadcast_request_id=str(request.id), error=str(e))
        return
    if head_sha == request.pinged_head_sha:
        return
    # Recorded before the reply, so a failed reply is not sent again.
    BroadcastRequest.objects.for_team(team_id).using(using).filter(id=request.id).update(
        pinged_head_sha=head_sha, updated_at=timezone.now()
    )
    if lookers and state.status in _REVIEWABLE_STATUSES:
        # Slack threads a reply under the post that opened the thread, so a card that is itself a reply pings there.
        ping_lookers(
            card,
            delivery.channel_id,
            delivery.thread_ts or delivery.message_ts,
            reviewing=state.status == BroadcastRequestStatus.PENDING,
        )


def record_look(click: LookClick) -> bool:
    """Mark the person who clicked a card as looking at its pull request, or as no longer looking.

    Returns True when the card must be refreshed. The click counts only on the card that the request
    posted, and only from a person in the workspace that the card was posted in, because a button value
    can be copied into another message. Slack expects an answer in 3 seconds, so the refresh is queued
    by the caller, and the click event goes through the background client, which does not wait for a flush.
    """
    db = router.db_for_write(BroadcastRequest)
    request = (
        BroadcastRequest.objects.for_team(click.team_id)
        .using(db)
        .select_related("pull_request__repo_config")
        .filter(id=click.broadcast_request_id, status__in=_REVIEWABLE_STATUSES)
        .first()
    )
    if request is None:
        return False
    on_card = (
        BroadcastRequestDelivery.objects.for_team(click.team_id)
        .using(db)
        .filter(
            broadcast_request=request,
            kind=BroadcastRequestDeliveryKind.SLACK_MESSAGE,
            state=BroadcastRequestDelivery.State.POSTED,
            integration_id=click.integration_id,
            channel_id=click.channel_id,
            message_ts=click.message_ts,
        )
        .exists()
    )
    if not on_card:
        return False
    workspace = card_workspace(click.team_id, click.integration_id)
    if not workspace or workspace != click.slack_team_id or click.slack_user_team_id != workspace:
        logger.info("stamphog_broadcast_request_click_from_another_workspace", broadcast_request_id=str(request.id))
        return False

    participants = BroadcastRequestParticipant.objects.for_team(click.team_id).using(db)
    if click.looking:
        participant, created = participants.get_or_create(
            team_id=click.team_id,
            broadcast_request=request,
            slack_user_id=click.slack_user_id,
            defaults={"display_name": click.display_name, "looking": True},
        )
        changed = created or bool(
            participants.filter(id=participant.id, looking=False).update(
                looking=True,
                display_name=click.display_name or participant.display_name,
                updated_at=timezone.now(),
            )
        )
    else:
        changed = bool(
            participants.filter(broadcast_request=request, slack_user_id=click.slack_user_id, looking=True).update(
                looking=False, updated_at=timezone.now()
            )
        )
    if changed:
        _capture(request, LOOK_CLICKED_EVENT, {"stamphog_broadcast_request_looking": click.looking}, background=True)
    return changed
