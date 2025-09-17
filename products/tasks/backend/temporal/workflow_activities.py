"""
Workflow-agnostic activities for the configurable task system.
"""

import json
import logging
from typing import Dict, Any, Optional, List

import temporalio
from temporalio import activity

from posthog.temporal.common.logger import get_logger

logger = get_logger(__name__)


@temporalio.activity.defn(name="get_workflow_configuration")
async def get_workflow_configuration_activity(task_id: str, team_id: int) -> Dict[str, Any]:
    """Get the workflow configuration for a task."""
    try:
        from django.db import transaction
        from products.tasks.backend.models import Task, TaskWorkflow
        
        with transaction.atomic():
            task = Task.objects.select_related('workflow', 'current_stage').get(
                id=task_id, team_id=team_id
            )
            
            # Get effective workflow (custom or team default)
            workflow = task.effective_workflow
            if not workflow:
                logger.warning(f"No workflow found for task {task_id}, using legacy behavior")
                return {
                    "has_workflow": False,
                    "current_stage_key": task.current_stage.key if task.current_stage else 'backlog',
                    "transitions": []
                }
            
            # Get current stage
            current_stage = task.current_stage
            if not current_stage:
                # Use first stage as default
                current_stage = workflow.stages.filter(is_archived=False).order_by('position').first()
                if current_stage:
                    task.current_stage = current_stage
                    task.save(update_fields=['current_stage'])
                else:
                    logger.error(f"Could not find any stage for task {task_id}")
                    return {
                        "has_workflow": False,
                        "current_stage_key": task.current_stage.key if task.current_stage else 'backlog',
                        "transitions": []
                    }
            
            # Get available transitions from current stage
            transitions = list(workflow.transitions.filter(
                from_stage=current_stage,
                is_active=True
            ).select_related('to_stage', 'agent').values(
                'id',
                'to_stage__key',
                'to_stage__name',
                'trigger_type',
                'agent__name',
                'agent__agent_type',
                'agent__config',
                'conditions'
            ))
            
            return {
                "has_workflow": True,
                "workflow_id": str(workflow.id),
                "workflow_name": workflow.name,
                "current_stage_key": current_stage.key,
                "current_stage_name": current_stage.name,
                "current_stage_is_manual_only": current_stage.is_manual_only,
                "transitions": transitions
            }
            
    except Exception as e:
        logger.exception(f"Failed to get workflow configuration for task {task_id}: {e}")
        return {
            "has_workflow": False,
            "current_stage_key": "backlog",
            "transitions": [],
            "error": str(e)
        }


@temporalio.activity.defn(name="get_agent_triggered_transition")
async def get_agent_triggered_transition_activity(
    task_id: str, 
    team_id: int, 
    current_stage_key: str
) -> Optional[Dict[str, Any]]:
    """Find an agent-triggered transition from the current stage."""
    try:
        from django.db import transaction
        from products.tasks.backend.models import Task
        
        with transaction.atomic():
            task = Task.objects.select_related('workflow', 'current_stage').get(
                id=task_id, team_id=team_id
            )
            
            workflow = task.effective_workflow
            if not workflow:
                return None
            
            current_stage = task.current_stage
            if not current_stage or current_stage.key != current_stage_key:
                # Try to find stage by key
                try:
                    current_stage = workflow.stages.get(key=current_stage_key)
                except:
                    logger.error(f"Could not find stage with key {current_stage_key}")
                    return None
            
            # Find agent-triggered transitions
            agent_transitions = workflow.transitions.filter(
                from_stage=current_stage,
                trigger_type='agent',
                is_active=True
            ).select_related('to_stage', 'agent').first()
            
            if not agent_transitions:
                return None
            
            return {
                "transition_id": str(agent_transitions.id),
                "to_stage_key": agent_transitions.to_stage.key,
                "to_stage_name": agent_transitions.to_stage.name,
                "agent_name": agent_transitions.agent.name if agent_transitions.agent else None,
                "agent_type": agent_transitions.agent.agent_type if agent_transitions.agent else None,
                "agent_config": agent_transitions.agent.config if agent_transitions.agent else {},
                "conditions": agent_transitions.conditions
            }
            
    except Exception as e:
        logger.exception(f"Failed to get agent transition for task {task_id}: {e}")
        return None


@temporalio.activity.defn(name="move_task_to_stage")
async def move_task_to_stage_activity(
    task_id: str, 
    team_id: int, 
    target_stage_key: str,
    transition_id: Optional[str] = None
) -> Dict[str, Any]:
    """Move a task to a specific workflow stage."""
    try:
        from django.db import transaction
        from products.tasks.backend.models import Task
        
        with transaction.atomic():
            task = Task.objects.select_related('workflow', 'current_stage').get(
                id=task_id, team_id=team_id
            )
            
            workflow = task.effective_workflow
            if not workflow:
                # Without workflow, cannot move to specific stage
                logger.warning(f"Task {task_id} has no workflow, cannot move to stage {target_stage_key}")
                return {
                    "success": False,
                    "error": f"Task has no workflow configured",
                    "previous_stage": task.current_stage.key if task.current_stage else 'backlog',
                    "new_stage": target_stage_key
                }
            
            # Find target stage
            try:
                target_stage = workflow.stages.get(key=target_stage_key)
            except:
                logger.error(f"Could not find target stage {target_stage_key}")
                return {
                    "success": False,
                    "error": f"Target stage {target_stage_key} not found"
                }
            
            # Check if transition is valid
            if transition_id:
                transition_exists = workflow.transitions.filter(
                    id=transition_id,
                    from_stage=task.current_stage,
                    to_stage=target_stage,
                    is_active=True
                ).exists()
                
                if not transition_exists:
                    return {
                        "success": False,
                        "error": f"Invalid transition from {task.current_stage.key if task.current_stage else 'none'} to {target_stage_key}"
                    }
            
            previous_stage_key = task.current_stage.key if task.current_stage else 'backlog'
            
            # Update task
            task.current_stage = target_stage
            task.save(update_fields=['current_stage'])
            
            logger.info(f"Task {task_id} moved from {previous_stage_key} to {target_stage_key}")
            
            return {
                "success": True,
                "message": f"Task moved from {previous_stage_key} to {target_stage_key}",
                "previous_stage": previous_stage_key,
                "new_stage": target_stage_key
            }
            
    except Exception as e:
        logger.exception(f"Failed to move task {task_id} to stage {target_stage_key}: {e}")
        return {
            "success": False,
            "error": str(e)
        }


