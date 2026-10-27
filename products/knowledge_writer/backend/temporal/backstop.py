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

BACKSTOP_DELAY = timedelta(minutes=15)
PUSH_SEEN = "push_seen"
VERDICT_RECORDED = "verdict_recorded"
BACKSTOP_REASON = "backstop_no_merge_check"
MERGE_CHECK_ATTEMPTS = 3


@dataclass
class MergeBackstopInputs:
    commit_sha: str
    team_id: int


def record_backstop_verdict(inputs: MergeBackstopInputs) -> None:
    verdict = AdapterVerdict(
        source=DocsRequestSource.REPO_MERGE,
        subject_id=inputs.commit_sha,
        needs_docs=False,
        reason=BACKSTOP_REASON,
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


def run_backstop_merge_check(inputs: MergeBackstopInputs, *, is_final_attempt: bool) -> None:
    github_token = posthog_github_token(inputs.team_id)
    anthropic_api_key = getattr(settings, "ANTHROPIC_API_KEY", "")
    if github_token is None or not anthropic_api_key:
        record_backstop_verdict(inputs)
        return
    try:
        with github_client(github_token) as github, httpx.Client(timeout=30) as http:
            report = run_merge_check(
                inputs.commit_sha,
                github=github,
                http=http,
                anthropic_client=Anthropic(api_key=anthropic_api_key),
                checkouts=None,
            )
    except (httpx.HTTPError, APIError) as error:
        if not is_final_attempt:
            raise
        capture_exception(error, {"commit_sha": inputs.commit_sha})
        record_backstop_verdict(inputs)
        return
    intake.submit(REGISTRY[DocsRequestSource.REPO_MERGE].assess(report), team_id=inputs.team_id)


@activity.defn
@close_db_connections
async def run_merge_check_activity(inputs: MergeBackstopInputs) -> None:
    is_final_attempt = activity.info().attempt >= MERGE_CHECK_ATTEMPTS
    await database_sync_to_async(run_backstop_merge_check, thread_sensitive=False)(
        inputs, is_final_attempt=is_final_attempt
    )


@workflow.defn(name="knowledge-writer-merge-backstop")
class MergeBackstopWorkflow:
    def __init__(self) -> None:
        self.is_verdict_recorded = False

    @workflow.signal(name=PUSH_SEEN)
    def push_seen(self) -> None:
        return None

    @workflow.signal(name=VERDICT_RECORDED)
    def verdict_recorded(self) -> None:
        self.is_verdict_recorded = True

    async def verdict_arrives_in_time(self) -> bool:
        try:
            await workflow.wait_condition(lambda: self.is_verdict_recorded, timeout=BACKSTOP_DELAY)
        except TimeoutError:
            return False
        return True

    @workflow.run
    async def run(self, inputs: MergeBackstopInputs) -> None:
        if await self.verdict_arrives_in_time():
            return
        await workflow.execute_activity(
            run_merge_check_activity,
            inputs,
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=MERGE_CHECK_ATTEMPTS),
        )
