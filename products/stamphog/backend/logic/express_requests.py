"""Requests for a person to review a pull request that stamphog did not approve.

A request starts with a manual review request that sets ``express``. It follows the pull request
until a person or stamphog approves it, or the pull request merges or closes. ``refresh`` decides
the request's state from the database and GitHub, then posts or edits its Slack card, so every
change to a request goes through one idempotent path.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from django.db import IntegrityError, connections, router, transaction
from django.db.models import Q
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen
from posthog.egress.limiter.policies import Priority
from posthog.models import User
from posthog.ph_client import ph_background_capture, ph_scoped_capture

from ..facade.enums import (
    ACTIVE_EXPRESS_REQUEST_STATUSES,
    ExpressRequestDeliveryKind,
    ExpressRequestSource,
    ExpressRequestStatus,
    ReviewRunStatus,
    ReviewVerdict,
)
from ..models import ExpressRequest, ExpressRequestDelivery, ExpressRequestParticipant, PullRequest, ReviewRun
from .express_request_slack import (
    CardLooker,
    ExpressRequestCard,
    ExpressRequestSlackError,
    LookClick,
    card_permalink,
    card_workspace,
    find_card_integration,
    ping_lookers,
    post_card,
    update_card,
)
from .github_client import StamphogGitHubClient
from .merge_approval import retained_at_head
from .rerun_evidence import is_person
from .reviewer import parse_reviewer_output
from .scrubbing import neutralize_active_markdown, scrub_credentials

logger = structlog.get_logger(__name__)

REQUEST_CREATED_EVENT = "stamphog_express_request_created"
CARD_POSTED_EVENT = "stamphog_express_card_posted"
LOOK_CLICKED_EVENT = "stamphog_express_look_clicked"
STATUS_CHANGED_EVENT = "stamphog_express_request_status_changed"

CARD_COUNT_WINDOW = timedelta(days=7)

# The outcomes that send a pull request to people. An ERROR is here because nothing reviews that head again on its own.
# A WAIT is absent because stamphog reviews the head again.
_NOT_APPROVED_VERDICTS = frozenset({ReviewVerdict.REFUSED, ReviewVerdict.ESCALATE, ReviewVerdict.ERROR})


@frozen
class ExpressRequestAsk:
    """Who asked for people to review a pull request, and from where."""

    requested_by_user_id: int | None
    requested_via: ExpressRequestSource
    requester_slack_user_id: str = ""
    requester_github_login: str = ""
    note: str = ""


@frozen
class OpenedExpressRequest:
    """The active request for a pull request, and whether this ask created it."""

    request: ExpressRequest
    created: bool


def status_for_run(run: ReviewRun) -> ExpressRequestStatus:
    """What a request waits for while ``run`` is stamphog's newest review of the request's head.

    Only a verdict that GitHub already has counts, so a run that has not posted one leaves the request
    PENDING. ``stamphog_status_at_head`` never passes a silent run that withheld its verdict.
    """
    if run.status == ReviewRunStatus.FAILED:
        return ExpressRequestStatus.OPEN if run.may_publish() else ExpressRequestStatus.PENDING
    if run.status not in (ReviewRunStatus.COMPLETED, ReviewRunStatus.GATED) or run.verdict_posted_at is None:
        return ExpressRequestStatus.PENDING
    # A gate denial is stored as a GATED WAIT, and stamphog does not review that head again.
    if run.status == ReviewRunStatus.GATED:
        return ExpressRequestStatus.OPEN
    if run.verdict == ReviewVerdict.APPROVED and run.approval_dismissed_at is None:
        return ExpressRequestStatus.STAMPHOG_APPROVED
    if run.verdict in _NOT_APPROVED_VERDICTS:
        return ExpressRequestStatus.OPEN
    return ExpressRequestStatus.PENDING


def open_express_request(
    pull_request: PullRequest, run: ReviewRun, ask: ExpressRequestAsk, *, using: str
) -> OpenedExpressRequest:
    """Return the pull request's active request, or create one for the head that ``run`` covers.

    Call it inside the transaction that locked ``run``. The run cannot reach a terminal state before
    the request commits, so the finished-review path always sees the request.

    A new request takes its status from ``run``. A request for a head that stamphog already approved
    is created as STAMPHOG_APPROVED, which is final, so it does not block a later request. A repeated
    ask for that head returns the newest request when that request already records this approval.
    """
    active = (
        ExpressRequest.objects.for_team(pull_request.team_id)
        .using(using)
        .filter(pull_request=pull_request, status__in=ACTIVE_EXPRESS_REQUEST_STATUSES)
    )
    existing = active.first()
    if existing is not None:
        return OpenedExpressRequest(request=existing, created=False)
    status = status_for_run(run)
    if status == ExpressRequestStatus.STAMPHOG_APPROVED:
        latest = (
            ExpressRequest.objects.for_team(pull_request.team_id)
            .using(using)
            .filter(pull_request=pull_request)
            .order_by("-created_at")
            .first()
        )
        if (
            latest is not None
            and latest.status == ExpressRequestStatus.STAMPHOG_APPROVED
            and latest.head_sha == run.head_sha
        ):
            return OpenedExpressRequest(request=latest, created=False)
    try:
        # The savepoint keeps the outer transaction usable when a concurrent ask wins the unique constraint.
        with transaction.atomic(using=using):
            request = (
                ExpressRequest.objects.for_team(pull_request.team_id)
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
        return OpenedExpressRequest(request=active.get(), created=False)
    transaction.on_commit(
        lambda: _capture(
            request,
            REQUEST_CREATED_EVENT,
            {
                "stamphog_express_request_status": str(request.status),
                "stamphog_express_request_has_note": bool(request.note),
            },
        ),
        using=using,
    )
    return OpenedExpressRequest(request=request, created=True)


# The review states that replace a person's earlier review. A COMMENTED review leaves an approval standing.
_DECIDING_REVIEW_STATES = frozenset({"APPROVED", "CHANGES_REQUESTED", "DISMISSED"})
_REVIEWABLE_STATUSES = frozenset({ExpressRequestStatus.OPEN, ExpressRequestStatus.PENDING})


def stamphog_status_at_head(
    pull_request: PullRequest, head_sha: str, *, using: str
) -> tuple[ExpressRequestStatus, ReviewRun | None]:
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
        return ExpressRequestStatus.STAMPHOG_APPROVED, retained
    return ExpressRequestStatus.OPEN, None


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


def _requester_name(request: ExpressRequest) -> str:
    if request.requester_slack_user_id:
        return ""
    name = ""
    if request.requested_by_user_id is not None:
        name = User.objects.filter(id=request.requested_by_user_id).values_list("first_name", flat=True).first() or ""
    return name or request.requester_github_login


def _same_requester(request: ExpressRequest) -> Q | None:
    """Requests by the person who made ``request``: any one of its identities matches. None when it has none."""
    match = Q()
    if request.requested_by_user_id is not None:
        match |= Q(express_request__requested_by_user_id=request.requested_by_user_id)
    if request.requester_slack_user_id:
        match |= Q(express_request__requester_slack_user_id=request.requester_slack_user_id)
    if request.requester_github_login:
        # GitHub logins are case-insensitive.
        match |= Q(express_request__requester_github_login__iexact=request.requester_github_login)
    return match or None


def _lock_requester_cards(request: ExpressRequest, *, using: str) -> None:
    """Serialize card posts of one requester until the transaction ends, so each post counts the ones before it.

    A post saves its delivery as POSTED in a transaction that is still open, so a concurrent post for the same
    person would not see it and both cards would show the same count. One lock per identity, taken in a fixed
    order, also covers a person who asks once from Slack and once from GitHub.
    """
    identities = []
    if request.requested_by_user_id is not None:
        identities.append(f"user:{request.requested_by_user_id}")
    if request.requester_slack_user_id:
        identities.append(f"slack:{request.requester_slack_user_id}")
    if request.requester_github_login:
        identities.append(f"github:{request.requester_github_login.lower()}")
    with connections[using].cursor() as cursor:
        for identity in sorted(identities):
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                [f"stamphog-express-cards:{request.team_id}:{identity}"],
            )


def requester_card_count(request: ExpressRequest, *, at: datetime, using: str) -> int:
    """How many cards the person who made ``request`` caused in the window up to ``at``, its own card included.

    Only posted cards count, because a request that stamphog approved asked nobody to look.
    """
    match = _same_requester(request)
    if match is None:
        return 1
    earlier = (
        ExpressRequestDelivery.objects.for_team(request.team_id)
        .using(using)
        .filter(
            match,
            kind=ExpressRequestDeliveryKind.SLACK_MESSAGE,
            state=ExpressRequestDelivery.State.POSTED,
            posted_at__gt=at - CARD_COUNT_WINDOW,
        )
        .exclude(express_request_id=request.id)
        .count()
    )
    return earlier + 1


def card_cannot_post(request: ExpressRequest, *, using: str) -> bool:
    """Whether the card of an open request cannot go out until a person fixes something.

    That is the case when the team has no Slack integration, or when Slack refused an earlier post, for
    example because the channel is gone or the app cannot join it.
    """
    if find_card_integration(request.team_id) is None:
        return True
    return (
        ExpressRequestDelivery.objects.for_team(request.team_id)
        .using(using)
        .filter(
            express_request_id=request.id,
            kind=ExpressRequestDeliveryKind.SLACK_MESSAGE,
            state=ExpressRequestDelivery.State.FAILED,
        )
        .exists()
    )


def _card(
    request: ExpressRequest,
    pr: Mapping[str, Any],
    *,
    integration_id: int,
    status: ExpressRequestStatus,
    approved_by_login: str,
    run: ReviewRun | None,
    lookers: list[ExpressRequestParticipant],
) -> ExpressRequestCard:
    pull_request = request.pull_request
    return ExpressRequestCard(
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
        findings=_findings(run) if status in (ExpressRequestStatus.OPEN, ExpressRequestStatus.APPROVED) else (),
        stamphog_failed=run is not None
        and run.status == ReviewRunStatus.FAILED
        and status == ExpressRequestStatus.OPEN,
        note=request.note,
        requester_slack_user_id=request.requester_slack_user_id,
        requester_name=_requester_name(request),
        lookers=tuple(CardLooker(slack_user_id=p.slack_user_id, display_name=p.display_name) for p in lookers),
        approved_by_login=approved_by_login,
        requester_card_count=request.requester_card_count,
    )


@frozen
class _NextState:
    status: ExpressRequestStatus
    approved_by_login: str
    # Stamphog's newest review of the head, for its findings. None for a final request.
    run: ReviewRun | None


def _next_state(
    request: ExpressRequest,
    client: StamphogGitHubClient,
    pr: Mapping[str, Any],
    *,
    decided_head_sha: str,
    using: str,
) -> _NextState | None:
    """The request's next state, or None while the review path has not yet decided a new head."""
    if request.status not in ACTIVE_EXPRESS_REQUEST_STATUSES:
        return _NextState(
            status=ExpressRequestStatus(request.status), approved_by_login=request.approved_by_login, run=None
        )
    if pr.get("merged") or pr.get("merged_at"):
        return _NextState(status=ExpressRequestStatus.MERGED, approved_by_login=request.approved_by_login, run=None)
    if pr.get("state") == "closed":
        return _NextState(status=ExpressRequestStatus.CLOSED, approved_by_login=request.approved_by_login, run=None)
    pull_request = request.pull_request
    head_sha = pr["head"]["sha"]
    status, run = stamphog_status_at_head(pull_request, head_sha, using=using)
    # Other GitHub deliveries for a push, such as review_requested, can refresh before the review path creates
    # the new head's run. That missing run does not mean that no review is coming, so the request waits.
    if (
        run is None
        and status == ExpressRequestStatus.OPEN
        and head_sha != request.head_sha
        and head_sha != decided_head_sha
    ):
        return None
    if status == ExpressRequestStatus.STAMPHOG_APPROVED:
        return _NextState(status=status, approved_by_login="", run=run)
    author = (pr.get("user") or {}).get("login") or pull_request.author_login
    approver = human_approver(
        client.get_pr_reviews(pull_request.repo_config.repository, pull_request.pr_number), head_sha, author
    )
    if approver:
        return _NextState(status=ExpressRequestStatus.APPROVED, approved_by_login=approver, run=run)
    return _NextState(status=status, approved_by_login="", run=run)


