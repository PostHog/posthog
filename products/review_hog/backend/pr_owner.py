"""Who owns a pull request: the person whose opt-ins decide what ReviewHog may do to it.

1. The author, when the GitHub login maps to an active member of the project's organization.
2. A self-driving pull request, which the PostHog GitHub App authors for an Inbox report: the report's
   canonical reviewer among the active members (`receivers.pick_reviewer`).
3. Else nobody. A pull request without an owner never gets writes, because nobody opted in to them.

`pick_pr_owner` is pure. `PullRequestOwnerResolver.resolve` loads what it needs. Callers pass the head
branch only for a head in the base repository: a fork's branch name is chosen by the fork's owner, and
the Inbox link matches on it.
"""

from typing import Literal

from posthog.dataclasses import frozen
from posthog.models.instance_setting import get_instance_setting
from posthog.models.organization import OrganizationMembership

from products.review_hog.backend.receivers import pick_reviewer, resolve_assigned_reviewers

PullRequestOwnerSource = Literal["author", "inbox_reviewer", "none"]


@frozen
class PullRequestOwner:
    user_id: int | None
    source: PullRequestOwnerSource


def pick_pr_owner(
    *, author_user_id: int | None, authored_by_posthog_app: bool, inbox_reviewer_id: int | None
) -> PullRequestOwner:
    if author_user_id is not None:
        return PullRequestOwner(user_id=author_user_id, source="author")
    if authored_by_posthog_app and inbox_reviewer_id is not None:
        return PullRequestOwner(user_id=inbox_reviewer_id, source="inbox_reviewer")
    return PullRequestOwner(user_id=None, source="none")


def is_active_member(*, team_id: int, user_id: int) -> bool:
    return OrganizationMembership.objects.filter(
        organization__team__id=team_id, user_id=user_id, user__is_active=True
    ).exists()


def posthog_app_login() -> str | None:
    """The login GitHub gives the PostHog GitHub App, which opens self-driving pull requests."""
    slug = get_instance_setting("GITHUB_APP_SLUG")
    return f"{slug}[bot]".lower() if slug else None


class PullRequestOwnerResolver:
    @staticmethod
    def active_author_id(team_id: int, author_login: str) -> int | None:
        # Pulls in the signals product, which a webhook must not load at import.
        from products.signals.backend.report_generation.resolve_reviewers import (  # noqa: PLC0415
            resolve_org_github_login_to_users,
        )

        login = author_login.strip().lower()
        if not login:
            return None
        user = resolve_org_github_login_to_users(team_id, [login]).get(login)
        # An inactive user cannot act and cannot opt in, so they own nothing.
        if user is None or not is_active_member(team_id=team_id, user_id=user.id):
            return None
        return user.id

    @staticmethod
    def inbox_reviewer_id(team_id: int, *, repository: str, head_branch: str | None) -> int | None:
        # The tasks facade loads the tasks product, which a webhook must not load at import.
        from products.tasks.backend.facade.api import find_signal_implementation_run  # noqa: PLC0415

        run = find_signal_implementation_run(team_id=team_id, repository=repository, head_branch=head_branch)
        if run is None or run.team_id != team_id:
            return None
        # An inactive reviewer cannot act or opt in, so ownership falls to the next active one.
        reviewers = [
            user
            for user in resolve_assigned_reviewers(team_id, run.signal_report_id)
            if is_active_member(team_id=team_id, user_id=user.id)
        ]
        return pick_reviewer(reviewers, run.task_created_by_id) if reviewers else None

    @classmethod
    def resolve(cls, team_id: int, *, repository: str, author_login: str, head_branch: str | None) -> PullRequestOwner:
        author_user_id = cls.active_author_id(team_id, author_login)
        app_login = posthog_app_login()
        authored_by_posthog_app = app_login is not None and author_login.strip().lower() == app_login
        inbox_reviewer_id = None
        if author_user_id is None and authored_by_posthog_app:
            inbox_reviewer_id = cls.inbox_reviewer_id(team_id, repository=repository, head_branch=head_branch)
        return pick_pr_owner(
            author_user_id=author_user_id,
            authored_by_posthog_app=authored_by_posthog_app,
            inbox_reviewer_id=inbox_reviewer_id,
        )
