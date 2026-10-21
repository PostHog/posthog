"""Pick the (team, user) pairs that the next activity summary tick updates, and measure the daily caps.

Row counts here are only a queue estimate. `update_activity_summary` still applies the real drop
rules and `min_units`, and backs a pair off when it skips, so the pair leaves the queue head.
"""

import datetime
from collections import Counter

from django.db.models import Count, OuterRef, Q, Subquery, Sum
from django.db.models.functions import Coalesce

from posthog.dataclasses import frozen
from posthog.models import ActivityLog, Team

from products.signals.backend.activity_summary.config import ActivitySummaryConfig
from products.signals.backend.activity_summary.inputs import TASK_ORIGIN_PRODUCTS
from products.signals.backend.activity_summary.logic import EXCEPTION_ERROR_PREFIX, is_stale
from products.signals.backend.activity_summary.prompt import system_prompt
from products.signals.backend.activity_summary.render import (
    DEFAULT_LIMITS,
    MAX_LIMITS,
    MAX_SUMMARY_CHARS,
    SCOUT_CLIENT_PREFIX,
    RenderLimits,
)
from products.signals.backend.activity_summary.summaries import DEFAULT_MODEL, MAX_ATTEMPTS, MODEL_PRICES, cost_usd
from products.signals.backend.models import UserActivitySummary
from products.tasks.backend.facade.user_task_summaries import list_user_task_times

DAY = datetime.timedelta(days=1)
# Fewer characters per token than the render estimate, so the bound is high, not low.
_BOUND_CHARS_PER_TOKEN = 2
# The cost bound when the model has no price. One update of the default model costs far less.
_UNPRICED_UPDATE_COST_USD = 0.05
_CALLED_MODEL = (UserActivitySummary.Status.OK, UserActivitySummary.Status.FAILED)


@frozen(order=True)
class ActivitySummaryPair:
    team_id: int
    user_id: int


@frozen
class _Stored:
    input_watermark: datetime.datetime | None
    generated_at: datetime.datetime | None
    next_eligible_at: datetime.datetime | None
    prompt_version: int | None
    render_version: int | None


@frozen
class _RowCounts:
    new: int = 0
    window: int = 0


@frozen
class DailyUsage:
    updates: int
    cost_usd: float


def max_update_cost_usd(limits: RenderLimits = DEFAULT_LIMITS, model: str = DEFAULT_MODEL) -> float:
    """The most one update can cost: every attempt with the largest input and output."""
    # The previous summary is a profile, cut to `limits.profile_max_chars`, plus fields that `MAX_SUMMARY_CHARS` covers.
    input_chars = (
        limits.sections_max_chars
        + limits.profile_max_chars
        + MAX_SUMMARY_CHARS
        + len(system_prompt(limits.profile_max_chars))
    )
    bound = cost_usd(
        MAX_ATTEMPTS * input_chars // _BOUND_CHARS_PER_TOKEN,
        MAX_ATTEMPTS * limits.max_completion_tokens,
        MODEL_PRICES.get(model),
    )
    return _UNPRICED_UPDATE_COST_USD if bound is None else bound


def daily_usage(now: datetime.datetime) -> DailyUsage:
    """Updates that called the model in the last 24 hours, and their summed cost, over all teams.

    One row holds the latest update of a pair, so an earlier update of the same pair in the same 24
    hours is not counted. With the minimum update interval that happens only after a failure.
    A row without a cost counts as the most one update can cost under the largest limits the flag allows,
    because the row can come from a tick with larger limits than now. So missing usage cannot pass the cap.
    An update that raised before it called the model is not counted, unless the row holds an earlier paid update.
    """
    rows = (
        # nosemgrep: idor-lookup-without-team (the daily caps are global over all teams, with no user input)
        UserActivitySummary.all_teams.filter(status__in=_CALLED_MODEL, updated_at__gte=now - DAY)
        .exclude(error__startswith=EXCEPTION_ERROR_PREFIX, cost_usd=0)
        .aggregate(
            updates=Count("id"),
            unpriced=Count("id", filter=Q(cost_usd__isnull=True)),
            cost=Sum("cost_usd"),
        )
    )
    return DailyUsage(
        updates=rows["updates"],
        cost_usd=(rows["cost"] or 0.0) + rows["unpriced"] * max_update_cost_usd(MAX_LIMITS),
    )


def _enrolled_team_ids(config: ActivitySummaryConfig) -> list[int]:
    if not config.organization_ids:
        return []
    return list(
        Team.objects.filter(
            organization_id__in=config.organization_ids,
            organization__is_ai_data_processing_approved=True,
        )
        .exclude(id__in=config.skip_team_ids)
        .values_list("id", flat=True)
    )


