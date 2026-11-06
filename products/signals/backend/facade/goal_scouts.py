import re
from typing import Any
from uuid import UUID

from rest_framework.exceptions import ValidationError

from posthog.models import Team, User

from products.signals.backend.goal_scouts import goals
from products.signals.backend.goal_scouts.activity import ActivityEntry, recent_activity
from products.signals.backend.goal_scouts.build import (
    build_idea as _build_idea,
    retry,
    retry_cleanup,
)
from products.signals.backend.goal_scouts.goals import GoalInput, goal_scouts_enabled, track
from products.signals.backend.goal_scouts.measures import (
    BeliefLabels,
    GuardrailOption,
    MeasureSearch,
    belief_labels,
    guardrail_options,
    measure_options,
)
from products.signals.backend.goal_scouts.metrics import Metric, measure_problem, metric
from products.signals.backend.goal_scouts.plan import plan_refusal
from products.signals.backend.goal_scouts.read import detail, list_goals
from products.signals.backend.goal_scouts.spend import goal_spend
from products.signals.backend.models import SignalScoutGoal, SignalScoutGoalIdea

__all__ = [
    "ActivityEntry",
    "BeliefLabels",
    "GoalInput",
    "GoalNotFound",
    "GuardrailOption",
    "MeasureSearch",
    "Metric",
    "act_on_work",
    "add_owner_idea",
    "belief_labels",
    "build_idea",
    "close_goal",
    "create_goal",
    "goal_activity",
    "goal_detail",
    "goal_scouts_enabled",
    "guardrail_options",
    "list_goals",
    "measure_options",
    "metric_preview",
    "update_goal",
]

RETRY = "retry"
RETRY_CLEANUP = "retry_cleanup"


class GoalNotFound(Exception):
    pass


def _goal(team: Team, goal_id: str | UUID) -> SignalScoutGoal:
    goal = SignalScoutGoal.objects.for_team(team.id).select_related("config", "created_by").filter(pk=goal_id).first()
    if goal is None:
        raise GoalNotFound(str(goal_id))
    return goal


def goal_detail(team: Team, user: User, goal_id: str | UUID) -> dict[str, Any]:
    return detail(team, user, _goal(team, goal_id))


def create_goal(team: Team, user: User, data: GoalInput) -> dict[str, Any]:
    goal = goals.create_goal(team=team, user=user, data=data)
    return goal_detail(team, user, goal.pk)


def update_goal(team: Team, user: User, goal_id: str | UUID, changes: dict[str, Any]) -> dict[str, Any]:
    goals.update_goal(team=team, user=user, goal=_goal(team, goal_id), changes=changes)
    return goal_detail(team, user, goal_id)


def close_goal(team: Team, user: User, goal_id: str | UUID) -> dict[str, Any]:
    goals.close_goal(team, user, _goal(team, goal_id))
    return goal_detail(team, user, goal_id)


def add_owner_idea(team: Team, user: User, goal_id: str | UUID, title: str) -> dict[str, Any]:
    goals.add_owner_idea(team, user, _goal(team, goal_id), title)
    return goal_detail(team, user, goal_id)


def build_idea(team: Team, user: User, goal_id: str | UUID, work_id: str, plan: dict[str, Any]) -> dict[str, Any]:
    goal = _goal(team, goal_id)
    if plan:
        measured = metric(team, user, goal.insight_short_id)
        if refusal := plan_refusal(measured, days=plan["days"], mde=plan["mde"], audience=plan["audience"]):
            raise ValidationError({"plan": refusal})
    idea = _build_idea(team, user, goal, work_id, plan)
    track(
        team,
        user,
        "goal scout idea built",
        {"goal_id": str(goal.pk), "idea_id": str(idea.id), "plan_days": plan.get("days"), "plan_mde": plan.get("mde")},
    )
    return goal_detail(team, user, goal_id)


OWNER_WORK_ID = re.compile(r"owner-(\d+)")


def _uuid(value: str) -> UUID | None:
    try:
        return UUID(value)
    except ValueError:
        return None


def act_on_work(team: Team, user: User, goal_id: str | UUID, work_id: str, action: str) -> dict[str, Any]:
    goal = _goal(team, goal_id)
    if owner_number := OWNER_WORK_ID.fullmatch(work_id):
        if action == RETRY:
            raise ValidationError({"action": "An idea that waits for the scout can only be removed."})
        goals.remove_owner_idea(team, user, goal, int(owner_number.group(1)))
        return goal_detail(team, user, goal_id)
    idea = SignalScoutGoalIdea.objects.for_team(goal.team_id).filter(goal=goal, id=_uuid(work_id)).first()
    if idea is None:
        raise ValidationError({"work_id": "This work does not belong to the goal."})
    if action == RETRY:
        retry(user, goal, idea)
    elif action == RETRY_CLEANUP:
        retry_cleanup(user, goal, idea)
    else:
        goals.drop(team, user, goal, idea)
    track(team, user, "goal scout idea action", {"goal_id": str(goal.pk), "idea_id": str(idea.id), "action": action})
    return goal_detail(team, user, goal_id)


def goal_activity(team: Team, user: User, goal_id: str | UUID) -> list[ActivityEntry]:
    goal = _goal(team, goal_id)
    return recent_activity(team, user, goal, goal_spend(goal))


def metric_preview(team: Team, user: User, short_id: str) -> Metric:
    if problem := measure_problem(team, user, short_id):
        raise ValidationError({"insight": problem})
    return metric(team, user, short_id, blocking=True)
