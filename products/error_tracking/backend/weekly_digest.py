import datetime

from django.conf import settings
from django.utils import timezone

import structlog

from posthog.models import Team

logger = structlog.get_logger(__name__)


def get_exception_counts(team_ids: list[int] | None = None) -> list:
    """Query ClickHouse for exception counts and ingestion failures, optionally filtered to specific team IDs"""
    from posthog.clickhouse.client import sync_execute

    team_filter = ""
    query_params: dict = {}
    if team_ids is not None:
        team_filter = "AND team_id IN %(team_ids)s"
        query_params["team_ids"] = team_ids

    exception_counts_query = f"""
    SELECT
        team_id,
        count() as exception_count,
        countIf(mat_$exception_issue_id IS NULL) as ingestion_failure_count
    FROM events
    WHERE event = '$exception'
    AND timestamp >= now() - INTERVAL 7 DAY
    AND timestamp < now()
    {team_filter}
    GROUP BY team_id
    HAVING exception_count > 0
    """

    results = sync_execute(exception_counts_query, query_params)
    return results if isinstance(results, list) else []


def get_crash_free_sessions(team: Team) -> dict:
    """Calculate crash free sessions rate for the last 7 days via HogQL"""
    from posthog.hogql.query import execute_hogql_query

    try:
        response = execute_hogql_query(
            query="""
                SELECT
                    uniq($session_id) as total_sessions,
                    uniqIf($session_id, event = '$exception') as crash_sessions
                FROM events
                WHERE timestamp >= now() - INTERVAL 7 DAY
                AND timestamp < now()
                AND notEmpty($session_id)
            """,
            team=team,
        )
    except Exception:
        logger.exception(f"Failed to query crash free sessions for team {team.pk}")
        return {}

    if not response.results or not response.results[0]:
        return {}

    total_sessions, crash_sessions = response.results[0]
    if total_sessions == 0:
        return {}

    crash_free_rate = round((1 - crash_sessions / total_sessions) * 100, 2)
    return {
        "total_sessions": total_sessions,
        "crash_sessions": crash_sessions,
        "crash_free_rate": crash_free_rate,
    }


def get_daily_exception_counts(team_id: int) -> list[dict]:
    """Get exception counts per day for the last 7 days from ClickHouse"""
    from posthog.clickhouse.client import sync_execute

    try:
        results = sync_execute(
            """
            SELECT
                toDate(timestamp) as day,
                count() as day_count
            FROM events
            WHERE event = '$exception'
            AND team_id = %(team_id)s
            AND timestamp >= toStartOfDay(now() - INTERVAL 7 DAY)
            AND timestamp < now()
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
        d["height_pct"] = int((d["count"] / max_count) * 100) if max_count > 0 else 0
        if d["count"] > 0 and d["height_pct"] < 5:
            d["height_pct"] = 5

    return daily_counts


def get_top_issues_for_team(team: Team) -> list[dict]:
    """Query top 5 issues by occurrence count in the last 7 days via HogQL"""
    from posthog.hogql.query import execute_hogql_query

    from products.error_tracking.backend.models import ErrorTrackingIssue

    try:
        response = execute_hogql_query(
            query="""
                SELECT issue_id, count(*) as occurrence_count
                FROM events
                WHERE event = '$exception'
                AND timestamp >= now() - INTERVAL 7 DAY
                AND timestamp < now()
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

    sparklines = _get_issue_sparklines(team, issue_ids)

    top_issues = []
    for issue_id, occurrence_count in response.results:
        if not issue_id:
            continue
        issue = issues_by_id.get(str(issue_id))
        top_issues.append(
            {
                "id": issue_id,
                "name": issue.name if issue else "Unknown issue",
                "description": issue.description if issue else None,
                "occurrence_count": occurrence_count,
                "sparkline": sparklines.get(str(issue_id), []),
                "url": f"{settings.SITE_URL}/project/{team.pk}/error_tracking/{issue_id}",
            }
        )

    return top_issues


def get_new_issues_for_team(team: Team) -> list[dict]:
    """Query top 5 issues first seen in the last 7 days, ranked by occurrence count"""
    from posthog.hogql import ast
    from posthog.hogql.query import execute_hogql_query

    from products.error_tracking.backend.models import ErrorTrackingIssue

    week_ago = timezone.now() - datetime.timedelta(days=7)
    new_issue_objects = list(
        ErrorTrackingIssue.objects.filter(team=team, created_at__gte=week_ago).values_list("id", flat=True)
    )

    if not new_issue_objects:
        return []

    new_issue_ids = [str(i) for i in new_issue_objects]

    try:
        response = execute_hogql_query(
            query="SELECT issue_id, count(*) as occurrence_count FROM events WHERE event = '$exception' AND timestamp >= now() - INTERVAL 7 DAY AND timestamp < now() AND issue_id IN {issue_ids} GROUP BY issue_id ORDER BY occurrence_count DESC LIMIT 5",
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

    sparklines = _get_issue_sparklines(team, result_issue_ids)

    new_issues = []
    for issue_id, occurrence_count in response.results:
        if not issue_id:
            continue
        issue = issues_by_id.get(str(issue_id))
        new_issues.append(
            {
                "id": issue_id,
                "name": issue.name if issue else "Unknown issue",
                "description": issue.description if issue else None,
                "occurrence_count": occurrence_count,
                "sparkline": sparklines.get(str(issue_id), []),
                "url": f"{settings.SITE_URL}/project/{team.pk}/error_tracking/{issue_id}",
            }
        )

    return new_issues


def _get_issue_sparklines(team: Team, issue_ids: list[str]) -> dict[str, list[dict]]:
    """Get daily occurrence counts per issue for sparkline bars"""
    from posthog.hogql import ast
    from posthog.hogql.query import execute_hogql_query

    if not issue_ids:
        return {}

    try:
        response = execute_hogql_query(
            query="SELECT issue_id, toDate(timestamp) as day, count(*) as day_count FROM events WHERE event = '$exception' AND timestamp >= toStartOfDay(now() - INTERVAL 7 DAY) AND timestamp < now() AND issue_id IN {issue_ids} GROUP BY issue_id, day ORDER BY issue_id, day ASC",
            team=team,
            placeholders={"issue_ids": ast.Constant(value=issue_ids)},
        )
    except Exception:
        logger.exception(f"Failed to query issue sparklines for team {team.pk}")
        return {}

    if not response.results:
        return {}

    counts_by_issue: dict[str, dict[str, int]] = {}
    for issue_id, day, count in response.results:
        issue_str = str(issue_id)
        if issue_str not in counts_by_issue:
            counts_by_issue[issue_str] = {}
        day_str = day.isoformat() if hasattr(day, "isoformat") else str(day)
        counts_by_issue[issue_str][day_str] = count

    today = timezone.now().date()
    sparklines: dict[str, list[dict]] = {}

    for issue_id, daily_map in counts_by_issue.items():
        bars = []
        for i in range(7, 0, -1):
            day = today - datetime.timedelta(days=i)
            bars.append(daily_map.get(day.isoformat(), 0))
        max_val = max(bars) if bars else 0
        sparklines[issue_id] = [{"height_pct": int((v / max_val) * 100) if max_val > 0 else 0} for v in bars]

    return sparklines


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
