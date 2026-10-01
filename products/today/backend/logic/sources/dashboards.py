"""Dashboards and insights the person cares about, with their biggest week-over-week change.

Interest comes from two signals: the shortcuts the person starred in the navigation, and the
last 14 days of their view log. Starred items come first, then the latest viewed. Changes come
from cached results only, and are cached per dashboard per day so everyone who watches it shares
the work.
"""

from datetime import datetime, timedelta

from django.core.cache import cache

from posthog.dataclasses import frozen
from posthog.models.file_system.file_system_shortcut import FileSystemShortcut
from posthog.models.file_system.file_system_view_log import recent_view_logs

from products.dashboards.backend.facade import api as dashboards
from products.product_analytics.backend.facade import api as product_analytics
from products.product_analytics.backend.facade.contracts import CachedTrends

from ...facade.enums import ItemGroup, ItemReason, ItemSource
from ..candidates import URGENCY_THIS_WEEK, URGENCY_TODAY, URGENCY_WHEN_FREE, Candidate, SourceContext, app_url
from ..movements import Movement, biggest_movements, week_over_week
from .base import Source

VIEW_WINDOW_DAYS = 14
MAX_DASHBOARDS = 5
MAX_INSIGHTS = 5
_CACHE_SECONDS = 24 * 60 * 60


@frozen
class _Interest:
    """How much one dashboard or insight matters to the person, from what they starred and opened."""

    ref: str
    starred: bool
    last_viewed_at: datetime | None

    @property
    def sort_key(self) -> tuple[float, ...]:
        last = self.last_viewed_at.timestamp() if self.last_viewed_at else 0.0
        return (0 if self.starred else 1, -last)


def _interests(ctx: SourceContext, type: str, limit: int) -> list[_Interest]:
    since = ctx.now - timedelta(days=VIEW_WINDOW_DAYS)
    viewed = {
        log.ref: log.viewed_at
        for log in recent_view_logs(team_id=ctx.team.id, user_id=ctx.user.id, type=type, limit=limit)
        if log.viewed_at >= since
    }
    starred: set[str] = {
        ref
        for ref in FileSystemShortcut.objects.filter(team_id=ctx.team.id, user_id=ctx.user.id, type=type).values_list(
            "ref", flat=True
        )
        if ref
    }
    interests = [
        _Interest(ref=ref, starred=ref in starred, last_viewed_at=viewed.get(ref)) for ref in starred | set(viewed)
    ]
    return sorted(interests, key=lambda interest: interest.sort_key)[:limit]


def _movements(trends: list[CachedTrends], ctx: SourceContext) -> list[Movement]:
    found = []
    for insight in trends:
        for series in insight.series:
            label = insight.name if len(insight.series) == 1 else f"{insight.name}: {series.label}"
            movement = week_over_week(
                label=label, interval=insight.interval, days=series.days, data=series.data, today=ctx.now.date()
            )
            if movement is not None:
                found.append(movement)
    return biggest_movements(found)


def _dashboard_movements(ctx: SourceContext, dashboard_id: int) -> list[Movement]:
    cache_key = f"today:movements:{ctx.team.id}:{dashboard_id}:{ctx.now.date().isoformat()}"
    cached = cache.get(cache_key)
    if cached is not None:
        return [Movement.model_validate(row) for row in cached]
    movements = _movements(
        dashboards.cached_trends_for_dashboard(team_id=ctx.team.id, user=ctx.user, dashboard_id=dashboard_id), ctx
    )
    cache.set(cache_key, [m.model_dump() for m in movements], _CACHE_SECONDS)
    return movements


def _urgency(movements: list[Movement], interest: _Interest) -> int:
    """A metric that halved or doubled is for today; a fifth either way is for the week. A starred
    item moves up one tier, but a chart move is never for right now."""
    change = abs(movements[0].pct_change or 0)
    if change >= 50:
        tier = URGENCY_TODAY
    elif change >= 20:
        tier = URGENCY_THIS_WEEK
    else:
        tier = URGENCY_WHEN_FREE
    return max(tier - int(interest.starred), URGENCY_TODAY)


def _facts(movements: list[Movement], interest: _Interest, now: datetime) -> dict:
    top = movements[0]
    facts: dict = {
        "metric": top.metric,
        "last_week": round(top.previous, 2),
        "this_week": round(top.current, 2),
        "pct_change": top.pct_change,
        "starred": interest.starred,
        "viewed_days_ago": (now - interest.last_viewed_at).days if interest.last_viewed_at else None,
    }
    if len(movements) > 1:
        facts["second_metric"] = movements[1].metric
        facts["second_pct_change"] = movements[1].pct_change
    return facts


class DashboardsSource(Source):
    name = "dashboards"

    def collect(self, ctx: SourceContext) -> list[Candidate]:
        candidates: list[Candidate] = []

        dashboard_interest = {
            interest.ref: interest
            for interest in _interests(ctx, "dashboard", MAX_DASHBOARDS)
            if interest.ref.isdigit()
        }
        for ref in dashboards.viewable_dashboard_refs(
            team_id=ctx.team.id, user=ctx.user, dashboard_ids=[int(ref) for ref in dashboard_interest]
        ):
            movements = _dashboard_movements(ctx, ref.id)
            if not movements:
                continue
            interest = dashboard_interest[str(ref.id)]
            candidates.append(
                Candidate(
                    key=f"dashboard:{ref.id}",
                    group=ItemGroup.DASHBOARD,
                    source=ItemSource.PRODUCT_ANALYTICS,
                    reason=ItemReason.DASHBOARD_YOU_STARRED if interest.starred else ItemReason.DASHBOARD_YOU_VIEWED,
                    title=ref.name or "Untitled dashboard",
                    url=app_url(ctx.team.id, f"dashboard/{ref.id}"),
                    urgency=_urgency(movements, interest),
                    sort_key=(1, *interest.sort_key),
                    facts=_facts(movements, interest, ctx.now),
                )
            )

        insight_interest = {interest.ref: interest for interest in _interests(ctx, "insight", MAX_INSIGHTS)}
        for trends in product_analytics.cached_trends_for_insights(
            team=ctx.team, user=ctx.user, short_ids=list(insight_interest)
        ):
            movements = _movements([trends], ctx)
            if not movements:
                continue
            interest = insight_interest[trends.short_id]
            candidates.append(
                Candidate(
                    key=f"insight:{trends.short_id}",
                    group=ItemGroup.DASHBOARD,
                    source=ItemSource.PRODUCT_ANALYTICS,
                    reason=ItemReason.INSIGHT_YOU_STARRED if interest.starred else ItemReason.INSIGHT_YOU_VIEWED,
                    title=trends.name or "Untitled insight",
                    url=app_url(ctx.team.id, f"insights/{trends.short_id}"),
                    urgency=_urgency(movements, interest),
                    sort_key=(1, *interest.sort_key),
                    facts=_facts(movements, interest, ctx.now),
                )
            )
        return candidates
