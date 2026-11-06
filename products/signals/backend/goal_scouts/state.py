import re
from dataclasses import replace
from datetime import datetime, timedelta

from posthog.dataclasses import frozen

from ..models import SignalScoutConfig, SignalScoutGoal, SignalScoutGoalIdea
from .ideas import NOT_SUPPORTED, IdeaView, open_row, ready_ideas, tracking_view, unchecked_owner_ideas
from .metrics import meets
from .plan import EXPOSURE_GRACE
from .scout import DISMISS_LIMIT, ScoutJob

Status = SignalScoutGoal.Status
Stage = SignalScoutGoalIdea.Stage
Kind = SignalScoutGoalIdea.Kind
Outcome = SignalScoutGoalIdea.Outcome

CONFIRM_HOURS = 72
BASELINE_PATIENCE = timedelta(days=3)
ERROR_LIMIT = 3
NO_ACCESS = "The goal owner no longer has access."
FAILURES = re.compile(r"^The scout failed (\d+) times? in a row")
LIVE = (Status.SETTING_UP, Status.RUNNING)
LATER = ("review", "scout-empty", "scout-dismissed")
WORKING = ("tracking", "baseline", "building", "testing", "confirming", "checking", "finding")
ASKS = {
    "reached": ("The goal is reached", "Close the goal, or raise the target and add budget to keep going."),
    "spent": ("The budget is used", "Add budget to continue, or close the goal."),
    "access": ("The goal owner has no access", "{note}"),
    "errors": ("The scout keeps failing", "{note}"),
    "target": (
        "Set the target",
        "The scout will measure this goal with {metric}. Check that it fits, then set the value to reach in Edit goal.",
    ),
    "baseline": (
        "The baseline is not ready",
        "{note} Check that the events reach PostHog, or close the goal and measure it another way.",
    ),
    "choose": ("Choose an idea to build", "{ready} Nothing is built until you choose one."),
    "scout-empty": ("The Scout found no new ideas", "{empty}\n\n{empty_summary}"),
    "scout-dismissed": ("The Scout stopped", "{scout}"),
    "scout-failing": ("The Scout keeps failing", "{scout}"),
    "budget": ("The budget is used up", "Add budget to keep going, or close the goal."),
    "target-met": ("The goal already meets the target", "{met_at_start}"),
    "unseen": ("{title}", "{work_note}"),
    "review": ("{title}", "Review and merge the pull request when you are happy with it."),
    "stuck": ("{title}", "{work_note}"),
}
LINES = {
    "access": ("problem", "{problem}", "{note}"),
    "budget": ("problem", "The budget is used up", "{used} Add budget to keep going."),
    "target": ("measure", "Set the target to start", "{found}"),
    "tracking": ("tracking", "Checking how the goal is measured", "{tracking}"),
    "stalled": ("problem", "The baseline is not ready", "{note}"),
    "baseline": ("measure", "Collecting a baseline", "{note}"),
    "stuck": ("problem", "{stopped}", "{work_note}"),
    "review": ("pull_request", "Review the pull request", "{merge} starts when you merge it."),
    "building": ("tracking", "Building an idea", "{building}"),
    "unseen": ("experiment", "Testing an idea", "{work_note}"),
    "testing": ("experiment", "Testing an idea", "{testing}"),
    "target-met": ("problem", "The goal already meets the target", "{met_at_start}"),
    "confirming": ("measure", "The goal is at the target", "{progress}{confirming}"),
    "choosing": ("idea", "Choose an idea to build", "{ready} The scout builds the one you choose."),
    "unsupported": ("idea", "All ideas have low confidence", "{ready} Add your own idea, or build one anyway."),
    "checking": ("idea", "Checking your ideas", "{checking}"),
    "finding": ("scout", "Finding ideas", "{finding}"),
    "scout-failing": ("problem", "The Scout keeps failing", "{scout}"),
    "scout-empty": ("idle", "The Scout found no new ideas", "{empty}"),
    "scout-dismissed": (
        "idle",
        f"You dismissed the last {DISMISS_LIMIT} ideas",
        "The scout stops looking until you add an idea.",
    ),
    "scout": ("scout", "{scout_label}", "{scout}"),
    "paused": ("paused", "The goal is paused", "The scout does no work until you resume the goal."),
    "reached": ("reached", "{reached}", "{ideas_summary}"),
    "spent": ("ended", "Budget used. The goal was not reached.", "{ideas_summary}"),
    "closed": ("ended", "{closed}", "{ideas_summary}"),
}


