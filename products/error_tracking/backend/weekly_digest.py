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
from posthog.utils import compact_number

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


def _query_daily_rows(team: Team) -> list:
    """Per-day counts over 14 days. Explicit LIMIT: HogQL appends LIMIT 100 to unlimited selects.

    Missing ``$exception_issue_id`` = ingestion failure. Query errors propagate so the task retries
    instead of mistaking a failure for "no activity".
    """
    from posthog.hogql.query import execute_hogql_query

    tag_queries(product=ProductKey.ERROR_TRACKING, team_id=team.pk, name="weekly_digest:daily_rows")

    response = execute_hogql_query(
        query="""
            SELECT
                toDate(timestamp) AS day,
                count() AS day_count,
                countIf(isNull(properties.$exception_issue_id)) AS failure_count
            FROM events
            WHERE event = '$exception'
            AND timestamp >= toStartOfDay(now()) - INTERVAL 14 DAY
            AND timestamp < toStartOfDay(now())
            AND {filters}
            GROUP BY day
            ORDER BY day ASC
            LIMIT 14
        """,
        team=team,
        filters=HogQLFilters(filterTestAccounts=True),
    )
    return response.results or []


def get_exception_summary_for_team(team: Team, daily_rows: list | None = None) -> dict:
    """Exception counts, ingestion failures, and previous-week count. This week = 1-7 days ago, previous = 8-14."""
    if daily_rows is None:
        daily_rows = _query_daily_rows(team)
    if not daily_rows:
        return {}

    # ClickHouse returns team-timezone dates, so bucket against the team-local today, not UTC
    today = timezone.now().astimezone(team.timezone_info).date()
    exception_count = 0
    ingestion_failure_count = 0
    prev_exception_count = 0
    for day, day_count, failure_count in daily_rows:
        days_ago = (today - day).days
        if 1 <= days_ago <= 7:
            exception_count += day_count
            ingestion_failure_count += failure_count
        elif 8 <= days_ago <= 14:
            prev_exception_count += day_count

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
    """Per-team exception counts over the last 7 days: ``(team_id, count)`` rows.

    Used both for digest routing (which teams have any exceptions) and to pick a first-time user's
    busiest project without needing a per-team build.
    """
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
    SELECT team_id, count() AS exception_count
    FROM events
    WHERE event = '$exception'
    AND timestamp >= toStartOfDay(now()) - INTERVAL 7 DAY
    AND timestamp < toStartOfDay(now())
    {team_filter}
    GROUP BY team_id
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

    # A ClickHouse failure propagates (task fails and retries) rather than being swallowed into an
    # empty result. A successful query with no sessions still returns {} below.
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


def get_daily_exception_counts(team: Team, daily_rows: list | None = None) -> list[dict]:
    """Exception counts per day for the last 7 days, as sparkline-ready bars."""
    if daily_rows is None:
        daily_rows = _query_daily_rows(team)

    # ClickHouse returns team-timezone dates, so bucket against the team-local today, not UTC
    today = timezone.now().astimezone(team.timezone_info).date()
    counts_by_day: dict[datetime.date, int] = {}
    for day, day_count, _failure_count in daily_rows:
        if 1 <= (today - day).days <= 7:
            counts_by_day[day] = day_count

    daily_counts: list[dict[str, Any]] = []
    for i in range(7, 0, -1):
        day = today - datetime.timedelta(days=i)
        count = counts_by_day.get(day, 0)
        daily_counts.append({"day": day.strftime("%a"), "count": count})

    max_count = max((d["count"] for d in daily_counts), default=0)
    for d in daily_counts:
        d["height_percent"] = int((d["count"] / max_count) * 100) if max_count > 0 else 0
        if d["count"] > 0 and d["height_percent"] < 5:
            d["height_percent"] = 5

    return daily_counts


