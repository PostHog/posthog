from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from django.conf import settings

import structlog

from posthog.schema import (
    ActionConversionGoal,
    CompareFilter,
    CustomEventConversionGoal,
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
from posthog.models import Team
from posthog.models.user import User
from posthog.tasks.email_utils import compute_week_over_week_change
from posthog.utils import relative_date_parse

from products.web_analytics.backend.context_events import gather_context_events
from products.web_analytics.backend.hogql_queries.stats_table import WebStatsTableQueryRunner
from products.web_analytics.backend.hogql_queries.web_goals import NoActionsError, WebGoalsQueryRunner
from products.web_analytics.backend.hogql_queries.web_overview import WebOverviewQueryRunner

logger = structlog.get_logger(__name__)


ConversionGoalT = ActionConversionGoal | CustomEventConversionGoal | None


@dataclass(frozen=True)
class DigestFilterSpec:
    date_range: DateRange
    compare: bool = True
    properties: list[dict[str, Any]] = field(default_factory=list)
    conversion_goal: ConversionGoalT = None
    filter_test_accounts: bool = True
    do_path_cleaning: bool = False


def _default_overview() -> dict:
    return {
        "visitors": {"current": 0, "previous": None, "change": None},
        "pageviews": {"current": 0, "previous": None, "change": None},
        "sessions": {"current": 0, "previous": None, "change": None},
        "bounce_rate": {"current": 0.0, "previous": None, "change": None},
        "avg_session_duration": {"current": "0s", "previous": "0s", "change": None},
    }


def _overview_from_spec(team: Team, spec: DigestFilterSpec) -> dict:
    tag_queries(product=ProductKey.WEB_ANALYTICS, team_id=team.pk, name="weekly_digest:web_overview")
    result = _default_overview()

    try:
        query = WebOverviewQuery(
            dateRange=spec.date_range,
            compareFilter=CompareFilter(compare=spec.compare),
            filterTestAccounts=spec.filter_test_accounts,
            properties=spec.properties,
            conversionGoal=spec.conversion_goal,
            doPathCleaning=spec.do_path_cleaning,
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
            "previous": _format_duration(prev_duration) if spec.compare else None,
            "change": compute_week_over_week_change(
                current_duration,
                prev_duration,
                higher_is_better=True,
            ),
        }

    return result


def _format_duration(seconds: float | None) -> str:
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


def _top_pages_from_spec(team: Team, spec: DigestFilterSpec, limit: int = 5) -> list[dict]:
    tag_queries(product=ProductKey.WEB_ANALYTICS, team_id=team.pk, name="weekly_digest:top_pages")

    try:
        query = WebStatsTableQuery(
            breakdownBy=WebStatsBreakdown.PAGE,
            dateRange=spec.date_range,
            limit=limit,
            orderBy=[WebAnalyticsOrderByFields.VISITORS, WebAnalyticsOrderByDirection.DESC],
            filterTestAccounts=spec.filter_test_accounts,
            properties=spec.properties,
            conversionGoal=spec.conversion_goal,
            doPathCleaning=spec.do_path_cleaning,
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


def _top_sources_from_spec(team: Team, spec: DigestFilterSpec, limit: int = 5) -> list[dict]:
    tag_queries(product=ProductKey.WEB_ANALYTICS, team_id=team.pk, name="weekly_digest:top_sources")

    try:
        query = WebStatsTableQuery(
            breakdownBy=WebStatsBreakdown.INITIAL_REFERRING_DOMAIN,
            dateRange=spec.date_range,
            limit=limit,
            orderBy=[WebAnalyticsOrderByFields.VISITORS, WebAnalyticsOrderByDirection.DESC],
            filterTestAccounts=spec.filter_test_accounts,
            properties=spec.properties,
            conversionGoal=spec.conversion_goal,
            doPathCleaning=spec.do_path_cleaning,
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


def _goals_from_spec(team: Team, spec: DigestFilterSpec, limit: int = 5) -> list[dict]:
    tag_queries(product=ProductKey.WEB_ANALYTICS, team_id=team.pk, name="weekly_digest:goals")

    try:
        query = WebGoalsQuery(
            dateRange=spec.date_range,
            compareFilter=CompareFilter(compare=spec.compare),
            properties=spec.properties,
            filterTestAccounts=spec.filter_test_accounts,
            doPathCleaning=spec.do_path_cleaning,
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


def _resolve_window(team: Team, spec: DigestFilterSpec) -> tuple[datetime, datetime] | None:
    if spec.date_range.date_from is None:
        return None
    tz = ZoneInfo(team.timezone)
    now = datetime.now(tz)
    try:
        date_from = relative_date_parse(spec.date_range.date_from, tz, now=now, increase=False)
        date_to = (
            relative_date_parse(spec.date_range.date_to, tz, now=now, increase=True) if spec.date_range.date_to else now
        )
    except Exception:
        logger.exception("failed to resolve digest window for context events", team_id=team.pk)
        return None
    if date_from > date_to:
        return None
    return date_from, date_to


def _context_events_from_spec(team: Team, spec: DigestFilterSpec) -> list[dict[str, Any]]:
    window = _resolve_window(team, spec)
    if window is None:
        return []
    return gather_context_events(team, window[0], window[1])


def build_digest_from_spec(team: Team, spec: DigestFilterSpec, *, include_context_events: bool = False) -> dict:
    overview = _overview_from_spec(team, spec)
    top_pages = _top_pages_from_spec(team, spec)
    top_sources = _top_sources_from_spec(team, spec)
    goals = _goals_from_spec(team, spec)
    context_events = _context_events_from_spec(team, spec) if include_context_events else []

    return {
        **overview,
        "top_pages": top_pages,
        "top_sources": top_sources,
        "goals": goals,
        "context_events": context_events,
    }


def _spec_for_days(days: int, compare: bool) -> DigestFilterSpec:
    return DigestFilterSpec(date_range=DateRange(date_from=f"-{days}d"), compare=compare)


def build_team_digest(team: Team, days: int = 7, compare: bool = True) -> dict:
    spec = _spec_for_days(days, compare)
    digest = build_digest_from_spec(team, spec)
    return {
        "team": team,
        **digest,
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
