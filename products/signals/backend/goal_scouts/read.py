from typing import Any

from django.utils import timezone

from posthog.clickhouse.workload import Workload
from posthog.models import Team, User

from products.tasks.backend.facade import api as tasks_facade

from ..artefact_schemas import SIGNALS_PRODUCT, TASK_RUN_TYPE_IMPLEMENTATION
from ..implementation_pr import ImplementationPr, fetch_implementation_pr_state_for_reports
from ..models import SignalReport, SignalScoutGoal, SignalScoutGoalIdea
from .build import build_refusal
from .goals import goal_area
from .ideas import IdeaView, goal_ideas
from .metrics import Metric, delivery, meets, metric, observed
from .plan import PlanAnchor, daily_audience, plan_anchor, plan_days
from .scout import ScoutJob, current_job, recent_scout_runs
from .spend import GoalSpend, goal_spend
from .state import LIVE, GoalState, StateInput, effective_status, goal_state, goal_title, tested

Outcome = SignalScoutGoalIdea.Outcome
Stage = SignalScoutGoalIdea.Stage
Kind = SignalScoutGoalIdea.Kind
ACTIVE_RUN = ("queued", "in_progress")


def pr_states(goal: SignalScoutGoal, views: list[IdeaView]) -> dict[str, ImplementationPr]:
    return fetch_implementation_pr_state_for_reports(
        [view.report_id for view in views if view.row is not None and view.report_id], team_id=goal.team_id
    )


def state_for(
    goal: SignalScoutGoal,
    views: list[IdeaView],
    *,
    spend: GoalSpend | None = None,
    job: ScoutJob | None = None,
    current: float | None = None,
    prs: dict[str, ImplementationPr] | None = None,
) -> GoalState:
    found = spend or goal_spend(goal)
    known = pr_states(goal, views) if prs is None else prs
    return goal_state(
        StateInput(
            goal=goal,
            views=views,
            job=job or current_job(goal, views, found.spent_cents),
            spent_cents=found.spent_cents,
            current=current,
            pr_urls={
                view.id: known[view.report_id].url for view in views if view.report_id in known and view.row is not None
            },
            build_blocked=build_refusal(goal, views, found.spent_cents),
            now=timezone.now(),
        )
    )


def goal_metric(team: Team, user: User, goal: SignalScoutGoal) -> Metric:
    if not goal.insight_short_id and goal.goal_description:
        return Metric(
            name=goal.metric_name or "Goal",
            unit=goal.unit,
            values=[],
            dates=[],
            current=None,
            message="The scout is finding the insight for this measure.",
        )
    return metric(team, user, goal.insight_short_id)


def money(goal: SignalScoutGoal, spend: GoalSpend) -> dict[str, int]:
    return {
        "allocated_cents": goal.budget_cents,
        "spent_cents": spend.spent_cents,
        "available_cents": max(goal.budget_cents - spend.spent_cents, 0),
    }


def entry(
    team: Team,
    user: User,
    goal: SignalScoutGoal,
    views: list[IdeaView],
    spend: GoalSpend,
    prs: dict[str, ImplementationPr] | None = None,
) -> dict[str, Any]:
    measured = goal_metric(team, user, goal)
    state = state_for(goal, views, spend=spend, current=measured.current, prs=prs)
    outcomes = [view.row.outcome for view in views if view.row is not None and view.kind == Kind.IDEA]
    return {
        "id": goal.pk,
        "skill_name": goal.config.skill_name,
        "title": goal_title(goal),
        "statement": goal.belief,
        "area": goal_area(goal.config),
        "repositories": list(goal.config.repositories or []),
        "goal_insight": goal.insight_short_id or "",
        "goal_description": goal.goal_description,
        "goal_metric": goal.metric_name,
        "secondary_metrics": goal.guardrails or [],
        "target": goal.target,
        "direction": goal.direction,
        "unit": goal.unit,
        "status": effective_status(goal),
        "baseline_value": goal.baseline_value,
        "baseline_at": goal.baseline_at,
        "owner_name": (goal.created_by.first_name or goal.created_by.email) if goal.created_by else "Former member",
        "money": money(goal, spend),
        "metric": measured,
        "ideas_tried": sum(1 for outcome in outcomes if tested(outcome)),
        "ideas_won": sum(1 for outcome in outcomes if outcome == Outcome.WON),
        "state": state,
    }


def _task_state(team_id: int, task_id: str | None) -> tuple[str, str]:
    if not task_id:
        return "", "not_started"
    runs = tasks_facade.get_latest_run_by_task([task_id])
    run = runs.get(task_id)
    return task_id, run.status if run else "not_started"


def _cleanup(goal: SignalScoutGoal, row: SignalScoutGoalIdea) -> dict[str, Any] | None:
    if row.cleanup_task_id is None:
        return None
    task_id = str(row.cleanup_task_id)
    prs = tasks_facade.get_pull_requests_for_tasks(goal.team_id, [task_id]).get(task_id, [])
    _, status = _task_state(goal.team_id, task_id)
    return {
        "task_id": task_id,
        "task_status": status,
        "pr_url": prs[0].url if prs else "",
        "pr_state": prs[0].state if prs else "",
    }


