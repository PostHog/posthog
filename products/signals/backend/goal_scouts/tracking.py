import re
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

from django.utils import timezone

from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.models import Team, User

from products.product_analytics.backend.facade.api import saved_insight_for_read
from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.contracts import TaskRunDTO

from ..models import SignalScoutGoal
from .metrics import delivery, metric, observed
from .plan import readiness

FRESH_WITHIN = timedelta(hours=24)
INSIGHT_LINE = re.compile(r"Insight:\s*`?([A-Za-z0-9]{8})\b")
ADOPT_NOTE = "End your last message with the line Insight: <short id> for the saved insight that measures the goal."

GOAL_TASK_RULES = """Rules for this goal:
- Never merge a pull request, push to the default branch, or deploy. People review and merge.
- Never edit the saved insights the goal names. Propose a change in your summary instead.
- Never invent events, results or evidence.
- Do not wait for reviews or data.

"""


@frozen
class Baseline:
    ready: bool
    value: float | None
    note: str


def tracking_task(goal: SignalScoutGoal) -> str:
    if not goal.insight_short_id:
        return f"""## Task
Find or create the saved insight that measures the goal, then make sure it is measured.
The owner described the measure in words: {goal.goal_description}
1. Search the saved insights in PostHog for one that measures exactly this. A match is a trends insight that shows one line and measures the same kind of value: a count stays a count, and a share, rate or average stays a share, rate or average.
2. If no saved insight matches, create and save a trends insight that shows one line and measures it. For a share or rate, use two series and a formula, for example A / B. Name it after the metric.
3. List the events and properties that insight needs. Read the repositories and check that those events are captured where the behavior happens.
4. If tracking is missing or wrong, open one pull request that fixes it, with focused tests. If tracking is correct, open no pull request and say so.
End your last message with one line in this form, with the 8-character short ID of the saved insight:
Insight: <short id>"""
    return f"""## Task
Make sure the primary metric is measured.
1. Read the saved insight {goal.insight_short_id} in PostHog and list the events and properties it needs.
2. Read the repository and check that those events are captured where the behavior happens.
3. If tracking is missing or wrong, open one pull request that fixes it, with focused tests. If tracking is correct, open no pull request and say so."""


def event_names(node: Any) -> set[str]:
    if isinstance(node, dict):
        own = {str(node["event"])} if node.get("kind") == "EventsNode" and node.get("event") else set()
        return own | {name for value in node.values() for name in event_names(value)}
    if isinstance(node, list):
        return {name for value in node for name in event_names(value)}
    return set()


def baseline(team: Team, user: User, goal: SignalScoutGoal, *, since: datetime | None) -> Baseline:
    short_id = goal.insight_short_id
    if not short_id:
        return Baseline(ready=False, value=None, note="Waiting for a saved insight that measures the goal.")
    insight = saved_insight_for_read(team=team, user=user, short_id=short_id)
    if insight is None:
        return Baseline(ready=False, value=None, note="The goal insight is not accessible to the goal owner.")
    current = metric(team, user, short_id, blocking=True, workload=Workload.OFFLINE)
    found = delivery(team, user, short_id, workload=Workload.OFFLINE, since=since)
    missing = event_names(insight.query) - set(found.event_names if found else ())
    if missing:
        return Baseline(ready=False, value=current.current, note=f"Waiting for events: {', '.join(sorted(missing))}.")
    last = found.last_event_at if found else None
    if last is None or last < timezone.now() - FRESH_WITHIN:
        return Baseline(ready=False, value=current.current, note="Waiting for fresh events.")
    if current.current is None:
        return Baseline(ready=False, value=None, note=current.message or "Waiting for a value.")
    seen = observed(found)
    ready = readiness(replace(seen, tracked_before_window=False) if since is not None else seen)
    return Baseline(ready=ready.ready, value=current.current, note=ready.note)


def run_logs(team_id: int, run: TaskRunDTO) -> str:
    return (tasks_facade.read_task_run_logs(run.id, run.task_id, team_id) or "").replace("\\n", "\n")


def reported_insight(logs: str) -> str:
    found = INSIGHT_LINE.findall(logs)
    return found[-1] if found else ""


def turn_finished(logs: str) -> bool:
    return logs.rfind('"stopReason"') > logs.rfind('"session/prompt"') >= 0
