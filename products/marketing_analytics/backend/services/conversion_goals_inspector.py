"""Inspect configured conversion goals: shape, last-30d counts, integrated split,
and per-goal event breakdowns. Read-only.

Unlike the dashboard's attribution math (`ConversionGoalProcessor`), this uses a
fixed 30d window (ignoring the team's `attribution_window_days`) and, for
ActionsNode goals, matches only the action's step events — property/URL filters
are not applied. Both deviations are surfaced via `ConversionGoalSummary.is_approximate`.
"""

import re
import asyncio
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal, cast

from django.utils import timezone

import structlog

from posthog.schema import DateRange

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.action.action import Action, ActionStepJSON
from posthog.models.team.team import Team
from posthog.sync import database_sync_to_async

from products.marketing_analytics.backend.services.native_integrations import (
    NativeIntegration,
    build_combined_alias_map,
    lookup_in,
)

logger = structlog.get_logger(__name__)

# Sanity-check that DataWarehouseNode `table_name` and `timestamp_field` look
# like identifiers before passing them into the HogQL AST. The AST builder
# itself never interpolates these as raw SQL (we use `ast.Field(chain=...)`
# and `ast.Constant`), so this isn't security — it's a clear, early "your
# config is malformed" rejection vs. a downstream HogQL parse error.
_DW_TABLE_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")
_DW_COLUMN_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

GoalKind = Literal["EventsNode", "ActionsNode", "DataWarehouseNode"]
DEFAULT_LOOKBACK_DAYS = 30
EXPLAIN_SAMPLE_LIMIT = 10
EXPLAIN_BREAKDOWN_LIMIT = 20
# Max events scanned by `explain_conversion_goal`. When a goal exceeds this in
# the period, total_count and the breakdowns are a most-recent sample, not the
# full count — the response carries a note saying so.
EXPLAIN_EVENT_SCAN_LIMIT = 5000


@dataclass
class ConversionGoalSummary:
    id: str
    name: str
    kind: GoalKind
    target_label: str
    last_30d_count: int
    integrated_count: int | None
    # Non-integrated events split by ROOT CAUSE — these have OPPOSITE fixes:
    # - `events_without_utm_source`: event has NO utm_source at all. Fix is to
    #   tag UTMs on the conversion page (or use server-side persistence). NOT
    #   solvable by adding custom_source_mappings.
    # - `events_with_unmatched_utm_source`: event has utm_source set but it
    #   doesn't match any known integration alias. Fix is custom_source_mappings
    #   (or fix UTM tagging upstream). Solvable from settings.
    events_without_utm_source: int | None
    events_with_unmatched_utm_source: int | None
    non_integrated_count: int | None
    integrated_pct: float | None
    is_misconfigured: bool
    misconfig_reason: str | None
    # True when the count is a fast-path approximation that may differ from the
    # dashboard's attribution-windowed number. Set for ActionsNode goals whose
    # action has property/URL step filters (we only match step events here),
    # and always when `attribution_window_days != DEFAULT_LOOKBACK_DAYS`.
    is_approximate: bool = False
    approximation_reason: str | None = None


@dataclass
class ConversionGoalsListResponse:
    goals: list[ConversionGoalSummary] = field(default_factory=list)
    attribution_window_days: int = 0
    attribution_mode: str = "last_touch"
    has_misconfigured: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GoalEventSample:
    event_uuid: str
    timestamp: datetime
    distinct_id: str
    utm_source: str | None
    utm_campaign: str | None
    matched_integration: str | None


@dataclass
class GoalExplanation:
    goal_id: str
    goal_name: str
    kind: GoalKind
    period: DateRange
    total_count: int
    integrated_count: int | None
    # See `ConversionGoalSummary` for why we split non-integrated by root cause
    # — these two have OPPOSITE fixes.
    events_without_utm_source: int | None
    events_with_unmatched_utm_source: int | None
    non_integrated_count: int | None
    by_event: list[tuple[str, int]]
    by_utm_source: list[tuple[str, int]]
    by_matched_integration: list[tuple[str, int]]
    samples: list[GoalEventSample]
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