def _idea_plan(view: IdeaView, anchor: PlanAnchor | None) -> dict[str, Any]:
    stored = dict(view.row.plan) if view.row is not None else {}
    audience = stored.get("audience") or view.audience or (anchor.audience if anchor else None)
    return {
        "days": stored.get("days") or (plan_days(anchor.sample_size, audience) if anchor else None),
        "mde": stored.get("mde") or (anchor.mde if anchor else None),
        "audience": audience,
    }


def work_entry(
    goal: SignalScoutGoal,
    view: IdeaView,
    spend: GoalSpend,
    urls: dict[str, ImplementationPr],
    anchor: PlanAnchor | None,
) -> dict[str, Any]:
    row = view.row
    pr = urls.get(view.report_id or "") if row is not None else None
    task_id = ""
    task_status = "not_started"
    if row is not None:
        entries = SignalReport.associated_task_runs(
            report_id=str(row.report_id),
            team_id=goal.team_id,
            product=SIGNALS_PRODUCT,
            type=TASK_RUN_TYPE_IMPLEMENTATION,
        )
        task_id, task_status = _task_state(goal.team_id, entries[-1].task_id if entries else None)
    return {
        "id": view.id,
        "kind": view.kind,
        "stage": view.stage,
        "title": view.title,
        "summary": view.summary,
        "note": row.note if row else "",
        "pr_url": pr.url if pr else "",
        "experiment_id": row.experiment_id if row else None,
        "outcome": row.outcome if row else "",
        "result": row.result if row else {},
        "task_id": task_id or None,
        "task_status": task_status,
        "spent_cents": spend.by_report.get(view.report_id or "", 0),
        "created_at": view.created_at,
        "finished_at": row.finished_at if row else None,
        "number": row.number if row and row.kind == Kind.IDEA else None,
        "chosen_at": row.created_at if row else None,
        "merged_at": row.merged_at if row else None,
        "exposed_at": row.exposed_at if row else None,
        "source": view.source,
        "assessment": view.assessment if view.kind == Kind.IDEA else "",
        "evidence": view.evidence,
        "report_id": view.report_id,
        "dismissed_reason": view.dismissed_reason,
        "moves_metric": view.moves_metric,
        "plan": _idea_plan(view, anchor),
        "cleanup": _cleanup(goal, row) if row is not None else None,
    }


def spend_split(goal: SignalScoutGoal, spend: GoalSpend, tested_count: int) -> dict[str, Any]:
    ended = goal.status not in LIVE
    return {
        "scout_cents": spend.scout_cents,
        "scout_runs": spend.scout_runs,
        "ideas_cents": spend.ideas_cents,
        "tracking_cents": spend.tracking_cents,
        "returned_cents": max(goal.budget_cents - spend.spent_cents, 0) if ended else 0,
        "tested_ideas": tested_count,
        "per_tested_idea_cents": round(spend.spent_cents / tested_count) if tested_count else None,
    }


def results(goal: SignalScoutGoal, views: list[IdeaView], spend: GoalSpend) -> dict[str, Any] | None:
    if goal.status in LIVE:
        return None
    built = [
        view.row
        for view in views
        if view.row is not None and view.kind == Kind.IDEA and view.stage in (Stage.DONE, Stage.DROPPED)
    ]
    first_merge = min((row.merged_at for row in built if row.merged_at), default=None)
    return {
        "started_at": goal.baseline_at or goal.created_at,
        "ended_at": goal.closed_at or goal.reached_at or goal.updated_at,
        "met_at_start": meets(goal.direction, goal.target, goal.baseline_value)
        or bool(goal.reached_at and (first_merge is None or goal.reached_at < first_merge)),
        "spend": spend_split(goal, spend, sum(1 for row in built if tested(row.outcome))),
    }


def spend_history(spend: GoalSpend) -> list[dict[str, Any]]:
    total = 0
    points = []
    for point in spend.points:
        total += point.spent_cents
        points.append({"at": point.at, "spent_cents": total})
    return points


def anchor_for(team: Team, user: User, goal: SignalScoutGoal, measured: Metric) -> PlanAnchor | None:
    if not goal.insight_short_id:
        return None
    seen = observed(delivery(team, user, goal.insight_short_id, workload=Workload.ONLINE))
    return plan_anchor(measured, daily_audience(seen))


def detail(team: Team, user: User, goal: SignalScoutGoal) -> dict[str, Any]:
    views = goal_ideas(goal)
    spend = goal_spend(goal)
    urls = pr_states(goal, views)
    row = entry(team, user, goal, views, spend, urls)
    measured: Metric = row["metric"]
    anchor = anchor_for(team, user, goal, measured)
    return {
        **row,
        "results": results(goal, views, spend),
        "work": [work_entry(goal, view, spend, urls, anchor) for view in views],
        "spend_history": spend_history(spend),
        "is_owner": user.id == goal.created_by_id,
        "secondary_values": [metric(team, user, item["insight"]) for item in goal.guardrails or []],
        "scout_running": any(run.status in ACTIVE_RUN for _, run in recent_scout_runs(goal, limit=1)),
        "plan_anchor": anchor,
    }


def list_goals(team: Team, user: User) -> list[dict[str, Any]]:
    goals = list(
        SignalScoutGoal.objects.for_team(team.id).select_related("config", "created_by").order_by("-created_at")[:200]
    )
    return [entry(team, user, goal, goal_ideas(goal), goal_spend(goal)) for goal in goals]
