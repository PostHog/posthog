import json
from datetime import timedelta

from temporalio import common, workflow

from posthog.temporal.common.base import PostHogWorkflow

from products.error_tracking.backend.temporal.lifecycle.issue_spiking.types import (
    IssueSpikingSnapshot,
    IssueSpikingWorkflowInputs,
    IssueSpikingWorkflowResult,
    SpikeEventPersistenceResult,
)
from products.error_tracking.backend.temporal.lifecycle.types import SpikeEventPersistenceStatus

WORKFLOW_NAME = "error-tracking-issue-spiking"

ACTIVITY_RETRY_POLICY = common.RetryPolicy(
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(seconds=15),
    maximum_attempts=10,
)
ACTIVITY_START_TO_CLOSE_TIMEOUT = timedelta(minutes=5)


@workflow.defn(name=WORKFLOW_NAME)
class ErrorTrackingIssueSpikingWorkflow(PostHogWorkflow):
    @staticmethod
    def workflow_id_for(notification_id: str) -> str:
        return f"{WORKFLOW_NAME}-{notification_id}"

    @staticmethod
    def parse_inputs(inputs: list[str]) -> IssueSpikingWorkflowInputs:
        if len(inputs) != 1:
            raise ValueError("Issue spiking workflow requires exactly one input")
        data = json.loads(inputs[0])
        data.pop("type", None)
        data.pop("event_properties", None)
        data["issue"] = IssueSpikingSnapshot(**data["issue"])
        return IssueSpikingWorkflowInputs(**data)

    @workflow.run
    async def run(self, inputs: IssueSpikingWorkflowInputs) -> IssueSpikingWorkflowResult:
        persistence = await workflow.execute_activity(
            "persist_issue_spiking_event_activity",
            inputs,
            result_type=SpikeEventPersistenceResult,
            start_to_close_timeout=ACTIVITY_START_TO_CLOSE_TIMEOUT,
            retry_policy=ACTIVITY_RETRY_POLICY,
        )
        if persistence.status == SpikeEventPersistenceStatus.MISSING_ISSUE:
            workflow.logger.warning(
                "Dropping spike notification for missing issue",
                extra={
                    "notification_id": inputs.notification_id,
                    "team_id": inputs.team_id,
                    "issue_id": inputs.issue_id,
                },
            )
            (
                workflow.metric_meter()
                .create_counter(
                    "error_tracking_issue_spiking_missing_issue",
                    "Issue-spiking workflows dropped because their issue no longer exists",
                )
                .add(1)
            )
            return IssueSpikingWorkflowResult()
        if persistence.status not in {
            SpikeEventPersistenceStatus.INSERTED,
            SpikeEventPersistenceStatus.ALREADY_PERSISTED,
        }:
            raise ValueError(f"Unknown spike persistence status: {persistence.status}")

        await workflow.execute_activity(
            "emit_issue_spiking_internal_event_activity",
            inputs,
            start_to_close_timeout=ACTIVITY_START_TO_CLOSE_TIMEOUT,
            retry_policy=ACTIVITY_RETRY_POLICY,
        )
        await workflow.execute_activity(
            "emit_issue_spiking_signal_activity",
            inputs,
            start_to_close_timeout=ACTIVITY_START_TO_CLOSE_TIMEOUT,
            retry_policy=ACTIVITY_RETRY_POLICY,
        )
        return IssueSpikingWorkflowResult(persisted=True, notified=True)