async def list_conversion_goals(team: Team) -> ConversionGoalsListResponse:
    """Return one summary entry per configured conversion goal."""
    goals_raw, attribution_window, attribution_mode = await _read_team_goal_config(team)
    alias_map = await _build_team_alias_map(team)

    summaries = await asyncio.gather(
        *(_summarize_goal(team, goal, alias_map, attribution_window) for goal in goals_raw)
    )

    return ConversionGoalsListResponse(
        goals=list(summaries),
        attribution_window_days=attribution_window,
        attribution_mode=attribution_mode,
        has_misconfigured=any(s.is_misconfigured for s in summaries),
    )


async def explain_conversion_goal(
    team: Team,
    goal_id: str,
    period: DateRange | None = None,
) -> GoalExplanation:
    """Resolve a goal by id and break down its events by name, utm_source,
    and matched integration."""
    goals_raw, _, _ = await _read_team_goal_config(team)
    goal = next((g for g in goals_raw if str(g.get("conversion_goal_id") or g.get("id") or "") == goal_id), None)
    if goal is None:
        raise ValueError(f"Conversion goal '{goal_id}' not found in team config")
    alias_map = await _build_team_alias_map(team)

    kind = cast(GoalKind, goal.get("kind", "EventsNode"))
    name = goal.get("conversion_goal_name") or goal.get("name") or goal_id
    resolved_period = period or _default_period()

    if kind == "DataWarehouseNode":
        return GoalExplanation(
            goal_id=goal_id,
            goal_name=name,
            kind=kind,
            period=resolved_period,
            total_count=0,
            integrated_count=None,
            events_without_utm_source=None,
            events_with_unmatched_utm_source=None,
            non_integrated_count=None,
            by_event=[],
            by_utm_source=[],
            by_matched_integration=[],
            samples=[],
            notes=[
                "DataWarehouseNode goals are computed against an external table; per-event "
                "breakdown is not available in this service. Use the marketing analytics "
                "dashboard or query the underlying table directly."
            ],
        )

    rows = await _query_goal_events(team, goal, resolved_period)
    notes: list[str] = [
        "This is a flat breakdown of each conversion event by its own utm_source/utm_campaign. "
        "It is NOT the dashboard's attribution calculation: first-touch, last-touch and multi-touch "
        "(linear/time-decay/position-based) models distribute credit across touchpoints differently."
    ]
    if len(rows) >= EXPLAIN_EVENT_SCAN_LIMIT:
        notes.append(
            f"Only the {EXPLAIN_EVENT_SCAN_LIMIT} most recent events in the period were scanned. "
            "total_count and the breakdowns below are a recent-events sample, not the full count."
        )

    by_event: dict[str, int] = {}
    by_utm: dict[str, int] = {}
    by_integration: dict[str, int] = {}
    samples: list[GoalEventSample] = []
    integrated_count = 0
    without_utm_count = 0
    unmatched_with_utm_count = 0
    total_count = 0

    for row in rows:
        event_uuid, ts, distinct_id, event_name, utm_source, utm_campaign = row
        total_count += 1
        by_event[event_name] = by_event.get(event_name, 0) + 1

        utm_source_str = (utm_source or "").strip().lower()
        if utm_source_str:
            by_utm[utm_source_str] = by_utm.get(utm_source_str, 0) + 1

        matched = lookup_in(utm_source_str, alias_map) if utm_source_str else None
        if matched is not None:
            by_integration[matched] = by_integration.get(matched, 0) + 1
            integrated_count += 1
        elif utm_source_str:
            unmatched_with_utm_count += 1
        else:
            without_utm_count += 1

        if len(samples) < EXPLAIN_SAMPLE_LIMIT:
            samples.append(
                GoalEventSample(
                    event_uuid=str(event_uuid),
                    timestamp=ts,
                    distinct_id=str(distinct_id or ""),
                    utm_source=utm_source_str or None,
                    utm_campaign=(utm_campaign or "").strip() or None,
                    matched_integration=matched,
                )
            )

    return GoalExplanation(
        goal_id=goal_id,
        goal_name=name,
        kind=kind,
        period=resolved_period,
        total_count=total_count,
        integrated_count=integrated_count,
        events_without_utm_source=without_utm_count,
        events_with_unmatched_utm_source=unmatched_with_utm_count,
        non_integrated_count=without_utm_count + unmatched_with_utm_count,
        by_event=sorted(by_event.items(), key=lambda kv: kv[1], reverse=True)[:EXPLAIN_BREAKDOWN_LIMIT],
        by_utm_source=sorted(by_utm.items(), key=lambda kv: kv[1], reverse=True)[:EXPLAIN_BREAKDOWN_LIMIT],
        by_matched_integration=sorted(by_integration.items(), key=lambda kv: kv[1], reverse=True),
        samples=samples,
        notes=notes,
    )


