"""Find project members who own the code named by a report finding."""

import re
import logging
from dataclasses import dataclass

from django.db.models.functions import Lower

from owners_yaml.matcher import compile_pattern, normalize_path

from posthog.dataclasses import frozen
from posthog.egress.limiter.policies import Priority
from posthog.models.integration import GitHubIntegration
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.ownership.github_files import AuthenticatedRepoFiles, GitHubFilesFetcher
from posthog.ownership.paths import UNOWNED_TEAM, resolve_path_owners

from products.access_control.backend.facade.api import likely_roles, valid_role_member_user_ids_by_role
from products.signals.backend.report_generation.resolve_reviewers import (
    _github_identity_prefetches,
    _with_team_github_integrations,
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
    login: str | None
    reason: str
    user_uuid: str | None = None


@frozen
class _CandidateIdentity:
    key: str
    login: str | None
    user_uuid: str | None


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


def _extract_org_team_handles(org: str, groups: list[tuple[list[str], str]]) -> dict[str, str]:
    normalized_org = org.lower()
    team_handles: dict[str, str] = {}
    for owner_handles, _ in groups:
        for owner in owner_handles:
            if not owner.startswith("@") or "/" not in owner[1:]:
                continue
            owner_org, slug = owner[1:].split("/", 1)
            if owner_org.lower() == normalized_org and _TEAM_SLUG.fullmatch(slug):
                team_handles.setdefault(slug.lower(), f"@{owner_org}/{slug}")
    return team_handles


def _candidate_identity_for_user(user: User) -> _CandidateIdentity:
    raw_login = user.get_github_login()
    login = raw_login.lower() if raw_login else None
    user_uuid = str(user.uuid)
    key = login if login else f"uuid:{user_uuid}"
    return _CandidateIdentity(key=key, login=login, user_uuid=user_uuid)


def _resolve_role_team_members(
    team: Team,
    org: str,
    groups: list[tuple[list[str], str]],
) -> dict[str, list[_CandidateIdentity]]:
    team_handles = _extract_org_team_handles(org, groups)
    if not team_handles:
        return {}

    matched_roles = likely_roles(
        list(team_handles.values()),
        organization_id=team.organization_id,
        provider="github",
    )
    if not matched_roles:
        return {}

    role_user_ids = valid_role_member_user_ids_by_role(role_ids={role.id for role in matched_roles.values()})
    all_user_ids = {user_id for ids in role_user_ids.values() for user_id in ids}
    if not all_user_ids:
        return {}

    accessible_users = _with_team_github_integrations(
        team.all_users_with_access()
        .filter(id__in=all_user_ids)
        .prefetch_related(*_github_identity_prefetches())
        .order_by("id")
    )
    users_by_id: dict[int, User] = {user.id: user for user in accessible_users}

    resolved_by_slug: dict[str, list[_CandidateIdentity]] = {}
    for slug, handle in team_handles.items():
        matched_role = matched_roles.get(handle)
        if matched_role is None:
            continue
        identities: dict[str, _CandidateIdentity] = {}
        for user_id in sorted(role_user_ids.get(matched_role.id, ())):
            if (user := users_by_id.get(user_id)) is not None:
                identity = _candidate_identity_for_user(user)
                identities.setdefault(identity.key, identity)
        if identities:
            resolved_by_slug[slug] = list(identities.values())
    return resolved_by_slug


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
        github = GitHubIntegration.first_for_team_repository(
            team_id, repository, source="signals_reviewers", priority=Priority.BATCH
        )
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

    role_team_members: dict[str, list[_CandidateIdentity]] = {}
    try:
        role_team_members = _resolve_role_team_members(team, org, groups)
    except Exception:
        logger.exception("Could not resolve PostHog role mappings for %s", repository)

    team_logins: dict[str, list[str]] = {}
    group_candidates: list[tuple[list[str], list[_CandidateIdentity], str]] = []
    for owner_handles, reason in groups:
        unresolved_logins: list[str] = []
        direct_identities: list[_CandidateIdentity] = []
        for owner in owner_handles:
            if not owner.startswith("@"):
                if login := email_logins.get(owner):
                    unresolved_logins.append(login.lower())
                continue
            handle = owner[1:]
            if "/" not in handle:
                if _TEAM_SLUG.fullmatch(handle):
                    unresolved_logins.append(handle.lower())
                continue
            owner_org, slug = handle.split("/", 1)
            normalized_slug = slug.lower()
            if owner_org.lower() != org.lower() or not _TEAM_SLUG.fullmatch(slug):
                continue
            if normalized_slug in role_team_members:
                direct_identities.extend(role_team_members[normalized_slug])
                continue
            if normalized_slug not in team_logins:
                try:
                    response = github.list_team_members(org, normalized_slug)
                    team_logins[normalized_slug] = response.get("logins", []) if response.get("success") else []
                except Exception:
                    logger.exception("Could not list code owner team members for %s", repository)
                    team_logins[normalized_slug] = []
            unresolved_logins.extend(login.lower() for login in team_logins[normalized_slug])
        if unresolved_logins or direct_identities:
            group_candidates.append((list(dict.fromkeys(unresolved_logins)), direct_identities, reason))

    all_unresolved_logins = [login for logins, _, _ in group_candidates for login in logins]
    members: dict[str, User] = {}
    if all_unresolved_logins:
        try:
            members = resolve_org_github_login_to_users(team_id, all_unresolved_logins)
            accessible_ids = set(
                team.all_users_with_access()
                .filter(id__in=[member.id for member in members.values()])
                .values_list("id", flat=True)
            )
            members = {login: member for login, member in members.items() if member.id in accessible_ids}
        except Exception:
            logger.exception("Could not match code owners to project members for %s", repository)
            if not any(direct for _, direct, _ in group_candidates):
                return []

    reviewers: list[OwnershipReviewer] = []
    covered: set[str] = set()
    selected_sources: set[str] = set()
    for logins, direct_identities, reason in group_candidates:
        source = reason.split(":", 1)[0]
        if source in selected_sources:
            continue
        group_identities: dict[str, _CandidateIdentity] = {}
        for identity in direct_identities:
            group_identities.setdefault(identity.key, identity)
        for login in logins:
            if login in members:
                group_identities.setdefault(
                    login,
                    _CandidateIdentity(key=login, login=login, user_uuid=None),
                )
        available_keys = set(group_identities.keys()) - covered
        if not available_keys:
            continue

        chosen_key = next((login for login in preferred_logins if login in available_keys), None)
        if chosen_key is None:
            login_keys = sorted(key for key in available_keys if group_identities[key].login is not None)
            chosen_key = login_keys[0] if login_keys else min(available_keys)

        chosen = group_identities[chosen_key]
        covered.update(group_identities.keys())
        covered.update(logins)
        selected_sources.add(source)
        reviewers.append(
            OwnershipReviewer(
                login=chosen.login,
                reason=reason,
                user_uuid=chosen.user_uuid if chosen.login is None else None,
            )
        )
    return reviewers
