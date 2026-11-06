from collections.abc import Mapping
from decimal import Decimal
from functools import partial
from typing import Any

from django.conf import settings
from django.db import transaction
from django.http import HttpRequest
from django.utils import timezone

import structlog
import posthoganalytics
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.dataclasses import frozen
from posthog.event_usage import groups, report_user_action
from posthog.models import Team, User
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.ph_client import ph_scoped_capture
from posthog.temporal.common.client import sync_connect

from products.experiments.backend.facade.api import conclude
from products.experiments.backend.facade.contracts import ExperimentActionRefused

from ..models import SignalScoutConfig, SignalScoutGoal, SignalScoutGoalIdea
from ..scout_harness.run_gates import check_fleet_gates, check_run_in_flight, check_spend_gates
from ..scout_harness.serializers import validate_scout_repositories
from ..scout_harness.tags import slugify_tag
from .build import lock_goal, start_tracking
from .metrics import measure_problem, meets, metric
from .scout import GOAL_SKILL_BODY, GOAL_TAG, RUN_INTERVAL_MINUTES
from .state import number, takes_ideas

logger = structlog.get_logger(__name__)

GOAL_SCOUTS_FLAG = "goal-scouts"
MAX_OWNER_IDEAS = 20
LOCKED_FIELDS = (
    "insight_short_id",
    "goal_description",
    "metric_name",
    "unit",
    "direction",
    "guardrails",
    "repositories",
)
LOCKED_MESSAGE = "This is locked once the goal runs. Close the goal and create a new one to change it."
GOAL_FIELDS = ("belief", "target", "budget_cents", *LOCKED_FIELDS[:-1])

Status = SignalScoutGoal.Status


@frozen
class GoalInput:
    name: str
    belief: str
    area: str
    repositories: list[str]
    insight_short_id: str
    goal_description: str
    metric_name: str
    unit: str
    direction: str
    guardrails: list[dict[str, Any]]
    target: Decimal | None
    budget_cents: int
    ideas: list[str]


def goal_scouts_enabled(team: Team) -> bool:
    if settings.DEBUG and not settings.TEST:
        return True
    try:
        return (
            posthoganalytics.feature_enabled(
                GOAL_SCOUTS_FLAG,
                str(team.uuid),
                groups={"organization": str(team.organization_id), "project": str(team.id)},
                group_properties={
                    "organization": {"id": str(team.organization_id)},
                    "project": {"id": str(team.id)},
                },
                send_feature_flag_events=False,
            )
            is True
        )
    except Exception:
        logger.warning("goal_scouts_flag_check_failed", exc_info=True)
        return False


def track(team: Team, user: User, event: str, properties: dict[str, Any]) -> None:
    report_user_action(user, event, properties, team=team)


def track_from_task(team: Team, user: User, event: str, properties: dict[str, Any]) -> None:
    with ph_scoped_capture() as capture:
        capture(
            distinct_id=user.distinct_id, event=event, properties=properties, groups=groups(team.organization, team)
        )


def _logged(value: Any) -> Any:
    return str(value) if isinstance(value, Decimal) else value


def log_goal_change(
    *, team: Team, user: User | None, goal: SignalScoutGoal, activity: str, changes: dict[str, tuple[Any, Any]]
) -> None:
    log_activity(
        organization_id=team.organization_id,
        team_id=goal.team_id,
        user=user,
        was_impersonated=False,
        item_id=str(goal.pk),
        scope="SignalScoutConfig",
        activity=activity,
        detail=Detail(
            name=goal.config.display_name or goal.config.skill_name,
            changes=[
                Change(
                    type="SignalScoutConfig",
                    action="changed",
                    field=field,
                    before=_logged(before),
                    after=_logged(after),
                )
                for field, (before, after) in changes.items()
            ],
        ),
    )