@database_sync_to_async
def _read_team_goal_config(team: Team) -> tuple[list[dict], int, str]:
    """Return (raw_goals_list, attribution_window_days, attribution_mode)."""
    config = getattr(team, "marketing_analytics_config", None)
    if config is None:
        return [], 90, "last_touch"
    goals = config.conversion_goals or []
    return list(goals), int(config.attribution_window_days or 90), str(config.attribution_mode or "last_touch")


@database_sync_to_async
def _build_team_alias_map(team: Team) -> dict[str, NativeIntegration]:
    """Combine canonical alias table with the team's `custom_source_mappings` so
    user-defined source overrides (e.g. `meta2 -> MetaAds`) count as integrated."""
    config = getattr(team, "marketing_analytics_config", None)
    custom = config.custom_source_mappings if config is not None else {}
    return build_combined_alias_map(custom)


async def _summarize_goal(
    team: Team,
    goal: dict,
    alias_map: dict[str, NativeIntegration],
    attribution_window_days: int,
) -> ConversionGoalSummary:
    goal_id = str(goal.get("conversion_goal_id") or goal.get("id") or "")
    name = goal.get("conversion_goal_name") or goal.get("name") or goal_id
    # `kind_raw: str` keeps the "unknown kind" fallback reachable — a GoalKind
    # would let mypy treat the branches below as exhaustive.
    kind_raw: str = goal.get("kind") or "EventsNode"
    kind = cast(GoalKind, kind_raw)

    # Always-on caveat: this is a 30d non-attribution-windowed count, used for
    # quick "what is this number?" answers. Mark approximate when the team's
    # attribution_window_days differs from our window so the LLM doesn't claim
    # the dashboard would agree.
    base_approximate = attribution_window_days != DEFAULT_LOOKBACK_DAYS
    base_reason = (
        f"fast {DEFAULT_LOOKBACK_DAYS}d count without attribution windowing; "
        f"team is configured for a {attribution_window_days}d attribution window — "
        "the dashboard's number may differ"
        if base_approximate
        else None
    )

    if kind_raw == "EventsNode":
        target_label = goal.get("event") or "(all events)"
        total, integrated, without_utm, unmatched_with_utm = await _count_event_goal(team, goal, alias_map)
        return _summary_with_split(
            goal_id,
            name,
            kind,
            target_label,
            total,
            integrated,
            without_utm,
            unmatched_with_utm,
            is_approximate=base_approximate,
            approximation_reason=base_reason,
        )

    if kind_raw == "ActionsNode":
        action, action_error = await _resolve_action(team, goal_id)
        if action is None:
            return ConversionGoalSummary(
                id=goal_id,
                name=name,
                kind=kind,
                target_label=f"Action #{goal_id}",
                last_30d_count=0,
                integrated_count=None,
                events_without_utm_source=None,
                events_with_unmatched_utm_source=None,
                non_integrated_count=None,
                integrated_pct=None,
                is_misconfigured=True,
                misconfig_reason=action_error or f"Action {goal_id} no longer exists",
            )
        target_label = f"Action: {action.name}"
        total, integrated, without_utm, unmatched_with_utm, has_step_filters = await _count_action_goal(
            team, action, alias_map
        )
        action_is_approximate = base_approximate or has_step_filters
        action_reason: str | None
        if has_step_filters:
            action_reason = (
                "matches the action's step events only — property/URL filters from the action are not applied"
            )
        else:
            action_reason = base_reason
        return _summary_with_split(
            goal_id,
            name,
            kind,
            target_label,
            total,
            integrated,
            without_utm,
            unmatched_with_utm,
            is_approximate=action_is_approximate,
            approximation_reason=action_reason,
        )

    if kind_raw == "DataWarehouseNode":
        table_name = goal.get("table_name") or "(unknown table)"
        target_label = f"{table_name}"
        last_30d_count, dw_misconfig = await _count_dw_goal(team, goal)
        return ConversionGoalSummary(
            id=goal_id,
            name=name,
            kind=kind,
            target_label=target_label,
            last_30d_count=last_30d_count,
            integrated_count=None,
            events_without_utm_source=None,
            events_with_unmatched_utm_source=None,
            non_integrated_count=None,
            integrated_pct=None,
            is_misconfigured=dw_misconfig is not None,
            misconfig_reason=dw_misconfig,
            is_approximate=base_approximate,
            approximation_reason=base_reason,
        )

    return ConversionGoalSummary(
        id=goal_id,
        name=name,
        kind=kind,
        target_label="(unknown kind)",
        last_30d_count=0,
        integrated_count=None,
        events_without_utm_source=None,
        events_with_unmatched_utm_source=None,
        non_integrated_count=None,
        integrated_pct=None,
        is_misconfigured=True,
        misconfig_reason=f"Unknown goal kind: {kind_raw}",
    )


