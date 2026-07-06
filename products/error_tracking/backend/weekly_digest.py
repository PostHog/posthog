import datetime
from typing import Any

from django.conf import settings
from django.utils import timezone

import requests
import structlog

from posthog.schema import HogQLFilters

from posthog.clickhouse.query_tagging import tag_queries
from posthog.models import Team
from posthog.schema_enums import ProductKey

logger = structlog.get_logger(__name__)

DIGEST_WEBHOOK_TIMEOUT_SECONDS = 10

# Keep in sync with SOURCE_MAPS_DOCS_URL in sourceMapsFixWizardLogic.ts
SOURCE_MAPS_DOCS_URL = "https://posthog.com/docs/error-tracking/upload-source-maps"


def get_org_ids_with_exceptions() -> list[str]:
    """Return distinct organization IDs that have teams with exceptions in the last 7 days"""
    teams_with_exceptions = get_exception_counts()
    team_id_set = {row[0] for row in teams_with_exceptions}
    if not team_id_set:
        return []

    org_ids = list(Team.objects.filter(id__in=team_id_set).values_list("organization_id", flat=True).distinct())
    return org_ids


def get_exception_summary_for_team(team: Team) -> dict:
    """Get filtered exception counts, ingestion failures, and prev week count for a single team."""
    from posthog.hogql.query import execute_hogql_query

    tag_queries(product=ProductKey.ERROR_TRACKING, team_id=team.pk, name="weekly_digest:exception_summary")

    try:
        response = execute_hogql_query(
            query="""
                SELECT
                    countIf(timestamp >= toStartOfDay(now()) - INTERVAL 7 DAY) as exception_count,
                    countIf(timestamp >= toStartOfDay(now()) - INTERVAL 7 DAY AND issue_id IS NULL) as ingestion_failure_count,
                    countIf(timestamp < toStartOfDay(now()) - INTERVAL 7 DAY) as prev_exception_count
                FROM events
                WHERE event = '$exception'
                AND timestamp >= toStartOfDay(now()) - INTERVAL 14 DAY
                AND timestamp < toStartOfDay(now())
                AND {filters}
            """,
            team=team,
            filters=HogQLFilters(filterTestAccounts=True),
        )
    except Exception:
        logger.exception(f"Failed to query exception summary for team {team.pk}")
        return {}

    if not response.results or not response.results[0]:
        return {}

    exception_count, ingestion_failure_count, prev_exception_count = response.results[0]
    return {
        "exception_count": exception_count,
        "ingestion_failure_count": ingestion_failure_count,
        "prev_exception_count": prev_exception_count,
    }


ELIGIBLE_ROLES_FOR_AUTO_DIGEST = {"engineering", "data", "founder"}


def auto_select_project_for_user(user: Any, org_id: int, team_exception_counts: dict[int, dict]) -> bool:
    """For first-time users who have no ET digest project settings, auto-select the project with the most exceptions
    and persist the selection to their notification settings.

    Only auto-enrolls users with engineering, data, or founder roles. Users with other roles
    (marketing, sales, leadership, product, other, None) are marked as "processed" with an empty
    project map so auto-selection doesn't run again - they can still opt in manually via settings.
    """
    from posthog.models.user import User
    from posthog.tasks.email_utils import auto_select_digest_project

    setting_key = "error_tracking_weekly_digest_project_enabled"
    current_settings = user.partial_notification_settings or {}
    if setting_key in current_settings:
        return False

    if not team_exception_counts:
        return False

    role = (user.role_at_organization or "").lower()
    if role not in ELIGIBLE_ROLES_FOR_AUTO_DIGEST:
        current_settings[setting_key] = {}
        User.objects.filter(pk=user.pk).update(partial_notification_settings=current_settings)
        return True

    return auto_select_digest_project(
        user=user,
        team_data=team_exception_counts,
        setting_key=setting_key,
        sort_key=lambda d: d["exception_count"],
    )


