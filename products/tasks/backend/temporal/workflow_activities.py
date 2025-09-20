"""
Workflow-agnostic activities for the configurable task system.
"""

from typing import Any, Optional

import temporalio

from posthog.temporal.common.logger import get_logger

logger = get_logger(__name__)


@temporalio.activity.defn(name="get_workflow_configuration")
async def get_workflow_configuration_activity(params: dict[str, Any]) -> dict[str, Any]:
    """Get the workflow configuration for a task."""
    try:
        task_id = params["task_id"]
        team_id = params["team_id"]

        from django.db import transaction

        from asgiref.sync import sync_to_async

        from products.tasks.backend.models import Task

        @sync_to_async
        def get_workflow_config():
            with transaction.atomic():
                task = Task.objects.select_related("workflow", "current_stage").get(id=task_id, team_id=team_id)

                # Get effective workflow (custom or team default)
                workflow = task.effective_workflow
                if not workflow:
                    logger.warning(f"No workflow found for task {task_id}, using legacy behavior")
                    return {
                        "has_workflow": False,
                        "current_stage_key": task.current_stage.key if task.current_stage else "backlog",
                        "transitions": [],
                    }

                # Get current stage
                current_stage = task.current_stage
                if not current_stage:
                    # Use first stage as default
                    current_stage = workflow.stages.filter(is_archived=False).order_by("position").first()
                    if current_stage:
                        task.current_stage = current_stage
                        task.save(update_fields=["current_stage"])
                    else:
                        logger.error(f"Could not find any stage for task {task_id}")
                        return {
                            "has_workflow": False,
                            "current_stage_key": task.current_stage.key if task.current_stage else "backlog",
                            "transitions": [],
                        }

                # For now, simplified transitions (no transitions model yet)
                transitions = []

                return {
                    "has_workflow": True,
                    "workflow_id": str(workflow.id),
                    "workflow_name": workflow.name,
                    "current_stage_key": current_stage.key,
                    "current_stage_name": current_stage.name,
                    "current_stage_is_manual_only": current_stage.is_manual_only,
                    "transitions": transitions,
                }

        return await get_workflow_config()

    except Exception as e:
        logger.exception(f"Failed to get workflow configuration for task {task_id}: {e}")
        return {"has_workflow": False, "current_stage_key": "backlog", "transitions": [], "error": str(e)}