@frozen
class GoalAction:
    label: str
    kind: str
    work_id: str | None = None
    work_action: str | None = None
    url: str = ""


@frozen
class NextAction:
    key: str
    goal_title: str
    title: str
    description: str
    priority: int
    marker: str


@frozen
class GoalState:
    tile: str
    headline: str
    detail: str
    working: bool
    action: GoalAction | None
    scout_reason: str
    ready_ideas: int
    build_blocked: str
    can_add_idea: bool
    needs_you: bool
    actions: list[NextAction]


@frozen
class StateInput:
    goal: SignalScoutGoal
    views: list[IdeaView]
    job: ScoutJob
    spent_cents: int
    current: float | None
    pr_urls: dict[str, str]
    build_blocked: str
    now: datetime


BUTTONS = {
    "target": GoalAction(label="Set the target", kind="edit"),
    "target-met": GoalAction(label="Raise the target", kind="edit"),
    "budget": GoalAction(label="Add budget", kind="budget"),
    "choosing": GoalAction(label="See the ideas", kind="ideas"),
    "unsupported": GoalAction(label="See the ideas", kind="ideas"),
    "review": GoalAction(label="Review pull request", kind="pull_request"),
    "stuck": GoalAction(label="Try again", kind="work", work_action="retry"),
    "unseen": GoalAction(label="Check the deploy", kind="work"),
    "stalled": GoalAction(label="Edit goal", kind="edit"),
    "scout-failing": GoalAction(label="Open settings", kind="settings"),
    "scout-empty": GoalAction(label="Add an idea", kind="ideas"),
    "scout-dismissed": GoalAction(label="Add an idea", kind="ideas"),
}


def goal_title(goal: SignalScoutGoal) -> str:
    return goal.config.display_name or goal.config.skill_name


def effective_status(goal: SignalScoutGoal) -> str:
    if goal.status in LIVE and goal.config.status == SignalScoutConfig.Status.PAUSED_BY_USER:
        return "paused"
    return goal.status


def failure_note(previous: str, error: Exception) -> str:
    found = FAILURES.match(previous)
    count = int(found.group(1)) + 1 if found else 1
    return f"The scout failed {count} {'time' if count == 1 else 'times'} in a row and tries again: {str(error)[:300]}"


def goal_confirm_at(goal: SignalScoutGoal) -> datetime | None:
    return goal.goal_met_since + timedelta(hours=CONFIRM_HOURS) if goal.goal_met_since else None


def takes_ideas(goal: SignalScoutGoal) -> bool:
    return goal.status not in (Status.CLOSED, Status.REACHED)


def number(value: float) -> str:
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def dollars(cents: int) -> str:
    return f"${cents // 100:,}" if cents % 100 == 0 else f"${cents / 100:,.2f}"


def day(moment: datetime | None) -> str:
    return f"{moment:%b} {moment.day}" if moment else ""


def plural(count: int, word: str) -> str:
    return f"{count} {word if count == 1 else word + 's'}"


def tested(outcome: str | None) -> bool:
    return bool(outcome) and outcome != Outcome.DROPPED


def built(views: list[IdeaView]) -> list[SignalScoutGoalIdea]:
    return [view.row for view in views if view.row is not None and view.kind == Kind.IDEA]


def ideas_summary(rows: list[SignalScoutGoalIdea]) -> str:
    count = sum(1 for row in rows if tested(row.outcome))
    if not count:
        return "No ideas were tested"
    won = [row for row in rows if row.outcome == Outcome.WON]
    shipped = sum(1 for row in won if (row.result or {}).get("shipped"))
    return f"{len(won)} of {plural(count, 'idea')} won · {shipped} {'change' if shipped == 1 else 'changes'} shipped"


