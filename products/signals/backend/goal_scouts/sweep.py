from datetime import datetime, timedelta
from functools import partial
from statistics import fmean
from uuid import UUID

from django.db import transaction
from django.utils import timezone

import structlog

from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.models import Team, User
from posthog.user_permissions import UserPermissions

from products.experiments.backend.facade.api import (
    cleanup_task_id,
    conclude,
    experiment_for_read,
    get_experiment_results,
    ship,
)
from products.experiments.backend.facade.contracts import ExperimentActionRefused, ExperimentResults
from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.contracts import TaskRunDTO

from ..artefact_schemas import SIGNALS_PRODUCT, TASK_RUN_TYPE_IMPLEMENTATION
from ..implementation_pr import ImplementationPr, fetch_implementation_pr_state_for_reports
from ..models import SignalReport, SignalScoutConfig, SignalScoutGoal, SignalScoutGoalIdea
from .goals import end_experiment, goal_scouts_enabled, log_goal_change, pause_scout, start_scout_run, track_from_task
from .ideas import goal_ideas
from .metrics import Metric, measure_problem, meets, metric
from .notify import notify_owner
from .plan import DEFAULT_MDE, EXPOSURE_GRACE, MIN_DAYS, plan_anchor
from .read import state_for
from .spend import goal_spend
from .state import LIVE, NO_ACCESS, failure_note, goal_confirm_at
from .tracking import ADOPT_NOTE, Baseline, baseline, reported_insight, run_logs, turn_finished
from .verdict import CONCLUSIONS, confirm_harm, verdict

logger = structlog.get_logger(__name__)

Stage = SignalScoutGoalIdea.Stage
Kind = SignalScoutGoalIdea.Kind
Outcome = SignalScoutGoalIdea.Outcome
Status = SignalScoutGoal.Status

GOAL_POINTS = 3
CLEANUP_WINDOW = timedelta(days=2)
PLAN_AFTER = timedelta(days=1)
RESULTS_EVERY = timedelta(minutes=30)
FAILED_RUNS = ("failed", "cancelled")


@frozen
class IdeaFacts:
    pr: ImplementationPr | None
    run: TaskRunDTO | None
    logs: str
    experiment_id: int | None
    results: ExperimentResults | None
    results_read: bool
    cleanup_task_id: UUID | None


@frozen
class GoalFacts:
    measured: Metric | None
    baseline: Baseline | None
    spent_cents: int
    now: datetime


def live_goal_keys() -> list[tuple[int, UUID]]:
    return list(
        SignalScoutGoal.objects.unscoped()
        .filter(status__in=LIVE)
        .exclude(config__status=SignalScoutConfig.Status.PAUSED_BY_USER)
        .values_list("team_id", "pk")
    )


def latest_run(team_id: int, report_id: str) -> TaskRunDTO | None:
    entries = SignalReport.associated_task_runs(
        report_id=report_id, team_id=team_id, product=SIGNALS_PRODUCT, type=TASK_RUN_TYPE_IMPLEMENTATION
    )
    if not entries:
        return None
    runs = tasks_facade.get_signal_report_implementation_runs(team_id, report_id, [entries[-1].task_id])
    return runs[0] if runs else None


def results_due(idea: SignalScoutGoalIdea, now: datetime) -> bool:
    checked = idea.result.get("checked_at")
    return checked is None or now - datetime.fromisoformat(checked) >= RESULTS_EVERY


