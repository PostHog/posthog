"""Recent-contributor activity per repository area, cached for reviewer routing.

Supplies the recency signal blame resolution lacks: for each *area* (a path prefix like
``products/signals``) it knows who actually committed there in the last
``ACTIVITY_WINDOW_DAYS`` days. Two sources joined on commit sha: a local
``git log --name-only`` pass in a short-lived sandbox (sha → changed paths, via the tasks
facade) and GitHub's commits listing (sha → login — git author emails are unverified free
text, so identity comes only from GitHub's own attribution). Cached in
``SignalRepositoryAreaActivity`` — reviewer resolution only ever reads the cache; rebuilds
run async (on cache miss and weekly).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone

from posthog.egress.limiter.policies import Priority
from posthog.models.github_integration_base import GitHubCommitAttribution
from posthog.models.integration import GitHubIntegration
from posthog.models.scoping import team_scope

from products.tasks.backend.facade.repo_activity import (
    RepositoryCommitActivityError,
    collect_repository_commit_activity,
)

from ..models import SignalRepositoryAreaActivity

logger = logging.getLogger(__name__)

ACTIVITY_WINDOW_DAYS = 90
ACTIVITY_STALE_AFTER = timedelta(days=7)
# The weekly refresh only rebuilds repositories whose rows were read this recently.
ACTIVITY_KEEP_WARM_WINDOW = timedelta(days=45)
AREA_PATH_DEPTH = 2
MAX_AREAS_PER_RESOLUTION = 6
MAX_CONTRIBUTORS_PER_AREA = 50
# Synthetic area holding every contributor to the repository; the last fallback level.
# Distinct from "" (files at the repository root).
REPO_WIDE_AREA = "*"


@dataclass(frozen=True)
class ContributorActivity:
    login: str
    name: str | None
    commit_count: int
    last_commit_at: datetime
    last_commit_sha: str
    last_commit_url: str


def area_for_path(path: str) -> str:
    """Map a repo-relative file path to its area (first ``AREA_PATH_DEPTH`` directories).

    ``products/signals/backend/models.py`` → ``products/signals``;
    ``posthog/models.py`` → ``posthog``; a root-level file → ``""`` (repository root).
    """
    directories = [p for p in path.strip("/").split("/") if p][:-1]
    return "/".join(directories[:AREA_PATH_DEPTH])


def areas_for_paths(paths: list[str]) -> list[str]:
    """Distinct areas for a set of file paths, most-touched first, capped."""
    counts: dict[str, int] = {}
    for path in paths:
        area = area_for_path(path)
        counts[area] = counts.get(area, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [area for area, _count in ranked[:MAX_AREAS_PER_RESOLUTION]]


def area_fallback_chain(area: str) -> list[str]:
    """Lookup order when an area has no active contributors: itself, its parent, repo-wide.

    ``products/signals`` → ``["products/signals", "products", "*"]``; the rebuild indexes
    every commit at all of these levels, so walking up never invents data.
    """
    chain = [area]
    if "/" in area:
        chain.append(area.rsplit("/", 1)[0])
    if area != REPO_WIDE_AREA:
        chain.append(REPO_WIDE_AREA)
    return chain


def get_area_activity(team_id: int, repository: str, areas: list[str]) -> dict[str, list[ContributorActivity]]:
    """Recent contributors per area, read from the ``SignalRepositoryAreaActivity`` cache.

    Cache-only — never hits git or GitHub. Missing areas get a placeholder row (so rebuilds
    know they are wanted) and are absent from the result; callers must treat absence as
    "no signal", not "nobody is active".
    """
    if not areas:
        return {}

    repository = repository.strip().lower()
    now = timezone.now()
    result: dict[str, list[ContributorActivity]] = {}

    with team_scope(team_id):
        rows = {
            row.area: row
            for row in SignalRepositoryAreaActivity.objects.filter(
                team_id=team_id, repository=repository, area__in=areas
            )
        }
        missing = [area for area in areas if area not in rows]
        if missing:
            # Placeholder rows so rebuilds know these areas are wanted; ignore_conflicts
            # covers a concurrent resolution creating the same row.
            SignalRepositoryAreaActivity.objects.bulk_create(
                [
                    SignalRepositoryAreaActivity(team_id=team_id, repository=repository, area=area, last_used_at=now)
                    for area in missing
                ],
                ignore_conflicts=True,
            )
        if rows:
            SignalRepositoryAreaActivity.objects.filter(
                team_id=team_id, id__in=[row.id for row in rows.values()]
            ).update(last_used_at=now)
        for area, row in rows.items():
            if row.refreshed_at is not None:
                result[area] = _parse_contributors(row.contributors)

    return result


def repository_activity_needs_rebuild(team_id: int, repository: str) -> bool:
    """Whether the repository's cached map is missing or older than ``ACTIVITY_STALE_AFTER``."""
    repository = repository.strip().lower()
    with team_scope(team_id):
        return not SignalRepositoryAreaActivity.objects.filter(
            team_id=team_id,
            repository=repository,
            refreshed_at__gte=timezone.now() - ACTIVITY_STALE_AFTER,
        ).exists()


