from temporalio import workflow
from temporalio.exceptions import ActivityError, ApplicationError

from posthog.temporal.common.base import PostHogWorkflow

from products.docs_freshness.backend.facade.contracts import LandedCommit, MergeRefMissing, PullRequestHead
from products.docs_freshness.backend.logic.impact_check import ImpactVerdict, VerdictName, pull_request_merge_ref
from products.docs_freshness.backend.temporal.activities import check_head, record_verdict, start_landed_check
from products.docs_freshness.backend.temporal.constants import (
    CHECK_HEAD_TIMEOUT,
    CHECK_LANDED_COMMIT_WORKFLOW,
    CHECK_PULL_REQUEST_HEAD_WORKFLOW,
    DURABLE_RETRY_POLICY,
    RECORD_VERDICT_TIMEOUT,
    START_LANDED_CHECK_TIMEOUT,
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
            await self._record(
                head, "unmergeable", ImpactVerdict(checked_ref=pull_request_merge_ref(head), impacted=[])
            )
            raise ApplicationError(
                f"Pull request {head.pr_number} has no merge ref for head {head.head_sha}", non_retryable=True
            ) from error
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


@workflow.defn(name=CHECK_LANDED_COMMIT_WORKFLOW)
class CheckLandedCommitWorkflow(PostHogWorkflow):
    inputs_cls = LandedCommit

    @workflow.run
    async def run(self, commit: LandedCommit) -> None:
        await workflow.execute_activity(
            start_landed_check,
            commit,
            start_to_close_timeout=START_LANDED_CHECK_TIMEOUT,
            retry_policy=DURABLE_RETRY_POLICY,
        )
