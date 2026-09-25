import json
import asyncio
from datetime import timedelta

from temporalio import common, workflow
from temporalio.exceptions import ActivityError, ApplicationError

from posthog.temporal.common.base import PostHogWorkflow

from products.error_tracking.backend.temporal.fingerprint_embedding_result.types import (
    AutoMergeReopenedTarget,
    FingerprintEmbeddingMergeResult,
)
from products.error_tracking.backend.temporal.lifecycle.issue_created.types import (
    EMBEDDING_SERVICE_UNAVAILABLE_ERROR_TYPE,
    IssueCreatedSnapshot,
    IssueCreatedWorkflowInputs,
    IssueCreatedWorkflowResult,
    IssueEmbeddingPreparationResult,
)
from products.error_tracking.backend.temporal.lifecycle.issue_reopened.types import IssueReopenedWorkflowInputs
from products.error_tracking.backend.temporal.lifecycle.issue_reopened.workflow import run_issue_reopened_side_effects

WORKFLOW_NAME = "error-tracking-issue-created"

ACTIVITY_RETRY_POLICY = common.RetryPolicy(
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(seconds=15),
    maximum_attempts=10,
)
ACTIVITY_START_TO_CLOSE_TIMEOUT = timedelta(minutes=5)
ALERT_DISPATCH_PATCH = "error-tracking-alert-dispatch-activity"
# Unlimited attempts inside the window: the start is cheap and idempotent, and only a
# Temporal outage longer than this loses the alert.
ALERT_DISPATCH_RETRY_POLICY = common.RetryPolicy(
    initial_interval=timedelta(seconds=5),
    maximum_interval=timedelta(minutes=1),
    maximum_attempts=0,
)
ALERT_DISPATCH_SCHEDULE_TO_CLOSE_TIMEOUT = timedelta(hours=1)
EMBEDDING_ACTIVITY_RETRY_POLICY = common.RetryPolicy(
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(seconds=15),
    maximum_attempts=4,
)


@workflow.defn(name=WORKFLOW_NAME)
class ErrorTrackingIssueCreatedWorkflow(PostHogWorkflow):
    @staticmethod
    def workflow_id_for(notification_id: str) -> str:
        return f"error-tracking-issue-created-{notification_id}"

    @staticmethod
    def parse_inputs(inputs: list[str]) -> IssueCreatedWorkflowInputs:
        if len(inputs) != 1:
            raise ValueError("Issue created workflow requires exactly one input")
        data = json.loads(inputs[0])
        # Event properties are loaded by reference inside activities to keep them out of Temporal payloads.
        data.pop("type", None)
        data.pop("event_properties", None)
        data["issue"] = IssueCreatedSnapshot(**data["issue"])
        return IssueCreatedWorkflowInputs(**data)

    @workflow.run
    async def run(self, inputs: IssueCreatedWorkflowInputs) -> IssueCreatedWorkflowResult:
        try:
            preparation = await workflow.execute_activity(
                "generate_issue_created_embedding_activity",
                inputs,
                result_type=IssueEmbeddingPreparationResult,
                start_to_close_timeout=ACTIVITY_START_TO_CLOSE_TIMEOUT,
                retry_policy=EMBEDDING_ACTIVITY_RETRY_POLICY,
            )
        except ActivityError as error:
            if not (
                isinstance(error.cause, ApplicationError)
                and error.cause.type == EMBEDDING_SERVICE_UNAVAILABLE_ERROR_TYPE
            ):
                raise
            workflow.logger.warning("Embedding service unavailable; emitting issue-created side effects without merge")
            (
                workflow.metric_meter()
                .with_additional_attributes({"reason": "embedding_service_unavailable"})
                .create_counter(
                    "error_tracking_issue_created_embedding_fail_open",
                    "Issue-created workflows that emitted side effects after embedding became unavailable",
                )
                .add(1)
            )
            preparation = IssueEmbeddingPreparationResult(
                team_exists=True,
                skipped_reason="embedding_service_unavailable",
            )
        if not preparation.team_exists:
            return IssueCreatedWorkflowResult()

        if preparation.embedding is not None:
            await workflow.execute_activity(
                "persist_issue_created_embedding_activity",
                preparation.embedding,
                start_to_close_timeout=ACTIVITY_START_TO_CLOSE_TIMEOUT,
                retry_policy=ACTIVITY_RETRY_POLICY,
            )
            merge_result = await workflow.execute_activity(
                "merge_issue_created_fingerprint_activity",
                preparation.embedding.merge_inputs,
                result_type=FingerprintEmbeddingMergeResult,
                start_to_close_timeout=ACTIVITY_START_TO_CLOSE_TIMEOUT,
                retry_policy=ACTIVITY_RETRY_POLICY,
            )
            if merge_result.merged_count > 0:
                # The exception belongs to the target issue now. A dormant target that the merge
                # put back to active owes its subscribers a reopened notification; an already
                # active target owes nothing, which matches a fingerprint that links directly.
                if merge_result.reopened_target is None:
                    return IssueCreatedWorkflowResult(merged=True)
                await run_issue_reopened_side_effects(_reopened_inputs(inputs, merge_result.reopened_target))
                return IssueCreatedWorkflowResult(merged=True, notified=True)

        # Patched: executions in flight when this activity shipped replay the old sequence.
        # Dispatch runs alongside the other side effects and is always awaited, so a
        # failure on either side never suppresses the other. Its open-ended retry covers
        # a Temporal outage; starts are idempotent on the notification id.
        dispatch = (
            asyncio.create_task(
                workflow.execute_activity(
                    "dispatch_issue_created_alert_activity",
                    inputs,
                    schedule_to_close_timeout=ALERT_DISPATCH_SCHEDULE_TO_CLOSE_TIMEOUT,
                    start_to_close_timeout=ACTIVITY_START_TO_CLOSE_TIMEOUT,
                    retry_policy=ALERT_DISPATCH_RETRY_POLICY,
                )
            )
            if workflow.patched(ALERT_DISPATCH_PATCH)
            else None
        )
        try:
            await workflow.execute_activity(
                "emit_issue_created_internal_event_activity",
                inputs,
                start_to_close_timeout=ACTIVITY_START_TO_CLOSE_TIMEOUT,
                retry_policy=ACTIVITY_RETRY_POLICY,
            )
            await workflow.execute_activity(
                "emit_issue_created_signal_activity",
                inputs,
                start_to_close_timeout=ACTIVITY_START_TO_CLOSE_TIMEOUT,
                retry_policy=ACTIVITY_RETRY_POLICY,
            )
        finally:
            if dispatch is not None:
                await dispatch
        return IssueCreatedWorkflowResult(
            notified=True,
            embedding_skipped_reason=preparation.skipped_reason,
        )


def _reopened_inputs(
    inputs: IssueCreatedWorkflowInputs, target: AutoMergeReopenedTarget
) -> IssueReopenedWorkflowInputs:
    return IssueReopenedWorkflowInputs(
        notification_id=target.notification_id,
        team_id=inputs.team_id,
        issue_id=target.issue_id,
        issue=target.issue,
        # The new fingerprint and its exception: the merge moved both onto the target issue.
        fingerprint=inputs.fingerprint,
        event_uuid=inputs.event_uuid,
        event_timestamp=inputs.event_timestamp,
        assignee=target.assignee,
    )
