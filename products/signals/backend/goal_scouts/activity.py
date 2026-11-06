from datetime import datetime
from typing import Any

from posthog.dataclasses import frozen
from posthog.models import Team, User
from posthog.models.activity_logging.activity_log import ActivityLog, apply_activity_visibility_restrictions
from posthog.models.activity_logging.retention import get_activity_log_lookback_restriction

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.experiments.backend.facade.api import activity_for_experiments
from products.tasks.backend.facade import api as tasks_facade

from ..artefact_schemas import SIGNALS_PRODUCT, TASK_RUN_TYPE_IMPLEMENTATION
from ..models import SignalReport, SignalScoutGoal, SignalScoutGoalIdea, SignalScoutRun, SignalSpend
from ..scout_authorship import GOAL_RUN_METADATA_KEY
from .ideas import clean_title
from .spend import GoalSpend

LIMIT = 200
RUN_ENDINGS = {"completed": "finished", "failed": "failed", "cancelled": "canceled"}
RUN_NOUNS = {SignalScoutGoalIdea.Kind.IDEA: "Build", SignalScoutGoalIdea.Kind.TRACKING: "Tracking check"}
FINISHED_TITLES = {
    ("idea", "done"): "Idea learned",
    ("idea", "dropped"): "Idea dropped",
    ("tracking", "done"): "Tracking checked",
    ("tracking", "dropped"): "Tracking check stopped",
}
FIELD_LABELS = {
    "name": "Name",
    "belief": "Belief",
    "insight_short_id": "Measure",
    "metric_name": "Measure",
    "goal_description": "Measure",
    "guardrails": "Guardrails",
    "target": "Target",
    "direction": "Direction",
    "budget_cents": "Budget",
    "repositories": "Repository",
}
STATUS_TITLES = {
    "running": "Goal running",
    "reached": "Goal reached",
    "spent": "Budget used",
    "closed": "Goal closed",
    "setting_up": "Goal updated",
}
SPEND_NOUNS: dict[str, str] = {SignalSpend.Kind.SCOUT_RUN.value: "Scout run"}


@frozen
class ActivityEntry:
    id: str
    at: datetime
    title: str
    detail: str
    resource: str
    resource_id: str


def _goal_log_title(row: ActivityLog) -> tuple[str, str] | None:
    changes: list[dict[str, Any]] = (row.safe_detail or {}).get("changes") or []
    fields = [FIELD_LABELS[field] for change in changes if (field := change.get("field")) in FIELD_LABELS]
    status = next((change for change in changes if change.get("field") == "status"), None)
    enabled = next((change for change in changes if change.get("field") == "enabled"), None)
    if status:
        return STATUS_TITLES.get(str(status.get("after")), "Goal updated"), ""
    if enabled is not None:
        return ("Goal resumed" if enabled.get("after") else "Goal paused"), ""
    if not fields or row.activity == "goal_created":
        return None
    return "Goal updated", ", ".join(dict.fromkeys(fields))


def _goal_logs(team: Team, user: User, goal: SignalScoutGoal) -> list[ActivityEntry]:
    if not UserAccessControl(user=user, team=team).check_access_level_for_resource("activity_log", "viewer"):
        return []
    rows = apply_activity_visibility_restrictions(
        ActivityLog.objects.filter(team_id=goal.team_id, scope="SignalScoutConfig", item_id=str(goal.pk)), user
    )
    since = get_activity_log_lookback_restriction(team.organization)
    if since:
        rows = rows.filter(created_at__gte=since)
    entries = []
    for row in rows.order_by("-created_at")[:LIMIT]:
        titled = _goal_log_title(row)
        if titled is not None:
            entries.append(
                ActivityEntry(
                    id=str(row.id), at=row.created_at, title=titled[0], detail=titled[1], resource="", resource_id=""
                )
            )
    return entries


def _task_runs(team_id: int, user: User, task_id: str, noun: str, title: str) -> list[ActivityEntry]:
    return [
        ActivityEntry(
            id=f"run:{run.id}",
            at=run.completed_at,
            title=f"{noun} {RUN_ENDINGS[run.status]}",
            detail=title,
            resource="task",
            resource_id=task_id,
        )
        for run in tasks_facade.list_task_runs(task_id, team_id, user_id=user.id)
        if run.status in RUN_ENDINGS and run.completed_at
    ]


