from dataclasses import dataclass, replace
from datetime import timedelta

from django.db import DatabaseError

import httpx
import requests
import structlog
from anthropic import APIError
from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

from posthog.egress.github.transport import GitHubEgressBudgetExhausted, GitHubRateLimitError
from posthog.egress.limiter.policies import Priority
from posthog.exceptions_capture import capture_exception
from posthog.github.installations import installation_integrations
from posthog.models.integration import GitHubIntegrationError
from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.utils import close_db_connections
from posthog.token_bucket import BucketUnavailable, Budget, consume, refund

from ...merge_check.check import run_merge_check
from ...merge_check.deadline import CheckDeadline, CheckDeadlineExceeded, DeadlineGitHub, deadline_http
from ...merge_check.judge import judge_client
from ...merge_check.sources import (
    GitHubReader,
    LandedChange,
    UnexpectedGitHubResponse,
    landed_change,
    read_pull_request,
)
from ..adapters.repo_merge import RepoMergeAdapter, pull_request_key
from ..facade.contracts import AdapterVerdict, MergeCheckReport
from ..facade.enums import DocsRequestSource, MergeCheckFailure
from ..facade.finished_check_hooks import FinishedDocsCheck, get_finished_docs_check_hooks
from ..logic import intake
from ..logic.pull_requests import docs_github, github_app_login
from ..settings import docs_source, writer_settings

logger = structlog.get_logger(__name__)

MERGE_CHECK_FAILED_REASON = "merge_check_failed"
NOT_ADMITTED_REASON = "not_admitted"
CHECK_CAPPED_REASON = "check_capped"
MERGE_CHECK_BUDGET = Budget(burst=200, per_hour=34)
MERGE_CHECK_ATTEMPTS = 3
MERGE_CHECK_RETRY_INTERVAL = timedelta(minutes=1)
ADD_DOCS_CHECK_WAITER_SIGNAL = "add_docs_check_waiter"
GITHUB_READ_ERRORS = (
    requests.RequestException,
    GitHubIntegrationError,
    GitHubRateLimitError,
    GitHubEgressBudgetExhausted,
)
MERGE_CHECK_RETRYABLE_ERRORS = (
    *GITHUB_READ_ERRORS,
    httpx.HTTPError,
    APIError,
    UnexpectedGitHubResponse,
    CheckDeadlineExceeded,
)
SITEMAP_TIMEOUT_SECONDS = 30


LEGACY_MERGE_CHECK_REPOSITORY = "PostHog/posthog"  # inputs started before pushes named the repository


@dataclass(frozen=True)
class MergeCheckInputs:
    commit_sha: str | None
    team_id: int
    repository: str = LEGACY_MERGE_CHECK_REPOSITORY
    pull_request_number: int | None = None
    installation_id: str | None = None
    origin: DocsRequestSource = DocsRequestSource.REPO_MERGE
    requested_by: str | None = None
    requested_by_user_id: int | None = None
    note: str = ""


class MergeCheckNotAdmitted(Exception):
    pass


def is_check_admitted(inputs: MergeCheckInputs) -> bool:
    if inputs.installation_id is None and inputs.origin != DocsRequestSource.COMMAND_TAG:
        return True
    writer = writer_settings()
    if writer is None or writer.team_id != inputs.team_id:
        return False
    if inputs.installation_id is None:
        return True
    return any(
        integration.team_id == inputs.team_id for integration in installation_integrations(inputs.installation_id)
    )


def record_merge_check_failed(inputs: MergeCheckInputs, failure_reason: MergeCheckFailure) -> FinishedDocsCheck:
    return record_unchecked_merge(inputs, reason=MERGE_CHECK_FAILED_REASON, failure_reason=failure_reason)


def record_unchecked_merge(
    inputs: MergeCheckInputs, *, reason: str, failure_reason: MergeCheckFailure | None
) -> FinishedDocsCheck:
    logger.warning(
        "knowledge_writer_merge_unchecked",
        commit_sha=inputs.commit_sha,
        repository=inputs.repository,
        pull_request_number=inputs.pull_request_number,
        team_id=inputs.team_id,
        installation_id=inputs.installation_id,
        reason=reason,
        failure_reason=failure_reason,
    )
    verdict = AdapterVerdict(
        source=inputs.origin,
        subject_id=inputs.commit_sha or pull_request_key(inputs.repository, inputs.pull_request_number),
        needs_docs=False,
        reason=reason,
        request=None,
        failure_reason=failure_reason,
    )
    return submit_verdict(inputs, verdict)


def submit_verdict(inputs: MergeCheckInputs, verdict: AdapterVerdict) -> FinishedDocsCheck:
    outcome = intake.submit(verdict, team_id=inputs.team_id)
    return FinishedDocsCheck(
        status=outcome.status, failure_reason=verdict.failure_reason, pull_request_url=outcome.pull_request_url
    )


def tell_docs_check_waiters(finished: FinishedDocsCheck) -> None:
    for hook in get_finished_docs_check_hooks():
        # A hook belongs to another product, and the verdict is already recorded.
        try:
            hook(finished)
        except Exception:
            logger.exception("knowledge_writer_docs_check_hook_failed", waiter_ids=finished.waiter_ids)


def merge_check_budget_key(team_id: int) -> str:
    return f"knowledge_writer:merge_check_budget:{team_id}"


def is_within_check_budget(team_id: int) -> bool:
    decision = consume(merge_check_budget_key(team_id), MERGE_CHECK_BUDGET)
    if isinstance(decision, BucketUnavailable):
        logger.warning("knowledge_writer_merge_check_budget_unavailable", team_id=team_id, error=decision.error)
        return True
    return decision.allowed