def _query_issue_rows(team: Team) -> list:
    """Ranked ``(issue_id, occurrence_count, daily_counts, is_new)`` rows for the last 7 days.

    ``LIMIT 5 BY is_new`` (≤10 rows) feeds both the top-issues and new-issues sections: the overall
    top 5 is always a subset of the per-group union. ``issue_id_v2`` and ``issue_first_seen`` come
    from the fingerprint issue state table, so merged issues are attributed and dated like the error
    tracking UI. Newness is computed in-query — embedding issue ids would make the rendered SQL grow
    with issue cardinality (ClickHouse caps query text at 1 MiB).
    """
    from posthog.hogql.query import execute_hogql_query

    tag_queries(product=ProductKey.ERROR_TRACKING, team_id=team.pk, name="weekly_digest:issue_rows")

    response = execute_hogql_query(
        query="""
            SELECT
                issue_id,
                sum(day_count) AS occurrence_count,
                arrayMap(x -> tupleElement(x, 2), arraySort(x -> tupleElement(x, 1), groupArray(tuple(day, day_count)))) AS daily_counts,
                if(min(first_seen) >= toStartOfDay(now()) - INTERVAL 7 DAY, 1, 0) AS is_new
            FROM (
                SELECT
                    issue_id_v2 AS issue_id,
                    toDate(timestamp) AS day,
                    count() AS day_count,
                    min(issue_first_seen) AS first_seen
                FROM events
                WHERE event = '$exception'
                AND timestamp >= toStartOfDay(now()) - INTERVAL 7 DAY
                AND timestamp < toStartOfDay(now())
                AND isNotNull(issue_id_v2)
                AND {filters}
                GROUP BY issue_id, day
            )
            GROUP BY issue_id
            ORDER BY occurrence_count DESC
            LIMIT 5 BY is_new
            LIMIT 10
        """,
        team=team,
        filters=HogQLFilters(filterTestAccounts=True),
    )
    return response.results or []


def _issues_payload(issue_rows: list, team: Team) -> list[dict]:
    """Top 5 of the given ranked rows, hydrated with issue names from Postgres."""
    from products.error_tracking.backend.models import ErrorTrackingIssue

    ranked = sorted(issue_rows, key=lambda row: row[1], reverse=True)[:5]
    if not ranked:
        return []

    ranked = [(issue_id, occurrence_count, daily_counts) for issue_id, occurrence_count, daily_counts, _ in ranked]
    issue_ids = [row[0] for row in ranked]
    issues_by_id = {str(issue.id): issue for issue in ErrorTrackingIssue.objects.filter(team=team, id__in=issue_ids)}
    return _build_issues_list(ranked, issues_by_id, team)


def get_top_issues_for_team(team: Team, issue_rows: list | None = None) -> list[dict]:
    """Top 5 issues by occurrence count for the last 7 days with sparkline data."""
    if issue_rows is None:
        issue_rows = _query_issue_rows(team)
    return _issues_payload(issue_rows, team)


def get_new_issues_for_team(team: Team, issue_rows: list | None = None) -> list[dict]:
    """Top 5 issues first seen in the last 7 days ranked by occurrence count with sparkline data."""
    if issue_rows is None:
        issue_rows = _query_issue_rows(team)
    return _issues_payload([row for row in issue_rows if row[3]], team)