@temporalio.activity.defn(name="get_agent_triggered_transition")
async def get_agent_triggered_transition_activity(params: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Return agent info for the current stage if present (no transition logic)."""
    try:
        task_id = params["task_id"]
        team_id = params["team_id"]

        from django.db import transaction

        from asgiref.sync import sync_to_async

        from products.tasks.backend.models import Task

        @sync_to_async
        def get_agent_transition():
            with transaction.atomic():
                task = Task.objects.select_related("workflow", "current_stage").get(id=task_id, team_id=team_id)

                workflow = task.effective_workflow
                if not workflow:
                    return None

                current_stage = task.current_stage
                if not current_stage:
                    return None

                # Return agent info if current stage has an agent
                if not current_stage.agent:
                    return None

                return {
                    "agent_name": current_stage.agent.name,
                    "agent_type": current_stage.agent.agent_type,
                    "agent_config": current_stage.agent.config,
                }

        return await get_agent_transition()

    except Exception as e:
        logger.exception(f"Failed to get agent transition for task {task_id}: {e}")
        return None


@temporalio.activity.defn(name="move_task_to_stage")
async def move_task_to_stage_activity(params: dict[str, Any]) -> dict[str, Any]:
    """Advance task to the next non-archived stage by position (linear)."""
    try:
        task_id = params["task_id"]
        team_id = params["team_id"]
        # key-based moves removed; always advance linearly

        from django.db import transaction

        from asgiref.sync import sync_to_async

        from products.tasks.backend.models import Task

        @sync_to_async
        def move_task():
            with transaction.atomic():
                task = Task.objects.select_related("workflow", "current_stage").get(id=task_id, team_id=team_id)

                workflow = task.effective_workflow
                if not workflow:
                    logger.warning(f"Task {task_id} has no workflow, cannot advance stage")
                    return {
                        "success": False,
                        "error": f"Task has no workflow configured",
                        "previous_stage": task.current_stage.key if task.current_stage else "backlog",
                        "new_stage": None,
                    }

                # Determine next stage linearly
                current_stage = task.current_stage
                if not current_stage:
                    # If no current stage, pick the first non-archived by position
                    target_stage = workflow.stages.filter(is_archived=False).order_by("position").first()
                    if not target_stage:
                        logger.error(f"Could not find any non-archived stage for workflow {workflow.id}")
                        return {"success": False, "error": "No stages available in workflow"}
                else:
                    target_stage = (
                        workflow.stages.filter(position__gt=current_stage.position, is_archived=False)
                        .order_by("position")
                        .first()
                    )
                    if not target_stage:
                        return {
                            "success": False,
                            "error": "Already at final stage",
                            "previous_stage": current_stage.key,
                            "new_stage": current_stage.key,
                        }

                # Simplified validation: can move to any stage in the same workflow
                # (transition_id parameter is ignored since there are no transition models)

                previous_stage_key = task.current_stage.key if task.current_stage else "backlog"

                # Update task
                task.current_stage = target_stage
                task.save(update_fields=["current_stage"])

                logger.info(f"Task {task_id} moved from {previous_stage_key} to {target_stage.key}")

                return {
                    "success": True,
                    "message": f"Task moved from {previous_stage_key} to {target_stage.key}",
                    "previous_stage": previous_stage_key,
                    "new_stage": target_stage.key,
                }

        return await move_task()

    except Exception as e:
        logger.exception(f"Failed to advance task {task_id} to next stage: {e}")
        return {"success": False, "error": str(e)}


@temporalio.activity.defn(name="should_trigger_agent_workflow")
async def should_trigger_agent_workflow_activity(params: dict[str, Any]) -> dict[str, Any]:
    """Determine if an agent workflow should be triggered for a status change."""
    try:
        task_id = params["task_id"]
        team_id = params["team_id"]
        # Stage will be inferred from the task in DB

        from django.db import transaction

        from asgiref.sync import sync_to_async

        from products.tasks.backend.models import Task

        @sync_to_async
        def get_task_and_check_trigger():
            with transaction.atomic():
                task = Task.objects.select_related("workflow", "current_stage").get(id=task_id, team_id=team_id)

                workflow = task.effective_workflow
                if not workflow:
                    # Legacy behavior: trigger only when entering first actionable stage is not supported without config
                    should_trigger = False
                    return {
                        "should_trigger": should_trigger,
                        "trigger_reason": "No workflow configured",
                        "workflow_name": "Legacy Workflow",
                    }

                # Use the task's current stage only
                current_stage = task.current_stage
                if not current_stage:
                    return {"should_trigger": False, "trigger_reason": "Task has no current stage"}

                # Simplified agent check: stages with agents attached can trigger workflows
                agent_transitions = current_stage.agent is not None

                if agent_transitions:
                    return {
                        "should_trigger": True,
                        "trigger_reason": f"Agent available at {current_stage.key}",
                        "workflow_name": workflow.name,
                        "current_stage_key": current_stage.key,
                    }

                return {
                    "should_trigger": False,
                    "trigger_reason": f"No agent at {current_stage.key}",
                    "workflow_name": workflow.name,
                }

        return await get_task_and_check_trigger()

    except Exception as e:
        logger.exception(f"Failed to check agent workflow trigger for task {task_id}: {e}")
        return {"should_trigger": False, "trigger_reason": f"Error: {str(e)}"}


@temporalio.activity.defn(name="trigger_task_processing")
async def trigger_task_processing_activity(params: dict[str, Any]) -> dict[str, Any]:
    """Enqueue the task processing workflow again for the next stage."""
    try:
        task_id = params["task_id"]
        team_id = params["team_id"]
        user_id = params.get("user_id")

        logger.info(f"Triggering task processing workflow for task {task_id}")

        # Fire-and-forget trigger via our temporal client helper
        from products.tasks.backend.temporal.client import execute_task_processing_workflow

        execute_task_processing_workflow(task_id=task_id, team_id=team_id, user_id=user_id)

        return {"success": True}
    except Exception as e:
        logger.exception(f"Failed to trigger task processing workflow: {e}")
        return {"success": False, "error": str(e)}

@temporalio.activity.defn(name="execute_agent_for_transition")
async def execute_agent_for_transition_activity(params: dict[str, Any]) -> dict[str, Any]:
    """Execute the appropriate agent for a workflow transition."""
    try:
        task_id = params["task_id"]
        team_id = params["team_id"]
        transition_config = params["transition_config"]
        repo_info = params.get("repo_info")

        agent_type = transition_config.get("agent_type")

        if agent_type == "code_generation":
            from .activities import ai_agent_work_activity

            result = await ai_agent_work_activity(
                {
                    "inputs": {
                        "task_id": task_id,
                        "team_id": team_id,
                        "new_status": transition_config.get("to_stage_key"),
                        "previous_status": transition_config.get("from_stage_key"),
                        "user_id": None,
                    },
                    "repo_path": repo_info.get("repo_path") if repo_info else None,
                    "repository": repo_info.get("repository") if repo_info else None,
                    "branch_name": repo_info.get("branch_name") if repo_info else None,
                }
            )

            return {
                "success": result.get("success", False),
                "message": result.get("message", "Agent execution completed"),
                "agent_type": agent_type,
                "details": result,
            }

        elif agent_type == "triage":
            # Placeholder for triage agent
            logger.info(f"Executing triage agent for task {task_id}")

            # TODO: Implement triage agent logic
            # This would analyze the task and write a clear plan/scope

            return {"success": True, "message": "Triage agent completed (placeholder)", "agent_type": agent_type}

        elif agent_type == "review":
            # Placeholder for review agent
            logger.info(f"Executing review agent for task {task_id}")

            # TODO: Implement review agent logic
            # This would review completed work and provide feedback

            return {"success": True, "message": "Review agent completed (placeholder)", "agent_type": agent_type}

        elif agent_type == "testing":
            # Placeholder for testing agent
            logger.info(f"Executing testing agent for task {task_id}")

            # TODO: Implement testing agent logic
            # This would run tests and verify the implementation

            return {"success": True, "message": "Testing agent completed (placeholder)", "agent_type": agent_type}

        else:
            return {"success": False, "error": f"Unknown agent type: {agent_type}", "agent_type": agent_type}

    except Exception as e:
        logger.exception(f"Failed to execute agent for task {task_id}: {e}")
        return {
            "success": False,
            "error": str(e),
            "agent_type": params.get("transition_config", {}).get("agent_type", "unknown"),
        }