def _summary_with_split(
    goal_id: str,
    name: str,
    kind: GoalKind,
    target_label: str,
    total: int,
    integrated: int,
    without_utm: int,
    unmatched_with_utm: int,
    *,
    is_approximate: bool = False,
    approximation_reason: str | None = None,
) -> ConversionGoalSummary:
    integrated_pct = round((integrated / total) * 100, 2) if total > 0 else 0.0
    return ConversionGoalSummary(
        id=goal_id,
        name=name,
        kind=kind,
        target_label=target_label,
        last_30d_count=total,
        integrated_count=integrated,
        events_without_utm_source=without_utm,
        events_with_unmatched_utm_source=unmatched_with_utm,
        non_integrated_count=without_utm + unmatched_with_utm,
        integrated_pct=integrated_pct,
        is_misconfigured=False,
        misconfig_reason=None,
        is_approximate=is_approximate,
        approximation_reason=approximation_reason,
    )


@database_sync_to_async
def _resolve_action(team: Team, goal_id: str) -> tuple[Action | None, str | None]:
    try:
        action_id_int = int(goal_id)
    except (TypeError, ValueError):
        return None, f"Goal id '{goal_id}' is not a valid integer for ActionsNode"
    try:
        return Action.objects.get(id=action_id_int, team_id=team.pk, deleted=False), None
    except Action.DoesNotExist:
        return None, f"Action {goal_id} does not exist or is deleted"


@database_sync_to_async
def _count_event_goal(
    team: Team, goal: dict[str, Any], alias_map: dict[str, NativeIntegration]
) -> tuple[int, int, int, int]:
    """For EventsNode: count last 30d events matching the goal, split by utm_source match.

    `goal["event"]` may be None, meaning "match any event" (rare but valid)."""
    since = timezone.now() - timedelta(days=DEFAULT_LOOKBACK_DAYS)
    event_name = goal.get("event")
    placeholders: dict[str, ast.Expr]

    if event_name:
        hogql = """
            SELECT lower(trim(properties.utm_source)) AS utm_source, count() AS c
            FROM events
            WHERE event = {event_name} AND timestamp >= {since}
            GROUP BY utm_source
        """
        placeholders = {"event_name": ast.Constant(value=event_name), "since": ast.Constant(value=since)}
    else:
        hogql = """
            SELECT lower(trim(properties.utm_source)) AS utm_source, count() AS c
            FROM events
            WHERE timestamp >= {since}
            GROUP BY utm_source
        """
        placeholders = {"since": ast.Constant(value=since)}

    return _execute_count_with_split(team, hogql, placeholders, alias_map)


