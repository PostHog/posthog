"""What counts as a conversion for a marketing analytics goal.

Both the Dashboard's `ConversionGoalProcessor` and the attribution table ask the same question of an
event row, so the answer lives here once. A goal is its event or action **and** its configured property
filters; splitting those apart is how one pipeline ends up counting every `purchase` while the other
counts only the ones over $100.
"""

from typing import Optional

from posthog.schema import ConversionGoalFilter1, ConversionGoalFilter2, ConversionGoalFilter3

from posthog.hogql import ast
from posthog.hogql.property import action_to_expr, property_to_expr

from posthog.models import Team

from products.actions.backend.models.action import Action

ConversionGoal = ConversionGoalFilter1 | ConversionGoalFilter2 | ConversionGoalFilter3


def conversion_goal_property_expr(conversion_goal: ConversionGoal, team: Team) -> Optional[ast.Expr]:
    """The goal's own property filters, or None when it has none."""
    if not conversion_goal.properties:
        return None
    return property_to_expr(conversion_goal.properties, team=team, scope="event")


def add_conversion_goal_property_filters(
    conditions: list[ast.Expr],
    conversion_goal: ConversionGoal,
    team: Team,
) -> list[ast.Expr]:
    """Add property filters for conversion goals"""
    property_expr = conversion_goal_property_expr(conversion_goal, team)
    if property_expr:
        conditions.append(property_expr)

    return conditions


def action_match_expr(conversion_goal: ConversionGoal, team: Team) -> Optional[ast.Expr]:
    """The goal's action as a condition, or None when its action no longer resolves for this project.

    Returning None rather than deciding here, because the right answer depends on the surface: the
    Dashboard renders many goals at once and degrades a broken one to zero, while the attribution table
    renders one goal and can tell the user their goal is misconfigured.
    """
    if not isinstance(conversion_goal, ConversionGoalFilter2) or not conversion_goal.id:
        return None
    try:
        action = Action.objects.get(pk=int(conversion_goal.id), team__project_id=team.project_id)
    except (Action.DoesNotExist, TypeError, ValueError):
        return None
    return action_to_expr(action)


def conversion_goal_match_expr(conversion_goal: ConversionGoal, team: Team) -> Optional[ast.Expr]:
    """The event or action half of the goal, without its property filters.

    None when the goal names nothing to match on: a bare "All Events" goal, a data warehouse goal (whose
    conversions aren't event rows at all), or an action that no longer resolves.
    """
    if isinstance(conversion_goal, ConversionGoalFilter1):
        if not conversion_goal.event:
            return None
        return ast.CompareOperation(
            left=ast.Field(chain=["events", "event"]),
            op=ast.CompareOperationOp.Eq,
            right=ast.Constant(value=conversion_goal.event),
        )
    return action_match_expr(conversion_goal, team)


def conversion_goal_condition(conversion_goal: ConversionGoal, team: Team) -> Optional[ast.Expr]:
    """True for an event row that counts as a conversion: the event or action, narrowed by the goal's
    property filters. None when the goal has no resolvable event condition at all."""
    match = conversion_goal_match_expr(conversion_goal, team)
    if match is None:
        return None
    properties = conversion_goal_property_expr(conversion_goal, team)
    return ast.And(exprs=[match, properties]) if properties else match
