from django.conf import settings

import structlog

from posthog.schema import (
    CompareFilter,
    DateRange,
    ProductKey,
    WebAnalyticsOrderByDirection,
    WebAnalyticsOrderByFields,
    WebGoalsQuery,
    WebOverviewQuery,
    WebStatsBreakdown,
    WebStatsTableQuery,
)

from posthog.clickhouse.query_tagging import tag_queries
from posthog.hogql_queries.web_analytics.stats_table import WebStatsTableQueryRunner
from posthog.hogql_queries.web_analytics.web_goals import NoActionsError, WebGoalsQueryRunner
from posthog.hogql_queries.web_analytics.web_overview import WebOverviewQueryRunner
from posthog.models import Team
from posthog.models.user import User
from posthog.tasks.email_utils import compute_week_over_week_change

logger = structlog.get_logger(__name__)


def _default_overview() -> dict:
    return {
        "visitors": {"current": 0, "previous": None, "change": None},
        "pageviews": {"current": 0, "previous": None, "change": None},
        "sessions": {"current": 0, "previous": None, "change": None},
        "bounce_rate": {"current": 0.0, "previous": None, "change": None},
        "avg_session_duration": {"current": "0s", "previous": "0s", "change": None},
    }


def get_overview_for_team(team: Team, days: int = 7, compare: bool = True) -> dict:
    tag_queries(product=ProductKey.WEB_ANALYTICS, team_id=team.pk, name="weekly_digest:web_overview")
    result = _default_overview()

    try:
        query = WebOverviewQuery(
            dateRange=DateRange(date_from=f"-{days}d"),
            compareFilter=CompareFilter(compare=compare),
            filterTestAccounts=True,
            properties=[],
        )
        runner = WebOverviewQueryRunner(team=team, query=query)
        response = runner.calculate()
    except Exception:
        logger.exception("failed to query web overview", team_id=team.pk)
        return result

    if not response.results:
        return result

    items_by_key = {item.key: item for item in response.results}

    for key, output_key, higher_is_better in [
        ("visitors", "visitors", True),
        ("views", "pageviews", True),
        ("sessions", "sessions", True),
    ]:
        item = items_by_key.get(key)
        if item:
            current = item.value or 0
            previous = item.previous or None
            result[output_key] = {
                "current": current,
                "previous": previous,
                "change": compute_week_over_week_change(current, previous, higher_is_better=higher_is_better),
            }

    bounce_item = items_by_key.get("bounce rate")
    if bounce_item:
        current_bounce = bounce_item.value if bounce_item.value is not None else 0
        prev_bounce = bounce_item.previous or None
        result["bounce_rate"] = {
            "current": round(current_bounce, 1),
            "previous": round(prev_bounce, 1) if prev_bounce is not None else None,
            "change": compute_week_over_week_change(
                current_bounce,
                prev_bounce,
                higher_is_better=False,
            ),
        }

    duration_item = items_by_key.get("session duration")
    if duration_item:
        current_duration = duration_item.value or 0
        prev_duration = duration_item.previous
        result["avg_session_duration"] = {
            "current": _format_duration(current_duration),
            "previous": _format_duration(prev_duration) if compare else None,
            "change": compute_week_over_week_change(
                current_duration,
                prev_duration,
                higher_is_better=True,
            ),
        }

    return result


def _format_duration(seconds: float | None) -> str:
    """Format seconds into a human-readable string like '2m 34s'."""
    if seconds is None or seconds <= 0:
        return "0s"
    total = int(seconds)
    if total < 60:
        return f"{total}s"
    minutes = total // 60
    secs = total % 60
    if secs == 0:
        return f"{minutes}m"
    return f"{minutes}m {secs}s"


