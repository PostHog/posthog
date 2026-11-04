from datetime import datetime
from uuid import UUID

from posthog.dataclasses import frozen
from posthog.models.team.team import Team
from posthog.models.user import User

from products.feature_flags.backend import rollout_plans
from products.feature_flags.backend.facade.enums import FeatureFlagRolloutPlanStatus
from products.feature_flags.backend.models.feature_flag_rollout_plan import FeatureFlagRolloutPlan


@frozen
class RolloutPlan:
    id: UUID
    feature_flag: int
    condition_index: int
    percentages: list[int]
    soak_hours: int
    health_checks: str
    status: FeatureFlagRolloutPlanStatus
    steps_applied: int
    next_check_at: datetime | None
    task_id: UUID | None
    last_summary: str
    stop_reason: str
    created_at: datetime


def _to_contract(plan: FeatureFlagRolloutPlan) -> RolloutPlan:
    return RolloutPlan(
        id=plan.pk,
        feature_flag=plan.feature_flag_id,
        condition_index=plan.condition_index,
        percentages=plan.percentages,
        soak_hours=plan.soak_hours,
        health_checks=plan.health_checks,
        status=FeatureFlagRolloutPlanStatus(plan.status),
        steps_applied=plan.steps_applied,
        next_check_at=plan.next_check_at,
        task_id=plan.task_id,
        last_summary=plan.last_summary,
        stop_reason=plan.stop_reason,
        created_at=plan.created_at,
    )


def get_rollout_plan(plan_id: UUID, *, team: Team) -> RolloutPlan:
    return _to_contract(rollout_plans.get_rollout_plan(plan_id, team=team))


def list_rollout_plans(feature_flag_id: int, *, team: Team, user: User) -> list[RolloutPlan]:
    return [_to_contract(plan) for plan in rollout_plans.list_rollout_plans(feature_flag_id, team=team, user=user)]


def start_rollout_plan(
    *,
    team: Team,
    user: User,
    feature_flag_id: int,
    condition_index: int,
    percentages: list[int],
    soak_hours: int,
    health_checks: str,
) -> RolloutPlan:
    return _to_contract(
        rollout_plans.start_rollout_plan(
            team=team,
            user=user,
            feature_flag_id=feature_flag_id,
            condition_index=condition_index,
            percentages=percentages,
            soak_hours=soak_hours,
            health_checks=health_checks,
        )
    )


def advance_rollout_plan(plan_id: UUID, *, team: Team, user: User, summary: str) -> RolloutPlan:
    return _to_contract(rollout_plans.advance_rollout_plan(plan_id, team=team, user=user, summary=summary))


def fail_rollout_plan(plan_id: UUID, *, team: Team, user: User, reason: str) -> RolloutPlan:
    return _to_contract(rollout_plans.fail_rollout_plan(plan_id, team=team, user=user, reason=reason))


def stop_rollout_plan(plan_id: UUID, *, team: Team, user: User, reason: str) -> RolloutPlan:
    return _to_contract(rollout_plans.stop_rollout_plan_for_person(plan_id, team=team, user=user, reason=reason))
