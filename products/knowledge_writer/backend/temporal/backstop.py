from dataclasses import dataclass
from datetime import timedelta

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.sync import database_sync_to_async
from posthog.temporal.common.utils import close_db_connections

from ..facade.contracts import AdapterVerdict
from ..facade.enums import DocsRequestSource
from ..logic import intake

BACKSTOP_DELAY = timedelta(minutes=15)
PUSH_SEEN = "push_seen"
VERDICT_RECORDED = "verdict_recorded"
BACKSTOP_REASON = "backstop_no_merge_check"


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


@activity.defn
@close_db_connections
async def run_merge_check_activity(inputs: MergeBackstopInputs) -> None:
    await database_sync_to_async(record_backstop_verdict, thread_sensitive=False)(inputs)


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
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