def _capture(request: ExpressRequest, event: str, properties: dict[str, Any], *, background: bool = False) -> None:
    repo_config = request.pull_request.repo_config
    all_properties = {
        "stamphog_repo": repo_config.repository,
        "stamphog_team_id": request.team_id,
        "stamphog_express_request_id": str(request.id),
        "stamphog_express_request_via": request.requested_via,
        **properties,
    }
    try:
        if background:
            ph_background_capture()(distinct_id=repo_config.repository, event=event, properties=all_properties)
            return
        with ph_scoped_capture() as capture:
            capture(distinct_id=repo_config.repository, event=event, properties=all_properties)
    except Exception:
        logger.exception("stamphog_express_request_capture_failed", express_request_id=str(request.id))


def _capture_status_change(
    request: ExpressRequest,
    delivery: ExpressRequestDelivery | None,
    old: ExpressRequestStatus,
    new: ExpressRequestStatus,
    *,
    using: str,
) -> None:
    """Record how a request with a posted card ended, or moved, so the data shows whether a card got a review."""
    if delivery is None or delivery.state != ExpressRequestDelivery.State.POSTED or delivery.posted_at is None:
        return
    properties = {
        "stamphog_express_request_old_status": old.value,
        "stamphog_express_request_new_status": new.value,
        "stamphog_express_request_seconds_since_card": int((timezone.now() - delivery.posted_at).total_seconds()),
    }
    # After the commit, so a refresh that rolls back and retries records the change once.
    transaction.on_commit(lambda: _capture(request, STATUS_CHANGED_EVENT, properties), using=using)


