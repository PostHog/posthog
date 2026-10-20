"""The rules every review request follows, whichever trigger asks.

- Resolution writes to the branch only after a Full review, only when the pull request's owner opted
  in (`resolve_comments`). Who triggered does not matter: one person's opt-in never writes to a
  teammate's branch.
- No Flash after Full: once a Full review of a pull request is published, Flash reviews of it stop.

The checks are small functions so every trigger can call the same ones.
"""

from posthog.dataclasses import frozen

from products.review_hog.backend.facade.enums import ReviewRequestRefusal
from products.review_hog.backend.models import ReviewReport, ReviewUserSettings
from products.review_hog.backend.reviewer.constants import REVIEW_MODE_FLASH, REVIEW_MODE_FULL
from products.review_hog.backend.reviewer.review_state import published_heads_by_mode


@frozen
class ResolutionGate:
    owner_user_id: int | None
    owner_opted_in: bool

    def allows(self, review_mode: str) -> bool:
        return review_mode == REVIEW_MODE_FULL and self.owner_user_id is not None and self.owner_opted_in

    @classmethod
    def load(cls, team_id: int, owner_user_id: int | None) -> "ResolutionGate":
        opted_in = (
            owner_user_id is not None and ReviewUserSettings.load_preferences(team_id, owner_user_id).resolve_comments
        )
        return cls(owner_user_id=owner_user_id, owner_opted_in=opted_in)


def full_review_published(report: ReviewReport | None) -> bool:
    return report is not None and REVIEW_MODE_FULL in published_heads_by_mode(report)


def trigger_review_mode(team_id: int, repository: str, pr_number: int) -> str:
    """The mode a label or Inbox trigger starts: Standard, or Deep once the pull request has a Deep review.

    A Standard request after a published Deep review is dropped, so without the Deep case the trigger
    would do nothing on such a pull request.
    """
    # Repository casing can differ per trigger, like the report lookup in `request_pr_review`.
    report = ReviewReport.objects.for_team(team_id).filter(repository__iexact=repository, pr_number=pr_number).first()
    return REVIEW_MODE_FULL if full_review_published(report) else REVIEW_MODE_FLASH


def flash_refusal(report: ReviewReport | None, review_mode: str) -> ReviewRequestRefusal | None:
    if review_mode == REVIEW_MODE_FLASH and full_review_published(report):
        return ReviewRequestRefusal.FLASH_AFTER_FULL
    return None
