"""Find project members who own the code named by a report finding."""

import re
import logging
from dataclasses import dataclass

from django.db.models.functions import Lower

from owners_yaml.matcher import compile_pattern, normalize_path

from posthog.egress.limiter.policies import Priority
from posthog.models.integration import GitHubIntegration
from posthog.models.team.team import Team
from posthog.ownership.github_files import AuthenticatedRepoFiles, GitHubFilesFetcher
from posthog.ownership.paths import UNOWNED_TEAM, resolve_path_owners

from products.signals.backend.report_generation.resolve_reviewers import (
    bounded_reviewer_reason,
    resolve_org_github_login_to_users,
)

logger = logging.getLogger(__name__)

_CODEOWNERS_LOCATIONS = (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS")
_MAX_CODEOWNERS_BYTES = 3 * 1024 * 1024
_MAX_PATHS = 12
_TEAM_SLUG = re.compile(r"[A-Za-z0-9._-]+\Z")


@dataclass(frozen=True)
class OwnershipReviewer:
    login: str
    reason: str


def _codeowners_for_paths(github: GitHubIntegration, repository: str, paths: list[str]) -> dict[str, tuple[str, ...]]:
    for location in _CODEOWNERS_LOCATIONS:
        try:
            file = github.get_file_contents(repository, location)
        except Exception:
            logger.exception("Could not read CODEOWNERS from %s", repository)
            return {}
        if file is not None:
            break
    else:
        return {}

    content = file["content"]
    if len(content.encode("utf-8")) >= _MAX_CODEOWNERS_BYTES:
        return {}
    rules = []
    for line in content.splitlines():
        parts = line.split()
        if not parts or parts[0].startswith("#") or parts[0].startswith("!") or "[" in parts[0]:
            continue
        try:
            matcher = compile_pattern(parts[0])
        except ValueError:
            continue
        rules.append((matcher, tuple(parts[1:])))

    return {path: next((owners for matcher, owners in reversed(rules) if matcher.test(path)), ()) for path in paths}


def suggest_repository_owners(
    team_id: int, repository: str, relevant_paths: list[str], preferred_logins: list[str]
) -> list[OwnershipReviewer]:
    """Add one routable member per owning source, preferring recent relevant authors."""
    paths = list(dict.fromkeys(normalize_path(path) for path in relevant_paths if path))[:_MAX_PATHS]
    paths = [path for path in paths if path and ".." not in path.split("/")]
    if not repository or not paths or "/" not in repository:
        return []

    try:
        team = Team.objects.get(id=team_id)
        github = GitHubIntegration.first_for_team_repository(team_id, repository)
        if github is None:
            return []
        codeowners = _codeowners_for_paths(github, repository, paths)
        owners_files = AuthenticatedRepoFiles(
            repository, GitHubFilesFetcher.from_integration(github, priority=Priority.BATCH)
        )
        ownership = resolve_path_owners(repository, paths, files=owners_files)
    except Exception:
        logger.exception("Could not resolve repository owners for %s", repository)
        return []

    org = repository.split("/", 1)[0]
    groups: list[tuple[list[str], str]] = []
    seen_owners: set[tuple[str, ...]] = set()
    if ownership.resolved:
        for path in paths:
            slug = ownership.team_by_path.get(path, UNOWNED_TEAM)
            if slug != UNOWNED_TEAM and _TEAM_SLUG.fullmatch(slug):
                handles = (f"@{org}/{slug}".lower(),)
                if handles not in seen_owners:
                    groups.append((list(handles), bounded_reviewer_reason(f"owners.yaml: {path}") or "owners.yaml"))
                    seen_owners.add(handles)
    for path in paths:
        owners = codeowners.get(path, ())
        codeowner_handles = tuple(owner.lower() for owner in owners)
        if codeowner_handles and codeowner_handles not in seen_owners:
            groups.append((list(codeowner_handles), bounded_reviewer_reason(f"CODEOWNERS: {path}") or "CODEOWNERS"))
            seen_owners.add(codeowner_handles)

    email_logins: dict[str, str] = {}
    email_owners = {owner for owners, _ in groups for owner in owners if "@" in owner[1:]}
    if email_owners:
        try:
            email_logins = {
                member.email.lower(): login
                for member in team.all_users_with_access()
                .annotate(normalized_email=Lower("email"))
                .filter(normalized_email__in=email_owners)
                if (login := member.get_github_login())
            }
        except Exception:
            logger.exception("Could not match code owner emails for %s", repository)
    team_logins: dict[str, list[str]] = {}
    candidates: list[tuple[list[str], str]] = []
    for owner_handles, reason in groups:
        logins: list[str] = []
        for owner in owner_handles:
            if not owner.startswith("@"):
                if login := email_logins.get(owner):
                    logins.append(login.lower())
                continue
            handle = owner[1:]
            if "/" not in handle:
                if _TEAM_SLUG.fullmatch(handle):
                    logins.append(handle.lower())
                continue
            owner_org, slug = handle.split("/", 1)
            if owner_org.lower() != org.lower() or not _TEAM_SLUG.fullmatch(slug):
                continue
            if slug not in team_logins:
                try:
                    response = github.list_team_members(org, slug)
                    team_logins[slug] = response.get("logins", []) if response.get("success") else []
                except Exception:
                    logger.exception("Could not list code owner team members for %s", repository)
                    team_logins[slug] = []
            logins.extend(login.lower() for login in team_logins[slug])
        if logins:
            candidates.append((list(dict.fromkeys(logins)), reason))

    try:
        members = resolve_org_github_login_to_users(team_id, (login for logins, _ in candidates for login in logins))
        accessible_ids = set(
            team.all_users_with_access()
            .filter(id__in=[member.id for member in members.values()])
            .values_list("id", flat=True)
        )
        members = {login: member for login, member in members.items() if member.id in accessible_ids}
    except Exception:
        logger.exception("Could not match code owners to project members for %s", repository)
        return []
    reviewers: list[OwnershipReviewer] = []
    covered: set[str] = set()
    selected_sources: set[str] = set()
    for logins, reason in candidates:
        source = reason.split(":", 1)[0]
        if source in selected_sources:
            continue
        available = (set(logins) & members.keys()) - covered
        if not available:
            continue
        login = next((login for login in preferred_logins if login in available), min(available))
        covered.update(logins)
        selected_sources.add(source)
        reviewers.append(OwnershipReviewer(login=login, reason=reason))
    return reviewers
