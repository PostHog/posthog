from dataclasses import dataclass
from datetime import datetime, timedelta

from django.core.cache import cache
from django.utils import timezone

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.egress.limiter.policies import Priority
from posthog.exceptions_capture import capture_exception
from posthog.sync import database_sync_to_async
from posthog.temporal.common.client import async_connect
from posthog.temporal.common.utils import close_db_connections

from ...merge_check.sources import GitHubReader, LandedChange, read_github
from ..logic.pull_requests import docs_github
from ..settings import writer_settings
from .client import start_merge_check_workflow
from .merge_workflow import GITHUB_READ_ERRORS

RECONCILE_WORKFLOW_NAME = "knowledge-writer-merge-reconcile"
RECONCILE_WINDOW = timedelta(hours=3)
RECONCILE_MAX_PAGES = 10
COMMITS_PER_PAGE = 100
RECONCILED_HEAD_TTL = timedelta(days=1)


class ReconcileWindowTruncated(Exception):
    pass


class RepositoryReconcileFailed(Exception):
    pass


class ReconciledHeadLost(Exception):
    pass


@dataclass(frozen=True)
class UnreconciledMerges:
    team_id: int
    changes: list[LandedChange]
    heads_by_repository: dict[str, str]


def reconciled_head_cache_key(repository: str) -> str:
    return f"knowledge_writer:reconciled_head:{repository.lower()}"


def default_branch_commits(
    github: GitHubReader, repository: str, *, reconciled_head: str | None, window_start: datetime
) -> list[dict]:
    listed_repository = read_github(github, f"/repos/{repository}", endpoint="/repos/{owner}/{repo}").json()
    if listed_repository.get("private") is not False:
        return []
    params: dict[str, str | int] = {"sha": listed_repository["default_branch"], "per_page": COMMITS_PER_PAGE}
    if reconciled_head is None:
        params["since"] = window_start.isoformat()
    commits: list[dict] = []
    for page in range(1, RECONCILE_MAX_PAGES + 1):
        listed = read_github(
            github,
            f"/repos/{repository}/commits",
            endpoint="/repos/{owner}/{repo}/commits",
            params={**params, "page": page},
        ).json()
        commits.extend(listed)
        if len(listed) < COMMITS_PER_PAGE or any(commit["sha"] == reconciled_head for commit in listed):
            return commits
    capture_exception(ReconcileWindowTruncated(f"more than {RECONCILE_MAX_PAGES} pages of {repository} commits"))
    return commits


def first_parent_changes(
    repository: str, commits: list[dict], *, reconciled_head: str | None = None
) -> list[LandedChange]:
    parents_by_sha = {commit["sha"]: [parent["sha"] for parent in commit["parents"]] for commit in commits}
    changes: list[LandedChange] = []
    commit_sha = commits[0]["sha"] if commits else None
    while commit_sha is not None and commit_sha != reconciled_head and commit_sha in parents_by_sha:
        parents = parents_by_sha.pop(commit_sha)
        changes.append(LandedChange(repository=repository, after=commit_sha))
        commit_sha = parents[0] if parents else None
    return changes


def list_unreconciled_merges() -> UnreconciledMerges | None:
    writer = writer_settings()
    if writer is None:
        return None
    window_start = timezone.now() - RECONCILE_WINDOW
    merges = UnreconciledMerges(team_id=writer.team_id, changes=[], heads_by_repository={})
    for repository in writer.source_repositories:
        github = docs_github(writer.team_id, repository.split("/", 1)[0], priority=Priority.NORMAL)
        if github is None:
            continue
        reconciled_head = cache.get(reconciled_head_cache_key(repository))
        try:
            commits = default_branch_commits(
                github, repository, reconciled_head=reconciled_head, window_start=window_start
            )
            if reconciled_head is not None and all(commit["sha"] != reconciled_head for commit in commits):
                capture_exception(ReconciledHeadLost(f"{repository} branch no longer reaches {reconciled_head}"))
                reconciled_head = None
                commits = default_branch_commits(github, repository, reconciled_head=None, window_start=window_start)
        except GITHUB_READ_ERRORS as error:
            capture_exception(RepositoryReconcileFailed(f"reconciling {repository} failed: {error}"))
            continue
        merges.changes.extend(first_parent_changes(repository, commits, reconciled_head=reconciled_head))
        if commits:
            merges.heads_by_repository[repository] = commits[0]["sha"]
    return merges


def save_reconciled_heads(heads_by_repository: dict[str, str]) -> None:
    for repository, head in heads_by_repository.items():
        cache.set(reconciled_head_cache_key(repository), head, timeout=RECONCILED_HEAD_TTL.total_seconds())


@activity.defn
@close_db_connections
async def reconcile_merged_pull_requests_activity() -> None:
    merges = await database_sync_to_async(list_unreconciled_merges, thread_sensitive=False)()
    if merges is None:
        return
    client = await async_connect()
    for change in merges.changes:
        await start_merge_check_workflow(change, team_id=merges.team_id, client=client)
    await database_sync_to_async(save_reconciled_heads, thread_sensitive=False)(merges.heads_by_repository)


@workflow.defn(name=RECONCILE_WORKFLOW_NAME)
class MergeReconcileWorkflow:
    @workflow.run
    async def run(self) -> None:
        await workflow.execute_activity(
            reconcile_merged_pull_requests_activity,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