def _post_once(request: ExpressRequest, card: ExpressRequestCard, head_sha: str, *, using: str) -> None:
    """Post the card unless another refresh already did. The delivery row lock makes a retry wait and then skip."""
    repo_config = request.pull_request.repo_config
    kind = ExpressRequestDeliveryKind.SLACK_MESSAGE
    deliveries = ExpressRequestDelivery.objects.for_team(request.team_id).using(using)
    with transaction.atomic(using=using):
        deliveries.get_or_create(team_id=request.team_id, express_request=request, kind=kind)
        delivery = deliveries.select_for_update().get(express_request=request, kind=kind)
        if delivery.state == ExpressRequestDelivery.State.POSTED:
            return
        _lock_requester_cards(request, using=using)
        posted_at = timezone.now()
        card_count = requester_card_count(request, at=posted_at, using=using)
        card = dataclasses.replace(card, requester_card_count=card_count)
        # When Slack accepts the post and the commit then fails, the retry posts one more card. That is accepted,
        # because recording the post before Slack accepts it could leave a card that never posts.
        try:
            ts = post_card(card, repo_config.express_slack_channel_id, repo_config.express_slack_channel_name)
        except ExpressRequestSlackError as e:
            # A missing integration, a channel the app cannot join, or a Slack refusal such as a revoked token needs a
            # person, so a retry would fail the same way. The next refresh tries again.
            logger.warning("stamphog_express_request_post_refused", express_request_id=str(request.id), error=str(e))
            delivery.state = ExpressRequestDelivery.State.FAILED
            delivery.save(update_fields=["state", "updated_at"])
            return
        delivery.integration_id = card.integration_id
        delivery.channel_id = repo_config.express_slack_channel_id
        delivery.message_ts = ts
        delivery.state = ExpressRequestDelivery.State.POSTED
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
        ExpressRequest.objects.for_team(request.team_id).using(using).filter(id=request.id).update(
            pinged_head_sha=head_sha, requester_card_count=card_count, updated_at=timezone.now()
        )
        channel_id = delivery.channel_id
        transaction.on_commit(
            lambda: _record_permalink(request.team_id, delivery.id, card, channel_id, ts, using=using), using=using
        )
    _capture(request, CARD_POSTED_EVENT, {"stamphog_express_request_status": card.status.value})


