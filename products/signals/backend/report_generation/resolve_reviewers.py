from __future__ import annotations

import json
import logging
from collections import Counter
from collections.abc import Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from django.db.models import Expression, Prefetch, Q, QuerySet, Subquery, Value
from django.db.models.fields.json import KeyTextTransform, KeyTransform
from django.db.models.functions import Concat, Lower
from django.utils import timezone

from social_django.models import UserSocialAuth

from posthog.egress.github.transport import GitHubRateLimitError
from posthog.models.integration import GitHubIntegration, Integration
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.user_integration import UserIntegration

from products.signals.backend.contracts import RelevantCommit
from products.signals.backend.report_generation.repo_activity import (
    ACTIVITY_WINDOW_DAYS,
    REPO_WIDE_AREA,
    ContributorActivity,
    area_fallback_chain,
    areas_for_paths,
    get_area_activity,
    repository_activity_needs_rebuild,
)

from ..models import SignalReportArtefact

logger = logging.getLogger(__name__)

MAX_SUGGESTED_REVIEWERS = 3
MAX_COMMIT_LOOKUPS = 15

RECENCY_FULL_WEIGHT_DAYS = 30
RECENCY_DECAY_FLOOR = 0.3
STALE_BLAME_MULTIPLIER = 0.15
# Caps activity-only fallbacks below blame candidates: they only win when every blame author is stale.
ACTIVITY_ONLY_SCORE_CAP = 0.25
ACTIVITY_BONUS_SATURATION_COMMITS = 10
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
    """Resolve commit hashes to up to 3 reviewers, preferring recently-active owners.

    Blame candidates (commit authors, weighted by finding position) are recency-shaped
    against cached area activity, and recently-active area contributors enter as capped
    fallbacks — see ``_score_candidates``. With no activity data available at all, scoring
    degrades to blame-only.
    """
    if not commit_hashes_with_reasons or not repository:
        return []

    try:
        github = GitHubIntegration.first_for_team_repository(team_id, repository)
    except GitHubRateLimitError:
        # Suggested reviewers are an optional artefact — omit them rather than failing the report.
        logger.info("GitHub rate limited while probing %s, skipping reviewer resolution", repository)
        return []
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
            try:
                author_results[future_to_idx[future]] = future.result()
            except GitHubRateLimitError:
                # Best-effort: score reviewers from whatever lookups landed before the limit.
                logger.info("GitHub rate limited during commit author lookups for %s", repository)

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

    touched_paths = [path for info in author_results.values() if info is not None for path in info.file_paths]
    activity_by_login = _relevant_area_activity(team_id, repository, touched_paths)

    return _rank_scored_candidates(login_weights, activity_by_login, login_commits, login_names)


def rank_assignee_candidates(
    team_id: int,
    repository: str,
    candidate_logins: list[str],
    touched_paths: list[str],
) -> list[_ResolvedReviewer]:
    """Rank agent-proposed assignees through the area-activity system.

    The ordered candidate list is position-weighted like blame commits, blended with
    cached recent activity for the touched paths, and topped up with active-in-area
    fallbacks — the same scoring the deterministic reviewer path uses. Returns an empty
    list when nothing is known (no candidates and no activity data), so callers keep
    their own ordering as the fallback.
    """
    deduped = list(dict.fromkeys(login.strip().lower() for login in candidate_logins if login.strip()))
    login_weights: Counter[str] = Counter()
    total = len(deduped)
    for i, login in enumerate(deduped):
        login_weights[login] = total - i

    activity_by_login = _relevant_area_activity(team_id, repository, touched_paths)
    if not activity_by_login and not login_weights:
        return []
    return _rank_scored_candidates(login_weights, activity_by_login, login_commits={}, login_names={})


def _rank_scored_candidates(
    login_weights: Counter[str],
    activity_by_login: dict[str, _AreaContributor],
    login_commits: dict[str, list[RelevantCommit]],
    login_names: dict[str, str | None],
) -> list[_ResolvedReviewer]:
    scores = _score_candidates(login_weights, activity_by_login)

    def rank_key(item: tuple[str, float]) -> tuple[float, int, str]:
        login, score = item
        activity = activity_by_login.get(login)
        return (-score, -(activity.commit_count if activity else 0), login)

    ranked = sorted(scores.items(), key=rank_key)[:MAX_SUGGESTED_REVIEWERS]
    reviewers: list[_ResolvedReviewer] = []
    for login, score in ranked:
        commits = list(login_commits.get(login, []))
        activity = activity_by_login.get(login)
        if not commits and activity is not None:
            commits = [
                RelevantCommit(
                    sha=activity.last_commit_sha,
                    url=activity.last_commit_url,
                    reason=(
                        f"Recently active in {_area_label(activity.area)} "
                        f"({activity.commit_count} commit(s) in the last {ACTIVITY_WINDOW_DAYS} days)."
                    ),
                )
            ]
        name = login_names.get(login)
        if name is None and activity is not None:
            name = activity.name
        reviewers.append(_ResolvedReviewer(login=login, name=name, commits=commits, weight=score))
    return reviewers