@temporalio.activity.defn(name="should_trigger_agent_workflow")
async def should_trigger_agent_workflow_activity(
    task_id: str,
    team_id: int,
    new_status: str,
    previous_status: str
) -> Dict[str, Any]:
    """Determine if an agent workflow should be triggered for a status change."""
    try:
        from django.db import transaction
        from products.tasks.backend.models import Task
        
        with transaction.atomic():
            task = Task.objects.select_related('workflow', 'current_stage').get(
                id=task_id, team_id=team_id
            )
            
            workflow = task.effective_workflow
            if not workflow:
                # Legacy behavior: trigger on move to "todo"
                should_trigger = new_status == "todo"
                return {
                    "should_trigger": should_trigger,
                    "trigger_reason": "Legacy behavior: moved to TODO" if should_trigger else "No legacy trigger",
                    "workflow_name": "Legacy Workflow"
                }
            
            # Find the stage corresponding to new_status
            try:
                current_stage = workflow.stages.get(key=new_status)
            except:
                logger.error(f"Could not find stage for status {new_status}")
                return {
                    "should_trigger": False,
                    "trigger_reason": f"Stage {new_status} not found in workflow"
                }
            
            # Check if there are any agent-triggered transitions from this stage
            agent_transitions = workflow.transitions.filter(
                from_stage=current_stage,
                trigger_type='agent',
                is_active=True
            ).exists()
            
            if agent_transitions:
                # Update task to use the correct stage
                task.current_stage = current_stage
                task.save(update_fields=['current_stage'])
                
                return {
                    "should_trigger": True,
                    "trigger_reason": f"Agent transitions available from {new_status}",
                    "workflow_name": workflow.name,
                    "current_stage_key": new_status
                }
            
            return {
                "should_trigger": False,
                "trigger_reason": f"No agent transitions from {new_status}",
                "workflow_name": workflow.name
            }
            
    except Exception as e:
        logger.exception(f"Failed to check agent workflow trigger for task {task_id}: {e}")
        return {
            "should_trigger": False,
            "trigger_reason": f"Error: {str(e)}"
        }


@temporalio.activity.defn(name="execute_agent_for_transition")
async def execute_agent_for_transition_activity(
    task_id: str,
    team_id: int,
    transition_config: Dict[str, Any],
    repo_info: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Execute the appropriate agent for a workflow transition."""
    try:
        agent_type = transition_config.get('agent_type')
        agent_config = transition_config.get('agent_config', {})
        
        if agent_type == 'code_generation':
            # Use the existing AI agent activity
            from .activities import ai_agent_work_activity
            
            result = await ai_agent_work_activity({
                "inputs": {
                    "task_id": task_id,
                    "team_id": team_id,
                    "new_status": transition_config.get('to_stage_key'),
                    "previous_status": transition_config.get('from_stage_key'),
                    "user_id": None
                },
                "repo_path": repo_info.get("repo_path") if repo_info else None,
                "repository": repo_info.get("repository") if repo_info else None,
                "branch_name": repo_info.get("branch_name") if repo_info else None,
            })
            
            return {
                "success": result.get("success", False),
                "message": result.get("message", "Agent execution completed"),
                "agent_type": agent_type,
                "details": result
            }
        
        elif agent_type == 'triage':
            # Placeholder for triage agent
            logger.info(f"Executing triage agent for task {task_id}")
            
            # TODO: Implement triage agent logic
            # This would analyze the task and write a clear plan/scope
            
            return {
                "success": True,
                "message": "Triage agent completed (placeholder)",
                "agent_type": agent_type
            }
        
        elif agent_type == 'review':
            # Placeholder for review agent  
            logger.info(f"Executing review agent for task {task_id}")
            
            # TODO: Implement review agent logic
            # This would review completed work and provide feedback
            
            return {
                "success": True,
                "message": "Review agent completed (placeholder)",
                "agent_type": agent_type
            }
        
        elif agent_type == 'testing':
            # Placeholder for testing agent
            logger.info(f"Executing testing agent for task {task_id}")
            
            # TODO: Implement testing agent logic
            # This would run tests and verify the implementation
            
            return {
                "success": True,
                "message": "Testing agent completed (placeholder)",
                "agent_type": agent_type
            }
        
        else:
            return {
                "success": False,
                "error": f"Unknown agent type: {agent_type}",
                "agent_type": agent_type
            }
            
    except Exception as e:
        logger.exception(f"Failed to execute agent for task {task_id}: {e}")
        return {
            "success": False,
            "error": str(e),
            "agent_type": transition_config.get('agent_type', 'unknown')
        }