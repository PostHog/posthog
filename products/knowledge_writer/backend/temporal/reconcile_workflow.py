from datetime import datetime, timedelta

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.exceptions_capture import capture_exception
from posthog.sync import database_sync_to_async
from posthog.temporal.common.client import async_connect
from posthog.temporal.common.utils import close_db_connections

from ...merge_check.sources import POSTHOG_REPOSITORY, GitHubReader, MergedCommit, merged_commit, read_github
from ..logic.pull_requests import source_repository_github
from ..settings import writer_settings
from .client import start_merge_check_workflow

RECONCILE_WORKFLOW_NAME = "knowledge-writer-merge-reconcile"
RECONCILE_WINDOW = timedelta(hours=3)
RECONCILE_MAX_PAGES = 10
PULL_REQUESTS_PER_PAGE = 100


class ReconcileWindowTruncated(Exception):
    pass


def _is_before(timestamp: str | None, window_start: datetime) -> bool:
    parsed = parse_datetime(timestamp or "")
    return parsed is None or parsed < window_start


def merged_commits_since(github: GitHubReader, window_start: datetime) -> list[MergedCommit]:
    merges: list[MergedCommit] = []
    for page in range(1, RECONCILE_MAX_PAGES + 1):
        listed = read_github(
            github,
            f"/repos/{POSTHOG_REPOSITORY}/pulls",
            endpoint="/repos/{owner}/{repo}/pulls",
            params={
                "state": "closed",
                "sort": "updated",
                "direction": "desc",
                "per_page": PULL_REQUESTS_PER_PAGE,
                "page": page,
            },
        ).json()
        for pull_request in listed:
            merge = merged_commit(pull_request)
            if merge and not _is_before(pull_request.get("merged_at"), window_start):
                merges.append(merge)
        if len(listed) < PULL_REQUESTS_PER_PAGE or _is_before(listed[-1].get("updated_at"), window_start):
            return merges
    capture_exception(ReconcileWindowTruncated(f"more than {RECONCILE_MAX_PAGES} pages of closed pull requests"))
    return merges


def list_unreconciled_merges() -> tuple[int, list[MergedCommit]] | None:
    writer = writer_settings()
    if writer is None:
        return None
    github = source_repository_github(writer.team_id)
    if github is None:
        return None
    return writer.team_id, merged_commits_since(github, timezone.now() - RECONCILE_WINDOW)


@activity.defn
@close_db_connections
async def reconcile_merged_pull_requests_activity() -> None:
    merges = await database_sync_to_async(list_unreconciled_merges, thread_sensitive=False)()
    if merges is None:
        return
    team_id, merged_commits = merges
    client = await async_connect()
    for merge in merged_commits:
        await start_merge_check_workflow(merge, team_id=team_id, client=client)


@workflow.defn(name=RECONCILE_WORKFLOW_NAME)
class MergeReconcileWorkflow:
    @workflow.run
    async def run(self) -> None:
        await workflow.execute_activity(
            reconcile_merged_pull_requests_activity,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