def _idea_entries(team_id: int, user: User, rows: list[SignalScoutGoalIdea]) -> list[ActivityEntry]:
    entries: list[ActivityEntry] = []
    for row in rows:
        title = clean_title(row.report.title or "")
        for task in SignalReport.associated_task_runs(
            report_id=str(row.report_id), team_id=team_id, product=SIGNALS_PRODUCT, type=TASK_RUN_TYPE_IMPLEMENTATION
        ):
            entries.extend(
                _task_runs(team_id, user, task.task_id, RUN_NOUNS[SignalScoutGoalIdea.Kind(row.kind)], title)
            )
        if row.cleanup_task_id:
            entries.extend(_task_runs(team_id, user, str(row.cleanup_task_id), "Flag cleanup", row.flag_key))
        if row.finished_at:
            entries.append(
                ActivityEntry(
                    id=f"finished:{row.id}",
                    at=row.finished_at,
                    title=FINISHED_TITLES.get((row.kind, row.stage), "Work finished"),
                    detail=f"{title}. {row.note}".strip() if row.kind == SignalScoutGoalIdea.Kind.IDEA else title,
                    resource="experiment" if row.experiment_id else "",
                    resource_id=str(row.experiment_id or ""),
                )
            )
        if row.merged_at:
            entries.append(
                ActivityEntry(
                    id=f"merged:{row.id}",
                    at=row.merged_at,
                    title="Pull request merged",
                    detail=title,
                    resource="pull_request",
                    resource_id=str(row.result.get("pr_url", "")) if row.result else "",
                )
            )
    return entries


def _scout_runs(team_id: int, goal: SignalScoutGoal) -> list[ActivityEntry]:
    entries = []
    for row in (
        SignalScoutRun.objects.for_team(team_id)
        .filter(scout_config_id=goal.pk, **{f"metadata__{GOAL_RUN_METADATA_KEY}": str(goal.pk)})
        .order_by("-created_at")[:LIMIT]
    ):
        run = tasks_facade.get_task_run(row.task_run_id, team_id=team_id)
        if run is None or run.status not in RUN_ENDINGS or not run.completed_at:
            continue
        entries.append(
            ActivityEntry(
                id=f"run:{run.id}",
                at=run.completed_at,
                title=f"Scout run {RUN_ENDINGS[run.status]}",
                detail="The run stopped with an error." if run.status == "failed" else "",
                resource="task",
                resource_id=str(run.task_id),
            )
        )
    return entries


def _experiment_entries(team: Team, user: User, rows: list[SignalScoutGoalIdea]) -> list[ActivityEntry]:
    ids = [row.experiment_id for row in rows if row.experiment_id is not None]
    entries = []
    for event in activity_for_experiments(team=team, user=user, experiment_ids=ids, limit=LIMIT):
        label = "Experiment" if event.scope == "Experiment" else "Feature flag"
        action = event.activity
        for change in event.changes:
            if change.get("field") == "active" and isinstance(change.get("after"), bool):
                action = "enabled" if change["after"] else "disabled"
            elif change.get("field") in ("start_date", "end_date") and change.get("after"):
                action = "started" if change["field"] == "start_date" else "ended"
        if action == "updated" or (label == "Feature flag" and action == "created"):
            continue
        entries.append(
            ActivityEntry(
                id=event.id,
                at=event.at,
                title=f"{label} {action.replace('_', ' ')}",
                detail=event.name,
                resource="experiment" if event.scope == "Experiment" else "flag",
                resource_id=event.item_id,
            )
        )
    return entries


def _spend_entries(goal: SignalScoutGoal, spend: GoalSpend, rows: list[SignalScoutGoalIdea]) -> list[ActivityEntry]:
    nouns = {str(row.report_id): RUN_NOUNS[SignalScoutGoalIdea.Kind(row.kind)] for row in rows}
    return [
        ActivityEntry(
            id=f"spend:{goal.pk}:{index}",
            at=point.at,
            title="Spend recorded",
            detail=f"${point.spent_cents / 100:,.2f} · {SPEND_NOUNS.get(point.kind) or nouns.get(point.report_id or '', 'Build')}",
            resource="",
            resource_id="",
        )
        for index, point in enumerate(spend.points)
        if point.spent_cents
    ]


def recent_activity(team: Team, user: User, goal: SignalScoutGoal, spend: GoalSpend) -> list[ActivityEntry]:
    rows = list(
        SignalScoutGoalIdea.objects.for_team(goal.team_id)
        .filter(goal=goal)
        .select_related("report")
        .order_by("created_at")
    )
    events = [
        ActivityEntry(
            id=f"goal:{goal.pk}",
            at=goal.created_at,
            title="Goal created",
            detail=goal.config.display_name,
            resource="",
            resource_id="",
        ),
        *_goal_logs(team, user, goal),
        *_idea_entries(goal.team_id, user, rows),
        *_scout_runs(goal.team_id, goal),
        *_experiment_entries(team, user, rows),
        *_spend_entries(goal, spend, rows),
    ]
    return sorted(events, key=lambda entry: (entry.at, entry.id), reverse=True)[:LIMIT]
