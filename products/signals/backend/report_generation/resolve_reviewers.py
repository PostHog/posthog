from __future__ import annotations

import json
import logging
from collections import Counter
from collections.abc import Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Literal

from django.db.models import Prefetch, QuerySet, Subquery
from django.db.models.functions import Lower

from social_django.models import UserSocialAuth

from posthog.schema import RelevantCommit

from posthog.models.integration import GitHubIntegration, Integration
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.user_integration import UserIntegration

from ..models import SignalReportArtefact

logger = logging.getLogger(__name__)

MAX_SUGGESTED_REVIEWERS = 3
MAX_COMMIT_LOOKUPS = 15
GitHubLoginFieldLookup = Literal[
    "extra_data__login",
    "config__github_user__login",
    "config__connecting_user_github_login",
]


def enrich_reviewer_dicts_with_org_members(
    team_id: int,
    reviewer_dicts: list[dict],
    *,
    login_to_user: Mapping[str, User] | None = None,
) -> list[dict]:
    """Enrich reviewer dicts (from artefact content) with fresh PostHog user info.

    Called at read time so that users who connect their GitHub account after the
    artefact was created show up properly.
    """
    if not reviewer_dicts:
        return reviewer_dicts

    resolved_map: Mapping[str, User]
    if login_to_user is not None:
        resolved_map = login_to_user
    else:
        wanted = normalized_github_logins_from_reviewer_payloads(reviewer_dicts)
        resolved_map = resolve_org_github_login_to_users(team_id, wanted) if wanted else {}

    enriched: list[dict] = []
    for r in reviewer_dicts:
        login = r.get("github_login", "")
        user = resolved_map.get(login.lower()) if login else None
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


def normalized_github_logins_from_suggested_reviewer_artefacts(
    artefacts: Iterable[SignalReportArtefact],
) -> frozenset[str]:
    out: set[str] = set()
    for art in artefacts:
        if art.type != SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS:
            continue
        try:
            parsed_list = json.loads(art.content)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        if not isinstance(parsed_list, list):
            continue
        out.update(normalized_github_logins_from_reviewer_payloads(parsed_list))
    return frozenset(out)


def normalized_github_logins_from_reviewer_payloads(rows: Iterable[object]) -> frozenset[str]:
    logins: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw = row.get("github_login")
        if not raw:
            continue
        s = str(raw).strip().lower()
        if s:
            logins.add(s)
    return frozenset(logins)


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

    # Cap lookups — we only need 3 reviewers, so diminishing returns past ~15 commits.
    items = list(commit_hashes_with_reasons.items())[:MAX_COMMIT_LOOKUPS]
    total = len(items)

    # Fetch all commit author info in parallel (IO-bound GitHub API calls)
    author_results: dict[int, Any] = {}
    with ThreadPoolExecutor(max_workers=min(total, 5)) as pool:
        future_to_idx = {
            pool.submit(github.get_commit_author_info, repository, sha): i for i, (sha, _reason) in enumerate(items)
        }
        for future in as_completed(future_to_idx):
            author_results[future_to_idx[future]] = future.result()

    # Weight earlier commits more heavily (position-based weighting)
    login_weights: Counter[str] = Counter()
    login_commits: dict[str, list[RelevantCommit]] = {}
    login_names: dict[str, str | None] = {}

    for i, (sha, reason) in enumerate(items):
        author_info = author_results.get(i)
        if author_info:
            login = author_info.login
            weight = total - i
            login_weights[login] += weight
            login_commits.setdefault(login, []).append(
                RelevantCommit(sha=sha, url=author_info.commit_url, reason=reason)
            )
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


@dataclass
class _ResolvedReviewer:
    """Intermediate result from commit resolution."""

    login: str
    name: str | None
    commits: list[RelevantCommit]
    weight: int


def get_org_member_github_login_to_user_map(team_id: int) -> dict[str, User] | None:
    """Build a mapping of GitHub login -> PostHog User for the team's org.

    Returns None if the team doesn't exist, otherwise a dict (possibly empty).
    """
    try:
        org_id = str(Team.objects.values_list("organization_id", flat=True).get(id=team_id))
    except Team.DoesNotExist:
        return None

    candidate_ids = _candidate_user_ids_for_organization(org_id)
    if not candidate_ids:
        return {}

    users = User.objects.filter(id__in=candidate_ids).prefetch_related(*_github_identity_prefetches()).order_by("id")

    login_to_user: dict[str, User] = {}
    for user in users:
        login = user.get_github_login()
        if login:
            login_to_user[login.lower()] = user

    return login_to_user