def _stored_rows(team_ids: list[int]) -> dict[ActivitySummaryPair, _Stored]:
    # nosemgrep: idor-lookup-without-team (system tick with no user input; filtered to the enrolled teams)
    rows = UserActivitySummary.all_teams.filter(team_id__in=team_ids).values_list(
        "team_id", "user_id", "input_watermark", "generated_at", "next_eligible_at", "prompt_version", "render_version"
    )
    return {
        ActivitySummaryPair(team_id=team_id, user_id=user_id): _Stored(
            input_watermark=watermark,
            generated_at=generated_at,
            next_eligible_at=eligible,
            prompt_version=prompt_version,
            render_version=render_version,
        )
        for team_id, user_id, watermark, generated_at, eligible, prompt_version, render_version in rows
    }


def _activity_rows(
    team_ids: list[int], window_start: datetime.datetime, now: datetime.datetime
) -> dict[ActivitySummaryPair, _RowCounts]:
    """Activity log rows per pair after the pair's watermark and in the window, with the scope filters of `inputs.py`."""
    watermark = Subquery(
        # nosemgrep: idor-lookup-without-team (correlated on the outer row's team_id)
        UserActivitySummary.all_teams.filter(team_id=OuterRef("team_id"), user_id=OuterRef("user_id")).values(
            "input_watermark"
        )[:1]
    )
    rows = (
        ActivityLog.objects.filter(
            team_id__in=team_ids, user_id__isnull=False, created_at__gte=window_start, created_at__lt=now
        )
        .exclude(is_system=True)
        .exclude(was_impersonated=True)
        .exclude(client__startswith=SCOUT_CLIENT_PREFIX)
        .values("team_id", "user_id")
        .annotate(new=Count("id", filter=Q(created_at__gt=Coalesce(watermark, window_start))), window=Count("id"))
        .values_list("team_id", "user_id", "new", "window")
    )
    return {
        ActivitySummaryPair(team_id=team_id, user_id=user_id): _RowCounts(new=new, window=window)
        for team_id, user_id, new, window in rows
        if team_id is not None and user_id is not None
    }


def _task_rows(
    team_ids: list[int],
    window_start: datetime.datetime,
    now: datetime.datetime,
    stored: dict[ActivitySummaryPair, _Stored],
) -> dict[ActivitySummaryPair, _RowCounts]:
    """Tasks per pair after the pair's watermark and in the window."""
    new: Counter[ActivitySummaryPair] = Counter()
    window: Counter[ActivitySummaryPair] = Counter()
    for task in list_user_task_times(
        team_ids=team_ids, start=window_start, end=now, origin_products=TASK_ORIGIN_PRODUCTS
    ):
        pair = ActivitySummaryPair(team_id=task.team_id, user_id=task.user_id)
        window[pair] += 1
        row = stored.get(pair)
        if row is None or row.input_watermark is None or task.created_at > row.input_watermark:
            new[pair] += 1
    return {pair: _RowCounts(new=new[pair], window=count) for pair, count in window.items()}


def select_pairs(config: ActivitySummaryConfig, now: datetime.datetime, limit: int) -> list[ActivitySummaryPair]:
    """The due pairs of the enrolled teams, highest priority first, cut to `limit`.

    A pair is due when it has a task or an activity log row after its watermark, or in the last
    `window_days` with no watermark or a stale summary, and its `next_eligible_at` is empty or past.
    Pairs with no summary or a stale summary come first, then the pairs with the most new rows,
    then the oldest summaries.
    """
    team_ids = _enrolled_team_ids(config)
    if not team_ids or limit <= 0:
        return []
    window_start = now - datetime.timedelta(days=config.limits.window_days)
    stored = _stored_rows(team_ids)
    activity_rows = _activity_rows(team_ids, window_start, now)
    task_rows = _task_rows(team_ids, window_start, now, stored)

    due: list[tuple[bool, int, datetime.datetime, ActivitySummaryPair]] = []
    for pair in activity_rows.keys() | task_rows.keys():
        row = stored.get(pair)
        if row is not None and row.next_eligible_at is not None and row.next_eligible_at > now:
            continue
        activity = activity_rows.get(pair, _RowCounts())
        tasks = task_rows.get(pair, _RowCounts())
        stale = is_stale(row, config.rebuild_before)
        count = activity.window + tasks.window if stale else activity.new + tasks.new
        if not count:
            continue
        generated_at = row.generated_at if row is not None else None
        due.append((generated_at is not None and not stale, -count, generated_at or window_start, pair))
    due.sort()
    return [pair for *_, pair in due[:limit]]