def read_facts(
    team: Team,
    user: User,
    goal: SignalScoutGoal,
    idea: SignalScoutGoalIdea,
    prs: dict[str, ImplementationPr],
    now: datetime,
) -> IdeaFacts:
    pr = prs.get(str(idea.report_id))
    run = latest_run(team.id, str(idea.report_id)) if idea.stage == Stage.BUILDING else None
    needs_logs = idea.kind == Kind.TRACKING and run is not None and (not goal.insight_short_id or pr is None)
    experiment_id = idea.experiment_id
    if experiment_id is None and idea.flag_key and idea.stage in (Stage.BUILDING, Stage.REVIEW):
        found = experiment_for_read(team=team, user=user, feature_flag_key=idea.flag_key)
        experiment_id = found.id if found else None
    live = idea.stage == Stage.LIVE and idea.experiment_id is not None and results_due(idea, now)
    cleanup = idea.stage == Stage.DONE and idea.experiment_id is not None and idea.cleanup_task_id is None
    return IdeaFacts(
        pr=pr,
        run=run,
        logs=run_logs(team.id, run) if needs_logs and run is not None else "",
        experiment_id=experiment_id,
        results=get_experiment_results(team=team, user=user, experiment_id=idea.experiment_id, fresh=True)
        if live and idea.experiment_id is not None
        else None,
        results_read=live,
        cleanup_task_id=cleanup_task_id(team=team, experiment_id=idea.experiment_id)
        if cleanup and idea.experiment_id is not None
        else None,
    )


def move(idea: SignalScoutGoalIdea, stage: str, note: str, **fields: object) -> None:
    ends_idea = idea.kind == Kind.IDEA and stage in (Stage.DONE, Stage.DROPPED) and idea.stage != stage
    idea.stage = stage
    idea.note = note
    for name, value in fields.items():
        setattr(idea, name, value)
    if stage in (Stage.DONE, Stage.DROPPED) and idea.finished_at is None:
        idea.finished_at = timezone.now()
    idea.save()
    if ends_idea and idea.goal.status == SignalScoutGoal.Status.RUNNING:
        transaction.on_commit(partial(start_scout_run, idea.goal))


def adopt_insight(team: Team, user: User, goal: SignalScoutGoal, logs: str) -> bool:
    short_id = reported_insight(logs)
    if not short_id or measure_problem(team, user, short_id):
        return False
    before = (goal.insight_short_id, goal.metric_name)
    goal.insight_short_id = short_id
    goal.metric_name = (metric(team, user, short_id).name or goal.metric_name)[:255]
    goal.save(update_fields=["insight_short_id", "metric_name", "updated_at"])
    log_goal_change(
        team=team,
        user=None,
        goal=goal,
        activity="goal_updated",
        changes={"insight_short_id": (before[0], short_id), "metric_name": (before[1], goal.metric_name)},
    )
    return True


def advance_building(
    team: Team, user: User, goal: SignalScoutGoal, idea: SignalScoutGoalIdea, found: IdeaFacts
) -> None:
    run = found.run
    finished = run is not None and (run.is_terminal or (idea.kind == Kind.TRACKING and turn_finished(found.logs)))
    failed = run is not None and run.status in FAILED_RUNS
    if idea.kind == Kind.TRACKING and not goal.insight_short_id:
        if not finished:
            return
        if failed:
            move(idea, Stage.STUCK, (run.error_message if run else "") or "The task ended without finding the insight.")
            return
        if not adopt_insight(team, user, goal, found.logs):
            move(idea, Stage.STUCK, ADOPT_NOTE)
            return
    if found.pr is not None:
        idea.result = {**idea.result, "pr_url": found.pr.url}
        if idea.kind == Kind.IDEA:
            if found.experiment_id is None:
                if finished:
                    move(idea, Stage.STUCK, f"Create and launch the experiment for the flag {idea.flag_key}.")
                else:
                    idea.save(update_fields=["result", "updated_at"])
                return
            idea.experiment_id = found.experiment_id
        move(idea, Stage.REVIEW, "Waiting for review.")
        return
    if not finished:
        return
    if idea.kind == Kind.TRACKING and not failed:
        move(idea, Stage.DONE, "Tracking already measures the goal.")
    else:
        move(idea, Stage.STUCK, (run.error_message if run else "") or "The task ended without a pull request.")


