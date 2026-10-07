import json
import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from django.utils import timezone

from posthog.hogql import ast
from posthog.hogql.constants import MAX_SELECT_RETURNED_ROWS, HogQLGlobalSettings
from posthog.hogql.helpers.timestamp_visitor import parse_zoned_datetime_string
from posthog.hogql.parser import parse_select
from posthog.hogql.property import action_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.dataclasses import frozen
from posthog.errors import CHQueryErrorTooManyBytes
from posthog.exceptions import ClickHouseEstimatedQueryExecutionTimeTooLong, ClickHouseQueryTimeOut
from posthog.models.team.team import Team
from posthog.models.user import User

from products.actions.backend.models.action import Action
from products.web_analytics.backend.achievements.definitions import STREAK_ARM_WEEKLY
from products.web_analytics.backend.achievements.query_concurrency import achievement_query_scope
from products.web_analytics.backend.hogql_queries.web_lazy_precompute_common import test_account_filter_expr
from products.web_analytics.backend.models import WebAnalyticsInteraction, WebAnalyticsVisit


@dataclass(frozen=True)
class EvalContext:
    team: Team
    user: User | None
    today: date
    arm: str | None


@frozen
class PriorProgress:
    value: int
    last_computed_at: datetime | None
    checkpoint: dict[str, object]


@frozen
class TrackEvaluation:
    value: int
    checkpoint: dict[str, object] | None = None
    complete: bool = True


def _week_monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _consecutive_days_with_grace(visit_dates: set[date], today: date) -> int:
    """Consecutive visited days ending at today, allowing a single 1-day grace gap. Today not yet
    visited keeps the streak alive (the day isn't over); a 2-day gap breaks it."""
    streak = 0
    grace_used = False
    cursor = today if today in visit_dates else today - timedelta(days=1)
    while True:
        if cursor in visit_dates:
            streak += 1
            cursor -= timedelta(days=1)
        elif not grace_used:
            grace_used = True
            cursor -= timedelta(days=1)
        else:
            break
    return streak


def _consecutive_weeks(visit_dates: set[date], today: date) -> int:
    visited_mondays = {_week_monday(day) for day in visit_dates}
    streak = 0
    cursor = _week_monday(today)
    if cursor not in visited_mondays:
        cursor -= timedelta(days=7)
    while cursor in visited_mondays:
        streak += 1
        cursor -= timedelta(days=7)
    return streak


def evaluate_streak(ctx: EvalContext) -> int:
    if ctx.user is None:
        return 0
    window_start = ctx.today - timedelta(days=90)
    visit_dates = set(
        WebAnalyticsVisit.objects.for_team(ctx.team.id)
        .filter(user_id=ctx.user.id, visit_date__gte=window_start)
        .values_list("visit_date", flat=True)
    )
    if not visit_dates:
        return 0
    if ctx.arm == STREAK_ARM_WEEKLY:
        return _consecutive_weeks(visit_dates, ctx.today)
    return _consecutive_days_with_grace(visit_dates, ctx.today)


def evaluate_loyal_days(ctx: EvalContext) -> int:
    if ctx.user is None:
        return 0
    return (
        WebAnalyticsVisit.objects.for_team(ctx.team.id)
        .filter(user_id=ctx.user.id)
        .values("visit_date")
        .distinct()
        .count()
    )


def _project_environment_teams(team: Team) -> list[Team]:
    """Every environment team of the project. Web traffic is stored per-environment (team_id), so a
    team-scoped total must aggregate across all environments, not just the canonical team — otherwise
    a project whose traffic lives in a child environment never progresses. N environments → N query
    runner executions; projects rarely have more than one or two."""
    return list(Team.objects.filter(project_id=team.project_id))


def _test_account_filter_expr(team: Team) -> ast.Expr:
    filters = team.test_account_filters if isinstance(team.test_account_filters, list) else []
    return test_account_filter_expr(test_account_filters=filters, team=team)


INGESTION_LAG = timedelta(hours=1)
LATE_ARRIVAL_LOOKBACK = timedelta(days=3)


