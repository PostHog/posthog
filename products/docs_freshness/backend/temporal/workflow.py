from temporalio import workflow
from temporalio.exceptions import ActivityError, ApplicationError

from posthog.temporal.common.base import PostHogWorkflow

from products.docs_freshness.backend.facade.contracts import MergeRefMissing, PullRequestHead
from products.docs_freshness.backend.logic.impact_check import ImpactVerdict, VerdictName
from products.docs_freshness.backend.temporal.activities import check_head, record_verdict
from products.docs_freshness.backend.temporal.constants import (
    CHECK_HEAD_TIMEOUT,
    CHECK_PULL_REQUEST_HEAD_WORKFLOW,
    DURABLE_RETRY_POLICY,
    RECORD_VERDICT_TIMEOUT,
)
from products.docs_freshness.backend.temporal.contracts import RecordVerdictInput


def _is_merge_ref_missing(error: ActivityError) -> bool:
    return isinstance(error.cause, ApplicationError) and error.cause.type == MergeRefMissing.__name__


@workflow.defn(name=CHECK_PULL_REQUEST_HEAD_WORKFLOW)
class CheckPullRequestHeadWorkflow(PostHogWorkflow):
    inputs_cls = PullRequestHead

    @workflow.run
    async def run(self, head: PullRequestHead) -> None:
        try:
            verdict = await workflow.execute_activity(
                check_head,
                head,
                start_to_close_timeout=CHECK_HEAD_TIMEOUT,
                retry_policy=DURABLE_RETRY_POLICY,
            )
        except ActivityError as error:
            if not _is_merge_ref_missing(error):
                raise
            await self._record(head, "unmergeable", ImpactVerdict(impacted=[]))
            return
        if verdict is None:
            return
        await self._record(head, "flagged" if verdict.is_flagged else "clear", verdict)

    async def _record(self, head: PullRequestHead, verdict_name: VerdictName, verdict: ImpactVerdict) -> None:
        await workflow.execute_activity(
            record_verdict,
            RecordVerdictInput(head=head, verdict_name=verdict_name, verdict=verdict),
            start_to_close_timeout=RECORD_VERDICT_TIMEOUT,
            retry_policy=DURABLE_RETRY_POLICY,
        )
