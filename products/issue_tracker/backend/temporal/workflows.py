import json
import temporalio
from datetime import timedelta
from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.logger import get_logger
from .inputs import IssueProcessingInputs
from .activities import (
    process_issue_moved_to_todo_activity,
    update_issue_status_activity,
    ai_agent_work_activity,
    commit_and_push_changes_activity,
    get_issue_details_activity,
    create_pull_request_activity,
    update_issue_github_info_activity,
)
from .github_activities import (
    clone_repo_and_create_branch_activity,
    cleanup_repo_activity,
)

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
        
        When an issue moves to 'todo', this workflow will:
        1. Clone the GitHub repository
        2. Create a new branch for the issue
        3. Run background processing/agent tasks
        4. Clean up resources
        """
        logger.info(f"Processing issue status change for issue {inputs.issue_id}")

        # Only process if the issue was moved to 'todo' status
        if inputs.new_status == "todo":
            logger.info(f"Issue {inputs.issue_id} moved to TODO, starting GitHub workflow")

            repo_info = None
            try:
                # Step 1: Clone repository and create branch
                logger.info(f"Step 1: Cloning repository and creating branch for issue {inputs.issue_id}")
                repo_info = await workflow.execute_activity(
                    clone_repo_and_create_branch_activity,
                    inputs,
                    start_to_close_timeout=timedelta(minutes=10),  # Allow time for large repos
                    retry_policy=RetryPolicy(
                        initial_interval=timedelta(seconds=30),
                        maximum_interval=timedelta(minutes=2),
                        maximum_attempts=2,  # Don't retry too many times for git operations
                    ),
                )

                if not repo_info.get("success"):
                    error_msg = f"Failed to clone repository: {repo_info.get('error', 'Unknown error')}"
                    logger.error(error_msg)
                    return error_msg

                logger.info(f"Repository cloned successfully. Branch: {repo_info['branch_name']}")

                # Step 2: Move issue to in_progress status
                logger.info(f"Step 2: Moving issue {inputs.issue_id} to in_progress status")
                await workflow.execute_activity(
                    update_issue_status_activity,
                    {"issue_id": inputs.issue_id, "team_id": inputs.team_id, "new_status": "in_progress"},
                    start_to_close_timeout=timedelta(minutes=2),
                    retry_policy=RetryPolicy(
                        initial_interval=timedelta(seconds=10),
                        maximum_interval=timedelta(seconds=30),
                        maximum_attempts=3,
                    ),
                )

                # Step 3: Execute initial background processing
                logger.info(f"Step 3: Running initial background processing for issue {inputs.issue_id}")
                processing_result = await workflow.execute_activity(
                    process_issue_moved_to_todo_activity,
                    inputs,
                    start_to_close_timeout=timedelta(minutes=5),
                    retry_policy=RetryPolicy(
                        initial_interval=timedelta(seconds=30),
                        maximum_interval=timedelta(minutes=2),
                        maximum_attempts=3,
                    ),
                )

                logger.info(f"Background processing completed: {processing_result}")

                # Step 4: Execute AI agent work
                logger.info(f"Step 4: Starting AI agent work for issue {inputs.issue_id}")
                ai_result = await workflow.execute_activity(
                    ai_agent_work_activity,
                    {"inputs": inputs, "repo_path": repo_info["repo_path"], "branch_name": repo_info["branch_name"]},
                    start_to_close_timeout=timedelta(minutes=30),  # Allow more time for AI work
                    retry_policy=RetryPolicy(
                        initial_interval=timedelta(minutes=1),
                        maximum_interval=timedelta(minutes=5),
                        maximum_attempts=2,  # Don't retry too many times for expensive operations
                    ),
                )

                if not ai_result.get("success"):
                    error_msg = f"AI agent work failed: {ai_result.get('error', 'Unknown error')}"
                    logger.error(error_msg)
                    return error_msg

                logger.info(f"AI agent work completed successfully for issue {inputs.issue_id}")

                # Step 5: Commit and push changes
                logger.info(f"Step 5: Committing and pushing changes for issue {inputs.issue_id}")

                # Get issue details for commit message
                issue_details = await workflow.execute_activity(
                    get_issue_details_activity,
                    {"issue_id": inputs.issue_id, "team_id": inputs.team_id},
                    start_to_close_timeout=timedelta(minutes=1),
                )

                commit_result = await workflow.execute_activity(
                    commit_and_push_changes_activity,
                    {"repo_path": repo_info["repo_path"], "branch_name": repo_info["branch_name"], "issue_title": issue_details["title"], "issue_id": inputs.issue_id},
                    start_to_close_timeout=timedelta(minutes=10),
                    retry_policy=RetryPolicy(
                        initial_interval=timedelta(seconds=30),
                        maximum_interval=timedelta(minutes=2),
                        maximum_attempts=3,
                    ),
                )

                if not commit_result.get("success"):
                    error_msg = f"Failed to commit and push changes: {commit_result.get('error', 'Unknown error')}"
                    logger.error(error_msg)
                    return error_msg

                logger.info(f"Changes committed and pushed successfully for issue {inputs.issue_id}")

                # Step 6: Update issue with GitHub branch info
                logger.info(f"Step 6: Updating issue {inputs.issue_id} with GitHub branch info")
                await workflow.execute_activity(
                    update_issue_github_info_activity,
                    {"issue_id": inputs.issue_id, "team_id": inputs.team_id, "branch_name": repo_info["branch_name"]},
                    start_to_close_timeout=timedelta(minutes=2),
                )

                # Step 7: Create pull request (optional, depends on GitHub integration settings)
                logger.info(f"Step 7: Creating pull request for issue {inputs.issue_id}")
                pr_result = await workflow.execute_activity(
                    create_pull_request_activity,
                    {"repo_path": repo_info["repo_path"], "branch_name": repo_info["branch_name"], "issue_id": inputs.issue_id, "issue_title": issue_details["title"], "issue_description": issue_details["description"]},
                    start_to_close_timeout=timedelta(minutes=5),
                    retry_policy=RetryPolicy(
                        initial_interval=timedelta(seconds=30),
                        maximum_interval=timedelta(minutes=1),
                        maximum_attempts=2,
                    ),
                )

                # Update issue with PR URL if PR was created successfully
                if pr_result.get("success") and pr_result.get("pr_url"):
                    logger.info(f"Pull request created: {pr_result['pr_url']}")
                    await workflow.execute_activity(
                        update_issue_github_info_activity,
                        {"issue_id": inputs.issue_id, "team_id": inputs.team_id, "branch_name": repo_info["branch_name"], "pr_url": pr_result["pr_url"]},
                        start_to_close_timeout=timedelta(minutes=2),
                    )
                else:
                    logger.info(f"Pull request creation skipped or failed: {pr_result.get('message', 'Unknown reason')}")

                # Step 8: Update issue status to testing
                logger.info(f"Step 8: Moving issue {inputs.issue_id} to testing status")
                await workflow.execute_activity(
                    update_issue_status_activity,
                    {"issue_id": inputs.issue_id, "team_id": inputs.team_id, "new_status": "testing"},
                    start_to_close_timeout=timedelta(minutes=2),
                    retry_policy=RetryPolicy(
                        initial_interval=timedelta(seconds=10),
                        maximum_interval=timedelta(seconds=30),
                        maximum_attempts=3,
                    ),
                )

                success_msg = f"Issue {inputs.issue_id} processed successfully. Branch: {repo_info['branch_name']}"
                logger.info(success_msg)
                return success_msg

            except Exception as e:
                error_msg = f"Workflow failed for issue {inputs.issue_id}: {str(e)}"
                logger.error(error_msg)
                return error_msg

            finally:
                # Step 9: Always clean up the cloned repository
                if repo_info and repo_info.get("repo_path"):
                    logger.info(f"Step 9: Cleaning up repository at {repo_info['repo_path']}")
                    try:
                        await workflow.execute_activity(
                            cleanup_repo_activity,
                            repo_info["repo_path"],
                            start_to_close_timeout=timedelta(minutes=2),
                            retry_policy=RetryPolicy(
                                initial_interval=timedelta(seconds=10),
                                maximum_interval=timedelta(seconds=30),
                                maximum_attempts=2,
                            ),
                        )
                        logger.info("Repository cleanup completed")
                    except Exception as cleanup_error:
                        logger.warning(f"Failed to cleanup repository: {cleanup_error}")
                        # Don't fail the whole workflow for cleanup issues
        else:
            logger.info(f"Issue {inputs.issue_id} status changed to {inputs.new_status}, no processing needed")
            return f"No processing required for status: {inputs.new_status}"