def _ingestion_window_expr(
    since: datetime | None,
    until: datetime,
    earliest_timestamp: datetime | None,
    latest_timestamp: datetime | None = None,
    latest_inclusive: bool = False,
) -> ast.Expr:
    exprs: list[ast.Expr] = [
        ast.CompareOperation(
            op=ast.CompareOperationOp.Lt, left=ast.Field(chain=["created_at"]), right=ast.Constant(value=until)
        )
    ]
    if since is not None:
        exprs.append(
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq, left=ast.Field(chain=["created_at"]), right=ast.Constant(value=since)
            )
        )
    if earliest_timestamp is not None:
        exprs.append(
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq,
                left=ast.Field(chain=["timestamp"]),
                right=ast.Constant(value=earliest_timestamp),
            )
        )
    if latest_timestamp is not None:
        exprs.append(
            ast.CompareOperation(
                op=ast.CompareOperationOp.LtEq if latest_inclusive else ast.CompareOperationOp.Lt,
                left=ast.Field(chain=["timestamp"]),
                right=ast.Constant(value=latest_timestamp),
            )
        )
    return ast.And(exprs=exprs)


def evaluate_cumulative_pageviews(ctx: EvalContext, prior: PriorProgress) -> TrackEvaluation:
    until = timezone.now() - INGESTION_LAG
    since = parse_zoned_datetime_string(prior.checkpoint.get("counted_through")) or prior.last_computed_at
    earliest_timestamp = since - LATE_ARRIVAL_LOOKBACK if since is not None else None
    total = prior.value if since is not None else 0
    with achievement_query_scope(ctx.team.id):
        for team in _project_environment_teams(ctx.team):
            query = parse_select(
                "SELECT count() FROM events WHERE and(event IN ('$pageview', '$screen'), {window}, {test})",
                placeholders={
                    "window": _ingestion_window_expr(since, until, earliest_timestamp),
                    "test": _test_account_filter_expr(team),
                },
            )
            response = execute_hogql_query(query=query, team=team, query_type="web_achievements_pageviews")
            if response.results:
                total += int(response.results[0][0] or 0)
    return TrackEvaluation(value=total, checkpoint={"counted_through": until.isoformat()})


CONVERSIONS_LOOKBACK_DAYS = 90
CONVERSIONS_BOOTSTRAP_CHUNK_DAYS = 7
CONVERSIONS_MAX_TIMESTAMP = datetime(2299, 12, 31, 23, 59, 59, 999999, tzinfo=UTC)
CONVERSIONS_FUTURE_CHUNK_MAX_HOURS = 24 * 365 * 50
CONVERSIONS_SCAN_LIMITS = (
    CHQueryErrorTooManyBytes,
    ClickHouseQueryTimeOut,
    ClickHouseEstimatedQueryExecutionTimeTooLong,
)


@frozen
class ConversionBootstrap:
    next_start: datetime
    end: datetime
    created_until: datetime
    phase: str = "initial"
    created_since: datetime | None = None
    chunk_hours: int = CONVERSIONS_BOOTSTRAP_CHUNK_DAYS * 24


def _action_event_filter_expr(actions: list[Action]) -> ast.Expr:
    event_names: set[str] = set()
    for action in actions:
        step_events = action.get_step_events()
        if not step_events or any(event is None for event in step_events):
            return ast.Constant(value=True)
        event_names.update(event for event in step_events if event is not None)
    return ast.CompareOperation(
        op=ast.CompareOperationOp.In,
        left=ast.Field(chain=["event"]),
        right=ast.Tuple(exprs=[ast.Constant(value=name) for name in sorted(event_names)]),
    )


def _action_fingerprints(actions: list[Action]) -> list[list[object]]:
    return [
        [action.id, hashlib.sha256(json.dumps(action.steps_json or [], sort_keys=True).encode()).hexdigest()[:16]]
        for action in actions
    ]


def _daily_buckets(checkpoint: dict[str, object], fingerprints: list[list[object]]) -> dict[str, list[int]] | None:
    daily = checkpoint.get("daily")
    if checkpoint.get("actions") != fingerprints or not isinstance(daily, dict):
        return None
    try:
        return {
            str(day): [int(count) for count in counts]
            for day, counts in daily.items()
            if isinstance(counts, list) and len(counts) == len(fingerprints)
        }
    except (TypeError, ValueError):
        return None