def _area_label(area: str) -> str:
    if area == REPO_WIDE_AREA:
        return "this repository"
    if area == "":
        return "the repository root"
    return f"`{area}`"


@dataclass(frozen=True)
class _AreaContributor:
    """A login's activity aggregated across the report's relevant areas."""

    name: str | None
    commit_count: int
    days_since_last_commit: float
    last_commit_sha: str
    last_commit_url: str
    area: str  # the area of the evidence (freshest) commit, for evidence wording


def _relevant_area_activity(
    team_id: int,
    repository: str,
    touched_paths: list[str],
) -> dict[str, _AreaContributor]:
    """Aggregate cached area activity across the areas the finding commits touched.

    Cache-only; a missing or stale map schedules an async rebuild and this report falls
    back to whatever is cached (possibly nothing). An area with no active contributors
    falls back up its chain (parent directory, then repo-wide) — someone active nearby
    beats nobody. Returns an empty dict when nothing is known — callers must treat that
    as "no signal", not "nobody is active".
    """
    areas = areas_for_paths(touched_paths)
    if not areas:
        return {}
    chains = [area_fallback_chain(area) for area in areas]
    lookup_areas = list(dict.fromkeys(area for chain in chains for area in chain))
    activity_by_area = get_area_activity(team_id, repository, lookup_areas)
    if repository_activity_needs_rebuild(team_id, repository):
        _schedule_activity_rebuild(team_id, repository)

    now = timezone.now()
    merged: dict[str, _AreaContributor] = {}
    used_levels: set[str] = set()
    for chain in chains:
        level = next((area for area in chain if activity_by_area.get(area)), None)
        if level is None or level in used_levels:
            continue
        used_levels.add(level)
        for contributor in activity_by_area[level]:
            existing = merged.get(contributor.login)
            merged[contributor.login] = _merge_contributor(existing, contributor, level, now)
    return merged


def _schedule_activity_rebuild(team_id: int, repository: str) -> None:
    # Local import: tasks.py imports repo_activity at load time.
    from products.signals.backend.tasks import rebuild_signal_repository_activity

    try:
        rebuild_signal_repository_activity.delay(team_id=team_id, repository=repository)
    except Exception:
        logger.warning("Failed to schedule activity rebuild for %s", repository, exc_info=True)


def _merge_contributor(
    existing: _AreaContributor | None,
    incoming: ContributorActivity,
    area: str,
    now: datetime,
) -> _AreaContributor:
    days_since = max(0.0, (now - incoming.last_commit_at).total_seconds() / 86400)
    if existing is None:
        return _AreaContributor(
            name=incoming.name,
            commit_count=incoming.commit_count,
            days_since_last_commit=days_since,
            last_commit_sha=incoming.last_commit_sha,
            last_commit_url=incoming.last_commit_url,
            area=area,
        )
    # Evidence follows the freshest commit, so sha/url/area always agree with
    # days_since_last_commit.
    keep_incoming_evidence = days_since < existing.days_since_last_commit
    return _AreaContributor(
        name=existing.name or incoming.name,
        commit_count=existing.commit_count + incoming.commit_count,
        days_since_last_commit=min(existing.days_since_last_commit, days_since),
        last_commit_sha=incoming.last_commit_sha if keep_incoming_evidence else existing.last_commit_sha,
        last_commit_url=incoming.last_commit_url if keep_incoming_evidence else existing.last_commit_url,
        area=area if keep_incoming_evidence else existing.area,
    )


def _recency_multiplier(days_since_last_commit: float | None) -> float:
    """How much of a blame weight survives, given the author's latest area commit."""
    if days_since_last_commit is None:
        return STALE_BLAME_MULTIPLIER
    if days_since_last_commit <= RECENCY_FULL_WEIGHT_DAYS:
        return 1.0
    if days_since_last_commit >= ACTIVITY_WINDOW_DAYS:
        return STALE_BLAME_MULTIPLIER
    span = ACTIVITY_WINDOW_DAYS - RECENCY_FULL_WEIGHT_DAYS
    progress = (days_since_last_commit - RECENCY_FULL_WEIGHT_DAYS) / span
    return 1.0 - progress * (1.0 - RECENCY_DECAY_FLOOR)