def check_merge(inputs: MergeCheckInputs, *, is_final_attempt: bool) -> FinishedDocsCheck:
    try:
        is_admitted = is_check_admitted(inputs)
    except DatabaseError as error:
        if not is_final_attempt:
            raise
        capture_exception(error, {"commit_sha": inputs.commit_sha})
        return record_merge_check_failed(inputs, MergeCheckFailure.ADMISSION_LOOKUP_FAILED)
    if not is_admitted and not is_final_attempt:
        raise MergeCheckNotAdmitted(inputs.commit_sha)
    if not is_admitted:
        return record_unchecked_merge(inputs, reason=NOT_ADMITTED_REASON, failure_reason=None)
    if inputs.pull_request_number is None:
        return record_merge_check_failed(inputs, MergeCheckFailure.NO_PULL_REQUEST_NUMBER)
    if not is_within_check_budget(inputs.team_id):
        return record_unchecked_merge(inputs, reason=CHECK_CAPPED_REASON, failure_reason=None)
    github = docs_github(inputs.team_id, inputs.repository.split("/", 1)[0], priority=Priority.NORMAL)
    if github is None:
        return record_merge_check_failed(inputs, MergeCheckFailure.NO_DOCS_GITHUB)
    deadline = CheckDeadline.starting_now()
    deadline_github = DeadlineGitHub(github, deadline)
    try:
        change = landed_change_for(inputs, inputs.pull_request_number, deadline_github)
        report = (
            None
            if change is None
            else judged_report(change, deadline_github, deadline, is_final_attempt=is_final_attempt)
        )
    except MERGE_CHECK_RETRYABLE_ERRORS as error:
        if not is_final_attempt:
            refund(merge_check_budget_key(inputs.team_id), MERGE_CHECK_BUDGET)
            raise
        capture_exception(error, {"commit_sha": inputs.commit_sha})
        return record_merge_check_failed(inputs, MergeCheckFailure.RETRIES_EXHAUSTED)
    if change is None:
        return record_merge_check_failed(inputs, MergeCheckFailure.PULL_REQUEST_NOT_MERGED)
    if report is None:
        return record_merge_check_failed(inputs, MergeCheckFailure.JUDGE_CLIENT_UNAVAILABLE)
    return submit_verdict(inputs, RepoMergeAdapter().assess(report, inputs))


def landed_change_for(inputs: MergeCheckInputs, pull_request_number: int, github: GitHubReader) -> LandedChange | None:
    if inputs.commit_sha is not None:
        return LandedChange(
            repository=inputs.repository, after=inputs.commit_sha, pull_request_number=pull_request_number
        )
    return landed_change(inputs.repository, read_pull_request(github, inputs.repository, pull_request_number))


def judged_report(
    change: LandedChange, github: GitHubReader, deadline: CheckDeadline, *, is_final_attempt: bool
) -> MergeCheckReport | None:
    try:
        anthropic_client = judge_client(change.after)
    except ValueError:
        return None
    with (
        anthropic_client,
        deadline_http(deadline, timeout_seconds=SITEMAP_TIMEOUT_SECONDS) as http,
        anthropic_client.with_options(http_client=http) as deadline_anthropic_client,
    ):
        return run_merge_check(
            change,
            is_final_attempt=is_final_attempt,
            github=github,
            http=http,
            anthropic_client=deadline_anthropic_client,
            source=docs_source(),
            writer_login=github_app_login(),
            deadline=deadline,
        )


# None: an activity a worker without docs check waiters ran returned nothing, and its history replays here.
@activity.defn
@close_db_connections
async def run_merge_check_activity(inputs: MergeCheckInputs) -> FinishedDocsCheck | None:
    is_final_attempt = activity.info().attempt >= MERGE_CHECK_ATTEMPTS
    async with Heartbeater():
        return await database_sync_to_async(check_merge, thread_sensitive=False)(
            inputs, is_final_attempt=is_final_attempt
        )


@activity.defn
async def tell_docs_check_waiters_activity(finished: FinishedDocsCheck) -> None:
    await database_sync_to_async(tell_docs_check_waiters, thread_sensitive=False)(finished)


@workflow.defn(name="knowledge-writer-merge-check")
class MergeCheckWorkflow:
    def __init__(self) -> None:
        self._waiter_ids: list[str] = []

    @workflow.signal(name=ADD_DOCS_CHECK_WAITER_SIGNAL)
    def add_docs_check_waiter(self, waiter_id: str) -> None:
        self._waiter_ids.append(waiter_id)

    @workflow.run
    async def run(self, inputs: MergeCheckInputs) -> None:
        try:
            finished = await workflow.execute_activity(
                run_merge_check_activity,
                inputs,
                start_to_close_timeout=timedelta(minutes=5),
                schedule_to_close_timeout=timedelta(minutes=20),
                heartbeat_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(
                    initial_interval=MERGE_CHECK_RETRY_INTERVAL, maximum_attempts=MERGE_CHECK_ATTEMPTS
                ),
            )
        except ActivityError:
            await self._tell_waiters(
                FinishedDocsCheck(
                    status="no_docs", failure_reason=MergeCheckFailure.RETRIES_EXHAUSTED, pull_request_url=None
                )
            )
            raise
        if finished is not None:
            await self._tell_waiters(finished)

    async def _tell_waiters(self, finished: FinishedDocsCheck) -> None:
        told_count = 0
        # A waiter can arrive while the last one is told; the workflow only closes once none is left.
        while told_count < len(self._waiter_ids):
            waiter_ids = tuple(self._waiter_ids[told_count:])
            told_count = len(self._waiter_ids)
            await workflow.execute_activity(
                tell_docs_check_waiters_activity,
                replace(finished, waiter_ids=waiter_ids),
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
