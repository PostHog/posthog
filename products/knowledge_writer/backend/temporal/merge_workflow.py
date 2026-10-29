from dataclasses import dataclass
from datetime import timedelta

import httpx
import requests
from anthropic import APIError
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.egress.github.transport import GitHubEgressBudgetExhausted, GitHubRateLimitError
from posthog.egress.limiter.policies import Priority
from posthog.exceptions_capture import capture_exception
from posthog.models.integration import GitHubIntegrationError
from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.utils import close_db_connections

from ...merge_check.check import run_merge_check
from ...merge_check.judge import judge_client
from ...merge_check.sources import POSTHOG_REPOSITORY
from ..adapters.registry import REGISTRY
from ..facade.contracts import AdapterVerdict
from ..facade.enums import DocsRequestSource
from ..logic import intake
from ..logic.pull_requests import docs_github

MERGE_CHECK_FAILED_REASON = "merge_check_failed"
MERGE_CHECK_ATTEMPTS = 3
MERGE_CHECK_RETRY_INTERVAL = timedelta(minutes=1)
MERGE_CHECK_RETRYABLE_ERRORS = (
    requests.RequestException,
    GitHubIntegrationError,
    GitHubRateLimitError,
    GitHubEgressBudgetExhausted,
    httpx.HTTPError,
    APIError,
)


@dataclass(frozen=True)
class MergeCheckInputs:
    commit_sha: str
    team_id: int


def record_merge_check_failed(inputs: MergeCheckInputs) -> None:
    verdict = AdapterVerdict(
        source=DocsRequestSource.REPO_MERGE,
        subject_id=inputs.commit_sha,
        needs_docs=False,
        reason=MERGE_CHECK_FAILED_REASON,
        request=None,
    )
    intake.submit(verdict, team_id=inputs.team_id)


def check_merge(inputs: MergeCheckInputs, *, is_final_attempt: bool) -> None:
    github = docs_github(inputs.team_id, POSTHOG_REPOSITORY.split("/", 1)[0], priority=Priority.NORMAL)
    if github is None:
        record_merge_check_failed(inputs)
        return
    try:
        anthropic_client = judge_client(inputs.commit_sha)
    except ValueError:
        record_merge_check_failed(inputs)
        return
    try:
        with httpx.Client(timeout=30) as http, anthropic_client:
            report = run_merge_check(inputs.commit_sha, github=github, http=http, anthropic_client=anthropic_client)
    except MERGE_CHECK_RETRYABLE_ERRORS as error:
        if not is_final_attempt:
            raise
        capture_exception(error, {"commit_sha": inputs.commit_sha})
        record_merge_check_failed(inputs)
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
            heartbeat_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(
                initial_interval=MERGE_CHECK_RETRY_INTERVAL, maximum_attempts=MERGE_CHECK_ATTEMPTS
            ),
        )
