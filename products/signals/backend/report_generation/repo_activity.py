"""Recent-contributor activity per repository area, cached for reviewer routing.

Supplies the recency signal blame resolution lacks: for each *area* (a path prefix like
``products/signals``) it knows who actually committed there in the last
``ACTIVITY_WINDOW_DAYS`` days. Cached in ``SignalRepositoryAreaActivity`` — rows are
created on demand, refreshed lazily when stale, and kept warm by the weekly
``refresh_signal_repository_activity`` Celery task.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.utils import timezone

from posthog.egress.github.transport import GitHubRateLimitError
from posthog.models.github_integration_base import GitHubIntegrationBase
from posthog.models.scoping import team_scope

from ..models import SignalRepositoryAreaActivity

logger = logging.getLogger(__name__)

ACTIVITY_WINDOW_DAYS = 90
ACTIVITY_STALE_AFTER = timedelta(days=7)
# The weekly refresh only keeps rows warm that reviewer resolution read this recently.
ACTIVITY_KEEP_WARM_WINDOW = timedelta(days=45)
AREA_PATH_DEPTH = 2
# Bounds GitHub calls per report on a cold cache.
MAX_AREAS_PER_RESOLUTION = 6


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


def get_area_activity(
    github: GitHubIntegrationBase,
    team_id: int,
    repository: str,
    areas: list[str],
) -> dict[str, list[ContributorActivity]]:
    """Recent contributors per area, read through the ``SignalRepositoryAreaActivity`` cache.

    Missing or stale rows are refreshed from GitHub inline; a failed refresh falls back to
    cached data. An area never refreshed successfully is absent from the result — callers
    must treat that as "no signal", not "nobody is active".
    """
    if not areas:
        return {}

    repository = repository.strip().lower()
    now = timezone.now()
    result: dict[str, list[ContributorActivity]] = {}

    with team_scope(team_id):
        for area in areas[:MAX_AREAS_PER_RESOLUTION]:
            row, _created = SignalRepositoryAreaActivity.objects.get_or_create(
                team_id=team_id,
                repository=repository,
                area=area,
            )
            if row.refreshed_at is None or now - row.refreshed_at >= ACTIVITY_STALE_AFTER:
                try:
                    refresh_area_activity_row(row, github)
                except GitHubRateLimitError:
                    logger.info(
                        "GitHub rate limited refreshing area activity for %s %r, using cached data",
                        repository,
                        area,
                    )
                except Exception:
                    logger.warning("Failed to refresh area activity for %s %r", repository, area, exc_info=True)
            SignalRepositoryAreaActivity.objects.filter(id=row.id).update(last_used_at=now)
            if row.refreshed_at is not None:
                result[area] = _parse_contributors(row.contributors)

    return result


def refresh_area_activity_row(row: SignalRepositoryAreaActivity, github: GitHubIntegrationBase) -> None:
    """Rebuild one row's contributor map from GitHub's recent default-branch commits.

    Raises on failure (including ``GitHubRateLimitError``) — callers decide whether stale
    data is acceptable. On success the row is saved with a fresh ``refreshed_at``.
    """
    since = timezone.now() - timedelta(days=ACTIVITY_WINDOW_DAYS)
    commits = github.list_recent_commits(row.repository, path=row.area or None, since=since)

    by_login: dict[str, dict] = {}
    for commit in commits:
        entry = by_login.get(commit.login)
        if entry is None:
            by_login[commit.login] = {
                "login": commit.login,
                "name": commit.name,
                "commit_count": 1,
                # The listing is newest-first, so the first commit seen per login is their latest.
                "last_commit_at": commit.committed_at,
                "last_commit_sha": commit.sha,
                "last_commit_url": commit.html_url,
            }
        else:
            entry["commit_count"] += 1

    row.contributors = sorted(by_login.values(), key=lambda c: -c["commit_count"])
    row.refreshed_at = timezone.now()
    row.save(update_fields=["contributors", "refreshed_at"])


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