def _build_issues_list(results: list, issues_by_id: dict, team: Team) -> list[dict]:
    """Build issue dicts with sparkline from query results containing issue_id, occurrence_count, daily_counts."""
    from products.error_tracking.backend.logic import build_issue_permalink_path, list_first_fingerprints

    issue_ids = [issue_id for issue_id, _, _ in results if issue_id]
    fingerprints_by_issue_id = {
        str(fingerprint.issue_id): fingerprint.fingerprint
        for fingerprint in list_first_fingerprints(team_id=team.pk, issue_ids=issue_ids)
    }

    issues = []
    for issue_id, occurrence_count, daily_counts in results:
        if not issue_id:
            continue
        issue = issues_by_id.get(str(issue_id))
        sparkline = _daily_counts_to_sparkline(daily_counts)
        permalink_path = build_issue_permalink_path(
            project_id=team.pk, issue_id=issue_id, fingerprint=fingerprints_by_issue_id.get(str(issue_id))
        )
        issues.append(
            {
                "id": issue_id,
                "name": issue.name if issue else "Unknown issue",
                "description": issue.description if issue else None,
                "occurrence_count": occurrence_count,
                "sparkline": sparkline,
                "url": f"{settings.SITE_URL}{permalink_path}?utm_source=error_tracking_weekly_digest",
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

    # Two bounded ClickHouse passes + crash-free: three queries per team instead of five.
    daily_rows = _query_daily_rows(team)
    counts = get_exception_summary_for_team(team, daily_rows)
    if not counts or counts["exception_count"] == 0:
        return None

    issue_rows = _query_issue_rows(team)

    return {
        "team": team,
        "exception_count": counts["exception_count"],
        "exception_change": compute_week_over_week_change(
            counts["exception_count"], counts["prev_exception_count"], higher_is_better=False
        ),
        "ingestion_failure_count": counts["ingestion_failure_count"],
        "top_issues": get_top_issues_for_team(team, issue_rows),
        "new_issues": get_new_issues_for_team(team, issue_rows),
        "daily_counts": get_daily_exception_counts(team, daily_rows),
        "crash_free": get_crash_free_sessions(team),
        "source_maps_recommendation": get_source_maps_recommendation_for_team(team),
        "error_tracking_url": f"{settings.SITE_URL}/project/{team.pk}/error_tracking?utm_source=error_tracking_weekly_digest",
        "ingestion_failures_url": build_ingestion_failures_url(team.pk),
    }


def build_team_section_payload(data: dict[str, Any]) -> dict[str, Any]:
    """JSON-safe project section for the digest workflow webhook payload.

    Big counts are pre-formatted here because the email template (Liquid) has no
    number formatting filter. ingestion_failure_count must stay numeric — the
    template branches on `> 0` — so it gets a display twin instead. Copies, not
    in-place mutation: the same data dict is reused across recipients.
    """

    def serialize_issue(issue: dict[str, Any]) -> dict[str, Any]:
        return {**issue, "id": str(issue["id"]), "occurrence_count": compact_number(issue["occurrence_count"])}

    section = {k: v for k, v in data.items() if k != "team"}
    section["team_name"] = data["team"].name
    section["exception_count"] = compact_number(data["exception_count"])
    section["ingestion_failure_count_display"] = compact_number(data["ingestion_failure_count"])
    if data["crash_free"]:
        section["crash_free"] = {
            **data["crash_free"],
            "total_sessions": compact_number(data["crash_free"]["total_sessions"]),
        }
    section["top_issues"] = [serialize_issue(i) for i in data["top_issues"]]
    section["new_issues"] = [serialize_issue(i) for i in data["new_issues"]]
    return section


# Webhook trigger of the "[Error tracking] Weekly digest email" workflow in the internal
# PostHog project. Protected by WORKFLOWS_WEBHOOK_SECRET, so the URL is not a secret.
DIGEST_WORKFLOW_WEBHOOK_URL = "https://webhooks.us.posthog.com/public/webhooks/019f2754-aeff-0000-6a0d-5d3933a94b08"


def send_digest_to_workflow(digest: dict[str, Any], distinct_id: str) -> None:
    """POST one recipient's digest to the delivery workflow's webhook trigger.

    Raises on failure so callers (celery autoretry) can retry.
    """
    headers = {}
    if settings.WORKFLOWS_WEBHOOK_SECRET:
        headers["Authorization"] = settings.WORKFLOWS_WEBHOOK_SECRET

    response = requests.post(
        DIGEST_WORKFLOW_WEBHOOK_URL,
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
