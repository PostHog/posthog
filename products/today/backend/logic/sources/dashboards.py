"""Dashboards and insights the person opened recently, with their biggest week-over-week change.

"Recently" is the last 14 days of the person's view log, newest first. Changes come from cached
results only, and are cached per dashboard per day so everyone who watches it shares the work.
"""

from datetime import timedelta

from django.core.cache import cache

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


def _urgency(movements: list[Movement]) -> int:
    """A metric that halved or doubled is for today; a fifth either way is for the week."""
    change = abs(movements[0].pct_change or 0)
    if change >= 50:
        return URGENCY_TODAY
    if change >= 20:
        return URGENCY_THIS_WEEK
    return URGENCY_WHEN_FREE


def _facts(movements: list[Movement], viewed_days_ago: int) -> dict:
    top = movements[0]
    facts: dict = {
        "metric": top.metric,
        "last_week": round(top.previous, 2),
        "this_week": round(top.current, 2),
        "pct_change": top.pct_change,
        "viewed_days_ago": viewed_days_ago,
    }
    if len(movements) > 1:
        facts["second_metric"] = movements[1].metric
        facts["second_pct_change"] = movements[1].pct_change
    return facts


class DashboardsSource(Source):
    name = "dashboards"

    def collect(self, ctx: SourceContext) -> list[Candidate]:
        since = ctx.now - timedelta(days=VIEW_WINDOW_DAYS)
        candidates: list[Candidate] = []

        dashboard_logs = [
            log
            for log in recent_view_logs(
                team_id=ctx.team.id, user_id=ctx.user.id, type="dashboard", limit=MAX_DASHBOARDS
            )
            if log.viewed_at >= since and log.ref.isdigit()
        ]
        viewed_at = {int(log.ref): log.viewed_at for log in dashboard_logs}
        for ref in dashboards.viewable_dashboard_refs(
            team_id=ctx.team.id, user=ctx.user, dashboard_ids=list(viewed_at)
        ):
            movements = _dashboard_movements(ctx, ref.id)
            if not movements:
                continue
            candidates.append(
                Candidate(
                    key=f"dashboard:{ref.id}",
                    group=ItemGroup.DASHBOARD,
                    source=ItemSource.PRODUCT_ANALYTICS,
                    reason=ItemReason.DASHBOARD_YOU_VIEWED,
                    title=ref.name or "Untitled dashboard",
                    url=app_url(ctx.team.id, f"dashboard/{ref.id}"),
                    urgency=_urgency(movements),
                    sort_key=(1, -viewed_at[ref.id].timestamp()),
                    facts=_facts(movements, (ctx.now - viewed_at[ref.id]).days),
                )
            )

        insight_logs = [
            log
            for log in recent_view_logs(team_id=ctx.team.id, user_id=ctx.user.id, type="insight", limit=MAX_INSIGHTS)
            if log.viewed_at >= since
        ]
        insight_viewed_at = {log.ref: log.viewed_at for log in insight_logs}
        for trends in product_analytics.cached_trends_for_insights(
            team=ctx.team, user=ctx.user, short_ids=list(insight_viewed_at)
        ):
            movements = _movements([trends], ctx)
            if not movements:
                continue
            seen_at = insight_viewed_at[trends.short_id]
            candidates.append(
                Candidate(
                    key=f"insight:{trends.short_id}",
                    group=ItemGroup.DASHBOARD,
                    source=ItemSource.PRODUCT_ANALYTICS,
                    reason=ItemReason.INSIGHT_YOU_VIEWED,
                    title=trends.name or "Untitled insight",
                    url=app_url(ctx.team.id, f"insights/{trends.short_id}"),
                    urgency=_urgency(movements),
                    sort_key=(1, -seen_at.timestamp()),
                    facts=_facts(movements, (ctx.now - seen_at).days),
                )
            )
        return candidates