def get_org_member_github_logins_by_user_uuid(team_id: int, user_uuids: list[str]) -> dict[str, str]:
    """Build a mapping of PostHog user UUID string -> GitHub login for org members on the team."""
    if not user_uuids:
        return {}

    try:
        org_id = str(Team.objects.values_list("organization_id", flat=True).get(id=team_id))
    except Team.DoesNotExist:
        return {}

    org_member_user_ids = list(
        OrganizationMembership.objects.filter(
            organization_id=org_id,
            user__uuid__in=user_uuids,
        ).values_list("user_id", flat=True)
    )
    if not org_member_user_ids:
        return {}

    users = User.objects.filter(id__in=org_member_user_ids).prefetch_related(*_github_identity_prefetches())

    user_uuid_to_login: dict[str, str] = {}
    for user in users:
        login = user.get_github_login()
        if login:
            user_uuid_to_login[str(user.uuid)] = login.lower()

    return user_uuid_to_login


def resolve_org_github_login_to_users(team_id: int, github_logins: Iterable[str]) -> dict[str, User]:
    """Map normalized GitHub login -> org member ``User`` (same identity rules as ``User.get_github_login()``).

    Restricts DB work to users that plausibly match the requested logins.
    """
    logins_normalized = frozenset(s.strip().lower() for s in github_logins if s and str(s).strip())
    if not logins_normalized:
        return {}

    try:
        org_id = str(Team.objects.values_list("organization_id", flat=True).get(id=team_id))
    except Team.DoesNotExist:
        return {}

    candidate_ids = _candidate_user_ids_for_org_and_logins(org_id, logins_normalized)
    if not candidate_ids:
        return {}

    users = User.objects.filter(id__in=candidate_ids).prefetch_related(*_github_identity_prefetches()).order_by("id")

    login_to_user: dict[str, User] = {}
    for user in users:
        gl = user.get_github_login()
        if not gl:
            continue
        k = gl.lower()
        if k in logins_normalized:
            login_to_user[k] = user
    return login_to_user


def _candidate_user_ids_for_organization(org_id: str) -> set[int]:
    """Org member IDs that might have any GitHub identity."""
    mid_sq = Subquery(OrganizationMembership.objects.filter(organization_id=org_id).values("user_id"))
    candidates: set[int] = set()
    candidates.update(
        UserSocialAuth.objects.filter(provider="github", user_id__in=mid_sq).values_list("user_id", flat=True)
    )
    candidates.update(
        UserIntegration.objects.filter(kind=UserIntegration.IntegrationKind.GITHUB, user_id__in=mid_sq).values_list(
            "user_id", flat=True
        )
    )
    candidates.update(
        Integration.objects.filter(kind="github", created_by_id__in=mid_sq)
        .exclude(config__connecting_user_github_login=None)
        .values_list("created_by_id", flat=True)
    )
    return candidates


def _candidate_user_ids_for_org_and_logins(org_id: str, logins_lower: frozenset[str]) -> set[int]:
    """Subset of org members whose stored GitHub identity might match one of ``logins_lower`` (case-insensitive)."""
    if not logins_lower:
        return set()
    mid_sq = Subquery(OrganizationMembership.objects.filter(organization_id=org_id).values("user_id"))
    candidates: set[int] = set()
    candidates.update(
        _filter_github_login_field_lc(
            UserSocialAuth.objects.filter(provider="github", user_id__in=mid_sq),
            "extra_data__login",
            logins_lower,
        ).values_list("user_id", flat=True)
    )
    candidates.update(
        _filter_github_login_field_lc(
            UserIntegration.objects.filter(kind=UserIntegration.IntegrationKind.GITHUB, user_id__in=mid_sq),
            "config__github_user__login",
            logins_lower,
        ).values_list("user_id", flat=True)
    )
    candidates.update(
        _filter_github_login_field_lc(
            Integration.objects.filter(kind="github", created_by_id__in=mid_sq).exclude(
                config__connecting_user_github_login=None
            ),
            "config__connecting_user_github_login",
            logins_lower,
        ).values_list("created_by_id", flat=True)
    )
    return candidates


def _filter_github_login_field_lc(
    qs: QuerySet,
    login_field_lookup: GitHubLoginFieldLookup,
    logins_lower: frozenset[str],
) -> QuerySet:
    """Case-insensitive match: ``Lower(login_field_lookup) ∈ logins_lower`` (expects lowercased logins)."""
    return qs.annotate(_github_login_lc_lookup=Lower(login_field_lookup)).filter(
        _github_login_lc_lookup__in=sorted(logins_lower)
    )


def _github_identity_prefetches() -> tuple[Prefetch, ...]:
    """Prefetch relations read by `User.get_github_login()`."""
    return (
        Prefetch(
            "integrations",
            UserIntegration.objects.filter(kind=UserIntegration.IntegrationKind.GITHUB),
            to_attr="_prefetched_github_user_integrations",
        ),
        Prefetch("social_auth", UserSocialAuth.objects.filter(provider="github")),
        Prefetch(
            "integration_set",
            Integration.objects.filter(kind="github")
            .exclude(config__connecting_user_github_login=None)
            .only("config", "id", "created_by_id"),
            to_attr="_prefetched_github_integrations",
        ),
    )