def get_exception_counts(team_ids: list[int] | None = None) -> list:
    """Teams with at least one exception in the last 7 days, used for digest routing."""
    from posthog.clickhouse.client import sync_execute
    from posthog.clickhouse.workload import Workload

    tag_queries(product=ProductKey.ERROR_TRACKING, name="weekly_digest:exception_counts")

    team_filter = ""
    query_params: dict = {}
    if team_ids is not None:
        team_filter = "AND team_id IN %(team_ids)s"
        query_params["team_ids"] = team_ids

    # nosemgrep: clickhouse-fstring-param-audit (team_filter is built from trusted code, not user input)
    query = f"""
    SELECT DISTINCT team_id
    FROM events
    WHERE event = '$exception'
    AND timestamp >= toStartOfDay(now()) - INTERVAL 7 DAY
    AND timestamp < toStartOfDay(now())
    {team_filter}
    """

    # Cross-team scan for a weekly batch job — keep it off the online cluster.
    results = sync_execute(query, query_params, workload=Workload.OFFLINE)
    return results if isinstance(results, list) else []


def get_crash_free_sessions(team: Team) -> dict:
    """Calculate crash free sessions rate for the last 7 days with previous week comparison."""
    from posthog.hogql.query import execute_hogql_query

    # posthog.tasks.__init__ eagerly imports every task module (celery autoimport);
    # import the helper at call time so this module doesn't pull the task graph.
    from posthog.tasks.email_utils import compute_week_over_week_change  # noqa: PLC0415

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
                AND {filters}
            """,
            team=team,
            filters=HogQLFilters(filterTestAccounts=True),
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


def get_daily_exception_counts(team: Team) -> list[dict]:
    """Get exception counts per day for the last 7 days"""
    from posthog.hogql.query import execute_hogql_query

    tag_queries(product=ProductKey.ERROR_TRACKING, team_id=team.pk, name="weekly_digest:daily_exception_counts")

    try:
        response = execute_hogql_query(
            query="""
            SELECT
                toDate(timestamp) as day,
                count() as day_count
            FROM events
            WHERE event = '$exception'
            AND timestamp >= toStartOfDay(now()) - INTERVAL 7 DAY
            AND timestamp < toStartOfDay(now())
            AND {filters}
            GROUP BY day
            ORDER BY day ASC
            """,
            team=team,
            filters=HogQLFilters(filterTestAccounts=True),
        )
    except Exception:
        logger.exception(f"Failed to query daily exception counts for team {team.pk}")
        return []

    results = response.results or []
    counts_by_day = {row[0].isoformat(): row[1] for row in results}

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
                    AND {filters}
                    GROUP BY issue_id, day
                    ORDER BY day ASC
                )
                GROUP BY issue_id
                ORDER BY occurrence_count DESC
                LIMIT 5
            """,
            team=team,
            filters=HogQLFilters(filterTestAccounts=True),
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
                    AND {filters}
                    GROUP BY issue_id, day
                    ORDER BY day ASC
                )
                GROUP BY issue_id
                ORDER BY occurrence_count DESC
                LIMIT 5
            """,
            team=team,
            placeholders={"issue_ids": ast.Constant(value=new_issue_ids)},
            filters=HogQLFilters(filterTestAccounts=True),
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


def _source_maps_wizard_command() -> str:
    """Source maps upload wizard command, mirroring sourceMapsFixWizardLogic on the frontend.

    Appends ``--region eu`` on EU Cloud so the wizard uploads to the right region.
    """
    region_flag = " --region eu" if (settings.CLOUD_DEPLOYMENT or "").upper() == "EU" else ""
    return f"npx -y @posthog/wizard@latest upload-source-maps{region_flag}"


def get_source_maps_recommendation_for_team(team: Team) -> dict | None:
    """Return wizard prompt data when the team has an active 'missing source maps' recommendation.

    Mirrors the in-app banner: only surface it once the recommendation has been computed, while
    there's still a problem (not completed), and the user hasn't dismissed it. Returns ``None``
    otherwise so the digest can omit the section entirely.
    """
    from products.error_tracking.backend.logic.recommendations import RECOMMENDATIONS_BY_TYPE
    from products.error_tracking.backend.models import ErrorTrackingRecommendation

    rec = RECOMMENDATIONS_BY_TYPE.get("source_maps")
    if rec is None:
        return None

    recommendation = ErrorTrackingRecommendation.objects.filter(
        team=team, type="source_maps", dismissed_at__isnull=True
    ).first()
    if recommendation is None or recommendation.computed_at is None:
        return None

    meta = recommendation.meta or {}
    if rec.is_completed(meta):
        return None

    return {
        "unresolved_percent": round((meta.get("unresolved_pct") or 0.0) * 100),
        "lookback_hours": meta.get("lookback_hours"),
        "wizard_command": _source_maps_wizard_command(),
        "docs_url": f"{SOURCE_MAPS_DOCS_URL}?utm_source=error_tracking_weekly_digest",
    }


def build_team_digest_data(team: Team) -> dict[str, Any] | None:
    """Assemble all digest data for one team, or None when it had no exceptions this week."""
    # posthog.tasks.__init__ eagerly imports every task module (celery autoimport);
    # import the helper at call time so this module doesn't pull the task graph.
    from posthog.tasks.email_utils import compute_week_over_week_change  # noqa: PLC0415

    counts = get_exception_summary_for_team(team)
    if not counts or counts["exception_count"] == 0:
        return None

    return {
        "team": team,
        "exception_count": counts["exception_count"],
        "exception_change": compute_week_over_week_change(
            counts["exception_count"], counts["prev_exception_count"], higher_is_better=False
        ),
        "ingestion_failure_count": counts["ingestion_failure_count"],
        "top_issues": get_top_issues_for_team(team),
        "new_issues": get_new_issues_for_team(team),
        "daily_counts": get_daily_exception_counts(team),
        "crash_free": get_crash_free_sessions(team),
        "source_maps_recommendation": get_source_maps_recommendation_for_team(team),
        "error_tracking_url": f"{settings.SITE_URL}/project/{team.pk}/error_tracking?utm_source=error_tracking_weekly_digest",
        "ingestion_failures_url": build_ingestion_failures_url(team.pk),
    }


def build_team_section_payload(data: dict[str, Any]) -> dict[str, Any]:
    """JSON-safe project section for the digest workflow webhook payload."""

    def serialize_issue(issue: dict[str, Any]) -> dict[str, Any]:
        return {**issue, "id": str(issue["id"])}

    section = {k: v for k, v in data.items() if k != "team"}
    section["team_name"] = data["team"].name
    section["top_issues"] = [serialize_issue(i) for i in data["top_issues"]]
    section["new_issues"] = [serialize_issue(i) for i in data["new_issues"]]
    return section


def get_digest_workflow_webhook_url() -> str | None:
    """Public webhook URL of the workflow that delivers the digest email, or None when not configured."""
    workflow_id = settings.ERROR_TRACKING_WEEKLY_DIGEST_WORKFLOW_ID
    if not workflow_id:
        return None

    webhooks_host = {
        "US": "https://webhooks.us.posthog.com",
        "EU": "https://webhooks.eu.posthog.com",
        "DEV": "https://app.dev.posthog.dev",
    }.get((settings.CLOUD_DEPLOYMENT or "").upper(), settings.SITE_URL)
    return f"{webhooks_host}/public/webhooks/{workflow_id}"


def send_digest_to_workflow(digest: dict[str, Any], distinct_id: str) -> None:
    """POST one recipient's digest to the delivery workflow's webhook trigger.

    Raises on failure so callers (celery autoretry) can retry.
    """
    webhook_url = get_digest_workflow_webhook_url()
    if not webhook_url:
        raise ValueError("ERROR_TRACKING_WEEKLY_DIGEST_WORKFLOW_ID is not configured")

    # The workflow trigger's "auth_header" input compares the Authorization header verbatim,
    # so the secret must be the full header value (e.g. "Bearer <token>").
    headers = {}
    if settings.ERROR_TRACKING_WEEKLY_DIGEST_WEBHOOK_SECRET:
        headers["Authorization"] = settings.ERROR_TRACKING_WEEKLY_DIGEST_WEBHOOK_SECRET

    response = requests.post(
        webhook_url,
        json={
            "event": "error_tracking_weekly_digest",
            "distinct_id": distinct_id,
            "digest": digest,
        },
        headers=headers,
        timeout=DIGEST_WEBHOOK_TIMEOUT_SECONDS,
    )
    response.raise_for_status()


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