def unseen(row: SignalScoutGoalIdea, now: datetime) -> bool:
    return row.merged_at is not None and row.exposed_at is None and now - row.merged_at > EXPOSURE_GRACE


def work_key(row: SignalScoutGoalIdea, now: datetime) -> str:
    if row.stage == Stage.LIVE:
        return "unseen" if unseen(row, now) else "testing"
    return {Stage.REVIEW: "review", Stage.STUCK: "stuck", Stage.BUILDING: "building"}.get(Stage(row.stage), "")


def work_text(goal: SignalScoutGoal, view: IdeaView, url: str) -> dict[str, str]:
    row = view.row
    note = row.note if row else ""
    step = (
        "measure check" if view.kind == Kind.TRACKING else "test" if row and row.merged_at else "review" if url else ""
    )
    return {
        "title": view.title,
        "work_note": note,
        "stopped": f"The {step} stopped" if step else "Building stopped",
        "merge": "The scout" if view.kind == Kind.TRACKING else "The test",
        "testing": "The goal is at the target. It ends when this test has a result." if goal.goal_met_since else note,
    }


def goal_text(found: StateInput, ready: int, checking: int) -> dict[str, str]:
    goal, job = found.goal, found.job
    rows = built(found.views)
    reached_on = day(goal.reached_at or goal.goal_met_since)
    target = number(float(goal.target)) if goal.target is not None else ""
    return {
        "note": goal.note,
        "used": f"{dollars(found.spent_cents)} of {dollars(goal.budget_cents)} spent.",
        "found": f"The scout found a measure: {goal.metric_name}. Check that it fits, then set the value to reach.",
        "ready": f"{plural(ready, 'idea')} {'waits' if ready == 1 else 'wait'} for you.",
        "metric": goal.metric_name or "the goal",
        "tracking": goal.note
        or f"The scout looks for the events behind {goal.metric_name or 'the goal'}. This takes a few minutes.",
        "building": goal.note or "An agent writes the change behind a feature flag.",
        "checking": goal.note or f"The scout checks {plural(checking, 'idea')} against the code and the goal.",
        "finding": goal.note or "Scout reads recordings, events and code to find changes that can move the goal.",
        "scout": job.reason,
        "scout_label": job.label,
        "empty": f"The last {job.empty_runs} Scout runs found no idea with enough evidence. "
        "Add your own idea for the Scout to check, or change the goal.",
        "empty_summary": job.empty_summary,
        "progress": f"{number(found.current)} against a target of {target}. "
        if found.current is not None and target
        else "",
        "confirming": f"The scout confirms it on {day(goal_confirm_at(goal))}.",
        "reached": f"Goal reached on {reached_on}" if reached_on else "Goal reached",
        "closed": " ".join(
            part
            for part in (
                f"Closed on {day(goal.closed_at)}" if goal.closed_at else "Closed",
                "" if any(tested(row.outcome) for row in rows) else "before any idea was tested",
            )
            if part
        ),
        "ideas_summary": ideas_summary(rows),
        "met_at_start": f"{goal.metric_name or 'The goal'} was {number(goal.baseline_value)} when the goal started, which already meets the target of {target}. Raise the target so the ideas have something to move."
        if goal.baseline_value is not None and target
        else "",
    }


def ask(
    goal: SignalScoutGoal, key: str, values: dict[str, str], view: IdeaView | None = None, marker: str = ""
) -> NextAction:
    title, description = ASKS[key]
    return NextAction(
        key=key,
        goal_title=goal_title(goal),
        title=title.format(**values),
        description=description.format(**values).strip(),
        priority=int(key in LATER),
        marker=marker or (view.id if view else ""),
    )