def _record_permalink(
    team_id: int, delivery_id: UUID, card: ExpressRequestCard, channel_id: str, ts: str, *, using: str
) -> None:
    permalink = card_permalink(card, channel_id, ts)
    if not permalink:
        return
    ExpressRequestDelivery.objects.for_team(team_id).using(using).filter(id=delivery_id, permalink="").update(
        permalink=permalink, updated_at=timezone.now()
    )


def _post_if_open(
    request: ExpressRequest,
    pr: Mapping[str, Any],
    state: _NextState,
    lookers: list[ExpressRequestParticipant],
    head_sha: str,
    *,
    using: str,
) -> None:
    if state.status != ExpressRequestStatus.OPEN:
        return
    repo_config = request.pull_request.repo_config
    if not repo_config.express_enabled or not repo_config.express_slack_channel_id:
        logger.info("stamphog_express_request_not_configured", express_request_id=str(request.id))
        return
    integration_id = find_card_integration(request.team_id)
    if integration_id is None:
        logger.warning("stamphog_express_request_no_slack_integration", express_request_id=str(request.id))
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


def refresh(team_id: int, express_request_id: str, *, decided_head_sha: str = "") -> None:
    """Recompute one Express request from the database and GitHub, then post or edit its Slack card.

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
    db = router.db_for_write(ExpressRequest)
    with transaction.atomic(using=db):
        request = (
            ExpressRequest.objects.for_team(team_id)
            .using(db)
            .select_related("pull_request__repo_config")
            # Only the request row: a lock on the pull request row would block the review path's upsert.
            # NO KEY UPDATE does not block the FOR KEY SHARE lock of a participant insert, so a click
            # does not wait for the GitHub and Slack calls of a refresh.
            .select_for_update(no_key=True, of=("self",))
            .filter(id=express_request_id)
            .first()
        )
        if request is None:
            return
        _refresh_locked(request, decided_head_sha=decided_head_sha, using=db)


def _refresh_locked(request: ExpressRequest, *, decided_head_sha: str, using: str) -> None:
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
        ExpressRequestDelivery.objects.for_team(team_id)
        .using(using)
        .filter(express_request=request, kind=ExpressRequestDeliveryKind.SLACK_MESSAGE)
        .first()
    )
    if request.status in ACTIVE_EXPRESS_REQUEST_STATUSES:
        ExpressRequest.objects.for_team(team_id).using(using).filter(id=request.id).update(
            status=state.status, head_sha=head_sha, approved_by_login=state.approved_by_login, updated_at=timezone.now()
        )
        if state.status != request.status:
            _capture_status_change(request, delivery, ExpressRequestStatus(request.status), state.status, using=using)
    lookers = list(
        ExpressRequestParticipant.objects.for_team(team_id)
        .using(using)
        .filter(express_request=request, looking=True)
        .order_by("created_at")
    )

    if delivery is None or delivery.state != ExpressRequestDelivery.State.POSTED or delivery.integration_id is None:
        _post_if_open(request, pr, state, lookers, head_sha, using=using)
        return
    # Turning Express off, or moving it to another channel, stops PR data from reaching the old card's audience.
    if not repo_config.express_enabled or repo_config.express_slack_channel_id != delivery.channel_id:
        logger.info("stamphog_express_request_card_frozen", express_request_id=str(request.id))
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
    except ExpressRequestSlackError as e:
        logger.warning("stamphog_express_request_update_refused", express_request_id=str(request.id), error=str(e))
        return
    if head_sha == request.pinged_head_sha:
        return
    # Recorded before the reply, so a failed reply is not sent again.
    ExpressRequest.objects.for_team(team_id).using(using).filter(id=request.id).update(
        pinged_head_sha=head_sha, updated_at=timezone.now()
    )
    if lookers and state.status in _REVIEWABLE_STATUSES:
        ping_lookers(
            card, delivery.channel_id, delivery.message_ts, reviewing=state.status == ExpressRequestStatus.PENDING
        )


def record_look(click: LookClick) -> bool:
    """Mark the person who clicked a card as looking at its pull request, or as no longer looking.

    Returns True when the card must be refreshed. The click counts only on the card that the request
    posted, and only from a person in the workspace that the card was posted in, because a button value
    can be copied into another message. Slack expects an answer in 3 seconds, so the refresh is queued
    by the caller, and the click event goes through the background client, which does not wait for a flush.
    """
    db = router.db_for_write(ExpressRequest)
    request = (
        ExpressRequest.objects.for_team(click.team_id)
        .using(db)
        .select_related("pull_request__repo_config")
        .filter(id=click.express_request_id, status__in=_REVIEWABLE_STATUSES)
        .first()
    )
    if request is None:
        return False
    on_card = (
        ExpressRequestDelivery.objects.for_team(click.team_id)
        .using(db)
        .filter(
            express_request=request,
            kind=ExpressRequestDeliveryKind.SLACK_MESSAGE,
            state=ExpressRequestDelivery.State.POSTED,
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
        logger.info("stamphog_express_request_click_from_another_workspace", express_request_id=str(request.id))
        return False

    participants = ExpressRequestParticipant.objects.for_team(click.team_id).using(db)
    if click.looking:
        participant, created = participants.get_or_create(
            team_id=click.team_id,
            express_request=request,
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
            participants.filter(express_request=request, slack_user_id=click.slack_user_id, looking=True).update(
                looking=False, updated_at=timezone.now()
            )
        )
    if changed:
        _capture(request, LOOK_CLICKED_EVENT, {"stamphog_express_request_looking": click.looking}, background=True)
    return changed