@database_sync_to_async
def _count_action_goal(
    team: Team, action: Action, alias_map: dict[str, NativeIntegration]
) -> tuple[int, int, int, int, bool]:
    """For ActionsNode: count events matching the action's step events, split by
    utm_source. Property/URL filters are NOT applied — a fast approximation.

    Returns (total, integrated, without_utm, unmatched_with_utm, has_step_filters).
    `has_step_filters` is True when a step narrows by URL/properties; caller surfaces
    it as the "approximate" caveat.
    """
    steps = action.steps
    step_events = [s.event for s in steps if s.event]
    has_step_filters = any(_step_has_filters(s) for s in steps)
    if not step_events:
        return 0, 0, 0, 0, has_step_filters

    since = timezone.now() - timedelta(days=DEFAULT_LOOKBACK_DAYS)
    hogql = """
        SELECT lower(trim(properties.utm_source)) AS utm_source, count() AS c
        FROM events
        WHERE event IN {events} AND timestamp >= {since}
        GROUP BY utm_source
    """
    placeholders: dict[str, ast.Expr] = {
        "events": ast.Tuple(exprs=[ast.Constant(value=e) for e in step_events]),
        "since": ast.Constant(value=since),
    }
    total, integrated, without_utm, unmatched_with_utm = _execute_count_with_split(team, hogql, placeholders, alias_map)
    return total, integrated, without_utm, unmatched_with_utm, has_step_filters


def _step_has_filters(step: ActionStepJSON) -> bool:
    """True when an ActionStep narrows beyond plain `event=`. Anything other
    than the bare event name (URL match, property filters, selector, text)
    means our flat events-by-name count is approximate vs the dashboard."""
    return bool(step.url or step.properties or step.selector or step.tag_name or step.href or step.text)


def _execute_count_with_split(
    team: Team, hogql: str, placeholders: dict[str, ast.Expr], alias_map: dict[str, NativeIntegration]
) -> tuple[int, int, int, int]:
    """Returns (total, integrated, without_utm, unmatched_with_utm).

    The two non-integrated buckets have OPPOSITE fixes (UTM tagging on the page
    vs. custom_source_mappings), so they're surfaced separately.
    """
    with tags_context(product=Product.MARKETING_ANALYTICS, feature=Feature.HEALTH_CHECK, team_id=team.pk):
        result = execute_hogql_query(hogql, team, placeholders=placeholders)
    total = 0
    integrated = 0
    without_utm = 0
    unmatched_with_utm = 0
    for row in result.results or []:
        utm_source = (row[0] or "").strip()
        count = int(row[1] or 0)
        total += count
        if not utm_source:
            without_utm += count
        elif lookup_in(utm_source, alias_map) is not None:
            integrated += count
        else:
            unmatched_with_utm += count
    return total, integrated, without_utm, unmatched_with_utm


@database_sync_to_async
def _count_dw_goal(team: Team, goal: dict[str, Any]) -> tuple[int, str | None]:
    """For DataWarehouseNode: a row count against the configured table.

    Returns (count, misconfig_reason). `table_name`/`timestamp_field` come from
    team-editable JSON, so they're validated against a strict identifier regex
    before going into the AST (constants are bound via placeholders).
    """
    table_name = goal.get("table_name")
    timestamp_field = goal.get("timestamp_field")
    if not table_name or not timestamp_field:
        return 0, "DataWarehouseNode goal is missing table_name or timestamp_field"

    if not _DW_TABLE_PATTERN.fullmatch(str(table_name)):
        return 0, f"DataWarehouseNode goal has invalid table_name: {table_name!r}"
    if not _DW_COLUMN_PATTERN.fullmatch(str(timestamp_field)):
        return 0, f"DataWarehouseNode goal has invalid timestamp_field: {timestamp_field!r}"

    since = timezone.now() - timedelta(days=DEFAULT_LOOKBACK_DAYS)
    table_chain: list[str | int] = list(str(table_name).split("."))
    timestamp_chain: list[str | int] = [str(timestamp_field)]
    query = ast.SelectQuery(
        select=[ast.Call(name="count", args=[])],
        select_from=ast.JoinExpr(table=ast.Field(chain=table_chain)),
        where=ast.CompareOperation(
            left=ast.Field(chain=timestamp_chain),
            op=ast.CompareOperationOp.GtEq,
            right=ast.Constant(value=since),
        ),
    )
    try:
        with tags_context(product=Product.MARKETING_ANALYTICS, feature=Feature.HEALTH_CHECK, team_id=team.pk):
            result = execute_hogql_query(query, team)
    except Exception as exc:
        logger.warning(
            "marketing_analytics.dw_goal_query_failed",
            team_id=team.pk,
            table_name=table_name,
            error=str(exc),
        )
        return 0, f"DW table or column not queryable: {exc}"

    if result.results and len(result.results) > 0:
        return int(result.results[0][0] or 0), None
    return 0, None


