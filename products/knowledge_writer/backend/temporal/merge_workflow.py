from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings

import httpx
from anthropic import Anthropic, APIError
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.exceptions_capture import capture_exception
from posthog.sync import database_sync_to_async
from posthog.temporal.common.utils import close_db_connections

from ...merge_check.check import run_merge_check
from ...merge_check.sources import POSTHOG_REPOSITORY, github_client
from ..adapters import REGISTRY
from ..facade.contracts import AdapterVerdict
from ..facade.enums import DocsRequestSource
from ..logic import intake
from ..logic.publish import docs_github

MERGE_CHECK_FAILED_REASON = "merge_check_failed"
MERGE_CHECK_ATTEMPTS = 3


@dataclass
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


def posthog_github_token(team_id: int) -> str | None:
    github = docs_github(team_id, POSTHOG_REPOSITORY.split("/", 1)[0])
    if github is None:
        return None
    if github.access_token_expired():
        github.refresh_access_token()
    return github.installation_access_token


def check_merge(inputs: MergeCheckInputs, *, is_final_attempt: bool) -> None:
    github_token = posthog_github_token(inputs.team_id)
    anthropic_api_key = getattr(settings, "ANTHROPIC_API_KEY", "")
    if github_token is None or not anthropic_api_key:
        record_merge_check_failed(inputs)
        return
    try:
        with github_client(github_token) as github, httpx.Client(timeout=30) as http:
            report = run_merge_check(
                inputs.commit_sha,
                github=github,
                http=http,
                anthropic_client=Anthropic(api_key=anthropic_api_key),
            )
    except (httpx.HTTPError, APIError) as error:
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
    await database_sync_to_async(check_merge, thread_sensitive=False)(inputs, is_final_attempt=is_final_attempt)


@workflow.defn(name="knowledge-writer-merge-check")
class MergeCheckWorkflow:
    @workflow.run
    async def run(self, inputs: MergeCheckInputs) -> None:
        await workflow.execute_activity(
            run_merge_check_activity,
            inputs,
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=MERGE_CHECK_ATTEMPTS),
        )
