from collections.abc import Iterable
from datetime import datetime
from typing import TypeVar

from django.conf import settings
from django.db import models

import structlog

from posthog.schema import (
    CacheMissResponse,
    CompareFilter,
    DateRange,
    ProductKey,
    QueryStatusResponse,
    WebAnalyticsOrderByDirection,
    WebAnalyticsOrderByFields,
    WebGoalsQuery,
    WebGoalsQueryResponse,
    WebOverviewQuery,
    WebOverviewQueryResponse,
    WebStatsBreakdown,
    WebStatsTableQuery,
    WebStatsTableQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import tag_queries
from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models import Team
from posthog.models.user import User
from posthog.tasks.email_utils import compute_week_over_week_change

from products.web_analytics.backend.hogql_queries.stats_table import WebStatsTableQueryRunner
from products.web_analytics.backend.hogql_queries.web_goals import NoActionsError, WebGoalsQueryRunner
from products.web_analytics.backend.hogql_queries.web_overview import WebOverviewQueryRunner

logger = structlog.get_logger(__name__)

DEFAULT_DIGEST_EXECUTION_MODE = ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE

DIGEST_METRIC_NOTES = [
    "Visitors, sessions, bounce rate and session duration count only sessions that contain at least one "
    "$pageview or $screen event. A direct count of the sessions table also includes sessions with other events, "
    "so it can be higher.",
    "Events from test accounts are excluded, as set in the project's test account filters.",
    "The period starts at the start of the day `days` days ago and ends now, in the project timezone.",
]


class DigestDataStatus(models.TextChoices):
    OK = "ok", "OK"
    NO_WEB_SESSIONS = "no_web_sessions", "No web sessions"
    NO_SESSIONS = "no_sessions", "No sessions"


DigestResponse = TypeVar("DigestResponse", WebOverviewQueryResponse, WebStatsTableQueryResponse, WebGoalsQueryResponse)


def _require_digest_response(
    response: DigestResponse | CacheMissResponse | QueryStatusResponse,
) -> DigestResponse:
    if isinstance(response, CacheMissResponse | QueryStatusResponse) or response.error:
        raise ValueError("Web analytics digest query did not return a successful result")
    return response


def _default_overview() -> dict:
    return {
        "visitors": {"current": 0, "previous": None, "change": None},
        "pageviews": {"current": 0, "previous": None, "change": None},
        "sessions": {"current": 0, "previous": None, "change": None},
        "bounce_rate": {"current": 0.0, "previous": None, "change": None},
        "avg_session_duration": {"current": "0s", "previous": "0s", "change": None},
    }


def get_overview_for_team(
    team: Team,
    days: int = 7,
    compare: bool = True,
    *,
    execution_mode: ExecutionMode = DEFAULT_DIGEST_EXECUTION_MODE,
    user: User | None = None,
) -> dict:
    tag_queries(product=ProductKey.WEB_ANALYTICS, team_id=team.pk, name="weekly_digest:web_overview")
    result = _default_overview()

    query = WebOverviewQuery(
        dateRange=DateRange(date_from=f"-{days}d"),
        compareFilter=CompareFilter(compare=compare),
        filterTestAccounts=True,
        properties=[],
    )
    runner = WebOverviewQueryRunner(team=team, query=query)
    response = _require_digest_response(runner.run(execution_mode=execution_mode, user=user))

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


def _run_stats_table_query(
    team: Team,
    breakdown_by: WebStatsBreakdown,
    limit: int,
    days: int,
    compare: bool,
    *,
    execution_mode: ExecutionMode,
    user: User | None,
) -> WebStatsTableQueryResponse:
    query = WebStatsTableQuery(
        breakdownBy=breakdown_by,
        dateRange=DateRange(date_from=f"-{days}d"),
        compareFilter=CompareFilter(compare=compare),
        limit=limit,
        orderBy=[WebAnalyticsOrderByFields.VISITORS, WebAnalyticsOrderByDirection.DESC],
        filterTestAccounts=True,
        properties=[],
    )
    runner = WebStatsTableQueryRunner(team=team, query=query)
    return _require_digest_response(runner.run(execution_mode=execution_mode, user=user))


def get_top_pages(
    team: Team,
    limit: int = 5,
    days: int = 7,
    compare: bool = True,
    *,
    execution_mode: ExecutionMode = DEFAULT_DIGEST_EXECUTION_MODE,
    user: User | None = None,
) -> list[dict]:
    tag_queries(product=ProductKey.WEB_ANALYTICS, team_id=team.pk, name="weekly_digest:top_pages")
    response = _run_stats_table_query(
        team, WebStatsBreakdown.PAGE, limit, days, compare, execution_mode=execution_mode, user=user
    )

    return [
        {
            "host": "",
            "path": row[0] or "",
            "visitors": row[1][0],
            "change": compute_week_over_week_change(row[1][0], row[1][1], higher_is_better=True),
        }
        for row in response.results
    ]


def get_top_sources(
    team: Team,
    limit: int = 5,
    days: int = 7,
    compare: bool = True,
    *,
    execution_mode: ExecutionMode = DEFAULT_DIGEST_EXECUTION_MODE,
    user: User | None = None,
) -> list[dict]:
    tag_queries(product=ProductKey.WEB_ANALYTICS, team_id=team.pk, name="weekly_digest:top_sources")
    response = _run_stats_table_query(
        team, WebStatsBreakdown.INITIAL_REFERRING_DOMAIN, limit, days, compare, execution_mode=execution_mode, user=user
    )

    return [
        {
            "name": row[0] or "",
            "visitors": row[1][0],
            "change": compute_week_over_week_change(row[1][0], row[1][1], higher_is_better=True),
        }
        for row in response.results
        if row[0]
    ]


def get_goals_for_team(
    team: Team,
    limit: int = 5,
    days: int = 7,
    compare: bool = True,
    *,
    execution_mode: ExecutionMode = DEFAULT_DIGEST_EXECUTION_MODE,
    user: User | None = None,
) -> list[dict]:
    tag_queries(product=ProductKey.WEB_ANALYTICS, team_id=team.pk, name="weekly_digest:goals")

    try:
        query = WebGoalsQuery(
            dateRange=DateRange(date_from=f"-{days}d"),
            compareFilter=CompareFilter(compare=compare),
            properties=[],
        )
        runner = WebGoalsQueryRunner(team=team, query=query)
        response = _require_digest_response(runner.run(execution_mode=execution_mode, user=user))
    except NoActionsError:
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


def _digest_date_range(team: Team, days: int) -> QueryDateRange:
    return QueryDateRange(
        date_range=DateRange(date_from=f"-{days}d"),
        team=team,
        timezone_info=team.timezone_info,
        interval=None,
        now=datetime.now(team.timezone_info),
    )


def _has_sessions_in_range(team: Team, date_range: QueryDateRange) -> bool:
    tag_queries(product=ProductKey.WEB_ANALYTICS, team_id=team.pk, name="weekly_digest:session_probe")
    query = parse_select(
        "SELECT 1 FROM events WHERE timestamp >= {date_from} AND timestamp < {date_to} "
        "AND notEmpty(events.$session_id) LIMIT 1",
        placeholders={
            "date_from": ast.Constant(value=date_range.date_from()),
            "date_to": ast.Constant(value=date_range.date_to()),
        },
    )
    response = execute_hogql_query(query_type="web_analytics_digest_session_probe", query=query, team=team)
    return bool(response.results)


def get_digest_metadata(team: Team, overview: dict, days: int = 7) -> dict:
    date_range = _digest_date_range(team, days)
    if overview["sessions"]["current"] or overview["pageviews"]["current"]:
        data_status = DigestDataStatus.OK
    elif _has_sessions_in_range(team, date_range):
        # A plain zero reads as "no traffic", but the project has sessions that the web definition excludes.
        data_status = DigestDataStatus.NO_WEB_SESSIONS
    else:
        data_status = DigestDataStatus.NO_SESSIONS

    return {
        "data_status": data_status.value,
        "date_from": date_range.date_from(),
        "date_to": date_range.date_to(),
        "timezone": team.timezone,
        "filter_test_accounts": True,
        "notes": DIGEST_METRIC_NOTES,
    }


def build_team_digest(
    team: Team,
    days: int = 7,
    compare: bool = True,
    *,
    execution_mode: ExecutionMode = DEFAULT_DIGEST_EXECUTION_MODE,
    user: User | None = None,
) -> dict:
    overview = get_overview_for_team(team, days=days, compare=compare, execution_mode=execution_mode, user=user)
    top_pages = get_top_pages(team, days=days, compare=compare, execution_mode=execution_mode, user=user)
    top_sources = get_top_sources(team, days=days, compare=compare, execution_mode=execution_mode, user=user)
    goals = get_goals_for_team(team, days=days, compare=compare, execution_mode=execution_mode, user=user)

    return {
        "team": team,
        **overview,
        "top_pages": top_pages,
        "top_sources": top_sources,
        "goals": goals,
        "metadata": get_digest_metadata(team, overview, days=days),
        "dashboard_url": f"{settings.SITE_URL}/project/{team.pk}/web?utm_source=web_analytics_weekly_digest&utm_medium=email",
    }


@frozen
class TeamDigestBuild:
    digests: dict[int, dict]
    failed_teams: list[Team]


def build_team_digests(teams: Iterable[Team]) -> TeamDigestBuild:
    digests: dict[int, dict] = {}
    failed_teams: list[Team] = []
    for team in teams:
        try:
            digests[team.id] = build_team_digest(team)
        except Exception as e:
            logger.warning("WA digest could not build a team section", team_id=team.id, error=str(e))
            capture_exception(e, {"team_id": team.id})
            failed_teams.append(team)
    if failed_teams and not digests:
        raise RuntimeError("WA digest: no team section could be built")
    return TeamDigestBuild(digests=digests, failed_teams=failed_teams)


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
