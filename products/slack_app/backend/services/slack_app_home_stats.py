"""Workspace activity aggregates behind the App Home stats card.

This module is deliberately free of Block Kit: it answers "what did this workspace ship
with @PostHog over the last N days" and returns plain dataclasses. The renderer in
`slack_app_home.py` decides how much of that fits into Slack's chart and table limits,
because caps like the 12 pie segments and 20-character labels are presentation
constraints rather than facts about the data.

Two caps are the exception and live here, because they change what gets *computed* rather
than what gets drawn: `MAX_TREND_POINTS` picks daily-vs-weekly bucketing, and
`_MAX_PEOPLE_ROWS` bounds the leaderboard so the cached aggregate stays small.

Everything is scoped to the tasks a Slack workspace started *and* the caller can already
see: the mapping query filters on `team_id__in=accessible_team_ids`, which the caller
derives from the same accessible-integration check the rest of the Home tab uses. A Slack
workspace admin is not automatically a PostHog org member, so the aggregates must never
widen what the viewer could otherwise reach.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from statistics import median
from typing import Any

from django.core.cache import cache
from django.utils import timezone as django_timezone

import structlog

from products.slack_app.backend.models import SlackThreadTaskMapping, SlackUserProfileCache

logger = structlog.get_logger(__name__)

# Window choices offered by the card's picker, in render order.
STATS_WINDOW_OPTIONS: tuple[tuple[int, str], ...] = (
    (7, "Last 7 days"),
    (30, "Last 30 days"),
    (90, "Last 90 days"),
)
DEFAULT_STATS_WINDOW_DAYS = 30
_VALID_WINDOW_DAYS = frozenset(days for days, _ in STATS_WINDOW_OPTIONS)

# Aggregation happens in Python over fetched rows rather than in SQL, so the row set is
# bounded. Hitting the cap is surfaced in the UI instead of silently under-reporting.
STATS_MAX_TASKS = 2000

# The Home tab republishes on open and on every interaction, all inside Slack's 3s SLA,
# so the same aggregate is recomputed far more often than the underlying data changes.
_STATS_CACHE_TTL_SECONDS = 300

# Slack rejects a chart series carrying more than 20 points. The trend is bucketed by day
# while a window fits under that, and by week beyond it, so the cap is enforced where the
# buckets are chosen rather than by truncating a too-long series at render time.
MAX_TREND_POINTS = 20

# The leaderboard is a top-N, not a directory — bounding it here also keeps the cached
# aggregate small on workspaces with hundreds of people.
_MAX_PEOPLE_ROWS = 20

# Display order for the outcome breakdown, and the labels the renderer decorates.
OUTCOME_DONE = "Done"
OUTCOME_FAILED = "Failed"
OUTCOME_CANCELLED = "Cancelled"
OUTCOME_RUNNING = "In progress"
_OUTCOME_ORDER: tuple[str, ...] = (OUTCOME_DONE, OUTCOME_FAILED, OUTCOME_CANCELLED, OUTCOME_RUNNING)

# Terminal run statuses get their own bucket; everything else — including a task with no
# run row yet — is still in flight.
_TERMINAL_OUTCOMES: dict[str, str] = {
    "completed": OUTCOME_DONE,
    "failed": OUTCOME_FAILED,
    "cancelled": OUTCOME_CANCELLED,
}


@dataclass(frozen=True)
class Slice:
    """One labelled count — an outcome bucket or a model's share of runs."""

    label: str
    value: int


@dataclass(frozen=True)
class ModelUsage:
    """How many runs a given pinned model handled.

    Carries the raw model id and its runtime so the renderer can format a display label
    without guessing the provider.
    """

    model: str
    runtime_adapter: str | None
    value: int


@dataclass(frozen=True)
class TrendBucket:
    """PRs opened and merged within one day or week of the window."""

    label: str
    opened: int
    merged: int


@dataclass(frozen=True)
class PersonRow:
    """One row of the most-active-people table."""

    name: str
    tasks: int
    merged: int


@dataclass(frozen=True)
class StatsState:
    """Everything the stats card renders, already aggregated.

    ``tasks_with_pr`` and ``tasks_merged`` are both counted off each task's latest
    *PR-bearing* run, so they describe the same runs and the merge rate between them
    cannot exceed 100%.
    """

    window_days: int = DEFAULT_STATS_WINDOW_DAYS
    tasks_started: int = 0
    tasks_with_pr: int = 0
    tasks_merged: int = 0
    # Everyone who started something, not just the leaderboard's top rows.
    active_people: int = 0
    # Median wall-clock of runs that finished successfully. Failed and cancelled runs are
    # excluded — they stop at an arbitrary point and would drag the figure toward noise.
    median_cycle_seconds: int | None = None
    outcomes: tuple[Slice, ...] = ()
    trend: tuple[TrendBucket, ...] = ()
    models: tuple[ModelUsage, ...] = ()
    people: tuple[PersonRow, ...] = ()
    truncated: bool = False
    refreshed_at_epoch: int = 0

    @property
    def has_data(self) -> bool:
        return self.tasks_started > 0

    @property
    def merge_rate_percent(self) -> int | None:
        """Merged as a percentage of tasks that opened a PR. None when nothing opened one."""
        if not self.tasks_with_pr:
            return None
        return round(self.tasks_merged * 100 / self.tasks_with_pr)