def rebuild_repository_activity(team_id: int, repository: str) -> int:
    """Rebuild the repository's whole area-activity map from its git history.

    One facade call collects the recent commits with their touched paths (sandbox git log);
    one paginated GitHub commits listing supplies sha→login attribution — the two join on
    sha, so identity never depends on author emails. Commits GitHub can't attribute, and
    bot accounts, are dropped. Each commit is indexed at every fallback level (its areas,
    their parents, and ``REPO_WIDE_AREA``) so lookups can walk up when an area has no
    active contributors. Every area row for the repository is replaced in one transaction —
    areas with no recent commits are stamped refreshed with no contributors, which scoring
    reads as "nobody is active here", distinct from a never-built row.

    Returns the number of areas with at least one contributor. Raises
    ``RepositoryCommitActivityError`` when collection fails; attribution failures
    (including rate limits) propagate so a rebuild never writes a half-attributed map.
    """
    repository = repository.strip().lower()
    commits = collect_repository_commit_activity(team_id, repository, since_days=ACTIVITY_WINDOW_DAYS)
    attribution_by_sha = _commit_attributions_by_sha(team_id, repository) if commits else {}

    per_area: dict[str, dict[str, dict]] = {}
    for commit in commits:  # newest-first, so the first commit seen per login is their latest
        attribution = attribution_by_sha.get(commit.sha)
        if attribution is None or attribution.is_bot:
            continue
        login = attribution.login.lower()
        commit_areas: set[str] = set()
        for path in commit.paths:
            commit_areas.update(area_fallback_chain(area_for_path(path)))
        for area in commit_areas:
            entry = per_area.setdefault(area, {}).get(login)
            if entry is None:
                per_area[area][login] = {
                    "login": login,
                    "name": attribution.name or login,
                    "commit_count": 1,
                    "last_commit_at": commit.committed_at,
                    "last_commit_sha": commit.sha,
                    "last_commit_url": f"https://github.com/{repository}/commit/{commit.sha}",
                }
            else:
                entry["commit_count"] += 1

    def contributors_for(area: str) -> list[dict]:
        by_login = per_area.get(area, {})
        return sorted(by_login.values(), key=lambda c: -c["commit_count"])[:MAX_CONTRIBUTORS_PER_AREA]

    now = timezone.now()
    with team_scope(team_id), transaction.atomic():
        existing = {
            row.area: row for row in SignalRepositoryAreaActivity.objects.filter(team_id=team_id, repository=repository)
        }
        to_update = []
        for area, row in existing.items():
            row.contributors = contributors_for(area)
            row.refreshed_at = now
            to_update.append(row)
        if to_update:
            SignalRepositoryAreaActivity.objects.bulk_update(to_update, ["contributors", "refreshed_at"])
        to_create = [
            SignalRepositoryAreaActivity(
                team_id=team_id,
                repository=repository,
                area=area,
                contributors=contributors_for(area),
                refreshed_at=now,
                last_used_at=now,
            )
            for area in per_area
            if area not in existing
        ]
        if to_create:
            # ignore_conflicts: the live read path may create a placeholder for the same
            # area concurrently — that row is then refreshed by the next rebuild.
            SignalRepositoryAreaActivity.objects.bulk_create(to_create, ignore_conflicts=True)

    logger.info(
        "rebuilt signal repository activity for team %d %s: %d commits, %d areas",
        team_id,
        repository,
        len(commits),
        len(per_area),
    )
    return len(per_area)


def _commit_attributions_by_sha(team_id: int, repository: str) -> dict[str, GitHubCommitAttribution]:
    """GitHub's sha→login attribution for the activity window, keyed for the sha join."""
    github = GitHubIntegration.first_for_team_repository(team_id, repository, source="signals_activity_rebuild")
    if github is None:
        # Same expected-deferral type the collector raises — the rebuild task logs it
        # instead of capturing an exception.
        raise RepositoryCommitActivityError(f"No GitHub integration for team {team_id} can access {repository}")
    # Sheddable: rebuilds are deferrable background work — the egress limiter drops BATCH
    # calls first when the installation's shared budget runs hot, and a denied listing
    # aborts the rebuild rather than writing a half-attributed map.
    github.priority = Priority.BATCH
    since = timezone.now() - timedelta(days=ACTIVITY_WINDOW_DAYS)
    return {attribution.sha: attribution for attribution in github.list_commit_attributions(repository, since=since)}


def _parse_contributors(raw: object) -> list[ContributorActivity]:
    if not isinstance(raw, list):
        return []
    parsed: list[ContributorActivity] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        login = entry.get("login")
        last_commit_at_raw = entry.get("last_commit_at")
        if not isinstance(login, str) or not isinstance(last_commit_at_raw, str):
            continue
        try:
            last_commit_at = datetime.fromisoformat(last_commit_at_raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        parsed.append(
            ContributorActivity(
                login=login,
                name=entry.get("name") if isinstance(entry.get("name"), str) else None,
                commit_count=int(entry.get("commit_count") or 0),
                last_commit_at=last_commit_at,
                last_commit_sha=str(entry.get("last_commit_sha") or ""),
                last_commit_url=str(entry.get("last_commit_url") or ""),
            )
        )
    return parsed
