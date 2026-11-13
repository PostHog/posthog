from dataclasses import dataclass
from datetime import timedelta

from django.db import DatabaseError

import httpx
import requests
import structlog
from anthropic import APIError
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

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
from ...merge_check.sources import LandedChange, UnexpectedGitHubResponse
from ..adapters.registry import REGISTRY
from ..facade.contracts import AdapterVerdict
from ..facade.enums import DocsRequestSource, MergeCheckFailure
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
    commit_sha: str
    team_id: int
    repository: str = LEGACY_MERGE_CHECK_REPOSITORY
    pull_request_number: int | None = None
    installation_id: str | None = None


class MergeCheckNotAdmitted(Exception):
    pass


def is_delivery_admitted(inputs: MergeCheckInputs, installation_id: str) -> bool:
    writer = writer_settings()
    if writer is None or writer.team_id != inputs.team_id:
        return False
    return any(integration.team_id == inputs.team_id for integration in installation_integrations(installation_id))


def record_merge_check_failed(inputs: MergeCheckInputs, failure_reason: MergeCheckFailure) -> None:
    record_unchecked_merge(inputs, reason=MERGE_CHECK_FAILED_REASON, failure_reason=failure_reason)


def record_unchecked_merge(inputs: MergeCheckInputs, *, reason: str, failure_reason: MergeCheckFailure | None) -> None:
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
        source=DocsRequestSource.REPO_MERGE,
        subject_id=inputs.commit_sha,
        needs_docs=False,
        reason=reason,
        request=None,
        failure_reason=failure_reason,
    )
    intake.submit(verdict, team_id=inputs.team_id)


def merge_check_budget_key(team_id: int) -> str:
    return f"knowledge_writer:merge_check_budget:{team_id}"


def is_within_check_budget(team_id: int) -> bool:
    decision = consume(merge_check_budget_key(team_id), MERGE_CHECK_BUDGET)
    if isinstance(decision, BucketUnavailable):
        logger.warning("knowledge_writer_merge_check_budget_unavailable", team_id=team_id, error=decision.error)
        return True
    return decision.allowed


def check_merge(inputs: MergeCheckInputs, *, is_final_attempt: bool) -> None:
    try:
        is_admitted = inputs.installation_id is None or is_delivery_admitted(inputs, inputs.installation_id)
    except DatabaseError as error:
        if not is_final_attempt:
            raise
        capture_exception(error, {"commit_sha": inputs.commit_sha})
        record_merge_check_failed(inputs, MergeCheckFailure.ADMISSION_LOOKUP_FAILED)
        return
    if not is_admitted and not is_final_attempt:
        raise MergeCheckNotAdmitted(inputs.commit_sha)
    if not is_admitted:
        record_unchecked_merge(inputs, reason=NOT_ADMITTED_REASON, failure_reason=None)
        return
    if inputs.pull_request_number is None:
        record_merge_check_failed(inputs, MergeCheckFailure.NO_PULL_REQUEST_NUMBER)
        return
    if not is_within_check_budget(inputs.team_id):
        record_unchecked_merge(inputs, reason=CHECK_CAPPED_REASON, failure_reason=None)
        return
    github = docs_github(inputs.team_id, inputs.repository.split("/", 1)[0], priority=Priority.NORMAL)
    if github is None:
        record_merge_check_failed(inputs, MergeCheckFailure.NO_DOCS_GITHUB)
        return
    try:
        anthropic_client = judge_client(inputs.commit_sha)
    except ValueError:
        record_merge_check_failed(inputs, MergeCheckFailure.JUDGE_CLIENT_UNAVAILABLE)
        return
    deadline = CheckDeadline.starting_now()
    try:
        with (
            anthropic_client,
            deadline_http(deadline, timeout_seconds=SITEMAP_TIMEOUT_SECONDS) as http,
            anthropic_client.with_options(http_client=http) as deadline_anthropic_client,
        ):
            report = run_merge_check(
                LandedChange(
                    repository=inputs.repository,
                    after=inputs.commit_sha,
                    pull_request_number=inputs.pull_request_number,
                ),
                is_final_attempt=is_final_attempt,
                github=DeadlineGitHub(github, deadline),
                http=http,
                anthropic_client=deadline_anthropic_client,
                source=docs_source(),
                writer_login=github_app_login(),
                deadline=deadline,
            )
    except MERGE_CHECK_RETRYABLE_ERRORS as error:
        if not is_final_attempt:
            refund(merge_check_budget_key(inputs.team_id), MERGE_CHECK_BUDGET)
            raise
        capture_exception(error, {"commit_sha": inputs.commit_sha})
        record_merge_check_failed(inputs, MergeCheckFailure.RETRIES_EXHAUSTED)
        return
    intake.submit(REGISTRY[DocsRequestSource.REPO_MERGE].assess(report), team_id=inputs.team_id)


@activity.defn
@close_db_connections
async def run_merge_check_activity(inputs: MergeCheckInputs) -> None:
    is_final_attempt = activity.info().attempt >= MERGE_CHECK_ATTEMPTS
    async with Heartbeater():
        await database_sync_to_async(check_merge, thread_sensitive=False)(inputs, is_final_attempt=is_final_attempt)


@workflow.defn(name="knowledge-writer-merge-check")
class MergeCheckWorkflow:
    @workflow.run
    async def run(self, inputs: MergeCheckInputs) -> None:
        await workflow.execute_activity(
            run_merge_check_activity,
            inputs,
            start_to_close_timeout=timedelta(minutes=5),
            schedule_to_close_timeout=timedelta(minutes=20),
            heartbeat_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(
                initial_interval=MERGE_CHECK_RETRY_INTERVAL, maximum_attempts=MERGE_CHECK_ATTEMPTS
            ),
        )