def advance_review(
    team: Team, user: User, goal: SignalScoutGoal, idea: SignalScoutGoalIdea, found: IdeaFacts, now: datetime
) -> None:
    pr = found.pr
    if pr is None:
        return
    if pr.merged:
        merged_at = pr.merged_at or now
        if idea.kind == Kind.TRACKING:
            move(idea, Stage.DONE, "Merged.", merged_at=merged_at)
        else:
            move(idea, Stage.LIVE, "Waiting for the first people to see it.", merged_at=merged_at)
    elif pr.state == "closed":
        if idea.kind == Kind.TRACKING:
            move(idea, Stage.STUCK, "The pull request was closed. Retry to open a new one.")
        else:
            move(idea, Stage.DROPPED, "The pull request was closed.", outcome=Outcome.DROPPED)
            transaction.on_commit(partial(end_experiment, team, user, goal, idea))


def end_live_experiment(
    team: Team, user: User, goal: SignalScoutGoal, idea: SignalScoutGoalIdea, outcome: str, variant: str, note: str
) -> str | None:
    comment = f"Concluded by the goal scout {goal.config.display_name}: {note}"
    repository = (goal.config.repositories or [""])[0]
    winner = variant if outcome == Outcome.WON and variant else "control"
    experiment_id = idea.experiment_id
    if experiment_id is None:
        return None
    try:
        ship(
            team=team,
            user=user,
            experiment_id=experiment_id,
            variant=winner,
            conclusion=CONCLUSIONS[Outcome(outcome)],
            comment=comment,
            repository=repository,
        )
        return "shipped" if winner != "control" else "ended"
    except ExperimentActionRefused as error:
        logger.warning("goal_scout_ship_failed", goal_id=str(goal.pk), error=error.message)
    try:
        conclude(
            team=team,
            user=user,
            experiment_id=experiment_id,
            conclusion=CONCLUSIONS[Outcome(outcome)],
            comment=comment,
            repository=repository,
        )
    except ExperimentActionRefused:
        return None
    return "ended"


def live_plan_days(
    team: Team, user: User, goal: SignalScoutGoal, idea: SignalScoutGoalIdea, results: ExperimentResults, now: datetime
) -> int:
    if idea.plan.get("days"):
        return int(idea.plan["days"])
    if idea.exposed_at is None or now - idea.exposed_at < PLAN_AFTER:
        return 0
    people = sum(value for key, value in results.exposures.items() if not key.startswith("$"))
    elapsed_days = (now - idea.exposed_at).total_seconds() / 86400
    audience = max(1, round(people / elapsed_days))
    anchor = plan_anchor(metric(team, user, goal.insight_short_id), audience)
    days = anchor.days if anchor is not None and anchor.days else MIN_DAYS
    idea.plan = {
        **idea.plan,
        "days": days,
        "mde": anchor.mde if anchor is not None else DEFAULT_MDE,
        "audience": audience,
    }
    idea.save(update_fields=["plan", "updated_at"])
    return days


def advance_live(
    team: Team, user: User, goal: SignalScoutGoal, idea: SignalScoutGoalIdea, found: IdeaFacts, now: datetime
) -> None:
    if not found.results_read:
        return
    results = found.results
    if results is None:
        move(idea, Stage.STUCK, "The experiment is gone, or the goal owner cannot view it.")
        return
    idea.result = {**idea.result, "checked_at": now.isoformat()}
    if idea.exposed_at is None and any(value for key, value in results.exposures.items() if not key.startswith("$")):
        idea.exposed_at = now
    days = live_plan_days(team, user, goal, idea, results, now)
    if not days:
        move(idea, Stage.LIVE, "Measuring traffic to plan the test.")
        return
    result = confirm_harm(
        idea.result,
        verdict(
            results,
            direction=goal.direction,
            guardrails=goal.guardrails or [],
            run_days=days,
            exposed_at=idea.exposed_at,
            now=now,
        ),
        now,
    )
    note = result.note
    if idea.exposed_at is None and idea.merged_at and now - idea.merged_at > EXPOSURE_GRACE:
        note = "No exposures since the merge. Check that the change is deployed."
    if result.outcome is None:
        move(idea, Stage.LIVE, note, result={**idea.result, **result.facts})
        return
    ended = end_live_experiment(team, user, goal, idea, result.outcome, result.variant, result.note)
    if ended is None:
        move(idea, Stage.STUCK, "The scout could not end the experiment. The goal owner cannot edit it.")
        return
    move(
        idea,
        Stage.DONE,
        result.note,
        outcome=result.outcome,
        result={
            **idea.result,
            **result.facts,
            "variant": result.variant,
            "verdict": result.note,
            "shipped": ended == "shipped",
        },
    )
    track_from_task(
        team,
        user,
        "goal scout idea concluded",
        {
            "goal_id": str(goal.pk),
            "idea_id": str(idea.id),
            "outcome": result.outcome,
            "planned_days": days,
            "owner_idea": bool(idea.plan.get("owner_idea")),
        },
    )


