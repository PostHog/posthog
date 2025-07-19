import temporalio

from posthog.temporal.common.logger import bind_contextvars, get_logger
from posthog.sync import database_sync_to_async
from .inputs import IssueProcessingInputs

logger = get_logger(__name__)


@temporalio.activity.defn
async def process_issue_moved_to_todo_activity(inputs: IssueProcessingInputs) -> str:
    """
    Background processing activity when an issue is moved to TODO status.
    This is where you can add any background work you want to happen when
    a card moves to the todo column. Examples:
    - Send notifications
    - Update external systems
    - Generate reports
    - Process dependencies
    - Log analytics events
    """
    bind_contextvars(
        issue_id=inputs.issue_id,
        team_id=inputs.team_id,
        status_change=f"{inputs.previous_status} -> {inputs.new_status}",
    )

    logger.info(f"Starting background processing for issue {inputs.issue_id}")

    try:
        # Import Issue model inside the activity to avoid Django apps loading issues
        from django.apps import apps

        Issue = apps.get_model("issue_tracker", "Issue")

        # Get the issue from the database
        issue = await database_sync_to_async(Issue.objects.get)(id=inputs.issue_id, team_id=inputs.team_id)

        # Verify the issue is still in todo status
        if issue.status != "todo":
            logger.warning(f"Issue {inputs.issue_id} is no longer in todo status, skipping processing")
            return f"Issue status changed, skipping processing"

        # TODO: Add your actual background processing logic here
        # Examples:

        # 1. Send a notification
        logger.info(f"Issue '{issue.title}' moved to TODO - sending notifications...")

        # 2. Update external systems
        logger.info(f"Updating external tracking systems for issue {inputs.issue_id}...")

        # 3. Log analytics event
        logger.info(f"Logging analytics event for todo transition...")

        # 4. Process any automated tasks
        logger.info(f"Running automated processing for issue type: {issue.origin_product}")

        # For now, just log the successful processing
        logger.info(f"Successfully processed issue {inputs.issue_id} moved to TODO")

        return f"Successfully processed issue {inputs.issue_id} background tasks"

    except Exception as e:
        if "DoesNotExist" in str(type(e)):
            logger.exception(f"Issue {inputs.issue_id} not found in team {inputs.team_id}")
        else:
            logger.exception(f"Error processing issue {inputs.issue_id}: {str(e)}")
        raise
