"""Action selection for the web analytics goals tile.

Shared by the live query runner and the lazy precompute path so both cover the
same set of goals.
"""

import structlog

from posthog.hogql import ast
from posthog.hogql.errors import BaseHogQLError
from posthog.hogql.property import action_to_expr

from posthog.models import Team

from products.actions.backend.models.action import Action

logger = structlog.get_logger(__name__)

# How many goals the tile shows. Both paths read this, so the live slice and the
# precomputed action set move together.
MAX_GOAL_ACTIONS = 5


def select_goal_actions(team: Team) -> list[tuple[Action, ast.Expr]]:
    """The goals the tile shows, each paired with its HogQL expression.

    The set is whichever actions rank first for the project, so it can hold an
    action that has nothing to do with web analytics and whose filter no longer
    compiles. Drop that action rather than fail the whole tile with it.
    """
    actions = Action.objects.filter(team__project_id=team.project_id, deleted=False).order_by(
        "pinned_at", "-last_calculated_at"
    )[:MAX_GOAL_ACTIONS]

    goals: list[tuple[Action, ast.Expr]] = []
    for action in actions:
        try:
            goals.append((action, action_to_expr(action)))
        except BaseHogQLError as e:
            logger.warning(
                "web_goals_action_expr_failed",
                team_id=team.pk,
                action_id=action.id,
                error=str(e),
            )
    return goals
