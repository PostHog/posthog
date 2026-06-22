from collections.abc import Callable
from dataclasses import dataclass
from typing import Optional

from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone

import requests
from temporalio import activity

from posthog.models.github_integration_base import GitHubIntegrationBase, GitHubIntegrationError
from posthog.temporal.common.utils import close_db_connections

from products.tasks.backend.models import TaskRun
from products.tasks.backend.temporal.code_workstreams.activities.github_resolution import (
    TeamIntegrationResolver,
    resolve_github_integration,
)
from products.tasks.backend.temporal.code_workstreams.activities.load_pr_urls import PrRef
from products.tasks.backend.temporal.code_workstreams.constants import (
    ACTIVITY_WINDOW,
    MAX_BRANCH_QUERIES_PER_TEAM_PER_CYCLE,
)

# A run that sits on a base branch never represents its own PR, and querying `head=owner:main`
# returns unrelated PRs. Mirrors DEFAULT_BASE_BRANCHES in logic/code_workstreams/grouping.py.
_SKIP_BRANCHES = frozenset({"main", "master"})


@dataclass
class _BranchCandidate:
    repository: str
    branch: str
    github_integration_id: Optional[int]
    github_user_integration_id: Optional[str]


@dataclass
class DiscoverBranchPrsInput:
    team_id: int
    # PR urls already harvested from output.pr_url this cycle; discovery skips these.
    known_pr_urls: list[str]
    # How many more PRs we may add before hitting MAX_PRS_PER_TEAM_PER_CYCLE.
    budget: int


@dataclass
class DiscoverBranchPrsOutput:
    prs: list[PrRef]


@activity.defn
@close_db_connections
def discover_branch_prs(input: DiscoverBranchPrsInput) -> DiscoverBranchPrsOutput:
    return discover_branch_prs_for_team(
        input.team_id,
        set(input.known_pr_urls),
        input.budget,
        heartbeat=activity.heartbeat,
    )


def _collect_branch_candidates(team_id: int) -> list[_BranchCandidate]:
    """Recent runs with a branch and a repository, deduped by (repo, branch), capped per cycle.

    This is the branch analogue of load_pr_urls' output.pr_url harvest: the durable fact a run
    leaves behind is the branch it pushed, even when no pr_url was ever recorded.
    """
    cutoff = timezone.now() - ACTIVITY_WINDOW
    runs = (
        TaskRun.objects.filter(team_id=team_id, updated_at__gte=cutoff)
        .exclude(branch__isnull=True)
        .exclude(branch="")
        .exclude(branch__in=list(_SKIP_BRANCHES))
        .select_related("task")
        .order_by("-updated_at")
    )
    resolver = TeamIntegrationResolver(team_id)
    seen: set[tuple[str, str]] = set()
    candidates: list[_BranchCandidate] = []
    for run in runs.iterator():
        task = run.task
        repository = task.repository
        branch = run.branch
        if not repository or not branch:
            continue
        key = (repository.casefold(), branch)
        if key in seen:
            continue
        seen.add(key)
        team_int, user_int = resolver.resolve(task)
        if team_int is None and user_int is None:
            continue
        candidates.append(_BranchCandidate(repository, branch, team_int, user_int))
        if len(candidates) >= MAX_BRANCH_QUERIES_PER_TEAM_PER_CYCLE:
            break
    return candidates


def discover_branch_prs_for_team(
    team_id: int,
    known_pr_urls: set[str],
    budget: int,
    *,
    heartbeat: Callable[[int], None] | None = None,
) -> DiscoverBranchPrsOutput:
    if budget <= 0:
        return DiscoverBranchPrsOutput(prs=[])

    candidates = _collect_branch_candidates(team_id)
    integrations: dict[str, GitHubIntegrationBase | None] = {}
    found: dict[str, PrRef] = {}

    for index, candidate in enumerate(candidates):
        if heartbeat is not None:
            heartbeat(index)
        if len(found) >= budget:
            break

        cache_key = (
            f"i:{candidate.github_integration_id}"
            if candidate.github_integration_id is not None
            else f"u:{candidate.github_user_integration_id}"
        )
        try:
            if cache_key not in integrations:
                integrations[cache_key] = resolve_github_integration(
                    candidate.github_integration_id, candidate.github_user_integration_id
                )
            integration = integrations[cache_key]
        except ObjectDoesNotExist:
            # Permanent failure: cache None so other candidates sharing this (deleted) integration
            # don't each re-run the failing DB lookup.
            activity.logger.warning("code_workstreams_discover_integration_missing", repository=candidate.repository)
            integrations[cache_key] = None
            continue
        except (GitHubIntegrationError, requests.RequestException) as e:
            # A token-refresh failure for one candidate must not abort the whole activity.
            activity.logger.warning(
                "code_workstreams_discover_integration_unavailable", repository=candidate.repository, error=str(e)
            )
            continue
        if integration is None:
            continue

        try:
            urls = integration.find_pull_request_urls_for_branch(candidate.repository, candidate.branch)
        except Exception as e:
            activity.logger.warning(
                "code_workstreams_discover_branch_failed",
                repository=candidate.repository,
                branch=candidate.branch,
                error=str(e),
            )
            continue

        for url in urls:
            if url in known_pr_urls or url in found:
                continue
            found[url] = PrRef(
                pr_url=url,
                github_integration_id=candidate.github_integration_id,
                github_user_integration_id=candidate.github_user_integration_id,
            )
            if len(found) >= budget:
                break

    return DiscoverBranchPrsOutput(prs=list(found.values()))