def advance_idea(
    team: Team, user: User, goal: SignalScoutGoal, idea: SignalScoutGoalIdea, found: IdeaFacts, now: datetime
) -> None:
    if idea.stage == Stage.DONE:
        if found.cleanup_task_id is not None:
            idea.cleanup_task_id = found.cleanup_task_id
            idea.save(update_fields=["cleanup_task_id", "updated_at"])
        return
    was_live = idea.stage == Stage.LIVE
    if idea.stage == Stage.BUILDING:
        advance_building(team, user, goal, idea, found)
    if idea.stage == Stage.REVIEW:
        advance_review(team, user, goal, idea, found, now)
    if was_live:
        advance_live(team, user, goal, idea, found, now)


def goal_reached(goal: SignalScoutGoal, measured: Metric | None) -> bool:
    values = measured.values[-GOAL_POINTS:] if measured else []
    if len(values) < GOAL_POINTS or goal.target is None:
        return False
    hits = sum(meets(goal.direction, goal.target, value) for value in values)
    return hits >= GOAL_POINTS - 1 and meets(goal.direction, goal.target, fmean(values))


def end_goal(team: Team, user: User, goal: SignalScoutGoal, status: str, spent_cents: int) -> None:
    before = goal.status
    goal.status = status
    goal.note = ""
    if status == Status.REACHED:
        goal.reached_at = goal.goal_met_since
    goal.save()
    log_goal_change(team=team, user=None, goal=goal, activity="goal_updated", changes={"status": (before, status)})
    transaction.on_commit(partial(pause_scout, goal))
    transaction.on_commit(
        partial(
            track_from_task,
            team,
            user,
            "goal scout ended",
            {"goal_id": str(goal.pk), "status": status, "spent_cents": spent_cents},
        )
    )


def advance_status(team: Team, user: User, goal: SignalScoutGoal, facts: GoalFacts) -> bool:
    rows = SignalScoutGoalIdea.objects.for_team(goal.team_id).filter(goal=goal)
    if goal.status == Status.SETTING_UP:
        tracking = rows.filter(kind=Kind.TRACKING).order_by("-number").first()
        if tracking is None or tracking.stage != Stage.DONE:
            goal.note = ""
        elif goal.target is None:
            goal.note = "Set the target to start."
        elif facts.baseline is not None and facts.baseline.ready:
            goal.status = Status.RUNNING
            goal.baseline_value = facts.baseline.value
            goal.baseline_at = facts.now
            goal.note = ""
            goal.save()
            log_goal_change(
                team=team,
                user=None,
                goal=goal,
                activity="goal_updated",
                changes={"status": (Status.SETTING_UP, Status.RUNNING)},
            )
            return True
        else:
            goal.note = facts.baseline.note if facts.baseline else ""
        goal.save(update_fields=["note", "updated_at"])
        return False
    idea_open = rows.filter(kind=Kind.IDEA, stage__in=SignalScoutGoalIdea.OPEN_STAGES).exists()
    tested = rows.filter(kind=Kind.IDEA, stage=Stage.DONE).exists()
    met = tested and not meets(goal.direction, goal.target, goal.baseline_value) and goal_reached(goal, facts.measured)
    goal.goal_met_since = (goal.goal_met_since or facts.now) if met else None
    goal.note = ""
    confirm_at = goal_confirm_at(goal)
    if confirm_at is not None and facts.now >= confirm_at and not idea_open:
        end_goal(team, user, goal, Status.REACHED, facts.spent_cents)
    elif not idea_open and facts.spent_cents >= goal.budget_cents:
        end_goal(team, user, goal, Status.SPENT, facts.spent_cents)
    else:
        goal.save(update_fields=["goal_met_since", "note", "updated_at"])
    return False


