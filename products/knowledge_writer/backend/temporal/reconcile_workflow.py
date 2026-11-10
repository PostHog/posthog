from collections.abc import Iterator
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
RECONCILE_CATCH_UP_MAX_PAGES = 30
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


def public_default_branch(github: GitHubReader, repository: str) -> str | None:
    listed_repository = read_github(github, f"/repos/{repository}", endpoint="/repos/{owner}/{repo}").json()
    if listed_repository.get("private") is not False:
        return None
    return listed_repository["default_branch"]


def commit_pages(
    github: GitHubReader, repository: str, branch: str, pages: range, *, since: datetime | None = None
) -> Iterator[list[dict]]:
    params: dict[str, str | int] = {"sha": branch, "per_page": COMMITS_PER_PAGE}
    if since is not None:
        params["since"] = since.isoformat()
    for page in pages:
        listed = read_github(
            github,
            f"/repos/{repository}/commits",
            endpoint="/repos/{owner}/{repo}/commits",
            params={**params, "page": page},
        ).json()
        yield listed
        if len(listed) < COMMITS_PER_PAGE:
            return


def commits_in_window(github: GitHubReader, repository: str, branch: str, window_start: datetime) -> list[dict]:
    pages = list(commit_pages(github, repository, branch, range(1, RECONCILE_MAX_PAGES + 1), since=window_start))
    if len(pages) == RECONCILE_MAX_PAGES and len(pages[-1]) == COMMITS_PER_PAGE:
        capture_exception(ReconcileWindowTruncated(f"more than {RECONCILE_MAX_PAGES} pages of {repository} commits"))
    return [commit for listed in pages for commit in listed]


def commits_ahead_of(github: GitHubReader, repository: str, branch: str, reconciled_head: str) -> int | None:
    response = github.api_request(
        "GET",
        f"/repos/{repository}/compare/{reconciled_head}...{branch}",
        endpoint="/repos/{owner}/{repo}/compare/{basehead}",
        params={"per_page": 1},
        priority=Priority.NORMAL,
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    comparison = response.json()
    if comparison["status"] != "ahead":
        return None
    return comparison["ahead_by"]


def extends_back_to(commits: list[dict], pages: Iterator[list[dict]], reconciled_head: str) -> bool:
    for listed in pages:
        commits.extend(listed)
        if any(commit["sha"] == reconciled_head for commit in listed):
            return True
    return False


def commits_back_to(github: GitHubReader, repository: str, branch: str, reconciled_head: str) -> list[dict] | None:
    commits: list[dict] = []
    capped_pages = commit_pages(github, repository, branch, range(1, RECONCILE_MAX_PAGES + 1))
    if extends_back_to(commits, capped_pages, reconciled_head):
        return commits
    head_lost = ReconciledHeadLost(f"{repository} {branch} no longer reaches {reconciled_head}")
    commits_ahead = commits_ahead_of(github, repository, branch, reconciled_head)
    if commits_ahead is None:
        capture_exception(head_lost)
        return None
    last_page = commits_ahead // COMMITS_PER_PAGE + 1
    if last_page > RECONCILE_CATCH_UP_MAX_PAGES:
        capture_exception(ReconcileWindowTruncated(f"{repository} is {commits_ahead} commits past {reconciled_head}"))
        return None
    catch_up_pages = commit_pages(github, repository, branch, range(RECONCILE_MAX_PAGES + 1, last_page + 1))
    if extends_back_to(commits, catch_up_pages, reconciled_head):
        return commits
    capture_exception(head_lost)
    return None


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


def collect_unreconciled_changes(
    merges: UnreconciledMerges, github: GitHubReader, repository: str, window_start: datetime
) -> None:
    branch = public_default_branch(github, repository)
    if branch is None:
        return
    reconciled_head = cache.get(reconciled_head_cache_key(repository))
    commits = commits_back_to(github, repository, branch, reconciled_head) if reconciled_head else None
    if commits is None:
        reconciled_head = None
        commits = commits_in_window(github, repository, branch, window_start)
    merges.changes.extend(first_parent_changes(repository, commits, reconciled_head=reconciled_head))
    if commits:
        merges.heads_by_repository[repository] = commits[0]["sha"]


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
        try:
            collect_unreconciled_changes(merges, github, repository, window_start)
        except GITHUB_READ_ERRORS as error:
            capture_exception(RepositoryReconcileFailed(f"reconciling {repository} failed: {error}"))
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
