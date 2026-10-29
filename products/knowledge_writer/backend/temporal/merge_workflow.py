import dataclasses
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

from products.business_knowledge.backend.facade import api as business_knowledge_facade

from ...merge_check.check import commit_url, run_merge_check
from ...merge_check.judge import judge_client
from ...merge_check.sources import POSTHOG_REPOSITORY, MergeSubject
from ..adapters.registry import REGISTRY
from ..facade.contracts import DocsCommandRequest, MergeCheckReport
from ..facade.enums import DocsRequestSource
from ..logic import intake
from ..logic.pull_requests import docs_github

MERGE_CHECK_FAILED_REASON = "merge_check_failed"
MERGE_CHECK_ATTEMPTS = 3
MERGE_CHECK_RETRY_INTERVAL = timedelta(minutes=1)
DOCS_QUERY_MAX_LENGTH = 500
MERGE_CHECK_RETRYABLE_ERRORS = (
    requests.RequestException,
    GitHubIntegrationError,
    GitHubRateLimitError,
    GitHubEgressBudgetExhausted,
    httpx.HTTPError,
    APIError,
)


@dataclass(frozen=True)
class MergeCheckCommand:
    pull_request_number: int
    pull_request_url: str
    head_sha: str
    note: str
    requested_by: str
    requested_by_user_id: int


@dataclass(frozen=True)
class MergeCheckInputs:
    commit_sha: str | None
    team_id: int
    repository: str = POSTHOG_REPOSITORY
    command: MergeCheckCommand | None = None


def merge_check_source(inputs: MergeCheckInputs) -> DocsRequestSource:
    return DocsRequestSource.COMMAND_TAG if inputs.command else DocsRequestSource.REPO_MERGE


def merge_check_subject_key(inputs: MergeCheckInputs) -> str:
    if inputs.command is None:
        return inputs.commit_sha or ""
    return f"{inputs.repository}#{inputs.command.pull_request_number}"


def docs_command_request(inputs: MergeCheckInputs) -> DocsCommandRequest | None:
    if inputs.command is None:
        return None
    return DocsCommandRequest(repository=inputs.repository, **dataclasses.asdict(inputs.command))


def submit_report(inputs: MergeCheckInputs, report: MergeCheckReport) -> None:
    report = dataclasses.replace(report, command=docs_command_request(inputs))
    intake.submit(REGISTRY[merge_check_source(inputs)].assess(report), team_id=inputs.team_id)


def record_merge_check_failed(inputs: MergeCheckInputs) -> None:
    failed_report = MergeCheckReport(
        commit_sha=inputs.commit_sha,
        commit_url=inputs.command.pull_request_url
        if inputs.command
        else commit_url(inputs.repository, inputs.commit_sha),
        title="",
        needs_docs=False,
        reason=MERGE_CHECK_FAILED_REASON,
    )
    submit_report(inputs, failed_report)


def find_docs_page_urls(team_id: int, docs_query: str) -> list[str]:
    if not docs_query.strip():
        return []
    hits = business_knowledge_facade.search_knowledge(team_id=team_id, query=docs_query[:DOCS_QUERY_MAX_LENGTH])
    return [hit.url for hit in hits]


def check_merge(inputs: MergeCheckInputs, *, is_final_attempt: bool) -> None:
    github = docs_github(inputs.team_id, inputs.repository.split("/", 1)[0], priority=Priority.NORMAL)
    if github is None:
        record_merge_check_failed(inputs)
        return
    subject_key = merge_check_subject_key(inputs)
    try:
        anthropic_client = judge_client(subject_key)
    except ValueError:
        record_merge_check_failed(inputs)
        return
    subject = MergeSubject(
        repository=inputs.repository,
        commit_sha=inputs.commit_sha,
        pull_request_number=inputs.command.pull_request_number if inputs.command else None,
        note=inputs.command.note if inputs.command else "",
    )
    try:
        with anthropic_client:
            report = run_merge_check(
                subject,
                github=github,
                find_docs_page_urls=lambda docs_query: find_docs_page_urls(inputs.team_id, docs_query),
                anthropic_client=anthropic_client,
            )
    except MERGE_CHECK_RETRYABLE_ERRORS as error:
        if not is_final_attempt:
            raise
        capture_exception(error, {"merge_check_subject": subject_key})
        record_merge_check_failed(inputs)
        return
    submit_report(inputs, report)


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
