"""Pure-SQL candidate metric selection for Pulse.

v1 strategy: top-N popular insights and high-volume events. No LLM.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from django.db.models import Count, Q

from posthog.schema import NodeKind, PulseScanConfig

from posthog.sync import database_sync_to_async

from products.pulse.backend.temporal.types import CandidateMetric, MetricDescriptor

if TYPE_CHECKING:
    from posthog.models import Team

    from products.product_analytics.backend.models.insight import Insight


def _trends_query_from_insight(insight: Insight) -> dict | None:
    """Extract a re-executable TrendsQuery from a saved Insight, or None if unsupported."""
    query = insight.query
    if not query:
        return None
    while isinstance(query, dict) and query.get("source"):
        query = query["source"]
    if not isinstance(query, dict) or query.get("kind") != NodeKind.TRENDS_QUERY:
        return None
    return query


def _build_event_volume_query(event_name: str) -> dict:
    return {
        "kind": NodeKind.TRENDS_QUERY,
        "series": [{"kind": "EventsNode", "event": event_name, "name": event_name, "math": "total"}],
        "dateRange": {"date_from": "-30d", "date_to": None},
        "interval": "day",
    }


def insight_to_descriptor(insight: Insight, source: str) -> MetricDescriptor | None:
    """Build a re-scoreable MetricDescriptor from a saved Insight, or None if it isn't a TrendsQuery.

    Shared by selection (candidate discovery) and the scout adapter (sources.py) so both resolve insights
    to a descriptor identically — one place to change the query unwrap, label fallback, and deep-link.
    """
    query = _trends_query_from_insight(insight)
    if not query:
        return None
    return MetricDescriptor(
        source=source,
        source_id=str(insight.id),
        label=insight.name or insight.derived_name or f"Insight {insight.short_id}",
        query=query,
        url=f"/insights/{insight.short_id}",
    )


def _insight_to_candidate(insight: Insight, source: str) -> CandidateMetric | None:
    descriptor = insight_to_descriptor(insight, source)
    return CandidateMetric(descriptor=descriptor) if descriptor else None


def _select_dashboard_tile_candidates(team: Team, limit: int, recent_days: int) -> list[CandidateMetric]:
    """Pick Trends insights on the team's most-pinned/visible dashboards."""
    # Lazy import: importing product models at module level triggers an app-init circular import
    # (the pulse package is eagerly preloaded via posthog.api). They resolve fine at activity-call time.
    from products.dashboards.backend.models.dashboard import Dashboard  # noqa: PLC0415
    from products.dashboards.backend.models.dashboard_tile import DashboardTile  # noqa: PLC0415

    dashboards = (
        Dashboard.objects.filter(team=team, deleted=False)
        .filter(Q(pinned=True) | Q(last_accessed_at__gte=datetime.now(UTC) - timedelta(days=recent_days)))
        .order_by("-pinned", "-last_accessed_at")[:limit]
    )
    tiles = (
        DashboardTile.objects.filter(dashboard__in=dashboards, deleted=False, insight__isnull=False)
        .select_related("insight")
        .order_by("dashboard_id", "id")
    )
    candidates: list[CandidateMetric] = []
    seen_insight_ids: set[str] = set()
    for tile in tiles:
        insight = tile.insight
        if insight is None or str(insight.id) in seen_insight_ids:
            continue
        seen_insight_ids.add(str(insight.id))
        candidate = _insight_to_candidate(insight, source="dashboard_tile")
        if candidate:
            candidates.append(candidate)
    return candidates


def _select_recent_viewed_insight_candidates(
    team: Team, limit: int, existing_ids: set[str], recent_days: int, min_viewers: int
) -> list[CandidateMetric]:
    """Pick Trends insights recently viewed by multiple team members."""
    # lazy: avoid app-init circular import
    from products.product_analytics.backend.models.insight import Insight, InsightViewed  # noqa: PLC0415

    since = datetime.now(UTC) - timedelta(days=recent_days)
    viewed = (
        InsightViewed.objects.filter(team=team, last_viewed_at__gte=since)
        .values("insight_id")
        .annotate(viewer_count=Count("user_id", distinct=True))
        .filter(viewer_count__gte=min_viewers)
        .order_by("-viewer_count")
    )
    insight_ids = [v["insight_id"] for v in viewed if str(v["insight_id"]) not in existing_ids]
    # `viewed` is ranked by -viewer_count, but a SQL `id__in` fetch imposes no ordering. Bound the fetch
    # (many insights aren't Trends-shaped and get dropped, so over-fetch a multiple of `limit`) and re-sort
    # the rows back into viewer-count order so the cap keeps the most-viewed insights, not an arbitrary subset.
    ranked_ids = insight_ids[: limit * 4]
    position = {insight_id: i for i, insight_id in enumerate(ranked_ids)}
    insights = sorted(
        Insight.objects.filter(id__in=ranked_ids, deleted=False),
        key=lambda insight: position[insight.id],
    )

    candidates: list[CandidateMetric] = []
    for insight in insights:
        candidate = _insight_to_candidate(insight, source="recent_insight")
        if candidate:
            candidates.append(candidate)
            if len(candidates) >= limit:
                break
    return candidates