async def _query_goal_events(team: Team, goal: dict[str, Any], period: DateRange) -> list[tuple[Any, ...]]:
    """Raw event rows for a goal in `period` (EventsNode/ActionsNode only; DW is
    short-circuited by the caller)."""
    kind = goal.get("kind")
    since, until = _resolve_period(period)
    placeholders: dict[str, ast.Expr]

    if kind == "EventsNode":
        event_name = goal.get("event")
        if event_name:
            hogql = """
                SELECT uuid, timestamp, distinct_id, event,
                       properties.utm_source, properties.utm_campaign
                FROM events
                WHERE event = {event_name} AND timestamp >= {since} AND timestamp <= {until}
                ORDER BY timestamp DESC
                LIMIT {scan_limit}
            """
            placeholders = {
                "event_name": ast.Constant(value=event_name),
                "since": ast.Constant(value=since),
                "until": ast.Constant(value=until),
                "scan_limit": ast.Constant(value=EXPLAIN_EVENT_SCAN_LIMIT),
            }
        else:
            hogql = """
                SELECT uuid, timestamp, distinct_id, event,
                       properties.utm_source, properties.utm_campaign
                FROM events
                WHERE timestamp >= {since} AND timestamp <= {until}
                ORDER BY timestamp DESC
                LIMIT {scan_limit}
            """
            placeholders = {
                "since": ast.Constant(value=since),
                "until": ast.Constant(value=until),
                "scan_limit": ast.Constant(value=EXPLAIN_EVENT_SCAN_LIMIT),
            }
        return await _run_hogql(team, hogql, placeholders)

    if kind == "ActionsNode":
        goal_id = str(goal.get("conversion_goal_id") or goal.get("id") or "")
        action, _ = await _resolve_action(team, goal_id)
        if action is None:
            return []
        step_events = await _action_step_events(action)
        if not step_events:
            return []
        hogql = """
            SELECT uuid, timestamp, distinct_id, event,
                   properties.utm_source, properties.utm_campaign
            FROM events
            WHERE event IN {events} AND timestamp >= {since} AND timestamp <= {until}
            ORDER BY timestamp DESC
            LIMIT {scan_limit}
        """
        placeholders = {
            "events": ast.Tuple(exprs=[ast.Constant(value=e) for e in step_events]),
            "since": ast.Constant(value=since),
            "until": ast.Constant(value=until),
            "scan_limit": ast.Constant(value=EXPLAIN_EVENT_SCAN_LIMIT),
        }
        return await _run_hogql(team, hogql, placeholders)

    return []


@database_sync_to_async
def _action_step_events(action: Action) -> list[str]:
    return [s.event for s in action.steps if s.event]


@database_sync_to_async
def _run_hogql(team: Team, hogql: str, placeholders: dict[str, ast.Expr]) -> list[tuple[Any, ...]]:
    with tags_context(product=Product.MARKETING_ANALYTICS, feature=Feature.HEALTH_CHECK, team_id=team.pk):
        result = execute_hogql_query(hogql, team, placeholders=placeholders)
    return list(result.results or [])


def _resolve_period(period: DateRange) -> tuple[datetime, datetime]:
    now = timezone.now()
    until = _parse_date_or(period.date_to, default=now)
    since = _parse_date_or(period.date_from, default=now - timedelta(days=DEFAULT_LOOKBACK_DAYS))
    return since, until


def _parse_date_or(raw: str | None, *, default: datetime) -> datetime:
    if not raw:
        return default
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return default


def _default_period() -> DateRange:
    now = timezone.now()
    return DateRange(date_from=(now - timedelta(days=DEFAULT_LOOKBACK_DAYS)).isoformat(), date_to=now.isoformat())
