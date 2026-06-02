"""Suggest custom events that are good candidates for becoming conversion goals.

Read-only. Ranks events by volume, UTM-tag coverage, and unique users; excludes
autocaptured/system events and de-prioritizes events already configured as goals.
"""

from dataclasses import asdict, dataclass, field
from datetime import timedelta
from typing import Any

from django.utils import timezone

import structlog

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.team.team import Team
from posthog.sync import database_sync_to_async
from posthog.taxonomy.taxonomy import CORE_FILTER_DEFINITIONS_BY_GROUP

logger = structlog.get_logger(__name__)

DEFAULT_LOOKBACK_DAYS = 30
DEFAULT_TOP_N = 20
DEFAULT_MIN_COUNT = 50
TOP_UTM_SOURCES_PER_EVENT = 3
HOGQL_GROUP_LIMIT = 200

# System/autocaptured events excluded. Driven from `CORE_FILTER_DEFINITIONS_BY_GROUP`
# so new taxonomy events roll in automatically. Overlay covers convention-based events
# that aren't `$`-prefixed (Surveys: "survey shown"/"sent"/"dismissed").
_TAXONOMY_OVERLAY_EXCLUDED: frozenset[str] = frozenset(
    {
        "survey shown",
        "survey sent",
        "survey dismissed",
    }
)


def _build_default_excluded_events() -> frozenset[str]:
    taxonomy_events = {key for key in CORE_FILTER_DEFINITIONS_BY_GROUP.get("events", {}) if key.startswith("$")}
    return frozenset(taxonomy_events | _TAXONOMY_OVERLAY_EXCLUDED)


DEFAULT_EXCLUDED_EVENTS: frozenset[str] = _build_default_excluded_events()

# Score weights — tuned so that high-volume events with consistent UTM tagging
# rank above niche events with perfect UTMs. Tweak before the LLM consumes this.
SCORE_WEIGHT_VOLUME = 0.40
SCORE_WEIGHT_UTM_COVERAGE = 0.40
SCORE_WEIGHT_NOT_ALREADY_GOAL = 0.20


@dataclass
class CandidateEvent:
    event_name: str
    last_30d_count: int
    distinct_users_30d: int
    pct_with_utm_source: float
    pct_with_utm_campaign: float
    top_utm_sources: list[tuple[str, int]]
    is_already_a_goal: bool
    suggestion_score: float
    suggestion_reason: str


@dataclass
class EventSuggestionsResponse:
    candidates: list[CandidateEvent] = field(default_factory=list)
    lookback_days: int = DEFAULT_LOOKBACK_DAYS
    excluded_events_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


