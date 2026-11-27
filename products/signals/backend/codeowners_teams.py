from __future__ import annotations

import re
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from uuid import UUID

import structlog

from posthog.dataclasses import frozen
from posthog.egress.limiter.policies import Priority
from posthog.integrations import IntegrationManager
from posthog.models.integration import GitHubIntegration
from posthog.models.team.team import Team
from posthog.ownership.github_files import AuthenticatedRepoFiles, GitHubFilesFetcher

from products.access_control.backend.facade.api import likely_roles
from products.access_control.backend.facade.contracts import RoleMatchSource

logger = structlog.get_logger(__name__)

CODEOWNERS_LOCATIONS: tuple[str, ...] = (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS")
MAX_AUTO_SCANNED_REPOSITORIES = 10
_MAX_SCAN_WORKERS = 5
_REPOSITORY_PATTERN = re.compile(r"^[a-z0-9._-]+/[a-z0-9._-]+$")
_GITHUB_TEAM_RE = re.compile(r"^@([A-Za-z0-9][A-Za-z0-9-]{0,38})/([A-Za-z0-9][A-Za-z0-9._-]*)$")
_SECTION_PREFIX_RE = re.compile(r"^\^?\[[^\]]+\](?:\[\d+\])?\s*(.*)$")


class InvalidCodeownersRepositoryError(ValueError):
    pass


@frozen
class ParsedCodeownersTeam:
    provider_organization_id: str
    team_slug: str


@frozen
class _RepositoryScanTarget:
    github: GitHubIntegration
    repository: str
    pushed_at: str = ""


@frozen
class CodeownersTeam:
    provider_organization_id: str
    team_slug: str
    handle: str
    repositories: tuple[str, ...]
    likely_role_id: UUID | None
    likely_role_name: str | None
    match_source: RoleMatchSource | None


@frozen
class CodeownersTeamsScan:
    teams: tuple[CodeownersTeam, ...]
    scanned_repository_count: int
    total_repository_count: int


def _tokenize_codeowners_line(line: str) -> list[str]:
    tokens: list[str] = []
    current: list[str] = []
    escaped = False
    for index, char in enumerate(line):
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        # An unescaped '#' at the start of a token begins an inline comment.
        if char == "#" and (index == 0 or line[index - 1].isspace()):
            break
        if char.isspace():
            if current:
                tokens.append("".join(current))
                current = []
            continue
        current.append(char)
    if current:
        tokens.append("".join(current))
    return tokens


def parse_codeowners_teams(content: str) -> list[ParsedCodeownersTeam]:
    """Extract deduplicated ``ParsedCodeownersTeam`` entries in source order."""
    seen: set[ParsedCodeownersTeam] = set()
    ordered: list[ParsedCodeownersTeam] = []
    for raw_line in content.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        section_match = _SECTION_PREFIX_RE.match(stripped)
        if section_match is not None:
            owner_tokens = _tokenize_codeowners_line(section_match.group(1))
        else:
            tokens = _tokenize_codeowners_line(stripped)
            if len(tokens) < 2 or tokens[0].startswith("!"):
                continue
            owner_tokens = tokens[1:]

        for token in owner_tokens:
            team_match = _GITHUB_TEAM_RE.match(token)
            if team_match is None:
                continue
            entry = ParsedCodeownersTeam(
                provider_organization_id=team_match.group(1).lower(),
                team_slug=team_match.group(2).lower(),
            )
            if entry not in seen:
                seen.add(entry)
                ordered.append(entry)
    return ordered


def _read_repository_codeowners_teams(github: GitHubIntegration, repository: str) -> list[ParsedCodeownersTeam]:
    try:
        files = AuthenticatedRepoFiles(
            repository,
            GitHubFilesFetcher.from_integration(github, priority=Priority.NORMAL),
        )
        files.read_all(list(CODEOWNERS_LOCATIONS))
        content = next((text for location in CODEOWNERS_LOCATIONS if (text := files.read(location)) is not None), None)
    except Exception:
        logger.warning("signals.codeowners_teams.repo_read_failed", repository=repository, exc_info=True)
        return []
    if not content:
        return []
    return parse_codeowners_teams(content)


def _list_team_repositories(team_id: int) -> list[_RepositoryScanTarget]:
    seen_repos: set[str] = set()
    targets: list[_RepositoryScanTarget] = []
    for integration in IntegrationManager.github.oauth.list(team_id):
        github = GitHubIntegration(integration, source="signals_codeowners_teams", priority=Priority.NORMAL)
        try:
            cached = github.list_all_cached_repositories()
        except Exception:
            logger.warning(
                "signals.codeowners_teams.list_repositories_failed",
                team_id=team_id,
                integration_id=integration.id,
                exc_info=True,
            )
            continue
        for entry in cached:
            if entry.get("archived"):
                continue
            full_name = str(entry.get("full_name") or "").strip()
            normalized = full_name.lower()
            if not full_name or "/" not in full_name or normalized in seen_repos:
                continue
            seen_repos.add(normalized)
            pushed_at = entry.get("pushed_at")
            targets.append(
                _RepositoryScanTarget(
                    github=github,
                    repository=full_name,
                    pushed_at=pushed_at if isinstance(pushed_at, str) else "",
                )
            )
    # Scan the most recently active repositories first so active monorepos win over dormant old repos.
    targets.sort(key=lambda item: item.pushed_at, reverse=True)
    return targets


def _scan_targets(
    team: Team,
    targets: Sequence[_RepositoryScanTarget],
    *,
    total_repository_count: int,
) -> CodeownersTeamsScan:
    if not targets:
        return CodeownersTeamsScan(
            teams=(),
            scanned_repository_count=0,
            total_repository_count=total_repository_count,
        )

    results_by_repo: dict[str, list[ParsedCodeownersTeam]] = {}
    with ThreadPoolExecutor(max_workers=min(len(targets), _MAX_SCAN_WORKERS)) as executor:
        futures = {
            executor.submit(_read_repository_codeowners_teams, target.github, target.repository): target.repository
            for target in targets
        }
        for future in as_completed(futures):
            repo_name = futures[future]
            try:
                results_by_repo[repo_name] = future.result()
            except Exception:
                logger.warning("signals.codeowners_teams.scan_worker_failed", repository=repo_name, exc_info=True)
                results_by_repo[repo_name] = []

    repos_by_team: dict[ParsedCodeownersTeam, list[str]] = {}
    for target in targets:
        for team_entry in results_by_repo.get(target.repository, ()):
            repos = repos_by_team.setdefault(team_entry, [])
            if target.repository not in repos:
                repos.append(target.repository)

    handles = [f"@{item.provider_organization_id}/{item.team_slug}" for item in repos_by_team]
    matched_roles = likely_roles(handles, organization_id=team.organization_id, provider="github") if handles else {}

    teams = tuple(
        CodeownersTeam(
            provider_organization_id=item.provider_organization_id,
            team_slug=item.team_slug,
            handle=f"@{item.provider_organization_id}/{item.team_slug}",
            repositories=tuple(repos),
            likely_role_id=(
                matched.id
                if (matched := matched_roles.get(f"@{item.provider_organization_id}/{item.team_slug}"))
                else None
            ),
            likely_role_name=matched.name if matched else None,
            match_source=matched.source if matched else None,
        )
        for item, repos in sorted(
            repos_by_team.items(),
            key=lambda pair: (pair[0].provider_organization_id, pair[0].team_slug),
        )
    )
    return CodeownersTeamsScan(
        teams=teams,
        scanned_repository_count=len(targets),
        total_repository_count=total_repository_count,
    )


def scan_team_codeowners(team: Team, *, repository: str | None = None) -> CodeownersTeamsScan:
    """Scan connected GitHub repositories for ``@org/team`` CODEOWNERS entries and resolve likely roles."""
    if repository is not None and repository.strip():
        normalized = repository.strip().lower()
        if not _REPOSITORY_PATTERN.match(normalized):
            raise InvalidCodeownersRepositoryError("Use the 'organization/repository' form, such as 'posthog/posthog'.")
        github = GitHubIntegration.first_for_team_repository(
            team.id,
            normalized,
            source="signals_codeowners_teams",
            priority=Priority.NORMAL,
        )
        if github is None:
            raise InvalidCodeownersRepositoryError(
                "No connected GitHub installation on this project can access that repository."
            )
        return _scan_targets(
            team,
            [_RepositoryScanTarget(github=github, repository=repository.strip())],
            total_repository_count=1,
        )

    all_targets = _list_team_repositories(team.id)
    scanned_targets = all_targets[:MAX_AUTO_SCANNED_REPOSITORIES]
    return _scan_targets(team, scanned_targets, total_repository_count=len(all_targets))