def coerce_window_days(raw: str | int | None) -> int:
    """Clamp an untrusted window value from a Slack payload to one we offer."""
    try:
        days = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_STATS_WINDOW_DAYS
    return days if days in _VALID_WINDOW_DAYS else DEFAULT_STATS_WINDOW_DAYS


def build_stats_state(
    *,
    slack_workspace_id: str,
    accessible_team_ids: Iterable[int],
    window_days: int = DEFAULT_STATS_WINDOW_DAYS,
    force_refresh: bool = False,
) -> StatsState:
    """Aggregate Slack-started task activity for a workspace over the given window.

    Cached for `_STATS_CACHE_TTL_SECONDS`; the card's Refresh button bypasses the cache.
    """
    team_ids = sorted(set(accessible_team_ids))
    window_days = coerce_window_days(window_days)
    if not slack_workspace_id or not team_ids:
        return StatsState(window_days=window_days)

    cache_key = _cache_key(slack_workspace_id, team_ids, window_days)
    cached = _cache_get(cache_key) if not force_refresh else None
    if cached is not None:
        return cached

    state = _compute_stats_state(
        slack_workspace_id=slack_workspace_id,
        team_ids=team_ids,
        window_days=window_days,
    )
    _cache_set(cache_key, state)
    return state


def _cache_key(slack_workspace_id: str, team_ids: list[int], window_days: int) -> str:
    teams = ",".join(str(t) for t in team_ids)
    return f"slack_app_home_stats:{slack_workspace_id}:{window_days}:{teams}"


def _cache_get(cache_key: str) -> StatsState | None:
    # A cache backend outage should slow the Home tab down, not make the card vanish, so
    # both sides of the cache swallow their errors.
    try:
        cached = cache.get(cache_key)
    except Exception:
        logger.warning("slack_app_home_stats_cache_read_failed", cache_key=cache_key)
        return None
    return cached if isinstance(cached, StatsState) else None


def _cache_set(cache_key: str, state: StatsState) -> None:
    try:
        cache.set(cache_key, state, _STATS_CACHE_TTL_SECONDS)
    except Exception:
        logger.warning("slack_app_home_stats_cache_write_failed", cache_key=cache_key)


def _compute_stats_state(*, slack_workspace_id: str, team_ids: list[int], window_days: int) -> StatsState:
    # Deferred to keep the tasks facade off this module's import path, matching how the
    # rest of the Home tab reaches it.
    from products.tasks.backend.facade import api as tasks_facade  # noqa: PLC0415

    now = django_timezone.now()
    refreshed_at_epoch = int(now.timestamp())
    cutoff = now - timedelta(days=window_days)

    # One extra row tells us the cap was hit without a second COUNT query.
    rows = list(
        SlackThreadTaskMapping.objects.filter(
            slack_workspace_id=slack_workspace_id,
            team_id__in=team_ids,
            created_at__gte=cutoff,
        )
        .order_by("-created_at")
        .values("task_id", "mentioning_slack_user_id", "created_at")[: STATS_MAX_TASKS + 1]
    )
    truncated = len(rows) > STATS_MAX_TASKS
    rows = rows[:STATS_MAX_TASKS]
    if not rows:
        return StatsState(window_days=window_days, refreshed_at_epoch=refreshed_at_epoch)

    # A task is mapped once per thread, but dedupe anyway so a task can't be double-counted.
    first_row_by_task: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        first_row_by_task.setdefault(str(row["task_id"]), row)

    task_ids = list(first_row_by_task)
    runs_by_task = tasks_facade.get_latest_run_by_task(task_ids)
    # `get_latest_pr_url_by_task` and `get_merged_pr_task_ids` resolve the same run for a
    # given task, so "opened a PR" and "merged" always describe one run. The latest run
    # overall — which carries the status and model — may well be a later, PR-less one.
    pr_urls_by_task = tasks_facade.get_latest_pr_url_by_task(task_ids)
    merged_task_ids = tasks_facade.get_merged_pr_task_ids(task_ids)

    outcome_counts: dict[str, int] = defaultdict(int)
    model_counts: dict[tuple[str, str | None], int] = defaultdict(int)
    tasks_by_person: dict[str, int] = defaultdict(int)
    merged_by_person: dict[str, int] = defaultdict(int)
    opened_by_bucket: dict[date, int] = defaultdict(int)
    merged_by_bucket: dict[date, int] = defaultdict(int)
    cycle_seconds: list[int] = []
    tasks_with_pr = 0

    bucket_by_week = window_days > MAX_TREND_POINTS

    for task_id, mapping_row in first_row_by_task.items():
        run = runs_by_task.get(task_id)
        person = mapping_row["mentioning_slack_user_id"] or ""
        bucket = _bucket_start(mapping_row["created_at"], by_week=bucket_by_week)

        outcome_counts[_outcome_label(run.status if run else None)] += 1

        if run is not None:
            model = (run.state or {}).get("model")
            if model:
                model_counts[(str(model), (run.state or {}).get("runtime_adapter"))] += 1
            if run.status == "completed" and run.completed_at and run.created_at:
                elapsed = int((run.completed_at - run.created_at).total_seconds())
                if elapsed >= 0:
                    cycle_seconds.append(elapsed)

        tasks_by_person[person] += 1

        if task_id in pr_urls_by_task:
            tasks_with_pr += 1
            opened_by_bucket[bucket] += 1
        if task_id in merged_task_ids:
            merged_by_bucket[bucket] += 1
            merged_by_person[person] += 1

    return StatsState(
        window_days=window_days,
        tasks_started=len(first_row_by_task),
        tasks_with_pr=tasks_with_pr,
        tasks_merged=len(merged_task_ids),
        active_people=len(tasks_by_person),
        median_cycle_seconds=int(median(cycle_seconds)) if cycle_seconds else None,
        outcomes=tuple(
            Slice(label=label, value=outcome_counts[label]) for label in _OUTCOME_ORDER if outcome_counts.get(label)
        ),
        trend=_build_trend(
            opened_by_bucket,
            merged_by_bucket,
            now=now,
            window_days=window_days,
            by_week=bucket_by_week,
        ),
        models=tuple(
            ModelUsage(model=model, runtime_adapter=runtime_adapter, value=count)
            for (model, runtime_adapter), count in sorted(model_counts.items(), key=lambda kv: (-kv[1], kv[0][0]))
        ),
        people=_build_people(tasks_by_person, merged_by_person, slack_workspace_id),
        truncated=truncated,
        refreshed_at_epoch=refreshed_at_epoch,
    )