def start_scout_run(goal: SignalScoutGoal) -> None:
    from products.signals.backend.temporal.agentic.scout_scheduler import (  # noqa: PLC0415
        start_manual_signals_scout_run,
    )

    skill_name = goal.config.skill_name
    rejection = (
        check_fleet_gates(goal.team_id)
        or check_spend_gates(Team.objects.get(id=goal.team_id))
        or check_run_in_flight(goal.team_id, skill_name)
    )
    if rejection is not None:
        logger.info("goal_scout_run_not_started", goal_id=str(goal.pk), reason=rejection.reason)
        return
    try:
        start_manual_signals_scout_run(sync_connect(), team_id=goal.team_id, skill_name=skill_name)
    except WorkflowAlreadyStartedError:
        logger.info("goal_scout_run_not_started", goal_id=str(goal.pk), reason="already_started")


def pause_scout(goal: SignalScoutGoal) -> None:
    goal.config.transition_status_by_system(
        SignalScoutConfig.Status.PAUSED_BY_SYSTEM, pause_reason=SignalScoutConfig.PauseReason.GOAL_ENDED
    )


def resume_scout(goal: SignalScoutGoal) -> None:
    goal.config.transition_status_by_system(
        SignalScoutConfig.Status.ACTIVE, pause_reason=SignalScoutConfig.PauseReason.GOAL_ENDED
    )


def end_experiment(team: Team, user: User, goal: SignalScoutGoal, idea: SignalScoutGoalIdea) -> None:
    if idea.experiment_id is None:
        return
    try:
        conclude(
            team=team,
            user=user,
            experiment_id=idea.experiment_id,
            conclusion="stopped_early",
            comment=f"Stopped by the goal scout {goal.config.display_name}: {idea.note}",
            repository=(goal.config.repositories or [""])[0],
        )
    except ExperimentActionRefused as error:
        logger.warning("goal_scout_end_experiment_failed", goal_id=str(goal.pk), error=error.message)


def check_measures(team: Team, user: User, insight: str, guardrails: list[dict[str, Any]]) -> None:
    if insight and (problem := measure_problem(team, user, insight)):
        raise ValidationError({"goal_insight": problem})
    ids = [item["insight"] for item in guardrails]
    if len(ids) != len(set(ids)) or (insight and insight in ids):
        raise ValidationError({"secondary_metrics": "Each insight can appear only once."})
    for item in guardrails:
        if problem := measure_problem(team, user, item["insight"]):
            raise ValidationError({"secondary_metrics": problem})


def refuse_met_target(team: Team, user: User, insight: str, target: Decimal | None, direction: str) -> None:
    if not insight or target is None:
        return
    value = metric(team, user, insight).current
    if meets(direction, target, value):
        raise ValidationError(
            {
                "target": f"The goal is already at {number(value or 0)}, which meets this target. Set a target the ideas still have to reach."
            }
        )


def _tags(area: str) -> list[str]:
    slug = slugify_tag(area) if area else ""
    return [GOAL_TAG, slug] if slug and slug != GOAL_TAG else [GOAL_TAG]


def goal_area(config: SignalScoutConfig) -> str:
    return next((tag for tag in config.tag_list if tag != GOAL_TAG), "")


def scout_request(user: User) -> Request:
    request = Request(HttpRequest())
    request.user = user
    return request


def scout_context(team: Team) -> dict[str, Any]:
    return {"team": team, "get_team": lambda: team, "project_id": team.project_id}


