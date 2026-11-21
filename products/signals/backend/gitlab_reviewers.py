"""Requests a reviewer on a Self-driving GitLab merge request, from the report's suggested reviewers.

A suggested reviewer is a PostHog user. Their GitLab account is the gitlab.com identity they sign in
to PostHog with, else the project developer whose public email is their PostHog email. A reviewer
with neither stays a suggestion on the report.
"""

from django.conf import settings

import requests
import structlog
from social_django.models import UserSocialAuth

from posthog.models import Team, User
from posthog.models.integration import GitLabIntegration, GitLabIntegrationError

from products.signals.backend.gitlab_merge_requests import (
    MergeRequestRef,
    fetch_merge_request,
    gitlab_connection_for_merge_request,
)
from products.signals.backend.models import SignalReportAssignment
from products.signals.backend.report_generation.resolve_reviewers import _normalized_reviewer_user_uuid

logger = structlog.get_logger(__name__)

GITLAB_COM_URL = "https://gitlab.com"
_REVIEWABLE_STATES = frozenset({SignalReportAssignment.PrState.DRAFT, SignalReportAssignment.PrState.OPEN})


def _gitlab_sign_in_user_id(user: User) -> int | None:
    # A sign-in identity from another GitLab instance numbers its users differently.
    if settings.SOCIAL_AUTH_GITLAB_API_URL.rstrip("/") != GITLAB_COM_URL:
        return None
    uid = UserSocialAuth.objects.filter(user=user, provider="gitlab").values_list("uid", flat=True).first()
    return int(uid) if isinstance(uid, str) and uid.isascii() and uid.isdigit() else None


def gitlab_reviewer_id(gitlab: GitLabIntegration, user: User) -> int | None:
    """The GitLab id of ``user`` when they can review in the connected project, or None."""
    user_id = _gitlab_sign_in_user_id(user)
    if user_id is not None and gitlab.is_developer(user_id):
        return user_id
    return gitlab.find_developer_by_public_email(user.email) if user.email else None


def ranked_reviewer_users(team_id: int, rows: list[dict]) -> list[User]:
    """The active users with project access that the reviewer rows name by uuid, in row order."""
    uuids = [uuid for row in rows if (uuid := _normalized_reviewer_user_uuid(row.get("user_uuid")))]
    if not uuids:
        return []
    users = {
        str(user.uuid): user
        for user in Team.objects.get(id=team_id).all_users_with_access(user_uuids=uuids).filter(is_active=True)
    }
    return [users[uuid] for uuid in dict.fromkeys(uuids) if uuid in users]


def request_merge_request_reviewer(*, team_id: int, ref: MergeRequestRef, candidates: list[User]) -> int | None:
    """Ask the first candidate with a GitLab identity to review, unless the merge request already has a
    reviewer. Returns the GitLab id asked, or None."""
    integration = gitlab_connection_for_merge_request(team_id, ref)
    if integration is None or not candidates:
        return None
    try:
        merge_request = fetch_merge_request(integration, ref)
        # A reviewer someone already chose wins, the same as on GitHub.
        if merge_request is None or merge_request.state not in _REVIEWABLE_STATES or merge_request.reviewer_ids:
            return None
        gitlab = GitLabIntegration(integration)
        for user in candidates:
            reviewer_id = gitlab_reviewer_id(gitlab, user)
            if reviewer_id is not None:
                gitlab.set_merge_request_reviewers(int(integration.config["project_id"]), ref.number, [reviewer_id])
                return reviewer_id
    except (GitLabIntegrationError, requests.RequestException):
        logger.warning("signals.gitlab_reviewer_request_failed", team_id=team_id, mr_iid=ref.number)
    return None