def owner_asks(
    found: StateInput, values: dict[str, str], ready: list[IdeaView], current: IdeaView | None
) -> list[NextAction]:
    goal, job = found.goal, found.job
    if goal.status not in LIVE:
        return [
            ask(goal, key, values, marker=str(goal.updated_at.date()))
            for key in ("reached", "spent")
            if goal.status == key
        ]
    tracking = tracking_view(found.views)
    failures = FAILURES.match(goal.note)
    setting_up = goal.status == Status.SETTING_UP
    tracking_done = tracking is not None and tracking.stage == Stage.DONE
    finished = tracking.row.finished_at if tracking and tracking.row else None
    applies = {
        "access": goal.note == NO_ACCESS,
        "errors": bool(failures and int(failures.group(1)) >= ERROR_LIMIT),
        "target": setting_up and bool(goal.insight_short_id) and goal.target is None,
        "baseline": setting_up
        and goal.target is not None
        and tracking_done
        and finished is not None
        and found.now - finished > BASELINE_PATIENCE,
        "choose": bool(ready) and current is None,
        "scout-empty": job.ask == "scout-empty",
        "scout-dismissed": job.ask == "scout-dismissed",
        "scout-failing": goal.config.pause_reason == SignalScoutConfig.PauseReason.REPEATED_FAILURES,
        "budget": found.spent_cents >= goal.budget_cents and current is None,
        "target-met": goal.status == Status.RUNNING and meets(goal.direction, goal.target, goal.baseline_value),
    }
    markers = {"choose": ready[0].id if ready else "", "scout-empty": job.empty_marker}
    result = [ask(goal, key, values, marker=markers.get(key, "")) for key, yes in applies.items() if yes]
    for view in found.views:
        if view.row is None or view.stage not in SignalScoutGoalIdea.OPEN_STAGES:
            continue
        key = work_key(view.row, found.now)
        if key in ASKS:
            url = found.pr_urls.get(view.id, "")
            result.append(ask(goal, key, {**values, **work_text(goal, view, url)}, view))
    return sorted(result, key=lambda item: item.priority)


def pick(
    found: StateInput, asks: dict[str, NextAction], current: IdeaView | None, ready: list[IdeaView]
) -> tuple[str, IdeaView | None]:
    goal, job = found.goal, found.job
    status = effective_status(goal)
    if status not in LIVE:
        return (status, None)
    if "access" in asks or "errors" in asks:
        return ("access", None)
    if "budget" in asks:
        return ("budget", None)
    tracking = tracking_view(found.views)
    if goal.status == Status.SETTING_UP:
        if "target" in asks:
            return ("target", None)
        if tracking is not None and tracking.stage in (Stage.REVIEW, Stage.STUCK) and tracking.row:
            return (work_key(tracking.row, found.now), tracking)
        done = tracking is not None and tracking.stage == Stage.DONE
        return ("tracking" if not done else "stalled" if "baseline" in asks else "baseline", None)
    if current is not None and current.row is not None:
        return (work_key(current.row, found.now), current)
    if "target-met" in asks:
        return ("target-met", None)
    if goal.goal_met_since:
        return ("confirming", None)
    if ready:
        unsupported = all(view.assessment == NOT_SUPPORTED for view in ready)
        return ("unsupported" if unsupported else "choosing", None)
    if job.mode:
        return ("checking" if unchecked_owner_ideas(found.views) else "finding", None)
    if "scout-failing" in asks:
        return ("scout-failing", None)
    return (job.ask or "scout", None)


def goal_state(found: StateInput) -> GoalState:
    goal = found.goal
    ready = ready_ideas(found.views)
    checking = len(unchecked_owner_ideas(found.views))
    current = open_row(found.views)
    values = goal_text(found, len(ready), checking)
    actions = owner_asks(found, values, ready, current)
    asks = {item.key: item for item in actions}
    key, view = pick(found, asks, current, ready)
    url = found.pr_urls.get(view.id, "") if view else ""
    problem = next((item.title for item in actions if item.key in ("access", "errors")), "")
    filled = {**values, **(work_text(goal, view, url) if view else {}), "problem": problem}
    tile, headline, detail = LINES[key]
    button = BUTTONS.get(key)
    return GoalState(
        tile=tile,
        headline=headline.format(**filled),
        detail=detail.format(**filled),
        working=key in WORKING,
        action=replace(button, work_id=view.id if view else None, url=url) if button else None,
        scout_reason=found.job.reason,
        ready_ideas=len(ready),
        build_blocked=found.build_blocked,
        can_add_idea=takes_ideas(goal),
        needs_you=bool(actions),
        actions=actions,
    )
