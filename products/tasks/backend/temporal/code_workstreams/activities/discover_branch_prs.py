import random
from collections.abc import Callable
from dataclasses import dataclass
from typing import Optional

from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone

import requests
from temporalio import activity

from posthog.egress.github.transport import GitHubEgressBudgetExhausted, GitHubRateLimitError
from posthog.egress.github.transport import GitHubRateLimitError
from posthog.models.github_integration_base import GitHubIntegrationBase, GitHubIntegrationError
from posthog.temporal.common.utils import close_db_connections

from products.tasks.backend.logic.code_workstreams.grouping import DEFAULT_BASE_BRANCHES
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


@dataclass
class _BranchCandidate:
    repository: str
    branch: str
    github_integration_id: Optional[int]
    github_user_integration_id: Optional[str]


@dataclass
class DiscoverBranchPrsInput:
    team_id: int
    # PR urls already found this cycle; discovery skips these.
    known_pr_urls: list[str]
    # Remaining capacity before hitting MAX_PRS_PER_TEAM_PER_CYCLE.
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

    The branch analogue of load_pr_urls' output.pr_url harvest: a run's branch is durable even
    when no pr_url was recorded. Base branches are excluded — they never head a task's own PR.
    """
    cutoff = timezone.now() - ACTIVITY_WINDOW
    runs = (
        TaskRun.objects.filter(team_id=team_id, updated_at__gte=cutoff)
        .exclude(branch__isnull=True)
        .exclude(branch="")
        .exclude(branch__in=list(DEFAULT_BASE_BRANCHES))
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
    # A shed sweep breaks mid-list; shuffling gives the tail equal coverage across cycles instead
    # of the same recency-ordered prefix consuming the budget every run.
    random.shuffle(candidates)
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
            # Cache None so other candidates sharing this integration don't re-run the failing lookup.
            activity.logger.warning("code_workstreams_discover_integration_missing", repository=candidate.repository)
            integrations[cache_key] = None
            continue
        except (GitHubIntegrationError, GitHubRateLimitError, requests.RequestException) as e:
            # Token-refresh failure; skip this candidate rather than aborting the activity.
            activity.logger.warning(
                "code_workstreams_discover_integration_unavailable", repository=candidate.repository, error=str(e)
            )
            continue
        if integration is None:
            continue

        try:
            urls = integration.find_pull_request_urls_for_branch(candidate.repository, candidate.branch)
        except GitHubEgressBudgetExhausted:
            # Our own limiter shed the sweep — stop for this cycle; the next scheduled run resumes.
            activity.logger.warning("code_workstreams_discover_budget_exhausted", repository=candidate.repository)
            break
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