def goal_owner(team: Team, goal: SignalScoutGoal) -> User | None:
    user = goal.created_by
    if user is None or not user.is_active:
        return None
    if UserPermissions(user=user, team=team).current_team.effective_membership_level is None:
        return None
    return user


def step(team: Team, user: User, goal: SignalScoutGoal) -> bool:
    now = timezone.now()
    rows = list(
        SignalScoutGoalIdea.objects.for_team(goal.team_id)
        .filter(goal=goal, stage__in=[*SignalScoutGoalIdea.OPEN_STAGES, Stage.DONE])
        .exclude(stage=Stage.DONE, cleanup_task_id__isnull=False)
        .exclude(stage=Stage.DONE, experiment_id__isnull=True)
        .exclude(stage=Stage.DONE, finished_at__lt=now - CLEANUP_WINDOW)
    )
    prs = fetch_implementation_pr_state_for_reports([str(row.report_id) for row in rows], team_id=goal.team_id)
    facts = {row.id: read_facts(team, user, goal, row, prs, now) for row in rows}
    tracking = (
        SignalScoutGoalIdea.objects.for_team(goal.team_id)
        .filter(goal=goal, kind=Kind.TRACKING)
        .order_by("-number")
        .first()
    )
    ready_for_baseline = (
        goal.status == Status.SETTING_UP
        and goal.target is not None
        and tracking is not None
        and tracking.stage == Stage.DONE
    )
    goal_facts = GoalFacts(
        measured=metric(team, user, goal.insight_short_id, blocking=True, workload=Workload.OFFLINE)
        if goal.status == Status.RUNNING and goal.insight_short_id
        else None,
        baseline=baseline(team, user, goal, since=tracking.merged_at if tracking else None)
        if ready_for_baseline
        else None,
        spent_cents=goal_spend(goal).spent_cents,
        now=now,
    )
    with transaction.atomic():
        locked = (
            SignalScoutGoal.objects.for_team(goal.team_id)
            .select_for_update(skip_locked=True, of=("self",))
            .select_related("config")
            .filter(pk=goal.pk)
            .first()
        )
        if locked is None or locked.status not in LIVE:
            return False
        for idea in SignalScoutGoalIdea.objects.for_team(goal.team_id).select_for_update().filter(id__in=list(facts)):
            advance_idea(team, user, locked, idea, facts[idea.id], now)
        started = advance_status(team, user, locked, goal_facts)
    return started


def advance_goal(team_id: int, goal_id: UUID) -> None:
    goal = SignalScoutGoal.objects.for_team(team_id).select_related("config", "created_by").filter(pk=goal_id).first()
    if goal is None or goal.status not in LIVE or goal.config.status == SignalScoutConfig.Status.PAUSED_BY_USER:
        return
    team = Team.objects.select_related("organization").get(id=team_id)
    if not goal_scouts_enabled(team):
        return
    user = goal_owner(team, goal)
    if user is None:
        SignalScoutGoal.objects.for_team(team_id).filter(pk=goal_id).update(note=NO_ACCESS)
        return
    try:
        started = step(team, user, goal)
    except Exception as error:
        logger.exception("goal_scout_step_failed", team_id=team_id, goal_id=str(goal_id))
        SignalScoutGoal.objects.for_team(team_id).filter(pk=goal_id).update(note=failure_note(goal.note, error))
        raise
    goal.refresh_from_db()
    if started:
        start_scout_run(goal)
    notify_owner(goal, state_for(goal, goal_ideas(goal)))
