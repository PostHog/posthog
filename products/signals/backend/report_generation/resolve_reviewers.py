from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from typing import Any

from social_django.models import UserSocialAuth

from posthog.schema import RelevantCommit

from posthog.models.integration import GitHubIntegration
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team

logger = logging.getLogger(__name__)

MAX_SUGGESTED_REVIEWERS = 3


@dataclass
class _ResolvedReviewer:
    """Intermediate result from commit resolution."""

    login: str
    name: str | None
    commits: list[RelevantCommit]
    weight: int


def resolve_suggested_reviewers(
    team_id: int,
    repository: str,
    commit_hashes_with_reasons: dict[str, str],
) -> list[_ResolvedReviewer]:
    """Resolve commit hashes to up to 3 reviewers with their relevant commits.

    Commits earlier in the dict are weighted more heavily (they come from
    higher-priority findings and more critical code paths).
    """
    if not commit_hashes_with_reasons or not repository:
        return []

    github = GitHubIntegration.first_for_team_repository(team_id, repository)
    if github is None:
        logger.info(
            "No GitHub integration for team %d can access %s, cannot resolve reviewers",
            team_id,
            repository,
        )
        return []

    # Weight earlier commits more heavily (position-based weighting)
    login_weights: Counter[str] = Counter()
    login_commits: dict[str, list[RelevantCommit]] = {}
    login_names: dict[str, str | None] = {}
    total = len(commit_hashes_with_reasons)

    for i, (sha, reason) in enumerate(commit_hashes_with_reasons.items()):
        author_info = github.get_commit_author_info(repository, sha)
        if author_info:
            login = author_info.login
            # Earlier commits get higher weight
            weight = total - i
            login_weights[login] += weight
            login_commits.setdefault(login, []).append(
                RelevantCommit(sha=sha, url=author_info.commit_url, reason=reason)
            )
            # Keep the first name we see (from highest-weight commit)
            if login not in login_names:
                login_names[login] = author_info.name

    # Return top reviewers by weighted score
    return [
        _ResolvedReviewer(
            login=login,
            name=login_names.get(login),
            commits=login_commits.get(login, []),
            weight=weight,
        )
        for login, weight in login_weights.most_common(MAX_SUGGESTED_REVIEWERS)
    ]


def _build_login_to_user_map(team_id: int) -> dict[str, Any] | None:
    """Build a mapping of GitHub login -> PostHog User for the team's org.

    Returns None if the team doesn't exist, otherwise a dict (possibly empty).
    """
    try:
        org_id = Team.objects.values_list("organization_id", flat=True).get(id=team_id)
    except Team.DoesNotExist:
        return None

    org_member_user_ids = OrganizationMembership.objects.filter(
        organization_id=org_id,
    ).values_list("user_id", flat=True)

    social_auths = (
        UserSocialAuth.objects.filter(
            provider="github",
            user_id__in=org_member_user_ids,
        )
        .select_related("user")
        .only(
            "extra_data",
            "user__id",
            "user__uuid",
            "user__first_name",
            "user__last_name",
            "user__email",
        )
    )

    login_to_user: dict[str, Any] = {}
    for sa in social_auths:
        extra = sa.extra_data
        if isinstance(extra, dict):
            login = extra.get("login")
        else:
            continue
        if login:
            login_to_user[login.lower()] = sa.user

    return login_to_user


def enrich_reviewer_dicts_with_org_members(
    team_id: int,
    reviewer_dicts: list[dict],
) -> list[dict]:
    """Enrich reviewer dicts (from artefact content) with fresh PostHog user info.

    Called at read time so that users who connect their GitHub account after the
    artefact was created show up properly.
    """
    if not reviewer_dicts:
        return reviewer_dicts

    login_to_user = _build_login_to_user_map(team_id)

    enriched: list[dict] = []
    for r in reviewer_dicts:
        login = r.get("github_login", "")
        user = login_to_user.get(login.lower()) if login_to_user and login else None
        enriched.append(
            {
                **r,
                "user": {
                    "id": user.id,
                    "uuid": str(user.uuid),
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "email": user.email,
                }
                if user
                else None,
            }
        )

    return enriched
