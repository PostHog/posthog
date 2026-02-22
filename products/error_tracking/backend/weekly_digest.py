import datetime

from django.conf import settings
from django.utils import timezone

import structlog

from posthog.schema import ProductKey

from posthog.clickhouse.query_tagging import tag_queries
from posthog.models import Team

logger = structlog.get_logger(__name__)


def get_exception_counts(team_ids: list[int] | None = None) -> list:
    """Exception counts and ingestion failures for the last 7 days"""
    from posthog.clickhouse.client import sync_execute

    tag_queries(product=ProductKey.ERROR_TRACKING, name="weekly_digest:exception_counts")

    team_filter = ""
    query_params: dict = {}
    if team_ids is not None:
        team_filter = "AND team_id IN %(team_ids)s"
        query_params["team_ids"] = team_ids

    # nosemgrep: clickhouse-fstring-param-audit (team_filter is built from trusted code, not user input)
    exception_counts_query = f"""
    SELECT
        team_id,
        countIf(timestamp >= toStartOfDay(now()) - INTERVAL 7 DAY) as exception_count,
        countIf(timestamp >= toStartOfDay(now()) - INTERVAL 7 DAY AND mat_$exception_issue_id IS NULL) as ingestion_failure_count,
        countIf(timestamp < toStartOfDay(now()) - INTERVAL 7 DAY) as prev_exception_count
    FROM events
    WHERE event = '$exception'
    AND timestamp >= toStartOfDay(now()) - INTERVAL 14 DAY
    AND timestamp < toStartOfDay(now())
    {team_filter}
    GROUP BY team_id
    HAVING exception_count > 0
    """

    results = sync_execute(exception_counts_query, query_params)
    return results if isinstance(results, list) else []


def get_crash_free_sessions(team: Team) -> dict:
    """Calculate crash free sessions rate for the last 7 days with previous week comparison."""
    from posthog.hogql.query import execute_hogql_query

    tag_queries(product=ProductKey.ERROR_TRACKING, team_id=team.pk, name="weekly_digest:crash_free_sessions")

    try:
        response = execute_hogql_query(
            query="""
                SELECT
                    uniqIf($session_id, timestamp >= toStartOfDay(now()) - INTERVAL 7 DAY) as total_sessions,
                    uniqIf($session_id, event = '$exception' AND timestamp >= toStartOfDay(now()) - INTERVAL 7 DAY) as crash_sessions,
                    uniqIf($session_id, timestamp < toStartOfDay(now()) - INTERVAL 7 DAY) as prev_total_sessions,
                    uniqIf($session_id, event = '$exception' AND timestamp < toStartOfDay(now()) - INTERVAL 7 DAY) as prev_crash_sessions
                FROM events
                WHERE timestamp >= toStartOfDay(now()) - INTERVAL 14 DAY
                AND timestamp < toStartOfDay(now())
                AND notEmpty($session_id)
            """,
            team=team,
        )
    except Exception:
        logger.exception(f"Failed to query crash free sessions for team {team.pk}")
        return {}

    if not response.results or not response.results[0]:
        return {}

    total_sessions, crash_sessions, prev_total_sessions, prev_crash_sessions = response.results[0]
    if total_sessions == 0:
        return {}

    crash_free_rate = round((1 - crash_sessions / total_sessions) * 100, 2)
    prev_crash_free_rate = (
        round((1 - prev_crash_sessions / prev_total_sessions) * 100, 2) if prev_total_sessions > 0 else None
    )

    result: dict = {
        "total_sessions": total_sessions,
        "crash_free_rate": crash_free_rate,
    }

    result["crash_free_rate_change"] = (
        compute_week_over_week_change(crash_free_rate, prev_crash_free_rate, higher_is_better=True)
        if prev_crash_free_rate is not None
        else None
    )
    result["total_sessions_change"] = compute_week_over_week_change(
        total_sessions, prev_total_sessions, higher_is_better=True
    )

    return result


