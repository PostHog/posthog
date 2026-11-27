"""Facade for asking stamphog to review one pull request on a PostHog user's behalf.

Lives apart from ``api.py`` for the same reason ``tasks.py`` and ``github.py`` do: this path pulls
the GitHub client and the Celery task module, which must stay off the module review_hog's settings
serializer imports on every request.
"""

import dataclasses
from collections.abc import Collection

from django.db import router
from django.utils import timezone

from posthog.models.scoping.manager import resolve_effective_team_id

from products.stamphog.backend.facade import contracts
from products.stamphog.backend.facade.api import _review_run_to_dto, broadcast_request_to_dto
from products.stamphog.backend.facade.enums import BroadcastRequestSource, BroadcastRequestStatus
from products.stamphog.backend.logic.broadcast_requests import (
    BroadcastRequestAsk,
    card_cannot_post,
    requester_card_count,
)
from products.stamphog.backend.models import BroadcastRequest
from products.stamphog.backend.tasks.tasks import (
    request_manual_review,
    reviewing_team_ids as _reviewing_team_ids,
)

__all__ = ["request_review", "reviewing_team_ids"]


def reviewing_team_ids(repository: str, team_ids: Collection[int]) -> list[int]:
    """The teams among ``team_ids``, environments included, where stamphog reviews ``repository``, by
    the rule ``request_review`` applies."""
    return _reviewing_team_ids(repository, team_ids)


def request_review(
    team_id: int,
    *,
    user_id: int | None,
    repository: str,
    pr_number: int,
    allow_broadcast: bool = False,
    note: str = "",
    requested_via: BroadcastRequestSource = BroadcastRequestSource.API,
    requester_slack_user_id: str = "",
    requester_github_login: str = "",
) -> contracts.ReviewRequestResultDTO:
    """Queue a stamphog review of a PR, or return the run already covering its current head.

    ``team_id`` may be an environment: the review runs in its project. Raises ``contracts.ReviewRequestRefusedError`` when the request is refused. The review itself
    runs asynchronously, and whether it approves is stamphog's decision.

    ``allow_broadcast`` also asks people to review in the repository's Slack channel when stamphog does not
    approve, or returns the pull request's request that is already active. ``note`` goes to Slack
    only, and only with ``allow_broadcast``.
    """
    if note and not allow_broadcast:
        raise ValueError("A note needs allow_broadcast set")
    ask = (
        BroadcastRequestAsk(
            requested_by_user_id=user_id,
            requested_via=requested_via,
            requester_slack_user_id=requester_slack_user_id,
            requester_github_login=requester_github_login,
            note=note,
        )
        if allow_broadcast
        else None
    )
    project_id = resolve_effective_team_id(team_id)
    queued = request_manual_review(project_id, user_id, repository, pr_number, allow_broadcast=ask)
    run = _review_run_to_dto(queued.run)
    if queued.broadcast_request is None:
        return contracts.ReviewRequestResultDTO(run=run, created=queued.created)
    broadcast_request = broadcast_request_to_dto(project_id, queued.broadcast_request.id)
    card_blocked = False
    card_count = None
    if broadcast_request.status == BroadcastRequestStatus.OPEN and not broadcast_request.deliveries:
        using = router.db_for_write(BroadcastRequest)
        card_blocked = card_cannot_post(queued.broadcast_request, using=using)
        # A request that someone else made counts their cards, not this caller's, so only a new one shows a count.
        if queued.broadcast_request_created and not card_blocked:
            card_count = requester_card_count(queued.broadcast_request, at=timezone.now(), using=using)
    return contracts.ReviewRequestResultDTO(
        run=dataclasses.replace(run, broadcast_request=broadcast_request),
        created=queued.created,
        broadcast_request=broadcast_request,
        broadcast_request_created=queued.broadcast_request_created,
        broadcast_request_card_blocked=card_blocked,
        broadcast_request_channel_name=queued.broadcast_request_channel_name,
        broadcast_request_card_count=card_count,
    )
