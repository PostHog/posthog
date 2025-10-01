import json
from datetime import timedelta

import temporalio
from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.logger import get_logger

from .github_activities import (
    cleanup_repo_activity,
    clone_repo_and_create_branch_activity,
    commit_local_changes_activity,
    create_pr_and_update_task_activity,
)
from .inputs import TaskProcessingInputs
from .workflow_activities import (
    execute_agent_for_transition_activity,
    get_agent_triggered_transition_activity,
    get_workflow_configuration_activity,
    move_task_to_stage_activity,
    should_trigger_agent_workflow_activity,
    trigger_task_processing_activity,
)

logger = get_logger(__name__)


@temporalio.workflow.defn(name="process-task-workflow-agnostic")
class WorkflowAgnosticTaskProcessingWorkflow(PostHogWorkflow):
    """Workflow-agnostic task processing that adapts to any workflow configuration."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> TaskProcessingInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return TaskProcessingInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: TaskProcessingInputs) -> str:
        """
        Main workflow execution that adapts to workflow configuration.

        This workflow:
        1. Checks if agent automation should be triggered
        2. Gets workflow configuration for the task
        3. Executes the appropriate agents based on transitions
        4. Moves the task through configured stages
        """
        logger.info(f"Starting workflow-agnostic processing for task {inputs.task_id}")

        try:
            permission_check = await workflow.execute_activity(
                "check_temporal_workflow_permissions",
                {
                    "task_id": inputs.task_id,
                    "team_id": inputs.team_id,
                    "user_id": inputs.user_id,
                },
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=5),
                    maximum_interval=timedelta(seconds=15),
                    maximum_attempts=2,
                ),
            )

            if not permission_check.get("allowed", False):
                error_msg = (
                    f"Workflow execution not permitted: {permission_check.get('reason', 'Feature flag not enabled')}"
                )
                logger.warning(error_msg)
                return error_msg
            # Step 1: Check if we should trigger agent processing
            logger.info(f"Step 1: Checking if agent workflow should be triggered for task {inputs.task_id}")
            trigger_check = await workflow.execute_activity(
                should_trigger_agent_workflow_activity,
                {
                    "task_id": inputs.task_id,
                    "team_id": inputs.team_id,
                },
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=10),
                    maximum_interval=timedelta(seconds=30),
                    maximum_attempts=3,
                ),
            )

            if not trigger_check.get("should_trigger", False):
                logger.info(f"Agent workflow not triggered: {trigger_check.get('trigger_reason', 'Unknown reason')}")
                return f"No agent processing needed: {trigger_check.get('trigger_reason', 'Unknown reason')}"

            logger.info(f"Agent workflow triggered: {trigger_check.get('trigger_reason', '')}")

            # Step 2: Get workflow configuration
            logger.info(f"Step 2: Getting workflow configuration for task {inputs.task_id}")
            workflow_config = await workflow.execute_activity(
                get_workflow_configuration_activity,
                {
                    "task_id": inputs.task_id,
                    "team_id": inputs.team_id,
                },
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=10),
                    maximum_interval=timedelta(seconds=30),
                    maximum_attempts=3,
                ),
            )

            if not workflow_config.get("has_workflow", False):
                logger.info("No workflow configuration found")
                raise ValueError("No workflow configuration found")

            current_stage_key = workflow_config.get("current_stage_key")
            logger.info(f"Current stage: {current_stage_key} in workflow: {workflow_config.get('workflow_name')}")

            # Step 3: If current stage has an agent, execute it once and advance
            agent_info = await workflow.execute_activity(
                get_agent_triggered_transition_activity,
                {
                    "task_id": inputs.task_id,
                    "team_id": inputs.team_id,
                },
                start_to_close_timeout=timedelta(minutes=2),
            )

            if not agent_info:
                msg = f"No agent configured for stage {current_stage_key}. Nothing to do."
                logger.info(msg)
                return msg

            logger.info(f"Executing agent '{agent_info['agent_name']}' for stage '{current_stage_key}'")

            # Set up repository if this is a code generation agent
            repo_info = None
            if agent_info.get("agent_type") == "code_generation":
                repo_info = await self._setup_repository(inputs)
                if not repo_info.get("success"):
                    error_msg = f"Failed to setup repository: {repo_info.get('error')}"
                    logger.error(error_msg)
                    return error_msg

            agent_result = await workflow.execute_activity(
                execute_agent_for_transition_activity,
                {
                    "task_id": inputs.task_id,
                    "team_id": inputs.team_id,
                    "user_id": inputs.user_id,
                    "transition_config": agent_info,
                    "repo_info": repo_info,
                },
                start_to_close_timeout=timedelta(minutes=30),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(minutes=1),
                    maximum_interval=timedelta(minutes=5),
                    maximum_attempts=2,
                ),
            )

            if not agent_result.get("success"):
                error_msg = f"Agent execution failed: {agent_result.get('error', 'Unknown error')}"
                logger.error(error_msg)
                return error_msg

            logger.info("Agent completed successfully")

            # Create PR if repository was set up (any agent that works with code)
            if repo_info and repo_info.get("success") and repo_info.get("branch_name"):
                logger.info(f"Repository was set up for {agent_info.get('agent_type', 'unknown')} agent work")
                logger.info(f"Checking if PR should be created for branch: {repo_info.get('branch_name')}")

                # Check for commits ahead of origin and create PR if changes exist
                try:
                    # Use the commit activity to handle both local changes and checking for commits ahead of origin
                    commit_result = await workflow.execute_activity(
                        commit_local_changes_activity,
                        {
                            "inputs": inputs.__dict__,
                            "repo_path": repo_info["repo_path"],
                            "branch_name": repo_info["branch_name"],
                            "task_title": f"Task: {inputs.task_id}",
                        },
                        start_to_close_timeout=timedelta(minutes=10),
                        retry_policy=RetryPolicy(
                            initial_interval=timedelta(seconds=10),
                            maximum_interval=timedelta(seconds=30),
                            maximum_attempts=2,
                        ),
                    )

                    # Create PR if there were changes (either local files committed or existing commits ahead of origin)
                    if commit_result.get("success"):
                        # Check if there were any changes at all (local commits or pushed commits)
                        has_changes = (
                            commit_result.get("committed_files")  # New local changes were committed
                            or "pushed" in commit_result.get("message", "").lower()  # Existing commits were pushed
                            or commit_result.get("total_files", 0) > 0  # Any files were processed
                        )

                        if has_changes:
                            logger.info(
                                f"Changes detected on branch, creating PR. Commit result: {commit_result.get('message', 'Unknown')}"
                            )
                            try:
                                pr_result = await workflow.execute_activity(
                                    create_pr_and_update_task_activity,
                                    {
                                        "task_id": inputs.task_id,
                                        "team_id": inputs.team_id,
                                        "branch_name": repo_info["branch_name"],
                                    },
                                    start_to_close_timeout=timedelta(minutes=5),
                                    retry_policy=RetryPolicy(
                                        initial_interval=timedelta(seconds=10),
                                        maximum_interval=timedelta(seconds=30),
                                        maximum_attempts=2,
                                    ),
                                )

                                if pr_result.get("success"):
                                    logger.info(f"PR created successfully: {pr_result.get('pr_url')}")
                                else:
                                    logger.warning(f"PR creation failed: {pr_result.get('error')}")

                            except Exception as pr_error:
                                logger.warning(f"PR creation failed with exception: {pr_error}")
                        else:
                            logger.info("No changes detected on branch, skipping PR creation")
                            logger.info(f"Commit result details: {commit_result}")
                    else:
                        logger.warning(f"Commit activity failed: {commit_result.get('error', 'Unknown error')}")

                except Exception as commit_error:
                    logger.warning(f"Failed to check for changes: {commit_error}")
                    # Don't fail the workflow just because commit/PR creation failed

            logger.info("Moving to next stage")
            move_result = await workflow.execute_activity(
                move_task_to_stage_activity,
                {
                    "task_id": inputs.task_id,
                    "team_id": inputs.team_id,
                },
                start_to_close_timeout=timedelta(minutes=2),
            )

            if not move_result.get("success"):
                error_msg = f"Failed to move task to next stage: {move_result.get('error', 'Unknown error')}"
                logger.error(error_msg)
                return error_msg

            # Cleanup repository if created
            if repo_info and repo_info.get("repo_path"):
                try:
                    await workflow.execute_activity(
                        cleanup_repo_activity,
                        repo_info["repo_path"],
                        start_to_close_timeout=timedelta(minutes=2),
                    )
                except Exception as cleanup_error:
                    logger.warning(f"Repository cleanup failed: {cleanup_error}")

            # Confirm new stage
            new_stage = move_result.get("new_stage")
            logger.info(f"Successfully moved to stage: {new_stage}")

            # Trigger processing again for the next stage (fire-and-forget)
            await workflow.execute_activity(
                trigger_task_processing_activity,
                {
                    "task_id": inputs.task_id,
                    "team_id": inputs.team_id,
                    "user_id": inputs.user_id,
                },
                start_to_close_timeout=timedelta(minutes=1),
            )

            return f"Agent executed and task advanced to stage: {new_stage} (next run enqueued)"

        except Exception as e:
            error_msg = f"Workflow-agnostic processing failed for task {inputs.task_id}: {str(e)}"
            logger.exception(error_msg)
            return error_msg

    async def _setup_repository(self, inputs: TaskProcessingInputs) -> dict:
        """Set up repository for code generation agents."""
        try:
            repo_info = await workflow.execute_activity(
                clone_repo_and_create_branch_activity,
                inputs,
                start_to_close_timeout=timedelta(minutes=10),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=30),
                    maximum_interval=timedelta(minutes=2),
                    maximum_attempts=2,
                ),
            )
            return repo_info
        except Exception as e:
            logger.exception(f"Failed to setup repository: {e}")
            return {"success": False, "error": str(e)}