def compute_week_over_week_change(current: float, previous: float | None, higher_is_better: bool) -> dict | None:
    """Compute a week-over-week percentage change dict for use in email templates.

    Returns None when there's no meaningful comparison (no previous data or 0% change).
    """
    if previous is None or previous == 0:
        return None

    percent_change = ((current - previous) / previous) * 100
    rounded = round(abs(percent_change))
    if rounded == 0:
        return None

    is_increase = percent_change > 0
    direction = "Up" if is_increase else "Down"
    is_good = (is_increase and higher_is_better) or (not is_increase and not higher_is_better)
    color = "#2f7d4f" if is_good else "#a13232"

    return {
        "percent": rounded,
        "direction": direction,
        "color": color,
        "text": f"{direction} {rounded}%",
        "long_text": f"{direction} {rounded}% from previous week",
    }


def get_daily_exception_counts(team_id: int) -> list[dict]:
    """Get exception counts per day for the last 7 days"""
    from posthog.clickhouse.client import sync_execute

    tag_queries(product=ProductKey.ERROR_TRACKING, team_id=team_id, name="weekly_digest:daily_exception_counts")

    try:
        results = sync_execute(
            """
            SELECT
                toDate(timestamp) as day,
                count() as day_count
            FROM events
            WHERE event = '$exception'
            AND team_id = %(team_id)s
            AND timestamp >= toStartOfDay(now()) - INTERVAL 7 DAY
            AND timestamp < toStartOfDay(now())
            GROUP BY day
            ORDER BY day ASC
            """,
            {"team_id": team_id},
        )
    except Exception:
        logger.exception(f"Failed to query daily exception counts for team {team_id}")
        return []

    counts_by_day = {row[0].isoformat(): row[1] for row in results} if isinstance(results, list) else {}

    today = timezone.now().date()
    daily_counts = []
    for i in range(7, 0, -1):
        day = today - datetime.timedelta(days=i)
        count = counts_by_day.get(day.isoformat(), 0)
        daily_counts.append({"day": day.strftime("%a"), "count": count})

    max_count = max((d["count"] for d in daily_counts), default=0)
    for d in daily_counts:
        d["height_percent"] = int((d["count"] / max_count) * 100) if max_count > 0 else 0
        if d["count"] > 0 and d["height_percent"] < 5:
            d["height_percent"] = 5

    return daily_counts


def get_top_issues_for_team(team: Team) -> list[dict]:
    """Query top 5 issues by occurrence count for the last 7 days with sparkline data"""
    from posthog.hogql.query import execute_hogql_query

    from products.error_tracking.backend.models import ErrorTrackingIssue

    tag_queries(product=ProductKey.ERROR_TRACKING, team_id=team.pk, name="weekly_digest:top_issues")

    try:
        response = execute_hogql_query(
            query="""
                SELECT
                    issue_id,
                    sum(day_count) as occurrence_count,
                    groupArray(day_count) as daily_counts
                FROM (
                    SELECT issue_id, toDate(timestamp) as day, count(*) as day_count
                    FROM events
                    WHERE event = '$exception'
                    AND timestamp >= toStartOfDay(now()) - INTERVAL 7 DAY
                    AND timestamp < toStartOfDay(now())
                    AND issue_id IS NOT NULL
                    GROUP BY issue_id, day
                    ORDER BY day ASC
                )
                GROUP BY issue_id
                ORDER BY occurrence_count DESC
                LIMIT 5
            """,
            team=team,
        )
    except Exception:
        logger.exception(f"Failed to query top issues for team {team.pk}")
        return []

    if not response.results:
        return []

    issue_ids = [row[0] for row in response.results if row[0]]
    issues_by_id = {str(issue.id): issue for issue in ErrorTrackingIssue.objects.filter(team=team, id__in=issue_ids)}

    return _build_issues_list(response.results, issues_by_id, team)


