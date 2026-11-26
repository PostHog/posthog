"""Requests for a person to review a pull request that stamphog did not approve.

A request starts with a manual review request that sets ``human``. It follows the pull request
until a person or stamphog approves it, or the pull request merges or closes. The Slack card that
asks people to look is rendered and posted from ``refresh_human_request``.
"""

from __future__ import annotations

from django.db import IntegrityError, transaction

from posthog.dataclasses import frozen

from ..facade.enums import (
    ACTIVE_HUMAN_REQUEST_STATUSES,
    HumanRequestSource,
    HumanRequestStatus,
    ReviewRunStatus,
    ReviewVerdict,
)
from ..models import HumanRequest, PullRequest, ReviewRun

# The outcomes that send a pull request to people. A WAIT is absent because stamphog reviews the head again.
_NOT_APPROVED_VERDICTS = frozenset({ReviewVerdict.REFUSED, ReviewVerdict.ESCALATE})


@frozen
class HumanRequestAsk:
    """Who asked for people to review a pull request, and from where."""

    requested_by_user_id: int | None
    requested_via: HumanRequestSource
    requester_slack_user_id: str = ""
    # Shown in Slack only. It is never written to GitHub, because pull request comments are public.
    note: str = ""


@frozen
class OpenedHumanRequest:
    """The active request for a pull request, and whether this ask created it."""

    request: HumanRequest
    created: bool


def status_for_run(run: ReviewRun) -> HumanRequestStatus:
    """What a request waits for while ``run`` is stamphog's newest review of the request's head.

    Only a verdict that GitHub already has counts, so a verdict that a silent run withheld leaves the
    request PENDING.
    """
    if run.status == ReviewRunStatus.FAILED:
        return HumanRequestStatus.OPEN if run.may_publish() else HumanRequestStatus.PENDING
    if run.status not in (ReviewRunStatus.COMPLETED, ReviewRunStatus.GATED) or run.verdict_posted_at is None:
        return HumanRequestStatus.PENDING
    # A gate denial is stored as a GATED WAIT, and stamphog does not review that head again.
    if run.status == ReviewRunStatus.GATED:
        return HumanRequestStatus.OPEN
    if run.verdict == ReviewVerdict.APPROVED and run.approval_dismissed_at is None:
        return HumanRequestStatus.STAMPHOG_APPROVED
    if run.verdict in _NOT_APPROVED_VERDICTS:
        return HumanRequestStatus.OPEN
    return HumanRequestStatus.PENDING


def open_human_request(
    pull_request: PullRequest, run: ReviewRun, ask: HumanRequestAsk, *, using: str
) -> OpenedHumanRequest:
    """Return the pull request's active request, or create one for the head that ``run`` covers.

    Call it inside the transaction that locked ``run``. The run cannot reach a terminal state before
    the request commits, so the finished-review path always sees the request.

    A new request takes its status from ``run``. A request for a head that stamphog already approved
    is created as STAMPHOG_APPROVED, which is final, so it does not block a later request.
    """
    active = (
        HumanRequest.objects.for_team(pull_request.team_id)
        .using(using)
        .filter(pull_request=pull_request, status__in=ACTIVE_HUMAN_REQUEST_STATUSES)
    )
    existing = active.first()
    if existing is not None:
        return OpenedHumanRequest(request=existing, created=False)
    try:
        # The savepoint keeps the outer transaction usable when a concurrent ask wins the unique constraint.
        with transaction.atomic(using=using):
            request = (
                HumanRequest.objects.for_team(pull_request.team_id)
                .using(using)
                .create(
                    team_id=pull_request.team_id,
                    pull_request=pull_request,
                    status=status_for_run(run),
                    head_sha=run.head_sha,
                    requested_by_user_id=ask.requested_by_user_id,
                    requested_via=ask.requested_via,
                    requester_slack_user_id=ask.requester_slack_user_id,
                    note=ask.note,
                )
            )
    except IntegrityError:
        return OpenedHumanRequest(request=active.get(), created=False)
    return OpenedHumanRequest(request=request, created=True)