def _select_saved_insight_candidates(team: Team, limit: int, existing_ids: set[str]) -> list[CandidateMetric]:
    """Pick the team's most recently edited saved Trends insights, independent of dashboards or views.

    The broad "watch our saved insights" net — surfaces insights even on small teams that never hit
    the multi-viewer bar or pin a dashboard.
    """
    # lazy: avoid app-init circular import
    from products.product_analytics.backend.models.insight import Insight  # noqa: PLC0415

    # Over-fetch: many saved insights aren't Trends-shaped and get dropped by _insight_to_candidate.
    insights = Insight.objects.filter(team=team, deleted=False, saved=True).order_by("-last_modified_at")[: limit * 4]
    candidates: list[CandidateMetric] = []
    for insight in insights:
        if str(insight.id) in existing_ids:
            continue
        candidate = _insight_to_candidate(insight, source="saved_insight")
        if candidate:
            candidates.append(candidate)
            if len(candidates) >= limit:
                break
    return candidates


def _select_top_event_candidates(team: Team, limit: int) -> list[CandidateMetric]:
    """Pick the team's highest-volume events as candidate metrics."""
    from posthog.models import EventDefinition  # noqa: PLC0415

    base_qs = EventDefinition.objects.filter(team=team).exclude(name__startswith="$")
    # Prefer events with computed 30-day usage stats.
    events = list(base_qs.exclude(query_usage_30_day__isnull=True).order_by("-query_usage_30_day")[:limit])
    if len(events) < limit:
        seen = {e.id for e in events}
        backfill = base_qs.exclude(id__in=seen).order_by("-last_seen_at")[: limit - len(events)]
        events.extend(backfill)

    return [
        CandidateMetric(
            descriptor=MetricDescriptor(
                source="top_event",
                source_id=str(event.id),
                label=event.name,
                query=_build_event_volume_query(event.name),
            )
        )
        for event in events
    ]


def _candidate_source_ids(candidates: list[CandidateMetric]) -> set[str]:
    return {str(c.descriptor.source_id) for c in candidates if c.descriptor.source_id is not None}


@database_sync_to_async
def _select_sync(team_id: int, config: PulseScanConfig) -> list[CandidateMetric]:
    from posthog.models import Team  # lazy: avoid app-init circular import  # noqa: PLC0415

    team = Team.objects.get(id=team_id)
    # Every PulseScanConfig field is Optional in the generated schema (so its @default can flow); a
    # resolved config is always fully populated at runtime. Narrow the fields used below.
    assert config.dashboard_tile_limit is not None
    assert config.recent_insight_limit is not None
    assert config.saved_insight_limit is not None
    assert config.top_event_limit is not None
    assert config.recent_days is not None
    assert config.min_viewers_for_recent_insight is not None
    assert config.max_candidates is not None
    # Each source contributes only when its limit is positive — a limit of 0 turns it off, the per-run
    # on/off lever. Order matters: earlier sources win the dedup, so dashboard tiles take priority.
    candidates: list[CandidateMetric] = []
    if config.dashboard_tile_limit > 0:
        candidates.extend(_select_dashboard_tile_candidates(team, config.dashboard_tile_limit, config.recent_days))
    if config.recent_insight_limit > 0:
        candidates.extend(
            _select_recent_viewed_insight_candidates(
                team,
                config.recent_insight_limit,
                _candidate_source_ids(candidates),
                config.recent_days,
                config.min_viewers_for_recent_insight,
            )
        )
    if config.saved_insight_limit > 0:
        candidates.extend(
            _select_saved_insight_candidates(team, config.saved_insight_limit, _candidate_source_ids(candidates))
        )
    if config.top_event_limit > 0:
        candidates.extend(_select_top_event_candidates(team, config.top_event_limit))
    return candidates[: config.max_candidates]


async def select_candidates(team_id: int, config: PulseScanConfig) -> list[CandidateMetric]:
    return await _select_sync(team_id, config)
