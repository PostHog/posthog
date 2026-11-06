"""Default repositories for a scout run that has no pinned repository.

A scout clones only the repositories pinned on its config. The first-report scout runs during
onboarding, before anyone could pin a repository, so without a default it starts repo-less and
cannot read the project's code. This module picks a short default list from what the project's
GitHub connection can reach.
"""

from datetime import datetime

from django.core.cache import cache
from django.db.models import Count
from django.db.models.functions import Lower

import structlog

from posthog.egress.limiter.policies import Priority
from posthog.integrations import IntegrationManager
from posthog.models.integration import GitHubIntegration

from products.signals.backend.models import SignalReportPullRequest
from products.tasks.backend.facade import api as tasks_facade

logger = structlog.get_logger(__name__)

DEFAULT_SCOUT_REPOSITORY_LIMIT = 5
# Each run clones every repository on the list, so the ranking does not need to follow every push.
DEFAULT_SCOUT_REPOSITORIES_CACHE_TTL_S = 24 * 60 * 60


def _cache_key(team_id: int) -> str:
    return f"signals:scout_default_repositories:v1:{team_id}"


def _pushed_at_timestamp(repository: dict) -> float:
    value = repository.get("pushed_at")
    if not isinstance(value, str):
        return 0.0
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def rank_scout_repositories(team_id: int, *, limit: int = DEFAULT_SCOUT_REPOSITORY_LIMIT) -> list[str]:
    """Up to `limit` repositories, ranked by merged self-driving fixes, then by the latest push.

    Only the installation a read-only scout token is minted from counts, because a repository that
    installation cannot reach fails to clone. Archived repositories are skipped. Raises when the
    GitHub repository list cannot be read, so the caller does not cache a failed read.
    """
    integration_id = tasks_facade.readonly_github_integration_id(team_id)
    if integration_id is None:
        return []
    integration = IntegrationManager.github.oauth.get(team_id, integration_id)
    github = GitHubIntegration(integration, source="signals_scout_default_repositories", priority=Priority.NORMAL)
    candidates: dict[str, dict] = {}
    for repository in github.list_all_cached_repositories():
        name = str(repository.get("full_name") or "").strip().lower()
        if name and "/" in name and repository.get("archived") is not True:
            candidates.setdefault(name, repository)
    if not candidates:
        return []

    merged_fixes = dict(
        SignalReportPullRequest.objects.for_team(team_id)
        .filter(merged_at__isnull=False)
        .annotate(name=Lower("repository"))
        .filter(name__in=list(candidates))
        .values("name")
        .annotate(count=Count("id"))
        .values_list("name", "count")
    )
    ranked = sorted(
        candidates,
        key=lambda name: (-merged_fixes.get(name, 0), -_pushed_at_timestamp(candidates[name]), name),
    )
    return ranked[:limit]


def default_scout_repositories(team_id: int) -> list[str]:
    """The cached default repository list for `team_id`. Never raises.

    An empty result is cached too, so a project with no reachable repository does not read GitHub on
    every run. A failed read is not cached, so the next run tries again.
    """
    key = _cache_key(team_id)
    cached = cache.get(key)
    if isinstance(cached, list):
        return cached
    try:
        repositories = rank_scout_repositories(team_id)
    except Exception:
        logger.warning("signals_scout_default_repositories_unavailable", team_id=team_id, exc_info=True)
        return []
    cache.set(key, repositories, DEFAULT_SCOUT_REPOSITORIES_CACHE_TTL_S)
    return repositories
