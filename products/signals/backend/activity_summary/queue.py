"""Pick the (team, user) pairs that the next activity summary tick updates, and measure the daily caps.

Each pair has a queue state row. One cursor per input source reads the new rows of all enrolled teams
and adds them to the pending units of their pair. `select_pairs` then ranks the due pairs and fills the
tick budget in two passes: paying organizations first, then free organizations with the budget that is
left. Row counts here are only a queue estimate. `update_activity_summary` still applies the real drop
rules and `min_units`, and backs a pair off when it skips, so the pair leaves the queue head.
"""

import math
import uuid
import hashlib
import datetime
from collections.abc import Callable
from typing import Any

from django.db import transaction
from django.db.models import (
    BooleanField,
    Case,
    Count,
    DateTimeField,
    F,
    FloatField,
    Max,
    OuterRef,
    Q,
    QuerySet,
    Subquery,
    Sum,
    Value,
    When,
    Window,
)
from django.db.models.expressions import Combinable
from django.db.models.functions import Cast, Coalesce, Extract, Greatest, Ln, RowNumber

from posthog.dataclasses import frozen
from posthog.models import ActivityLog, FileSystemViewLog, Team

from products.signals.backend.activity_summary.config import ActivitySummaryConfig
from products.signals.backend.activity_summary.inputs import TASK_ORIGIN_PRODUCTS
from products.signals.backend.activity_summary.logic import EXCEPTION_ERROR_PREFIX
from products.signals.backend.activity_summary.prompt import COMPUTED_MAX_CHARS, PROMPT_VERSION, system_prompt
from products.signals.backend.activity_summary.render import (
    DEFAULT_LIMITS,
    MAX_LIMITS,
    MAX_SUMMARY_CHARS,
    NOISY_ACTIVITY_SCOPES,
    RENDER_VERSION,
    SANDBOX_PROMPT_TITLE_PREFIX,
    SCOUT_CLIENT_PREFIX,
    RenderLimits,
)
from products.signals.backend.activity_summary.summaries import DEFAULT_MODEL, MAX_ATTEMPTS, MODEL_PRICES, cost_usd
from products.signals.backend.models import (
    UserActivitySummary,
    UserActivitySummaryQueueCursor,
    UserActivitySummaryQueueState,
)
from products.tasks.backend.facade.user_task_summaries import list_user_task_times

DAY = datetime.timedelta(days=1)
# Fewer characters per token than the render estimate, so the bound is high, not low.
_BOUND_CHARS_PER_TOKEN = 2
# The cost bound when the model has no price. One update of the default model costs far less.
_UNPRICED_UPDATE_COST_USD = 0.05
_CALLED_MODEL = (UserActivitySummary.Status.OK, UserActivitySummary.Status.FAILED)

SOURCE_ACTIVITY_LOG = "activity_log"
SOURCE_TASKS = "tasks"
SOURCE_VIEWS = "views"
# A cursor stays this far behind now, so it still reads a row that commits a little after its timestamp.
FEED_LAG = datetime.timedelta(minutes=5)
# One tick reads at most this much of one source. A cursor that fell behind catches up over the next ticks.
MAX_FEED_STEP = datetime.timedelta(hours=6)
TIER_PAYING = "paying"
TIER_FREE = "free"
# A summary younger than this many target intervals counts as fresh on the tick event.
_FRESH_STALENESS = 2


@frozen(order=True)
class ActivitySummaryPair:
    team_id: int
    user_id: int


@frozen
class ActivitySummaryTierStats:
    tier: str
    due_pairs: int = 0
    # Hours since the due time of the pair that waits longest. Null when no pair is due.
    oldest_due_hours: float | None = None
    # The share of pairs with activity in the window whose summary is younger than twice the tier's target interval.
    fresh_share: float | None = None


@frozen
class PairSelection:
    pairs: list[ActivitySummaryPair]
    due_pairs: int
    tiers: list[ActivitySummaryTierStats]


@frozen
class _NewRows:
    units: int
    last_at: datetime.datetime


_Pending = dict[ActivitySummaryPair, _NewRows]
_Reader = Callable[[list[int], datetime.datetime, datetime.datetime, bool], _Pending]


@frozen
class DailyUsage:
    updates: int
    cost_usd: float


