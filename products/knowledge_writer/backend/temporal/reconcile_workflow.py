from datetime import datetime, timedelta

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

RECONCILE_WORKFLOW_NAME = "knowledge-writer-merge-reconcile"
RECONCILE_WINDOW = timedelta(hours=3)
RECONCILE_MAX_PAGES = 10
COMMITS_PER_PAGE = 100


class ReconcileWindowTruncated(Exception):
    pass


def default_branch_commits_since(github: GitHubReader, repository: str, window_start: datetime) -> list[dict]:
    listed_repository = read_github(github, f"/repos/{repository}", endpoint="/repos/{owner}/{repo}").json()
    if listed_repository.get("private") is not False:
        return []
    commits: list[dict] = []
    for page in range(1, RECONCILE_MAX_PAGES + 1):
        listed = read_github(
            github,
            f"/repos/{repository}/commits",
            endpoint="/repos/{owner}/{repo}/commits",
            params={
                "sha": listed_repository["default_branch"],
                "since": window_start.isoformat(),
                "per_page": COMMITS_PER_PAGE,
                "page": page,
            },
        ).json()
        commits.extend(listed)
        if len(listed) < COMMITS_PER_PAGE:
            return commits
    capture_exception(ReconcileWindowTruncated(f"more than {RECONCILE_MAX_PAGES} pages of {repository} commits"))
    return commits


def first_parent_changes(repository: str, commits: list[dict]) -> list[LandedChange]:
    parents_by_sha = {commit["sha"]: [parent["sha"] for parent in commit["parents"]] for commit in commits}
    changes: list[LandedChange] = []
    commit_sha = commits[0]["sha"] if commits else None
    while commit_sha is not None and commit_sha in parents_by_sha:
        parents = parents_by_sha.pop(commit_sha)
        changes.append(LandedChange(repository=repository, after=commit_sha))
        commit_sha = parents[0] if parents else None
    return changes


def list_unreconciled_merges() -> tuple[int, list[LandedChange]] | None:
    writer = writer_settings()
    if writer is None:
        return None
    window_start = timezone.now() - RECONCILE_WINDOW
    changes: list[LandedChange] = []
    for repository in writer.source_repositories:
        github = docs_github(writer.team_id, repository.split("/", 1)[0], priority=Priority.NORMAL)
        if github is None:
            continue
        changes.extend(first_parent_changes(repository, default_branch_commits_since(github, repository, window_start)))
    return writer.team_id, changes


@activity.defn
@close_db_connections
async def reconcile_merged_pull_requests_activity() -> None:
    merges = await database_sync_to_async(list_unreconciled_merges, thread_sensitive=False)()
    if merges is None:
        return
    team_id, changes = merges
    client = await async_connect()
    for change in changes:
        await start_merge_check_workflow(change, team_id=team_id, client=client)


@workflow.defn(name=RECONCILE_WORKFLOW_NAME)
class MergeReconcileWorkflow:
    @workflow.run
    async def run(self) -> None:
        await workflow.execute_activity(
            reconcile_merged_pull_requests_activity,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