def _conversion_bootstrap_state(checkpoint: dict[str, object]) -> ConversionBootstrap | None:
    bootstrap = checkpoint.get("bootstrap")
    if not isinstance(bootstrap, dict):
        return None
    next_start = parse_zoned_datetime_string(bootstrap.get("next_start"))
    end = parse_zoned_datetime_string(bootstrap.get("end"))
    created_until = parse_zoned_datetime_string(bootstrap.get("created_until"))
    phase = bootstrap.get("phase", "initial")
    created_since = parse_zoned_datetime_string(bootstrap.get("created_since"))
    chunk_hours = bootstrap.get("chunk_hours", CONVERSIONS_BOOTSTRAP_CHUNK_DAYS * 24)
    if (
        next_start is None
        or end is None
        or created_until is None
        or phase not in ("initial", "initial_future", "catchup", "catchup_future", "tail")
        or (phase in ("initial_future", "catchup_future") and not end <= next_start < CONVERSIONS_MAX_TIMESTAMP)
        or (phase not in ("initial_future", "catchup_future") and next_start >= end)
        or (phase in ("catchup", "catchup_future", "tail") and created_since is None)
        or not isinstance(chunk_hours, int)
        or not 1
        <= chunk_hours
        <= (
            CONVERSIONS_FUTURE_CHUNK_MAX_HOURS
            if phase in ("initial_future", "catchup_future")
            else CONVERSIONS_BOOTSTRAP_CHUNK_DAYS * 24
        )
    ):
        return None
    return ConversionBootstrap(
        next_start=next_start,
        end=end,
        created_until=created_until,
        phase=phase,
        created_since=created_since,
        chunk_hours=chunk_hours,
    )


def _add_conversion_counts(
    ctx: EvalContext,
    actions: list[Action],
    daily: dict[str, list[int]],
    since: datetime | None,
    until: datetime,
    earliest_timestamp: datetime,
    latest_timestamp: datetime | None = None,
    latest_inclusive: bool = False,
) -> bool:
    chunk_daily: dict[str, list[int]] = {}
    for team in _project_environment_teams(ctx.team):
        query = parse_select(
            "SELECT toDate(toTimeZone(timestamp, 'UTC')) AS day FROM events WHERE and({window}, {events}, {test}) GROUP BY day",
            placeholders={
                "window": _ingestion_window_expr(since, until, earliest_timestamp, latest_timestamp, latest_inclusive),
                "events": _action_event_filter_expr(actions),
                "test": _test_account_filter_expr(team),
            },
        )
        if not isinstance(query, ast.SelectQuery):
            raise TypeError(f"evaluate_conversions: expected SelectQuery, got {type(query)}")
        query.select = [
            query.select[0],
            *(ast.Call(name="countIf", args=[action_to_expr(action)]) for action in actions),
        ]
        # Future slices can group more than the default 100 days; the largest bounded slice is 50 years.
        query.limit = ast.Constant(value=MAX_SELECT_RETURNED_ROWS)
        response = execute_hogql_query(
            query=query,
            team=team,
            query_type="web_achievements_conversions",
            settings=HogQLGlobalSettings(timeout_overflow_mode="throw", read_overflow_mode="throw"),
        )
        for row in response.results or []:
            day_counts = chunk_daily.setdefault(row[0].isoformat(), [0] * len(actions))
            for index, value in enumerate(row[1:]):
                day_counts[index] += int(value or 0)
    for day, counts in chunk_daily.items():
        day_counts = daily.setdefault(day, [0] * len(actions))
        for index, value in enumerate(counts):
            day_counts[index] += value
    return bool(chunk_daily)