def _outcome_label(status: str | None) -> str:
    """Map a run status onto a card bucket.

    A task with no run yet, and any status we don't recognise, counts as in flight —
    every task started in the window has to land in exactly one bucket for the outcome
    counts to add up to the headline total.
    """
    return _TERMINAL_OUTCOMES.get(status or "", OUTCOME_RUNNING)


def _bucket_start(when: datetime, *, by_week: bool) -> date:
    """The day, or the Monday of the week, a task belongs to."""
    day = when.date()
    return day - timedelta(days=day.weekday()) if by_week else day


def _build_trend(
    opened_by_bucket: dict[date, int],
    merged_by_bucket: dict[date, int],
    *,
    now: datetime,
    window_days: int,
    by_week: bool,
) -> tuple[TrendBucket, ...]:
    """Every bucket in the window, including empty ones.

    Slack requires each series to carry a point for every axis category, so gaps have to
    be materialised as zeroes rather than skipped.
    """
    end = _bucket_start(now, by_week=by_week)
    start = _bucket_start(now - timedelta(days=window_days - 1), by_week=by_week)
    step = timedelta(days=7 if by_week else 1)

    buckets: list[TrendBucket] = []
    current = start
    while current <= end:
        buckets.append(
            TrendBucket(
                label=current.strftime("%b %d"),
                opened=opened_by_bucket.get(current, 0),
                merged=merged_by_bucket.get(current, 0),
            )
        )
        current += step
    return tuple(buckets)


def _build_people(
    tasks_by_person: dict[str, int],
    merged_by_person: dict[str, int],
    slack_workspace_id: str,
) -> tuple[PersonRow, ...]:
    """The leaderboard, resolved to human names where the profile cache knows them."""
    if not tasks_by_person:
        return ()

    ranked = sorted(tasks_by_person.items(), key=lambda kv: (-kv[1], kv[0]))[:_MAX_PEOPLE_ROWS]
    slack_user_ids = [slack_user_id for slack_user_id, _ in ranked if slack_user_id]

    # The cache is per-integration and a workspace can be connected to several projects,
    # so match on the workspace and keep the first profile found for each Slack user.
    # Name precedence matches `slack_messages`, so one person reads the same on the
    # leaderboard as in forwarded thread context.
    names: dict[str, str] = {}
    for profile in SlackUserProfileCache.objects.filter(
        integration__integration_id=slack_workspace_id,
        slack_user_id__in=slack_user_ids,
    ).values("slack_user_id", "real_name", "display_name"):
        name = profile["display_name"] or profile["real_name"]
        if name:
            names.setdefault(profile["slack_user_id"], name)

    return tuple(
        PersonRow(
            name=names.get(slack_user_id) or slack_user_id or "Unknown",
            tasks=task_count,
            merged=merged_by_person.get(slack_user_id, 0),
        )
        for slack_user_id, task_count in ranked
    )
