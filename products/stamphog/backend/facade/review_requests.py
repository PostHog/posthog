"""Facade for asking stamphog to review one pull request on a PostHog user's behalf.

Lives apart from ``api.py`` for the same reason ``tasks.py`` and ``github.py`` do: this path pulls
the GitHub client and the Celery task module, which must stay off the module review_hog's settings
serializer imports on every request.
"""

import dataclasses
from collections.abc import Collection

from posthog.models.scoping.manager import resolve_effective_team_id

from products.stamphog.backend.facade import contracts
from products.stamphog.backend.facade.api import _review_run_to_dto, human_request_to_dto
from products.stamphog.backend.facade.enums import HumanRequestSource
from products.stamphog.backend.logic.human_requests import HumanRequestAsk
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
    human: bool = False,
    note: str = "",
    requested_via: HumanRequestSource = HumanRequestSource.API,
    requester_slack_user_id: str = "",
) -> contracts.ReviewRequestResultDTO:
    """Queue a stamphog review of a PR, or return the run already covering its current head.

    ``team_id`` may be an environment: the review runs in its project. Raises ``contracts.ReviewRequestRefusedError`` when the request is refused. The review itself
    runs asynchronously, and whether it approves is stamphog's decision.

    ``human`` also asks people to review in the repository's Slack channel when stamphog does not
    approve, or returns the pull request's request that is already active. ``note`` goes to Slack
    only, and only with ``human``.
    """
    if note and not human:
        raise ValueError("A note needs human set")
    ask = (
        HumanRequestAsk(
            requested_by_user_id=user_id,
            requested_via=requested_via,
            requester_slack_user_id=requester_slack_user_id,
            note=note,
        )
        if human
        else None
    )
    project_id = resolve_effective_team_id(team_id)
    queued = request_manual_review(project_id, user_id, repository, pr_number, human=ask)
    run = _review_run_to_dto(queued.run)
    if queued.human_request is None:
        return contracts.ReviewRequestResultDTO(run=run, created=queued.created)
    human_request = human_request_to_dto(project_id, queued.human_request.id)
    return contracts.ReviewRequestResultDTO(
        run=dataclasses.replace(run, human_request=human_request),
        created=queued.created,
        human_request=human_request,
        human_request_channel_name=queued.human_request_channel_name,
    )
