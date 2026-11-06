import math
from datetime import datetime, timedelta

from django.utils import timezone

from posthog.dataclasses import frozen

from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.contracts import TaskRunDTO

from ..models import SignalScoutConfig, SignalScoutGoal, SignalScoutGoalIdea, SignalScoutRun
from ..scout_authorship import GOAL_RUN_METADATA_KEY
from .ideas import DISMISSED, IdeaView, goal_ideas, open_row, ready_ideas, unchecked_owner_ideas
from .spend import goal_spend

FIND = "find"
CHECK = "check"
DISMISS_LIMIT = 10
EMPTY_LOOKBACK = 8
EMPTY_SCOUT_RUNS = 2
EMPTY_PAUSE = timedelta(minutes=30)
EMPTY_PAUSE_MAX = timedelta(hours=24)
MAX_CONTEXT = 24000
RUN_INTERVAL_MINUTES = 120
GOAL_TAG = "goal"

FIND_RULES = """1. Start from the saved primary insight. Find where people drop off or slow down. Use funnels, paths, events, errors and session replays.
2. Use at least the last 30 days of data. Compare the newest week with the weeks before. Look for changes in how events are tracked, outages, and weekday patterns. Use a short time range only to confirm a problem you found.
3. Read the code for that part of the product.
4. If the owner has ideas to check, check each one first. File one report per owner idea. The title starts with "Owner idea N:" (N is the number in the goal section) and then the idea. Tag it `owner-idea-N`, and `supported` or `not-supported`. The summary starts with the word "Supported." or "Not supported." Then give the evidence.
5. Then file up to 3 reports with your own ideas, the strongest first. Each report is one change that can move the primary metric and that we did not try or dismiss yet.
6. Each report has: the problem, the evidence, the proposed change, the files to touch, the expected effect, and the guardrail it could hurt. Add one line "Metric: <name>" with the metric this change moves first. When that is not the goal's primary metric, say how it leads to the primary metric. Add one line "Audience: <number> people a day" with how many people a day reach the place this change touches, measured in PostHog, and link the insight you used.
7. Evidence must be links to PostHog data in markdown link form: session replays you watched (with the time), insights or queries with the numbers, error groups, experiments. Never invent evidence. An idea without evidence is not an idea.

File nothing when you find no idea with evidence."""

CHECK_RULES = """An idea is in an experiment now, on the feature flag the goal section names. This run only checks the owner's ideas. Do not file ideas of your own.

1. For each owner idea in the goal section, file one report. The title starts with "Owner idea N:" (N is its number) and then the idea. Tag it `owner-idea-N`, and `supported` or `not-supported`. The summary starts with the word "Supported." or "Not supported." Then give the evidence. Add one line "Audience: <number> people a day" with how many people a day reach the place this idea touches, measured in PostHog, and link the insight you used.
2. The live experiment changes the data. Split every number by the variant of that flag, or use data from before the experiment started. Say which one you used.
3. Evidence must be links to PostHog data in markdown link form: session replays you watched (with the time), insights or queries with the numbers, error groups, experiments. Never invent evidence."""

GOAL_SKILL_BODY = f"""# Find ideas for a goal

The owner chooses which idea to build. Nothing is built before that. Give the owner real choices with real evidence.

Every run gets a *Goal* section near the end of its prompt: the goal, its measure, its guardrails, what was tried, the owner's ideas to check, the ideas that already wait for the owner, and the mode of this run. Follow the rules for that mode.

Tag every report you file with `goal-idea`.

## Mode: find

{FIND_RULES}

## Mode: check

{CHECK_RULES}

## Always

Never write code, open pull requests, change flags or start experiments. Never edit the saved insights the goal section names.
"""


@frozen
class ScoutJob:
    mode: str
    label: str
    reason: str
    ask: str = ""
    empty_runs: int = 0
    empty_summary: str = ""
    empty_marker: str = ""


@frozen
class GoalRunGate:
    refusal: str
    context: str


