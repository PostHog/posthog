from products.notifications.backend.facade.api import (
    NotificationData,
    NotificationType,
    TargetType,
    create_notification,
)

from ..models import SignalScoutGoal
from ..report_urls import scout_path
from .state import GoalState

MAX_KEY = 128


def notify_owner(goal: SignalScoutGoal, state: GoalState) -> None:
    if goal.created_by_id is None:
        return
    for item in state.actions:
        create_notification(
            NotificationData(
                team_id=goal.team_id,
                notification_type=NotificationType.APPROVAL_REQUESTED,
                title=f"{item.goal_title}: {item.title}",
                body=item.description,
                target_type=TargetType.USER,
                target_id=str(goal.created_by_id),
                resource_id=str(goal.pk),
                source_url=scout_path(goal.team_id, goal.config.skill_name),
                idempotency_key=f"goal:{goal.pk}:{item.key}:{item.marker}"[:MAX_KEY],
            )
        )
