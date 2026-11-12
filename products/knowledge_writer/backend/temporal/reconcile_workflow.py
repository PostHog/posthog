from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import count

from django.core.cache import cache
from django.utils import timezone
from django.utils.dateparse import parse_datetime

import structlog
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.egress.limiter.policies import Priority
from posthog.exceptions_capture import capture_exception
from posthog.sync import database_sync_to_async
from posthog.temporal.common.client import async_connect
from posthog.temporal.common.utils import close_db_connections

from ...merge_check.sources import GitHubReader, LandedChange, landed_change, read_closed_pull_requests, read_github
from ..logic.pull_requests import docs_github
from ..settings import writer_settings
from .client import start_merge_check_workflow
from .merge_workflow import GITHUB_READ_ERRORS

logger = structlog.get_logger(__name__)

RECONCILE_WORKFLOW_NAME = "knowledge-writer-merge-reconcile"
RECONCILE_OVERLAP = timedelta(hours=3)
PULL_REQUESTS_PER_PAGE = 100
RECONCILED_AT_TTL = timedelta(days=1)


class RepositoryReconcileFailed(Exception):
    pass


@dataclass(frozen=True)
class UnreconciledMerges:
    team_id: int
    changes: list[LandedChange]
    reconciled_at_by_repository: dict[str, datetime]


def reconciled_at_cache_key(repository: str) -> str:
    return f"knowledge_writer:reconciled_at:{repository.lower()}"


def is_public_repository(github: GitHubReader, repository: str) -> bool:
    listed_repository = read_github(github, f"/repos/{repository}", endpoint="/repos/{owner}/{repo}").json()
    return listed_repository.get("private") is False


def is_at_or_after(listed_time: object, look_back_start: datetime) -> bool:
    parsed_time = parse_datetime(listed_time) if isinstance(listed_time, str) else None
    return parsed_time is not None and parsed_time >= look_back_start


def merged_changes_since(github: GitHubReader, repository: str, look_back_start: datetime) -> list[LandedChange]:
    changes: list[LandedChange] = []
    for page in count(1):
        listed = read_closed_pull_requests(github, repository, page=page, per_page=PULL_REQUESTS_PER_PAGE)
        merged_in_look_back = (
            landed_change(repository, pull_request)
            for pull_request in listed
            if is_at_or_after(pull_request.get("merged_at"), look_back_start)
        )
        changes.extend(change for change in merged_in_look_back if change is not None)
        if len(listed) < PULL_REQUESTS_PER_PAGE or not is_at_or_after(listed[-1].get("updated_at"), look_back_start):
            break
    return changes


def collect_unreconciled_changes(
    merges: UnreconciledMerges, github: GitHubReader, repository: str, reconcile_started_at: datetime
) -> None:
    if not is_public_repository(github, repository):
        logger.info("knowledge_writer_reconcile_repository_skipped", repository=repository, reason="not_public")
        return
    reconciled_at = cache.get(reconciled_at_cache_key(repository))
    if reconciled_at is None:
        logger.warning("knowledge_writer_reconciled_at_missing", repository=repository)
        reconciled_at = reconcile_started_at
    merges.changes.extend(merged_changes_since(github, repository, reconciled_at - RECONCILE_OVERLAP))
    merges.reconciled_at_by_repository[repository] = reconcile_started_at


def list_unreconciled_merges() -> UnreconciledMerges | None:
    writer = writer_settings()
    if writer is None:
        logger.warning("knowledge_writer_reconcile_unconfigured")
        return None
    reconcile_started_at = timezone.now()
    merges = UnreconciledMerges(team_id=writer.team_id, changes=[], reconciled_at_by_repository={})
    for repository in writer.source_repositories:
        github = docs_github(writer.team_id, repository.split("/", 1)[0], priority=Priority.NORMAL)
        if github is None:
            logger.info("knowledge_writer_reconcile_repository_skipped", repository=repository, reason="no_docs_github")
            continue
        try:
            collect_unreconciled_changes(merges, github, repository, reconcile_started_at)
        except GITHUB_READ_ERRORS as error:
            logger.warning(
                "knowledge_writer_reconcile_repository_failed", repository=repository, error_type=type(error).__name__
            )
            capture_exception(RepositoryReconcileFailed(f"reconciling {repository} failed: {error}"))
    return merges


def save_reconciled_at(reconciled_at_by_repository: dict[str, datetime]) -> None:
    for repository, reconciled_at in reconciled_at_by_repository.items():
        cache.set(reconciled_at_cache_key(repository), reconciled_at, timeout=RECONCILED_AT_TTL.total_seconds())


@activity.defn
@close_db_connections
async def reconcile_merged_pull_requests_activity() -> None:
    merges = await database_sync_to_async(list_unreconciled_merges, thread_sensitive=False)()
    if merges is None:
        return
    client = await async_connect()
    for change in merges.changes:
        await start_merge_check_workflow(change, team_id=merges.team_id, client=client)
    await database_sync_to_async(save_reconciled_at, thread_sensitive=False)(merges.reconciled_at_by_repository)
    logger.info(
        "knowledge_writer_reconcile_finished",
        merged_changes=len(merges.changes),
        repositories_reconciled=len(merges.reconciled_at_by_repository),
    )


@workflow.defn(name=RECONCILE_WORKFLOW_NAME)
class MergeReconcileWorkflow:
    @workflow.run
    async def run(self) -> None:
        await workflow.execute_activity(
            reconcile_merged_pull_requests_activity,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