def recent_scout_runs(goal: SignalScoutGoal, limit: int = EMPTY_LOOKBACK) -> list[tuple[SignalScoutRun, TaskRunDTO]]:
    rows = list(
        SignalScoutRun.objects.for_team(goal.team_id)
        .filter(scout_config_id=goal.pk, **{f"metadata__{GOAL_RUN_METADATA_KEY}": str(goal.pk)})
        .order_by("-created_at")[:limit]
    )
    found = tasks_facade.get_task_runs([row.task_run_id for row in rows], team_id=goal.team_id)
    return [(row, found[str(row.task_run_id)]) for row in rows if str(row.task_run_id) in found]


def newest_idea_at(views: list[IdeaView]) -> datetime | None:
    return max((view.created_at for view in views if view.kind == SignalScoutGoalIdea.Kind.IDEA), default=None)


def empty_scout_runs(
    views: list[IdeaView], runs: list[tuple[SignalScoutRun, TaskRunDTO]]
) -> list[tuple[SignalScoutRun, TaskRunDTO]]:
    newest = newest_idea_at(views)
    return [
        (row, run)
        for row, run in runs
        if run.status == "completed" and not row.emitted_report_ids and (newest is None or row.created_at > newest)
    ]


def empty_runs_wait(empty: list[tuple[SignalScoutRun, TaskRunDTO]], now: datetime) -> str:
    latest = empty[0][1] if empty else None
    ended = (latest.completed_at or latest.updated_at or latest.created_at) if latest else None
    if ended is None:
        return ""
    left = min(EMPTY_PAUSE * 2 ** (len(empty) - 1), EMPTY_PAUSE_MAX) - (now - ended)
    if left <= timedelta(0):
        return ""
    hours = math.ceil(left.total_seconds() / 3600)
    found = "The last Scout run" if len(empty) == 1 else f"The last {len(empty)} Scout runs"
    return f"{found} found no new ideas. The Scout looks again in about {hours} {'hour' if hours == 1 else 'hours'}."


IDLE_REASONS = {
    SignalScoutGoal.Status.SETTING_UP: (
        "Waiting for tracking",
        "The scout looks for ideas once tracking is checked and the baseline is ready.",
    ),
    SignalScoutGoal.Status.REACHED: ("Stopped", "The goal is reached."),
    SignalScoutGoal.Status.SPENT: ("Waiting for budget", "The goal used its budget."),
    SignalScoutGoal.Status.CLOSED: ("Stopped", "The goal is closed."),
}


def scout_job(
    goal: SignalScoutGoal,
    views: list[IdeaView],
    *,
    spent_cents: int,
    runs: list[tuple[SignalScoutRun, TaskRunDTO]],
    now: datetime,
) -> ScoutJob:
    if goal.status != SignalScoutGoal.Status.RUNNING:
        label, reason = IDLE_REASONS[SignalScoutGoal.Status(goal.status)]
        return ScoutJob(mode="", label=label, reason=reason)
    if goal.config.status == SignalScoutConfig.Status.PAUSED_BY_USER:
        return ScoutJob(mode="", label="Paused", reason="The scout starts again when you resume the goal.")
    if spent_cents >= goal.budget_cents:
        return ScoutJob(mode="", label="Waiting for budget", reason="The goal has no budget left.")
    unchecked = unchecked_owner_ideas(views)
    if open_row(views) is not None:
        if not unchecked:
            return ScoutJob(mode="", label="Paused while an idea is tested", reason="New ideas come after its result.")
        return ScoutJob(
            mode=CHECK,
            label="Checking your ideas",
            reason="The Scout checks your ideas while the current idea is tested.",
        )
    if ready_ideas(views) and not unchecked:
        return ScoutJob(mode="", label="Waiting for you to choose an idea", reason="Choose an idea to build.")
    latest = [view.stage for view in views if view.kind == SignalScoutGoalIdea.Kind.IDEA][:DISMISS_LIMIT]
    if len(latest) == DISMISS_LIMIT and all(stage == DISMISSED for stage in latest) and not unchecked:
        return ScoutJob(
            mode="",
            label="Waiting for your idea",
            reason=f"You dismissed the last {DISMISS_LIMIT} ideas. Add your own idea to restart the Scout.",
            ask="scout-dismissed",
        )
    if unchecked:
        return ScoutJob(
            mode=FIND,
            label="Checking your ideas",
            reason="The Scout checks your ideas against your data before you choose.",
        )
    empty = empty_scout_runs(views, runs)
    found_nothing = (
        {
            "ask": "scout-empty",
            "empty_runs": len(empty),
            "empty_summary": empty[0][0].summary,
            "empty_marker": str(newest_idea_at(views) or ""),
        }
        if len(empty) >= EMPTY_SCOUT_RUNS
        else {}
    )
    if wait := empty_runs_wait(empty, now):
        return ScoutJob(mode="", label="Not searching right now", reason=wait, **found_nothing)
    return ScoutJob(
        mode=FIND,
        label="Looking for the next idea",
        reason="No ideas wait for a choice. The Scout looks for new ideas on its next run.",
        **found_nothing,
    )