def get_top_pages(team: Team, limit: int = 5, days: int = 7) -> list[dict]:
    tag_queries(product=ProductKey.WEB_ANALYTICS, team_id=team.pk, name="weekly_digest:top_pages")

    try:
        query = WebStatsTableQuery(
            breakdownBy=WebStatsBreakdown.PAGE,
            dateRange=DateRange(date_from=f"-{days}d"),
            limit=limit,
            orderBy=[WebAnalyticsOrderByFields.VISITORS, WebAnalyticsOrderByDirection.DESC],
            filterTestAccounts=True,
            properties=[],
        )
        runner = WebStatsTableQueryRunner(team=team, query=query)
        response = runner.calculate()

        if not response.results:
            return []

        return [
            {
                "host": "",
                "path": row[0] or "",
                "visitors": row[1][0],
                "change": compute_week_over_week_change(row[1][0], row[1][1], higher_is_better=True),
            }
            for row in response.results
        ]
    except Exception:
        logger.exception("failed to query top pages", team_id=team.pk)
        return []


def get_top_sources(team: Team, limit: int = 5, days: int = 7) -> list[dict]:
    tag_queries(product=ProductKey.WEB_ANALYTICS, team_id=team.pk, name="weekly_digest:top_sources")

    try:
        query = WebStatsTableQuery(
            breakdownBy=WebStatsBreakdown.INITIAL_REFERRING_DOMAIN,
            dateRange=DateRange(date_from=f"-{days}d"),
            limit=limit,
            orderBy=[WebAnalyticsOrderByFields.VISITORS, WebAnalyticsOrderByDirection.DESC],
            filterTestAccounts=True,
            properties=[],
        )
        runner = WebStatsTableQueryRunner(team=team, query=query)
        response = runner.calculate()

        if not response.results:
            return []

        return [
            {
                "name": row[0] or "",
                "visitors": row[1][0],
                "change": compute_week_over_week_change(row[1][0], row[1][1], higher_is_better=True),
            }
            for row in response.results
            if row[0]
        ]
    except Exception:
        logger.exception("failed to query top sources", team_id=team.pk)
        return []


def get_goals_for_team(team: Team, limit: int = 5, days: int = 7, compare: bool = True) -> list[dict]:
    tag_queries(product=ProductKey.WEB_ANALYTICS, team_id=team.pk, name="weekly_digest:goals")

    try:
        query = WebGoalsQuery(
            dateRange=DateRange(date_from=f"-{days}d"),
            compareFilter=CompareFilter(compare=compare),
            properties=[],
        )
        runner = WebGoalsQueryRunner(team=team, query=query)
        response = runner.calculate()
    except NoActionsError:
        return []
    except Exception:
        logger.exception("failed to query goals", team_id=team.pk)
        return []

    results = []
    for row in response.results[:limit]:
        name, _converting_users, (total_current, total_prev), _conversion_rate = row
        results.append(
            {
                "name": name,
                "conversions": total_current or 0,
                "change": compute_week_over_week_change(
                    total_current or 0,
                    total_prev,
                    higher_is_better=True,
                ),
            }
        )
    return results


def build_team_digest(team: Team, days: int = 7, compare: bool = True) -> dict:
    overview = get_overview_for_team(team, days=days, compare=compare)
    top_pages = get_top_pages(team, days=days)
    top_sources = get_top_sources(team, days=days)
    goals = get_goals_for_team(team, days=days, compare=compare)

    return {
        "team": team,
        **overview,
        "top_pages": top_pages,
        "top_sources": top_sources,
        "goals": goals,
        "dashboard_url": f"{settings.SITE_URL}/project/{team.pk}/web?utm_source=web_analytics_weekly_digest&utm_medium=email",
    }


def auto_select_project_for_user(user: User, team_traffic_data: dict[int, dict]) -> bool:
    """For first-time users who have no WA digest project settings, auto-select the project with the most visitors.

    Returns True if settings were updated (caller should refresh_from_db).
    """
    from posthog.tasks.email_utils import auto_select_digest_project

    return auto_select_digest_project(
        user=user,
        team_data=team_traffic_data,
        setting_key="web_analytics_weekly_digest_project_enabled",
        sort_key=lambda d: d.get("visitors", {}).get("current", 0),
    )
