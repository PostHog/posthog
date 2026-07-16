"""Resolution of the PostHog user acting on a task run.

Lives in logic (not temporal) so non-workflow callers — e.g. the permission
broker answering sandbox requests from the relay — can resolve the actor without
importing the temporal activity tree.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from posthog.models.user import User
from posthog.user_permissions import UserPermissions

if TYPE_CHECKING:
    from products.tasks.backend.models import Task

logger = logging.getLogger(__name__)


def is_slack_interaction_state(state: dict[str, Any] | None) -> bool:
    return (state or {}).get("interaction_origin") == "slack"


def get_task_run_actor_user(
    task: Task,
    state: dict[str, Any] | None = None,
    *,
    allow_task_creator_fallback: bool = True,
) -> User | None:
    """Return the PostHog user acting on this task run.

    Slack runs carry their current steering user in run state. Credential-bearing
    paths should pass ``allow_task_creator_fallback=False`` so a missing or
    unauthorized Slack actor fails closed instead of silently using the creator.
    """
    state = state or {}
    task_created_by = task.created_by if getattr(task, "created_by_id", None) is not None else None
    if not is_slack_interaction_state(state):
        return task_created_by

    def fallback_actor() -> User | None:
        return task_created_by if allow_task_creator_fallback else None

    actor_user_id = state.get("slack_actor_user_id")
    if not isinstance(actor_user_id, int) or isinstance(actor_user_id, bool):
        return fallback_actor()
    if task_created_by is not None and actor_user_id == task_created_by.id:
        return task_created_by

    actor = User.objects.filter(id=actor_user_id).first()
    if actor is None:
        logger.warning(
            "slack_actor_user_missing",
            extra={"task_id": task.id, "actor_user_id": actor_user_id},
        )
        return fallback_actor()

    try:
        has_team_access = (
            UserPermissions(user=actor, team=task.team).current_team.effective_membership_level is not None
        )
    except Exception:
        logger.warning(
            "slack_actor_user_access_check_failed",
            extra={"task_id": task.id, "actor_user_id": actor_user_id},
        )
        return fallback_actor()

    if not has_team_access:
        logger.warning(
            "slack_actor_user_no_team_access",
            extra={"task_id": task.id, "actor_user_id": actor_user_id},
        )
        return fallback_actor()

    return actor


def get_task_run_credential_user(task: Task, state: dict[str, Any] | None = None) -> User | None:
    """Return the user whose credentials may be minted for this run.

    Slack runs fail closed when their recorded actor can't be validated, but runs
    started before actor tracking existed carry no ``slack_actor_user_id`` at all —
    those grandfather to the task creator so in-flight runs survive the rollout.
    """
    state = state or {}
    allow_fallback = not is_slack_interaction_state(state) or "slack_actor_user_id" not in state
    return get_task_run_actor_user(task, state, allow_task_creator_fallback=allow_fallback)


def get_actor_distinct_id(actor: User) -> str:
    return actor.distinct_id or f"user_{actor.id}"