async def suggest_conversion_goals(
    team: Team,
    *,
    top_n: int = DEFAULT_TOP_N,
    exclude_autocapture: bool = True,
    min_count: int = DEFAULT_MIN_COUNT,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> EventSuggestionsResponse:
    rows = await _fetch_candidate_rows(team, min_count=min_count, lookback_days=lookback_days)
    existing_goal_events = await _read_existing_goal_event_names(team)
    excluded = DEFAULT_EXCLUDED_EVENTS if exclude_autocapture else frozenset()

    # max_volume over the post-exclusion set, so an excluded high-volume event
    # (e.g. $pageview) doesn't deflate every real candidate's volume score.
    candidate_rows = [r for r in rows if r["event_name"] not in excluded]
    max_volume = max((r["count"] for r in candidate_rows), default=1)
    candidates: list[CandidateEvent] = []
    for row in candidate_rows:
        event_name: str = row["event_name"]
        count = row["count"]
        users = row["users"]
        with_utm_source = row["with_utm_source"]
        with_utm_campaign = row["with_utm_campaign"]

        pct_utm_source = (with_utm_source / count * 100) if count else 0.0
        pct_utm_campaign = (with_utm_campaign / count * 100) if count else 0.0
        is_goal = event_name in existing_goal_events

        score = _compute_score(
            count=count,
            max_volume=max_volume,
            pct_utm_source=pct_utm_source,
            is_already_a_goal=is_goal,
        )
        reason = _build_reason(
            count=count,
            pct_utm_source=pct_utm_source,
            is_already_a_goal=is_goal,
        )

        candidates.append(
            CandidateEvent(
                event_name=event_name,
                last_30d_count=count,
                distinct_users_30d=users,
                pct_with_utm_source=round(pct_utm_source, 2),
                pct_with_utm_campaign=round(pct_utm_campaign, 2),
                top_utm_sources=row["top_utm_sources"],
                is_already_a_goal=is_goal,
                suggestion_score=round(score, 4),
                suggestion_reason=reason,
            )
        )

    candidates.sort(key=lambda c: c.suggestion_score, reverse=True)
    return EventSuggestionsResponse(
        candidates=candidates[:top_n],
        lookback_days=lookback_days,
        excluded_events_count=len(excluded),
    )


@database_sync_to_async
def _fetch_candidate_rows(team: Team, *, min_count: int, lookback_days: int) -> list[dict[str, Any]]:
    """One pass over events: grouped by event name with UTM coverage signals plus
    the per-event top-K utm_source via ClickHouse's `topK` aggregate."""
    since = timezone.now() - timedelta(days=lookback_days)
    aggregate_hogql = """
        SELECT
            event,
            count() AS c,
            uniq(distinct_id) AS u,
            countIf(properties.utm_source IS NOT NULL AND properties.utm_source != '') AS with_utm_source,
            countIf(properties.utm_campaign IS NOT NULL AND properties.utm_campaign != '') AS with_utm_campaign,
            topK({top_utm})(lower(trim(properties.utm_source))) AS top_utm_sources_raw
        FROM events
        WHERE timestamp >= {since}
        GROUP BY event
        HAVING c >= {min_count}
        ORDER BY c DESC
        LIMIT {limit}
    """
    placeholders = {
        "since": ast.Constant(value=since),
        "min_count": ast.Constant(value=min_count),
        "limit": ast.Constant(value=HOGQL_GROUP_LIMIT),
        "top_utm": ast.Constant(value=TOP_UTM_SOURCES_PER_EVENT),
    }
    with tags_context(product=Product.MARKETING_ANALYTICS, feature=Feature.HEALTH_CHECK, team_id=team.pk):
        aggregated = execute_hogql_query(aggregate_hogql, team, placeholders=placeholders)

    rows: list[dict[str, Any]] = []
    for row in aggregated.results or []:
        event_name = row[0]
        if not event_name:
            continue
        # `topK` returns values without counts. For a single source, attribute the
        # event's total utm_source count; for multiple, use 0 (avoids a second query).
        raw_top = row[5] or []
        with_utm_total = int(row[3] or 0)
        if isinstance(raw_top, list) and len(raw_top) == 1 and raw_top[0]:
            top_utm_sources = [(str(raw_top[0]), with_utm_total)]
        else:
            top_utm_sources = [(str(value), 0) for value in raw_top if value]
        rows.append(
            {
                "event_name": event_name,
                "count": int(row[1] or 0),
                "users": int(row[2] or 0),
                "with_utm_source": with_utm_total,
                "with_utm_campaign": int(row[4] or 0),
                "top_utm_sources": top_utm_sources,
            }
        )

    return rows


@database_sync_to_async
def _read_existing_goal_event_names(team: Team) -> set[str]:
    config = getattr(team, "marketing_analytics_config", None)
    if config is None:
        return set()
    goals = config.conversion_goals or []
    names: set[str] = set()
    for goal in goals:
        if goal.get("kind") == "EventsNode":
            event = goal.get("event")
            if event:
                names.add(event)
    return names


def _compute_score(*, count: int, max_volume: int, pct_utm_source: float, is_already_a_goal: bool) -> float:
    volume_norm = (count / max_volume) if max_volume > 0 else 0.0
    utm_norm = pct_utm_source / 100.0
    not_goal_bonus = 0.0 if is_already_a_goal else 1.0
    return (
        SCORE_WEIGHT_VOLUME * volume_norm
        + SCORE_WEIGHT_UTM_COVERAGE * utm_norm
        + SCORE_WEIGHT_NOT_ALREADY_GOAL * not_goal_bonus
    )


def _build_reason(*, count: int, pct_utm_source: float, is_already_a_goal: bool) -> str:
    parts = []
    if count >= 1000:
        parts.append(f"high volume ({count:,} events)")
    elif count >= 100:
        parts.append(f"steady volume ({count:,} events)")
    else:
        parts.append(f"{count:,} events")
    if pct_utm_source >= 70:
        parts.append(f"strong UTM coverage ({pct_utm_source:.0f}%)")
    elif pct_utm_source >= 30:
        parts.append(f"partial UTM coverage ({pct_utm_source:.0f}%)")
    else:
        parts.append(f"low UTM coverage ({pct_utm_source:.0f}%)")
    if is_already_a_goal:
        parts.append("already configured as a goal")
    else:
        parts.append("not yet a goal")
    return ", ".join(parts)