def _score_candidates(
    login_weights: Counter[str],
    activity_by_login: dict[str, _AreaContributor],
) -> dict[str, float]:
    """Blend blame weights with area recency; add capped activity-only fallbacks.

    Invariants: a freshly-active area contributor always outranks a blame author who is
    gone from the area (their base starts above the stale floor), and never outranks a
    blame author still active within the window (the cap sits below the decay floor).
    With no activity data at all, blame weights pass through unchanged (legacy behavior).
    """
    if not activity_by_login:
        return {login: float(weight) for login, weight in login_weights.items()}

    max_blame_weight = float(max(login_weights.values(), default=0)) or 1.0
    scores: dict[str, float] = {}
    for login, weight in login_weights.items():
        activity = activity_by_login.get(login)
        multiplier = _recency_multiplier(activity.days_since_last_commit if activity else None)
        scores[login] = float(weight) * multiplier

    for login, activity in activity_by_login.items():
        if login in scores:
            continue
        saturation = min(activity.commit_count, ACTIVITY_BONUS_SATURATION_COMMITS) / ACTIVITY_BONUS_SATURATION_COMMITS
        base = STALE_BLAME_MULTIPLIER + (ACTIVITY_ONLY_SCORE_CAP - STALE_BLAME_MULTIPLIER) * saturation
        scores[login] = max_blame_weight * base * _recency_multiplier(activity.days_since_last_commit)
    return scores


@dataclass
class _ResolvedReviewer:
    """Intermediate result from commit resolution."""

    login: str
    name: str | None
    commits: list[RelevantCommit]
    weight: float


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


MAX_PROJECT_MEMBERS = 200


@dataclass
class ProjectMemberIdentity:
    """One project member's routing identity — enough for a scout to pick a `suggested_reviewers` entry."""

    user_uuid: str
    email: str
    first_name: str
    last_name: str
    github_login: str | None


def list_project_members(
    team: Team, *, search: str | None = None, limit: int = MAX_PROJECT_MEMBERS
) -> list[ProjectMemberIdentity]:
    """Members with access to ``team`` — their UUID/email/name and resolved GitHub login.

    Backs the `scout-members-list` tool: the cold-start reviewer-routing path for a scout
    that can't read an owner off a fetched entity's ``created_by`` and has no cached
    ``reviewer:<area>`` memory or inbox precedent. Scoped via ``Team.all_users_with_access()`` so
    private-project access control is honored — a scout on a private project sees only the people who
    can actually act on it, not the whole org roster — and inactive users are excluded.
    ``get_github_login`` reads the same prefetched relations the reviewer resolver uses, so a member
    with no linked GitHub identity gets a null login rather than dropping out. ``search``
    (case-insensitive, over email + name) narrows the roster; the result is capped at ``limit`` so a
    large org can't push its whole directory into the scout's context in one call.
    """
    users = team.all_users_with_access()
    if search:
        # Match the search against email, each name part, AND the concatenated full name, so a
        # display-name query like "Jane Doe" still finds a member stored as first_name="Jane",
        # last_name="Doe" — not just one whose email happens to contain the whole phrase.
        users = users.annotate(_full_name=Concat("first_name", Value(" "), "last_name")).filter(
            Q(email__icontains=search)
            | Q(first_name__icontains=search)
            | Q(last_name__icontains=search)
            | Q(_full_name__icontains=search)
        )
    users = users.prefetch_related(*_github_identity_prefetches()).order_by("id")[:limit]
    return [
        ProjectMemberIdentity(
            user_uuid=str(user.uuid),
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
            github_login=(login.lower() if (login := user.get_github_login()) else None),
        )
        for user in users
    ]


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
    """Case-insensitive match: ``Lower(login_field_lookup) ∈ logins_lower`` (expects lowercased logins).

    Uses ``->>`` for the final JSON key so the operand of ``LOWER`` is text — Postgres has
    no ``lower(jsonb)`` overload, and Django's plain ``__`` JSON path lookups render to
    ``->`` (jsonb).
    """
    column, *intermediate_keys, final_key = login_field_lookup.split("__")
    expr: str | Expression = column
    for key in intermediate_keys:
        expr = KeyTransform(key, expr)
    return qs.annotate(_github_login_lc_lookup=Lower(KeyTextTransform(final_key, expr))).filter(
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
