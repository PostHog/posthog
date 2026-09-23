"""Facade for asking stamphog to review one pull request on a PostHog user's behalf.

Lives apart from ``api.py`` for the same reason ``tasks.py`` and ``github.py`` do: this path pulls
the GitHub client and the Celery task module, which must stay off the module review_hog's settings
serializer imports on every request.
"""

from products.stamphog.backend.facade import contracts
from products.stamphog.backend.facade.api import _review_run_to_dto
from products.stamphog.backend.tasks.tasks import request_manual_review

__all__ = ["request_review"]


def request_review(
    team_id: int, *, user_id: int | None, repository: str, pr_number: int
) -> contracts.ReviewRequestResultDTO:
    """Queue a stamphog review of a PR, or return the run already covering its current head.

    Raises ``contracts.ReviewRequestRefusedError`` when the request is refused. The review itself
    runs asynchronously, and whether it approves is stamphog's decision.
    """
    queued = request_manual_review(team_id, user_id, repository, pr_number)
    return contracts.ReviewRequestResultDTO(run=_review_run_to_dto(queued.run), created=queued.created)
