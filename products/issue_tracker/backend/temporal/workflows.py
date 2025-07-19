import json
import temporalio
from datetime import timedelta
from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.logger import get_logger
from .inputs import IssueProcessingInputs
from .activities import process_issue_moved_to_todo_activity

logger = get_logger(__name__)


@temporalio.workflow.defn(name="process-issue-status-change")
class IssueProcessingWorkflow(PostHogWorkflow):
    """Workflow to handle background processing when an issue status changes."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> IssueProcessingInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return IssueProcessingInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: IssueProcessingInputs) -> str:
        """
        Main workflow execution for processing issue status changes.
        Currently handles issues moved to 'todo' status with potential for expansion.
        """
        logger.info(f"Processing issue status change for issue {inputs.issue_id}")

        # Only process if the issue was moved to 'todo' status
        if inputs.new_status == "todo":
            logger.info(f"Issue {inputs.issue_id} moved to TODO, starting background processing")

            # Execute the background processing activity
            result = await workflow.execute_activity(
                process_issue_moved_to_todo_activity,
                inputs,
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=30),
                    maximum_interval=timedelta(minutes=2),
                    maximum_attempts=3,
                ),
            )

            logger.info(f"Background processing completed for issue {inputs.issue_id}: {result}")
            return result
        else:
            logger.info(f"Issue {inputs.issue_id} status changed to {inputs.new_status}, no processing needed")
            return f"No processing required for status: {inputs.new_status}"