def get_new_issues_for_team(team: Team) -> list[dict]:
    """Query top 5 issues first seen in the last 7 days ranked by occurrence count with sparkline data"""
    from posthog.hogql import ast
    from posthog.hogql.query import execute_hogql_query

    from products.error_tracking.backend.models import ErrorTrackingIssue

    tag_queries(product=ProductKey.ERROR_TRACKING, team_id=team.pk, name="weekly_digest:new_issues")

    week_ago = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0) - datetime.timedelta(days=7)
    new_issue_objects = list(
        ErrorTrackingIssue.objects.filter(team=team, created_at__gte=week_ago).values_list("id", flat=True)
    )

    if not new_issue_objects:
        return []

    new_issue_ids = [str(i) for i in new_issue_objects]

    try:
        response = execute_hogql_query(
            query="""
                SELECT
                    issue_id,
                    sum(day_count) as occurrence_count,
                    groupArray(day_count) as daily_counts
                FROM (
                    SELECT issue_id, toDate(timestamp) as day, count(*) as day_count
                    FROM events
                    WHERE event = '$exception'
                    AND timestamp >= toStartOfDay(now()) - INTERVAL 7 DAY
                    AND timestamp < toStartOfDay(now())
                    AND issue_id IN {issue_ids}
                    GROUP BY issue_id, day
                    ORDER BY day ASC
                )
                GROUP BY issue_id
                ORDER BY occurrence_count DESC
                LIMIT 5
            """,
            team=team,
            placeholders={"issue_ids": ast.Constant(value=new_issue_ids)},
        )
    except Exception:
        logger.exception(f"Failed to query new issues for team {team.pk}")
        return []

    if not response.results:
        return []

    result_issue_ids = [row[0] for row in response.results if row[0]]
    issues_by_id = {
        str(issue.id): issue for issue in ErrorTrackingIssue.objects.filter(team=team, id__in=result_issue_ids)
    }

    return _build_issues_list(response.results, issues_by_id, team)


def _build_issues_list(results: list, issues_by_id: dict, team: Team) -> list[dict]:
    """Build issue dicts with sparkline from query results containing issue_id, occurrence_count, daily_counts."""
    issues = []
    for issue_id, occurrence_count, daily_counts in results:
        if not issue_id:
            continue
        issue = issues_by_id.get(str(issue_id))
        sparkline = _daily_counts_to_sparkline(daily_counts)
        issues.append(
            {
                "id": issue_id,
                "name": issue.name if issue else "Unknown issue",
                "description": issue.description if issue else None,
                "occurrence_count": occurrence_count,
                "sparkline": sparkline,
                "url": f"{settings.SITE_URL}/project/{team.pk}/error_tracking/{issue_id}?utm_source=error_tracking_weekly_digest",
            }
        )
    return issues


def _daily_counts_to_sparkline(daily_counts: list[int]) -> list[dict]:
    """Convert a list of daily counts into sparkline bar dicts with height percentages."""
    if not daily_counts:
        return []
    max_val = max(daily_counts)
    return [{"height_percent": int((v / max_val) * 100) if max_val > 0 else 0} for v in daily_counts]


def build_ingestion_failures_url(team_id: int) -> str:
    return (
        f"{settings.SITE_URL}/project/{team_id}/activity/explore#q="
        "%7B%22kind%22%3A%22DataTableNode%22%2C%22full%22%3Atrue%2C%22source%22%3A%7B%22kind%22%3A%22EventsQuery%22%2C"
        "%22select%22%3A%5B%22*%22%2C%22event%22%2C%22person_display_name%20--%20Person%22%2C"
        "%22coalesce(properties.%24current_url%2C%20properties.%24screen_name)%20--%20Url%20%2F%20Screen%22%2C"
        "%22timestamp%22%2C%22properties.events_count%22%2C%22properties.analytics_version%22%5D%2C"
        "%22after%22%3A%22-7d%22%2C%22orderBy%22%3A%5B%22timestamp%20DESC%22%5D%2C"
        "%22event%22%3A%22%24exception%22%2C%22properties%22%3A%5B%7B%22key%22%3A%22%24cymbal_errors%22%2C"
        "%22value%22%3A%22is_set%22%2C%22operator%22%3A%22is_set%22%2C%22type%22%3A%22event%22%7D%5D%7D%2C"
        "%22propertiesViaUrl%22%3Atrue%2C%22showSavedQueries%22%3Atrue%2C"
        "%22showPersistentColumnConfigurator%22%3Atrue%7D"
    )