def _advance_conversion_future(
    ctx: EvalContext,
    actions: list[Action],
    daily: dict[str, list[int]],
    bootstrap: ConversionBootstrap,
    window_start: datetime,
    until: datetime,
) -> ConversionBootstrap | None:
    next_start = bootstrap.next_start
    chunk_hours = bootstrap.chunk_hours
    # Empty timestamp ranges are cheap to skip with the event timestamp index. Grow those
    # ranges so a scan with no future-dated events does not take hundreds of daily sweeps.
    for _ in range(20):
        chunk_end = min(next_start + timedelta(hours=chunk_hours), CONVERSIONS_MAX_TIMESTAMP)
        try:
            has_rows = _add_conversion_counts(
                ctx,
                actions,
                daily,
                bootstrap.created_since,
                bootstrap.created_until,
                next_start,
                chunk_end,
                latest_inclusive=chunk_end == CONVERSIONS_MAX_TIMESTAMP,
            )
        except CONVERSIONS_SCAN_LIMITS:
            if chunk_hours <= 1:
                raise
            return ConversionBootstrap(
                next_start=next_start,
                end=bootstrap.end,
                created_since=bootstrap.created_since,
                created_until=bootstrap.created_until,
                phase=bootstrap.phase,
                chunk_hours=max(1, chunk_hours // 2),
            )
        if chunk_end == CONVERSIONS_MAX_TIMESTAMP:
            if bootstrap.phase == "initial_future" and bootstrap.created_until < until:
                return ConversionBootstrap(
                    next_start=window_start,
                    end=bootstrap.end,
                    created_since=bootstrap.created_until,
                    created_until=bootstrap.created_until,
                    phase="tail",
                )
            return None
        next_start = chunk_end
        if has_rows:
            break
        chunk_hours = min(chunk_hours * 2, CONVERSIONS_FUTURE_CHUNK_MAX_HOURS)
    return ConversionBootstrap(
        next_start=next_start,
        end=bootstrap.end,
        created_since=bootstrap.created_since,
        created_until=bootstrap.created_until,
        phase=bootstrap.phase,
        chunk_hours=chunk_hours,
    )


def _advance_conversion_bootstrap(
    ctx: EvalContext,
    actions: list[Action],
    daily: dict[str, list[int]],
    bootstrap: ConversionBootstrap,
    window_start: datetime,
    until: datetime,
) -> ConversionBootstrap | None:
    if bootstrap.phase == "tail":
        try:
            _add_conversion_counts(ctx, actions, daily, bootstrap.created_since, until, window_start)
        except CONVERSIONS_SCAN_LIMITS:
            return ConversionBootstrap(
                next_start=window_start,
                end=bootstrap.end,
                created_since=bootstrap.created_since,
                created_until=until,
                phase="catchup",
            )
        return None

    if bootstrap.phase in ("initial_future", "catchup_future"):
        return _advance_conversion_future(ctx, actions, daily, bootstrap, window_start, until)

    next_start = max(bootstrap.next_start, window_start)
    end = bootstrap.end
    if bootstrap.phase == "catchup":
        # Events ingested after the first scan can have timestamps on later days.
        # Freeze a finite timestamp horizon for this catch-up interval.
        end = max(
            end,
            datetime.combine(bootstrap.created_until.astimezone(UTC).date() + timedelta(days=1), time.min, tzinfo=UTC),
        )
    if next_start >= end:
        daily.clear()
        bootstrap = ConversionBootstrap(
            next_start=window_start,
            end=window_start + timedelta(days=CONVERSIONS_LOOKBACK_DAYS),
            created_until=until,
        )
        next_start = window_start
        end = bootstrap.end

    chunk_hours = bootstrap.chunk_hours
    chunk_end = min(next_start + timedelta(hours=chunk_hours), end)
    try:
        _add_conversion_counts(
            ctx,
            actions,
            daily,
            bootstrap.created_since,
            bootstrap.created_until,
            next_start,
            chunk_end,
        )
    except CONVERSIONS_SCAN_LIMITS:
        if chunk_hours <= 1:
            raise
        return ConversionBootstrap(
            next_start=next_start,
            end=end,
            created_until=bootstrap.created_until,
            phase=bootstrap.phase,
            created_since=bootstrap.created_since,
            chunk_hours=max(1, chunk_hours // 2),
        )

    if chunk_end < end:
        return ConversionBootstrap(
            next_start=chunk_end,
            end=end,
            created_until=bootstrap.created_until,
            phase=bootstrap.phase,
            created_since=bootstrap.created_since,
            chunk_hours=chunk_hours,
        )

    if bootstrap.phase == "catchup":
        if bootstrap.created_since is None or bootstrap.created_since >= bootstrap.created_until:
            return None
        return ConversionBootstrap(
            next_start=end,
            end=end,
            created_since=bootstrap.created_since,
            created_until=bootstrap.created_until,
            phase="catchup_future",
            chunk_hours=CONVERSIONS_BOOTSTRAP_CHUNK_DAYS * 24,
        )
    if bootstrap.phase == "initial":
        return ConversionBootstrap(
            next_start=end,
            end=end,
            created_until=bootstrap.created_until,
            phase="initial_future",
        )
    if bootstrap.created_until < until:
        return ConversionBootstrap(
            next_start=window_start,
            end=bootstrap.end,
            created_since=bootstrap.created_until,
            created_until=bootstrap.created_until,
            phase="tail",
        )
    return None


def evaluate_conversions(ctx: EvalContext, prior: PriorProgress) -> TrackEvaluation:
    actions = list(
        Action.objects.filter(team__project_id=ctx.team.project_id, deleted=False)
        .select_related("team")
        .order_by("pinned_at", "-last_calculated_at")[:5]
    )
    if not actions:
        return TrackEvaluation(value=0, checkpoint={})

    until = timezone.now() - INGESTION_LAG
    window_start = datetime.combine(
        (until - timedelta(days=CONVERSIONS_LOOKBACK_DAYS - 1)).astimezone(UTC).date(), time.min, tzinfo=UTC
    )
    fingerprints = _action_fingerprints(actions)
    daily = _daily_buckets(prior.checkpoint, fingerprints)
    since = parse_zoned_datetime_string(prior.checkpoint.get("counted_through"))
    bootstrap = _conversion_bootstrap_state(prior.checkpoint) if daily is not None and since is None else None
    if daily is None:
        daily = {}
        since = None
    if since is None and bootstrap is None:
        daily = {}

    started_bootstrap = False
    completed_through = until
    with achievement_query_scope(ctx.team.id):
        if bootstrap is None:
            earliest_timestamp = max(window_start, since - LATE_ARRIVAL_LOOKBACK) if since is not None else window_start
            try:
                _add_conversion_counts(ctx, actions, daily, since, until, earliest_timestamp)
            except CONVERSIONS_SCAN_LIMITS:
                if since is not None:
                    raise
                daily = {}
                bootstrap = ConversionBootstrap(
                    next_start=window_start,
                    end=window_start + timedelta(days=CONVERSIONS_LOOKBACK_DAYS),
                    created_until=until,
                )
                started_bootstrap = True
        if bootstrap is not None and not started_bootstrap:
            if bootstrap.phase in ("catchup", "catchup_future"):
                completed_through = bootstrap.created_until
            bootstrap = _advance_conversion_bootstrap(ctx, actions, daily, bootstrap, window_start, until)

    oldest_kept_day = window_start.date().isoformat()
    daily = {day: counts for day, counts in daily.items() if day >= oldest_kept_day and any(counts)}
    per_action_totals = [sum(counts[index] for counts in daily.values()) for index in range(len(actions))]
    checkpoint: dict[str, object] = {"actions": fingerprints, "daily": daily}
    if bootstrap is not None:
        checkpoint["bootstrap"] = {
            "next_start": bootstrap.next_start.isoformat(),
            "end": bootstrap.end.isoformat(),
            "created_until": bootstrap.created_until.isoformat(),
            "phase": bootstrap.phase,
            "created_since": bootstrap.created_since.isoformat() if bootstrap.created_since is not None else None,
            "chunk_hours": bootstrap.chunk_hours,
        }
    else:
        checkpoint["counted_through"] = completed_through.isoformat()
    return TrackEvaluation(
        value=max(len(actions), max(per_action_totals, default=0)),
        checkpoint=checkpoint,
        complete="bootstrap" not in checkpoint,
    )


def _interaction_count(ctx: EvalContext, kind: str) -> int:
    if ctx.user is None:
        return 0
    row = WebAnalyticsInteraction.objects.for_team(ctx.team.id).filter(user_id=ctx.user.id, kind=kind).first()
    return row.count if row else 0


def evaluate_data_events(ctx: EvalContext) -> int:
    return _interaction_count(ctx, WebAnalyticsInteraction.DATA)


def evaluate_recordings_opened(ctx: EvalContext) -> int:
    return _interaction_count(ctx, WebAnalyticsInteraction.RECORDING)


EVALUATORS: dict[str, Callable[[EvalContext], int]] = {
    "streak": evaluate_streak,
    "loyal_days": evaluate_loyal_days,
    "data_events": evaluate_data_events,
    "recordings_opened": evaluate_recordings_opened,
}

INCREMENTAL_EVALUATORS: dict[str, Callable[[EvalContext, PriorProgress], TrackEvaluation]] = {
    "cumulative_pageviews": evaluate_cumulative_pageviews,
    "conversions": evaluate_conversions,
}
