from dataclasses import dataclass
from typing import Optional

from django.utils import timezone

from temporalio import activity

from posthog.models.github_integration_base import GitHubIntegrationBase
from posthog.temporal.common.utils import close_db_connections

from products.tasks.backend.models import TaskRun
from products.tasks.backend.temporal.code_workstreams.activities.github_resolution import TeamIntegrationResolver
from products.tasks.backend.temporal.code_workstreams.constants import ACTIVITY_WINDOW, MAX_PRS_PER_TEAM_PER_CYCLE


@dataclass
class PrRef:
    pr_url: str
    github_integration_id: Optional[int]
    github_user_integration_id: Optional[str]


def _pr_url_belongs_to_task_repo(pr_url: str, repository: Optional[str]) -> bool:
    """Whether ``pr_url`` points at the task's own ``repository`` (``owner/repo``).

    ``output.pr_url`` is user-writable, and a team's GitHub App installation can
    usually reach far more repos than any one task targeted. Without this check a
    user could point ``pr_url`` at an arbitrary PR the installation can see and
    have Code Home surface its metadata. The agent always opens the PR against
    ``task.repository``, so legitimate runs match; runs without a configured
    repository fail closed.
    """
    if not repository:
        return False
    parsed = GitHubIntegrationBase.parse_pull_request_url(pr_url)
    if parsed is None:
        return False
    owner, repo, _ = parsed
    return f"{owner}/{repo}".casefold() == repository.casefold()


@dataclass
class LoadTeamPrUrlsInput:
    team_id: int


@dataclass
class LoadTeamPrUrlsOutput:
    prs: list[PrRef]


@activity.defn
@close_db_connections
def load_team_pr_urls(input: LoadTeamPrUrlsInput) -> LoadTeamPrUrlsOutput:
    cutoff = timezone.now() - ACTIVITY_WINDOW
    runs = (
        TaskRun.objects.filter(team_id=input.team_id, updated_at__gte=cutoff, output__pr_url__isnull=False)
        .select_related("task")
        .order_by("-updated_at")
    )

    resolver = TeamIntegrationResolver(input.team_id)
    seen: dict[str, PrRef] = {}
    for run in runs.iterator():
        url = (run.output or {}).get("pr_url")
        if not url or url in seen:
            continue
        task = run.task
        if not _pr_url_belongs_to_task_repo(url, task.repository):
            continue
        team_int, user_int = resolver.resolve(task)
        seen[url] = PrRef(pr_url=url, github_integration_id=team_int, github_user_integration_id=user_int)
        if len(seen) >= MAX_PRS_PER_TEAM_PER_CYCLE:
            break

    return LoadTeamPrUrlsOutput(prs=list(seen.values()))