def create_goal(*, team: Team, user: User, data: GoalInput) -> SignalScoutGoal:
    check_measures(team, user, data.insight_short_id, data.guardrails)
    refuse_met_target(team, user, data.insight_short_id, data.target, data.direction)
    try:
        repositories = validate_scout_repositories(data.repositories, scout_context(team))
    except ValidationError as error:
        raise ValidationError({"repositories": error.detail}) from error
    from ..scout_harness.views import (  # noqa: PLC0415 — keeps the scout API surface off the Celery import path
        create_scout_with_generated_slug,
    )

    with transaction.atomic():
        outcome = create_scout_with_generated_slug(
            team=team,
            user=user,
            display_name=data.name,
            description=f"Find the next idea to improve {data.metric_name}.",
            body=GOAL_SKILL_BODY,
            files=[],
            config_options={
                "enabled": True,
                "emit": True,
                "output_destinations": {"inbox": False},
                "repositories": repositories,
                "run_interval_minutes": RUN_INTERVAL_MINUTES,
                "auto_pause_exempt": True,
                "tags": _tags(data.area),
            },
            request=scout_request(user),
            serializer_context=scout_context(team),
        )
        goal = SignalScoutGoal.objects.create(
            config=outcome.config,
            team_id=team.id,
            belief=data.belief,
            target=data.target,
            budget_cents=data.budget_cents,
            insight_short_id=data.insight_short_id or None,
            goal_description=data.goal_description,
            metric_name=data.metric_name,
            unit=data.unit,
            direction=data.direction,
            guardrails=data.guardrails,
            owner_ideas=[
                {"number": index, "title": title.strip()[:255], "added_at": timezone.now().isoformat()}
                for index, title in enumerate((idea for idea in data.ideas if idea.strip()), start=1)
            ],
            created_by=user,
        )
        log_goal_change(team=team, user=user, goal=goal, activity="goal_created", changes={})
    track(
        team,
        user,
        "goal scout created",
        {"goal_id": str(goal.pk), "guardrails": len(goal.guardrails), "has_insight": bool(goal.insight_short_id)},
    )
    start_tracking(goal, user)
    return goal


def _current(goal: SignalScoutGoal, field: str) -> Any:
    if field == "repositories":
        return list(goal.config.repositories or [])
    if field == "name":
        return goal.config.display_name
    if field == "area":
        return goal_area(goal.config)
    return getattr(goal, field)


def update_goal(
    *,
    team: Team,
    user: User,
    goal: SignalScoutGoal,
    changes: Mapping[str, Any],
) -> SignalScoutGoal:
    if goal.status == Status.CLOSED:
        raise ValidationError("This goal is closed.")
    editable = (*GOAL_FIELDS, "repositories", "name", "area")
    changed = {field for field, value in changes.items() if field in editable and value != _current(goal, field)}
    locked_changes = sorted(field for field in changed if field in LOCKED_FIELDS)
    if goal.status != Status.SETTING_UP and locked_changes:
        raise ValidationError(dict.fromkeys(locked_changes, LOCKED_MESSAGE))
    insight = changes.get("insight_short_id", goal.insight_short_id) or ""
    if "insight_short_id" in changed or "guardrails" in changed:
        check_measures(team, user, insight, changes.get("guardrails", goal.guardrails))
    if changed & {"insight_short_id", "target", "direction"}:
        refuse_met_target(
            team, user, insight, changes.get("target", goal.target), changes.get("direction", goal.direction)
        )
    repositories = (
        validate_scout_repositories(changes["repositories"], scout_context(team), current=goal.config.repositories)
        if "repositories" in changed
        else None
    )
    with transaction.atomic():
        locked = lock_goal(goal)
        before = {field: _current(locked, field) for field in (*GOAL_FIELDS, "repositories", "name")}
        for field in GOAL_FIELDS:
            if field in changes:
                setattr(locked, field, changes[field] or None if field == "insight_short_id" else changes[field])
        resumed = False
        if {"target", "direction"} & changed:
            locked.goal_met_since = None
            if locked.status == Status.REACHED:
                locked.status = Status.RUNNING if locked.baseline_at else Status.SETTING_UP
                locked.reached_at = None
                resumed = True
        if locked.status == Status.SPENT and "budget_cents" in changed and locked.budget_cents > before["budget_cents"]:
            locked.status = Status.RUNNING
            resumed = True
        locked.save()
        config_fields = []
        if "name" in changes:
            locked.config.display_name = changes["name"]
            config_fields.append("display_name")
        if repositories is not None:
            locked.config.repositories = repositories
            config_fields.append("repositories")
        if "area" in changes:
            locked.config.tags = _tags(changes["area"])
            config_fields.append("tags")
        if config_fields:
            locked.config.save(update_fields=[*config_fields, "updated_at"])
        after = {field: _current(locked, field) for field in before}
        logged = {field: (before[field], after[field]) for field in before if before[field] != after[field]}
        if goal.status != locked.status:
            logged["status"] = (goal.status, locked.status)
        log_goal_change(team=team, user=user, goal=locked, activity="goal_updated", changes=logged)
    if resumed:
        resume_scout(locked)
    if locked.status == Status.SETTING_UP and changed & {"insight_short_id", "goal_description"}:
        start_tracking(locked, user)
    track(team, user, "goal scout updated", {"goal_id": str(goal.pk), "fields": sorted(changed)})
    return locked


