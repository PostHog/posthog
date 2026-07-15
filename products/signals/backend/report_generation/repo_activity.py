"""Recent-contributor activity per repository area, cached for reviewer routing.

Supplies the recency signal blame resolution lacks: for each *area* (a path prefix like
``products/signals``) it knows who actually committed there in the last
``ACTIVITY_WINDOW_DAYS`` days. Built from the repository's own git history (one
``git log --name-only`` pass in a short-lived sandbox, via the tasks facade) and cached in
``SignalRepositoryAreaActivity`` — reviewer resolution only ever reads the cache; rebuilds
run async (on cache miss and weekly).
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone

from posthog.models.scoping import team_scope
from posthog.models.team.team import Team
from posthog.models.user import User

from products.tasks.backend.facade.repo_activity import collect_repository_commit_activity

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

_NOREPLY_EMAIL_RE = re.compile(r"^(?:\d+\+)?([a-z0-9-]+)@users\.noreply\.github\.com$", re.IGNORECASE)


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
        for area in areas:
            row, _created = SignalRepositoryAreaActivity.objects.get_or_create(
                team_id=team_id,
                repository=repository,
                area=area,
            )
            SignalRepositoryAreaActivity.objects.filter(id=row.id).update(last_used_at=now)
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

    One facade call collects the recent commits (with touched paths); commits map to areas
    locally and author emails resolve to GitHub logins (noreply-email parse, then org-member
    email match). Each commit is indexed at every fallback level (its areas, their parents,
    and ``REPO_WIDE_AREA``) so lookups can walk up when an area has no active contributors.
    Every area row for the repository is replaced in one transaction — areas with no recent
    commits are stamped refreshed with no contributors, which scoring reads as "nobody is
    active here", distinct from a never-built row.

    Returns the number of areas with at least one contributor. Raises
    ``RepositoryCommitActivityError`` when collection fails.
    """
    repository = repository.strip().lower()
    commits = collect_repository_commit_activity(team_id, repository, since_days=ACTIVITY_WINDOW_DAYS)
    login_by_email = _github_logins_for_emails(team_id, {c.author_email.lower() for c in commits})

    per_area: dict[str, dict[str, dict]] = {}
    for commit in commits:  # newest-first, so the first commit seen per login is their latest
        login = login_by_email.get(commit.author_email.lower())
        if login is None:
            continue
        commit_areas: set[str] = set()
        for path in commit.paths:
            commit_areas.update(area_fallback_chain(area_for_path(path)))
        for area in commit_areas:
            entry = per_area.setdefault(area, {}).get(login)
            if entry is None:
                per_area[area][login] = {
                    "login": login,
                    "name": commit.author_name or login,
                    "commit_count": 1,
                    "last_commit_at": commit.committed_at,
                    "last_commit_sha": commit.sha,
                    "last_commit_url": f"https://github.com/{repository}/commit/{commit.sha}",
                }
            else:
                entry["commit_count"] += 1

    now = timezone.now()
    with team_scope(team_id), transaction.atomic():
        for area, by_login in per_area.items():
            SignalRepositoryAreaActivity.objects.update_or_create(
                team_id=team_id,
                repository=repository,
                area=area,
                defaults={
                    "contributors": sorted(by_login.values(), key=lambda c: -c["commit_count"])[
                        :MAX_CONTRIBUTORS_PER_AREA
                    ],
                    "refreshed_at": now,
                },
            )
        SignalRepositoryAreaActivity.objects.filter(team_id=team_id, repository=repository).exclude(
            area__in=per_area.keys()
        ).update(contributors=[], refreshed_at=now)

    logger.info(
        "rebuilt signal repository activity for team %d %s: %d commits, %d areas",
        team_id,
        repository,
        len(commits),
        len(per_area),
    )
    return len(per_area)


def _github_logins_for_emails(team_id: int, emails: set[str]) -> dict[str, str]:
    """Map lowercased author emails to GitHub logins.

    GitHub noreply addresses carry the login directly (squash merges); other emails match
    org members with a linked GitHub identity. Unresolvable emails are dropped — reviewer
    routing needs addressable logins.
    """
    resolved: dict[str, str] = {}
    remaining: set[str] = set()
    for email in emails:
        match = _NOREPLY_EMAIL_RE.match(email)
        if match:
            resolved[email] = match.group(1).lower()
        else:
            remaining.add(email)

    if remaining:
        # Local import: resolve_reviewers imports this module at load time.
        from products.signals.backend.report_generation.resolve_reviewers import _github_identity_prefetches

        try:
            org_id = Team.objects.values_list("organization_id", flat=True).get(id=team_id)
        except Team.DoesNotExist:
            return resolved
        users = (
            User.objects.filter(organization_membership__organization_id=org_id, email__in=remaining)
            .prefetch_related(*_github_identity_prefetches())
            .order_by("id")
        )
        for user in users:
            login = user.get_github_login()
            if login:
                resolved[user.email.lower()] = login.lower()

    return resolved


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