def max_input_chars(limits: RenderLimits = DEFAULT_LIMITS) -> int:
    """The longest input of one attempt: the system prompt and the user turn."""
    # The previous summary is a profile, cut to `limits.profile_max_chars`, plus fields that `MAX_SUMMARY_CHARS` covers.
    return (
        limits.sections_max_chars
        + limits.profile_max_chars
        + MAX_SUMMARY_CHARS
        + COMPUTED_MAX_CHARS
        + len(system_prompt(limits.profile_max_chars))
    )


def max_update_cost_usd(limits: RenderLimits = DEFAULT_LIMITS, model: str = DEFAULT_MODEL) -> float:
    """The most one update can cost: every attempt with the largest input and output."""
    bound = cost_usd(
        MAX_ATTEMPTS * max_input_chars(limits) // _BOUND_CHARS_PER_TOKEN,
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


# A new salt reorders every organization, so change the version only to start a new rollout order.
_ROLLOUT_SALT = "activity-summary-self-driving-v1"
_ROLLOUT_BUCKETS = 10_000


def organization_rollout_bucket(organization_id: uuid.UUID) -> int:
    """The organization's fixed place in the percentage rollout, from 0 to `_ROLLOUT_BUCKETS` - 1."""
    digest = hashlib.sha256(f"{_ROLLOUT_SALT}:{organization_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % _ROLLOUT_BUCKETS


def _in_rollout(config: ActivitySummaryConfig, organization_id: uuid.UUID) -> bool:
    threshold = config.self_driving_organization_percentage * _ROLLOUT_BUCKETS / 100
    return organization_rollout_bucket(organization_id) < threshold


@frozen
class Enrollment:
    team_ids: list[int]
    organization_ids: list[uuid.UUID]
    # The organizations that a 100 percent rollout enrolls, with or without manual enrollment.
    qualifying_organization_ids: list[uuid.UUID]


def enrollment(config: ActivitySummaryConfig) -> Enrollment:
    """The teams that `is_team_enrolled_for_generation` enrolls, in a fixed number of queries."""
    if not config.enabled:
        return Enrollment(team_ids=[], organization_ids=[], qualifying_organization_ids=[])
    from products.signals.backend.facade.api import (
        team_ids_with_enabled_source,  # noqa: PLC0415 — the facade imports this module through `read`
    )

    listed = _parse_organization_ids(config.organization_ids)
    teams = (
        Team.objects.filter(organization__is_ai_data_processing_approved=True)
        .exclude(id__in=config.skip_team_ids)
        .exclude(organization_id__in=_parse_organization_ids(config.deny_organization_ids))
    )
    # The teams with an enabled source come first, because they are far fewer than the approved teams.
    with_source: dict[int, uuid.UUID] = dict(
        teams.filter(id__in=team_ids_with_enabled_source()).values_list("id", "organization_id")
    )
    enrolled: dict[int, uuid.UUID]
    if config.enroll_all_approved:
        enrolled = dict(teams.values_list("id", "organization_id"))
    else:
        enrolled = dict(teams.filter(organization_id__in=listed).values_list("id", "organization_id")) if listed else {}
        enrolled |= {
            team_id: organization_id
            for team_id, organization_id in with_source.items()
            if _in_rollout(config, organization_id)
        }
    return Enrollment(
        team_ids=sorted(enrolled),
        organization_ids=sorted(set(enrolled.values())),
        qualifying_organization_ids=sorted(set(with_source.values())),
    )


def enrolled_team_ids(config: ActivitySummaryConfig) -> list[int]:
    return enrollment(config).team_ids


def is_team_enrolled_for_generation(config: ActivitySummaryConfig, team: Team) -> bool:
    """The tick may generate summaries for the team. The single-team form of `enrolled_team_ids`.

    The kill switch, `skip_team_ids`, AI data processing approval and the denylist win over every enrollment.
    The percentage rollout enrolls only the projects that have an enabled signal source.
    """
    if not config.enabled or team.id in config.skip_team_ids:
        return False
    if team.organization.is_ai_data_processing_approved is not True:
        return False
    if team.organization_id in _parse_organization_ids(config.deny_organization_ids):
        return False
    if config.enroll_all_approved or team.organization_id in _parse_organization_ids(config.organization_ids):
        return True
    if not _in_rollout(config, team.organization_id):
        return False
    from products.signals.backend.facade.api import (
        has_enabled_source,  # noqa: PLC0415 — the facade imports this module through `read`
    )

    return has_enabled_source(team.id)


def is_team_enrolled_for_read(config: ActivitySummaryConfig, team: Team) -> bool:
    """The API and MCP tools read summaries only for these teams. The percentage rollout and the denylist do not apply.

    A disabled config enrolls no team.
    """
    if not config.enabled or team.id in config.skip_team_ids:
        return False
    if team.organization.is_ai_data_processing_approved is not True:
        return False
    return config.enroll_all_approved or team.organization_id in _parse_organization_ids(config.organization_ids)


def _parse_organization_ids(organization_ids: tuple[str, ...]) -> set[uuid.UUID]:
    # A UUID parse, so an id in another UUID format still matches, and an invalid id matches nothing.
    parsed: set[uuid.UUID] = set()
    for organization_id in organization_ids:
        try:
            parsed.add(uuid.UUID(organization_id))
        except ValueError:
            continue
    return parsed


def _add(pending: _Pending, pair: ActivitySummaryPair, units: int, at: datetime.datetime) -> None:
    current = pending.get(pair)
    if current is None:
        pending[pair] = _NewRows(units=units, last_at=at)
    else:
        pending[pair] = _NewRows(units=current.units + units, last_at=max(current.last_at, at))


def _watermarks(team_ids: list[int]) -> dict[ActivitySummaryPair, datetime.datetime | None]:
    # nosemgrep: idor-lookup-without-team (system tick with no user input; filtered to the enrolled teams)
    rows = UserActivitySummary.all_teams.filter(team_id__in=team_ids).values_list(
        "team_id", "user_id", "input_watermark"
    )
    return {ActivitySummaryPair(team_id=team_id, user_id=user_id): watermark for team_id, user_id, watermark in rows}


def _after_watermark(
    rows: list[tuple[int, int, datetime.datetime]], team_ids: list[int], after_watermark: bool
) -> _Pending:
    watermarks = _watermarks(team_ids) if after_watermark else {}
    pending: _Pending = {}
    for team_id, user_id, at in rows:
        pair = ActivitySummaryPair(team_id=team_id, user_id=user_id)
        watermark = watermarks.get(pair)
        # A row the summary already read is no pending unit, but it still dates the pair's last activity.
        _add(pending, pair, 1 if watermark is None or at > watermark else 0, at)
    return pending


def _activity_rows(
    team_ids: list[int], start: datetime.datetime, end: datetime.datetime, after_watermark: bool
) -> _Pending:
    """Activity log rows per pair in [start, end), with the filters of `inputs.user_activity`."""
    rows = (
        ActivityLog.objects.filter(
            team_id__in=team_ids, user_id__isnull=False, created_at__gte=start, created_at__lt=end
        )
        .exclude(is_system=True)
        .exclude(was_impersonated=True)
        .exclude(scope__in=NOISY_ACTIVITY_SCOPES)
        .exclude(client__startswith=SCOUT_CLIENT_PREFIX)
    )
    unit_count = Count("id")
    if after_watermark:
        watermark = Subquery(
            # nosemgrep: idor-lookup-without-team (correlated on the outer row's team_id)
            UserActivitySummary.all_teams.filter(team_id=OuterRef("team_id"), user_id=OuterRef("user_id")).values(
                "input_watermark"
            )[:1]
        )
        # A row the summary already read is no pending unit, but it still dates the pair's last activity.
        unit_count = Count("id", filter=Q(created_at__gt=Coalesce(watermark, start)))
    return {
        ActivitySummaryPair(team_id=team_id, user_id=user_id): _NewRows(units=units, last_at=last_at)
        for team_id, user_id, units, last_at in rows.values("team_id", "user_id")
        .annotate(units=unit_count, last_at=Max("created_at"))
        .values_list("team_id", "user_id", "units", "last_at")
        if team_id is not None and user_id is not None
    }


def _task_rows(
    team_ids: list[int], start: datetime.datetime, end: datetime.datetime, after_watermark: bool
) -> _Pending:
    """Tasks per pair in [start, end), with the filters of `inputs.user_tasks`."""
    tasks = list_user_task_times(
        team_ids=team_ids,
        start=start,
        end=end,
        origin_products=TASK_ORIGIN_PRODUCTS,
        exclude_title_prefixes=(SANDBOX_PROMPT_TITLE_PREFIX,),
    )
    return _after_watermark(
        [(task.team_id, task.user_id, task.created_at) for task in tasks], team_ids, after_watermark
    )


def _view_rows(
    team_ids: list[int], start: datetime.datetime, end: datetime.datetime, after_watermark: bool
) -> _Pending:
    """Viewed objects and scenes per pair with a latest view in [start, end). Folders are not views."""
    if not team_ids:
        return {}
    rows = (
        FileSystemViewLog.objects.filter(team_id__in=team_ids, viewed_at__gte=start, viewed_at__lt=end)
        .exclude(type="folder")
        .values_list("team_id", "user_id", "viewed_at")
    )
    return _after_watermark(list(rows), team_ids, after_watermark)


_READERS: dict[str, _Reader] = {
    SOURCE_ACTIVITY_LOG: _activity_rows,
    SOURCE_TASKS: _task_rows,
    SOURCE_VIEWS: _view_rows,
}


def queue_sources(config: ActivitySummaryConfig) -> tuple[str, ...]:
    return (
        (SOURCE_ACTIVITY_LOG, SOURCE_TASKS, SOURCE_VIEWS) if config.count_views else (SOURCE_ACTIVITY_LOG, SOURCE_TASKS)
    )


_STORED_FIELDS = ("next_eligible_at", "generated_at", "prompt_version", "render_version")


def _state_fields(stored: dict[str, Any]) -> dict[str, Any]:
    """The queue state fields that copy a stored summary."""
    return {
        "due_at": stored["next_eligible_at"],
        "summarized_at": stored["generated_at"],
        "prompt_version": stored["prompt_version"],
        "render_version": stored["render_version"],
    }


def _create_missing_states(pairs: list[ActivitySummaryPair]) -> None:
    """Create a state row for each pair that has none, with the times and versions of its stored summary."""
    team_ids = {pair.team_id for pair in pairs}
    # nosemgrep: idor-lookup-without-team (system tick with no user input; filtered to the given pairs)
    stored = UserActivitySummary.all_teams.filter(
        team_id__in=team_ids, user_id__in={pair.user_id for pair in pairs}
    ).values("team_id", "user_id", *_STORED_FIELDS)
    copies = {ActivitySummaryPair(team_id=row["team_id"], user_id=row["user_id"]): _state_fields(row) for row in stored}
    UserActivitySummaryQueueState.all_teams.bulk_create(
        [
            UserActivitySummaryQueueState(team_id=pair.team_id, user_id=pair.user_id, **copies.get(pair, {}))
            for pair in pairs
        ],
        ignore_conflicts=True,
    )


def _add_pending(pending: _Pending) -> None:
    if not pending:
        return
    _create_missing_states(list(pending))
    for pair, rows in pending.items():
        UserActivitySummaryQueueState.objects.for_team(pair.team_id).filter(user_id=pair.user_id).update(
            pending_units=F("pending_units") + rows.units,
            # Postgres GREATEST skips a null.
            last_activity_at=Greatest("last_activity_at", rows.last_at),
        )


def feed_queue(config: ActivitySummaryConfig, now: datetime.datetime, team_ids: list[int] | None = None) -> int:
    """Move each source cursor forward and add the rows it passes to the queue state. Returns the pairs fed.

    A source with no cursor starts at the current end, so the backfill command seeds the earlier rows.
    `team_ids` defaults to the enrolled teams.
    """
    if team_ids is None:
        team_ids = enrolled_team_ids(config)
    end = now - FEED_LAG
    fed = 0
    for source in queue_sources(config):
        with transaction.atomic():
            cursor = UserActivitySummaryQueueCursor.objects.select_for_update().filter(source=source).first()
            if cursor is None:
                UserActivitySummaryQueueCursor.objects.get_or_create(source=source, defaults={"position": end})
                continue
            stop = min(end, cursor.position + MAX_FEED_STEP)
            if stop <= cursor.position:
                continue
            pending = _READERS[source](team_ids, cursor.position, stop, False)
            _add_pending(pending)
            cursor.position = stop
            cursor.save(update_fields=["position", "updated_at"])
            fed += len(pending)
    return fed


def seed_queue(config: ActivitySummaryConfig, team_ids: list[int], end: datetime.datetime) -> int:
    """Set the queue state of these teams from the rows in the window before `end`.

    Pending units count the rows after each pair's watermark. Last activity counts every row, so a
    stale summary with no new rows is still due.

    Pending units of these teams that the window does not hold go to zero. Returns the pairs seeded.
    """
    if not team_ids:
        return 0
    window_start = end - datetime.timedelta(days=config.limits.window_days)
    pending: _Pending = {}
    for source in queue_sources(config):
        for pair, rows in _READERS[source](team_ids, window_start, end, True).items():
            _add(pending, pair, rows.units, rows.last_at)
    with transaction.atomic():
        # nosemgrep: idor-lookup-without-team (operator backfill with no user input; filtered to the given teams)
        UserActivitySummaryQueueState.all_teams.filter(team_id__in=team_ids).update(pending_units=0)
        _add_pending(pending)
    return len(pending)


def move_cursors_to(config: ActivitySummaryConfig, end: datetime.datetime) -> None:
    """Move each cursor to `end` unless it is already past it, so the feed does not count seeded rows again."""
    for source in queue_sources(config):
        cursor, created = UserActivitySummaryQueueCursor.objects.get_or_create(
            source=source, defaults={"position": end}
        )
        if not created and cursor.position < end:
            cursor.position = end
            cursor.save(update_fields=["position", "updated_at"])


def sync_pair_state(team_id: int, user_id: int) -> None:
    """Copy the times and versions of the stored summary to the pair's queue state.

    Pending units go to zero when the summary's watermark includes the newest pending row.
    """
    stored = (
        UserActivitySummary.objects.for_team(team_id)
        .filter(user_id=user_id)
        .values(*_STORED_FIELDS, "input_watermark")
        .first()
    )
    if stored is None:
        return
    watermark = stored["input_watermark"]
    UserActivitySummaryQueueState.objects.for_team(team_id).filter(user_id=user_id).update(
        **_state_fields(stored),
        pending_units=F("pending_units")
        if watermark is None
        else Case(When(last_activity_at__lte=watermark, then=0), default=F("pending_units")),
    )


def _current(config: ActivitySummaryConfig) -> Q:
    """Queue states with no summary, or a summary that `logic.is_stale` does not mark stale."""
    current = Q(prompt_version=PROMPT_VERSION, render_version=RENDER_VERSION)
    if config.rebuild_before is not None:
        current &= Q(summarized_at__gte=config.rebuild_before)
    return Q(summarized_at__isnull=True) | current


def _hours_since(now: datetime.datetime, at: Coalesce) -> Combinable:
    age = Value(now, output_field=DateTimeField()) - at
    return Cast(Extract(age, "epoch"), FloatField()) / Value(3600.0)


def _states(config: ActivitySummaryConfig, now: datetime.datetime, team_ids: list[int]) -> QuerySet:
    """The queue states of these teams, with their tier, staleness and priority score.

    Staleness is the summary age over the tier's target interval. A pair with no summary counts its age
    from its first queued row. The score is log(1 + pending units) times staleness, plus a bonus for a
    pair with no summary, or a bonus plus staleness for a stale summary.
    """
    paying = Coalesce(F("team__organization__has_active_subscription"), Value(False))
    target_hours = Case(
        When(paying=True, then=Value(config.target_interval_days_paying * 24)),
        default=Value(config.target_interval_days_free * 24),
        output_field=FloatField(),
    )
    age_hours = _hours_since(now, Coalesce("summarized_at", "created_at"))
    stale = Case(When(_current(config), then=Value(False)), default=Value(True), output_field=BooleanField())
    cold_bonus = Case(
        When(summarized_at__isnull=True, then=Value(config.cold_start_bonus)),
        # A stale pair often has no pending units, so its staleness orders it among the other rebuilds.
        When(stale=True, then=Value(config.cold_start_bonus) + F("staleness")),
        default=Value(0.0),
        output_field=FloatField(),
    )
    return (
        # nosemgrep: idor-lookup-without-team (system tick with no user input; filtered to the enrolled teams)
        UserActivitySummaryQueueState.all_teams.filter(team_id__in=team_ids)
        .annotate(organization_id=F("team__organization_id"), paying=paying, stale=stale)
        .annotate(staleness=age_hours / target_hours)
        .annotate(score=Ln(F("pending_units") + 1) * F("staleness") + cold_bonus)
    )


def _due(states: QuerySet, config: ActivitySummaryConfig, now: datetime.datetime) -> QuerySet:
    return states.filter(
        Q(due_at__isnull=True) | Q(due_at__lte=now),
        Q(pending_units__gte=max(1, config.min_units)) | Q(stale=True),
        last_activity_at__gte=now - datetime.timedelta(days=config.limits.window_days),
    )


def _cap_rebuilds(due: QuerySet, max_rebuilds: int) -> QuerySet:
    """The due pairs with at most `max_rebuilds` stale pairs, paying pairs and the highest scores first."""
    rebuild_ids = list(
        due.filter(stale=True)
        .order_by("-paying", F("score").desc(), "team_id", "user_id")
        .values_list("id", flat=True)[:max_rebuilds]
    )
    return due.filter(Q(stale=False) | Q(id__in=rebuild_ids))


def _fill_pass(due: QuerySet, limit: int, max_org_share: float) -> list[UserActivitySummaryQueueState]:
    """The highest scores first, with at most `max_org_share` of `limit` from one organization."""
    if limit <= 0:
        return []
    order = (F("score").desc(), "team_id", "user_id")
    return list(
        due.annotate(org_rank=Window(RowNumber(), partition_by=[F("organization_id")], order_by=order))
        .filter(org_rank__lte=max(1, int(max_org_share * limit)))
        .order_by(*order)
        .only("id", "team_id", "user_id")[:limit]
    )


def _tier_stats(
    states: QuerySet, due: QuerySet, config: ActivitySummaryConfig, now: datetime.datetime
) -> list[ActivitySummaryTierStats]:
    window_start = now - datetime.timedelta(days=config.limits.window_days)
    waiting = {
        row["paying"]: row
        for row in due.values("paying").annotate(
            pairs=Count("id"),
            oldest=Max(_hours_since(now, Coalesce("due_at", "created_at"))),
        )
    }
    activity = {
        row["paying"]: row
        for row in states.filter(last_activity_at__gte=window_start)
        .values("paying")
        .annotate(
            active=Count("id"),
            fresh=Count("id", filter=Q(summarized_at__isnull=False, staleness__lt=_FRESH_STALENESS)),
        )
    }
    stats = []
    for tier, paying in ((TIER_PAYING, True), (TIER_FREE, False)):
        due_row = waiting.get(paying)
        activity_row = activity.get(paying)
        stats.append(
            ActivitySummaryTierStats(
                tier=tier,
                due_pairs=due_row["pairs"] if due_row else 0,
                oldest_due_hours=max(0.0, due_row["oldest"]) if due_row else None,
                fresh_share=activity_row["fresh"] / activity_row["active"] if activity_row else None,
            )
        )
    return stats


def select_pairs(
    config: ActivitySummaryConfig, now: datetime.datetime, limit: int, team_ids: list[int] | None = None
) -> PairSelection:
    """The due pairs of the enrolled teams, highest priority first, cut to `limit`.

    A pair is due when it has a row in the last `window_days` and its due time is empty or past. A pair
    with a current summary also needs at least `min_units` pending units. One unit never comes from less
    than one row, so a pair with fewer rows would only skip. A pair with a stale summary needs no pending
    units, because its update reads the full window, and it ranks with the pairs with no summary.
    Stale pairs take at most `rebuild_budget_share` of `limit`, paying pairs first, so a version change
    does not stop the other updates. The first pass ranks the paying pairs and the free pairs with at
    least `max_overdue_factor` staleness, for `paying_budget_share` of `limit`. The second pass ranks the
    other free pairs for the budget that is left. `team_ids` defaults to the enrolled teams.
    """
    if team_ids is None:
        team_ids = enrolled_team_ids(config)
    if not team_ids:
        return PairSelection(pairs=[], due_pairs=0, tiers=[])
    states = _states(config, now, team_ids)
    due = _due(states, config, now)
    tiers = _tier_stats(states, due, config, now)
    due = _cap_rebuilds(due, math.ceil(limit * config.rebuild_budget_share))
    first = _fill_pass(
        due.filter(Q(paying=True) | Q(staleness__gte=config.max_overdue_factor)),
        int(limit * config.paying_budget_share),
        config.max_org_share,
    )
    second = _fill_pass(
        due.filter(paying=False).exclude(id__in=[state.id for state in first]),
        limit - len(first),
        config.max_org_share,
    )
    return PairSelection(
        pairs=[ActivitySummaryPair(team_id=state.team_id, user_id=state.user_id) for state in first + second],
        due_pairs=sum(tier.due_pairs for tier in tiers),
        tiers=tiers,
    )