def close_goal(team: Team, user: User, goal: SignalScoutGoal) -> SignalScoutGoal:
    if goal.status == Status.CLOSED:
        raise ValidationError("This goal is closed.")
    with transaction.atomic():
        locked = lock_goal(goal)
        before = locked.status
        dropped = list(
            SignalScoutGoalIdea.objects.for_team(goal.team_id).filter(
                goal=locked, stage__in=SignalScoutGoalIdea.OPEN_STAGES
            )
        )
        for idea in dropped:
            idea.stage = SignalScoutGoalIdea.Stage.DROPPED
            idea.note = "The goal was closed. Close the pull request if you do not need it."
            idea.finished_at = timezone.now()
            if idea.kind == SignalScoutGoalIdea.Kind.IDEA:
                idea.outcome = SignalScoutGoalIdea.Outcome.DROPPED
            idea.save(update_fields=["stage", "note", "finished_at", "outcome", "updated_at"])
        locked.status = Status.CLOSED
        locked.closed_at = timezone.now()
        locked.note = ""
        locked.save(update_fields=["status", "closed_at", "note", "updated_at"])
        log_goal_change(
            team=team, user=user, goal=locked, activity="goal_closed", changes={"status": (before, Status.CLOSED)}
        )
        transaction.on_commit(partial(pause_scout, locked))
        for idea in dropped:
            transaction.on_commit(partial(end_experiment, team, user, locked, idea))
    track(team, user, "goal scout closed", {"goal_id": str(goal.pk), "from": before})
    return locked


def add_owner_idea(team: Team, user: User, goal: SignalScoutGoal, title: str) -> SignalScoutGoal:
    if not takes_ideas(goal):
        raise ValidationError("This goal does not take new ideas.")
    with transaction.atomic():
        locked = lock_goal(goal)
        ideas = list(locked.owner_ideas or [])
        if len(ideas) >= MAX_OWNER_IDEAS:
            raise ValidationError(f"A goal takes up to {MAX_OWNER_IDEAS} of your own ideas.")
        number_ = max((int(item["number"]) for item in ideas), default=0) + 1
        ideas.append({"number": number_, "title": title.strip()[:255], "added_at": timezone.now().isoformat()})
        locked.owner_ideas = ideas
        locked.save(update_fields=["owner_ideas", "updated_at"])
    track(team, user, "goal scout owner idea added", {"goal_id": str(goal.pk)})
    if locked.status == Status.RUNNING:
        start_scout_run(locked)
    return locked


def remove_owner_idea(team: Team, user: User, goal: SignalScoutGoal, number: int) -> None:
    with transaction.atomic():
        locked = lock_goal(goal)
        ideas = [item for item in locked.owner_ideas or [] if int(item["number"]) != number]
        if len(ideas) == len(locked.owner_ideas or []):
            raise ValidationError({"work_id": "This idea is not waiting for the scout."})
        locked.owner_ideas = ideas
        locked.save(update_fields=["owner_ideas", "updated_at"])
    track(team, user, "goal scout owner idea removed", {"goal_id": str(goal.pk)})


def drop(team: Team, user: User, goal: SignalScoutGoal, idea: SignalScoutGoalIdea) -> None:
    if idea.kind != SignalScoutGoalIdea.Kind.IDEA or idea.stage not in SignalScoutGoalIdea.OPEN_STAGES:
        raise ValidationError("Only an idea in progress can be dropped.")
    idea.stage = SignalScoutGoalIdea.Stage.DROPPED
    idea.outcome = SignalScoutGoalIdea.Outcome.DROPPED
    idea.note = "Dropped by a person."
    idea.finished_at = timezone.now()
    idea.save(update_fields=["stage", "outcome", "note", "finished_at", "updated_at"])
    end_experiment(team, user, goal, idea)
    if goal.status == Status.RUNNING:
        start_scout_run(goal)