def _direction_word(direction: str) -> str:
    return "higher" if direction == "increase" else "lower"


def history(views: list[IdeaView]) -> str:
    lines = []
    for view in sorted(views, key=lambda view: view.created_at):
        if view.kind != SignalScoutGoalIdea.Kind.IDEA:
            continue
        if view.stage == DISMISSED:
            lines.append(f"- {view.title}: dismissed by the owner. Reason: {view.dismissed_reason}")
        elif view.row is not None and view.stage in (
            SignalScoutGoalIdea.Stage.DONE,
            SignalScoutGoalIdea.Stage.DROPPED,
        ):
            result = view.row.result or {}
            lines.append(f"- {view.title}: {view.row.outcome or view.stage}. {result.get('verdict', '')}".strip())
    return "\n".join(lines) or "No ideas tried yet."


def goal_summary(goal: SignalScoutGoal) -> str:
    guardrails = "\n".join(
        f"- {item['name']} (insight {item['insight']}): {_direction_word(item.get('direction', 'increase'))} is better, tolerate at most {float(item.get('max_regression', 0.05)):.0%} regression"
        for item in goal.guardrails or []
    )
    target = f"{goal.target}{goal.unit}" if goal.target is not None else "not set yet"
    return f"""## Goal
{goal.config.display_name or goal.config.skill_name}
Belief: {goal.belief}
Repositories: {", ".join(goal.config.repositories or [])}
Primary metric: {goal.metric_name}, saved insight {goal.insight_short_id or "not created yet"}. Target: {target} ({_direction_word(goal.direction)} is better). Baseline: {goal.baseline_value if goal.baseline_value is not None else "not measured yet"}.
Guardrails:
{guardrails or "- none"}"""


def goal_context(goal: SignalScoutGoal, views: list[IdeaView], job: ScoutJob) -> str:
    owner = "\n".join(f"- Owner idea {view.owner_number}: {view.title}" for view in unchecked_owner_ideas(views))
    waiting = "\n".join(f"- {view.title}" for view in ready_ideas(views))
    current = open_row(views)
    flag = f"\nLive experiment flag: `{current.row.flag_key}`" if current and current.row else ""
    return (
        f"{goal_summary(goal)}\n\n### What we tried\n{history(views)}"
        f"\n\n### Owner ideas to check\n{owner or 'No owner ideas to check.'}"
        f"\n\n### Ideas already waiting for the owner\n{waiting or 'None.'}"
        f"\n\n### Mode for this run: {job.mode or 'none'}{flag}"
    )[:MAX_CONTEXT]


def current_job(goal: SignalScoutGoal, views: list[IdeaView] | None = None, spent_cents: int | None = None) -> ScoutJob:
    found = views if views is not None else goal_ideas(goal)
    return scout_job(
        goal,
        found,
        spent_cents=goal_spend(goal).spent_cents if spent_cents is None else spent_cents,
        runs=recent_scout_runs(goal) if goal.status == SignalScoutGoal.Status.RUNNING else [],
        now=timezone.now(),
    )


def goal_run_gate(team_id: int, config_id: object) -> GoalRunGate | None:
    goal = SignalScoutGoal.objects.for_team(team_id).select_related("config").filter(config_id=config_id).first()
    if goal is None:
        return None
    views = goal_ideas(goal)
    job = current_job(goal, views)
    if not job.mode:
        return GoalRunGate(refusal=job.reason, context="")
    return GoalRunGate(refusal="", context=goal_context(goal, views, job))
