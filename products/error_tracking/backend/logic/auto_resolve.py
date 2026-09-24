"""Resolve inactive issues after the team-configured window.

The ingestion receipt watermark protects against delayed events and ClickHouse lag.
The event query adds a conservative check across all fingerprints for each issue.
"""

from datetime import datetime, timedelta
from uuid import UUID

from django.core.cache import cache
from django.db.models import DateTimeField, QuerySet
from django.db.models.functions import Coalesce
from django.utils import timezone

import structlog

from posthog.schema import ProductKey

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen

from products.error_tracking.backend.logic.recommendations.long_running_issues import exception_fingerprint_expr
from products.error_tracking.backend.models import (
    AUTO_RESOLVE_RECEIPT_GRACE_PERIOD,
    ErrorTrackingIssue,
    ErrorTrackingIssueFingerprintV2,
    ErrorTrackingSettings,
)

logger = structlog.get_logger(__name__)

# A fixed upper bound lets each traversal finish even while new issues arrive.
MAX_ISSUES_PER_TEAM_RUN = 1000
CURSOR_TTL_SECONDS = 30 * 24 * 60 * 60

RECENT_FINGERPRINTS_QUERY = """
    SELECT DISTINCT {fingerprint_expr} AS fingerprint
    FROM events
    WHERE team_id = %(team_id)s
        AND event = '$exception'
        AND timestamp >= %(cutoff)s
        AND {fingerprint_expr} IN %(fingerprints)s
"""


@frozen
class TeamAutoResolveSetting:
    team_id: int
    days: int | None


def get_auto_resolve_team_settings() -> list[TeamAutoResolveSetting]:
    settings_by_team = {
        setting.team_id: setting.auto_resolve_after_days
        for setting in ErrorTrackingSettings.objects.filter(auto_resolve_after_days__isnull=False).only(
            "team_id", "auto_resolve_after_days"
        )
    }
    # Pending writes must still reach ClickHouse after auto-resolve is disabled.
    pending_team_ids = (
        ErrorTrackingIssue.objects.filter(auto_resolve_sync_requested_at__isnull=False)
        .order_by()
        .values_list("team_id", flat=True)
        .distinct()
    )
    for team_id in pending_team_ids:
        settings_by_team.setdefault(team_id, None)
    return [TeamAutoResolveSetting(team_id=team_id, days=days) for team_id, days in sorted(settings_by_team.items())]


def _candidate_issues(team_id: int, cutoff: datetime) -> QuerySet[ErrorTrackingIssue]:
    # State age gives new and manually reactivated issues a complete grace period.
    return (
        ErrorTrackingIssue.objects.filter(
            team_id=team_id,
            status=ErrorTrackingIssue.Status.ACTIVE,
            last_received_at__lt=cutoff - AUTO_RESOLVE_RECEIPT_GRACE_PERIOD,
        )
        .annotate(last_state_change=Coalesce("state_updated_at", "created_at", output_field=DateTimeField()))
        .filter(last_state_change__lt=cutoff)
    )


def _recently_seen_fingerprints(team_id: int, fingerprints: list[str], cutoff: datetime) -> set[str]:
    if not fingerprints:
        return set()
    tag_queries(product=ProductKey.ERROR_TRACKING, feature=Feature.ENRICHMENT, name="auto_resolve:recent_fingerprints")
    rows = sync_execute(
        RECENT_FINGERPRINTS_QUERY.format(fingerprint_expr=exception_fingerprint_expr()),
        {"team_id": team_id, "cutoff": cutoff, "fingerprints": fingerprints},
        workload=Workload.OFFLINE,
    )
    return {row[0] for row in rows}


def find_inactive_issue_ids(team_id: int, candidate_ids: list[UUID], cutoff: datetime) -> list[UUID]:
    if not candidate_ids:
        return []

    fingerprints_by_issue: dict[UUID, list[str]] = {}
    for issue_id, fingerprint in ErrorTrackingIssueFingerprintV2.objects.filter(
        team_id=team_id, issue_id__in=candidate_ids
    ).values_list("issue_id", "fingerprint"):
        fingerprints_by_issue.setdefault(issue_id, []).append(fingerprint)

    all_fingerprints = [fp for fps in fingerprints_by_issue.values() for fp in fps]
    recent = _recently_seen_fingerprints(team_id, all_fingerprints, cutoff)

    return [
        issue_id
        for issue_id in candidate_ids
        if fingerprints_by_issue.get(issue_id) and not any(fp in recent for fp in fingerprints_by_issue[issue_id])
    ]


def auto_resolve_team(team_id: int) -> int:
    # Lifecycle events import the Temporal package, which imports this module through activities.
    from products.error_tracking.backend.logic.auto_resolve_sync import retry_auto_resolve_sync  # noqa: PLC0415
    from products.error_tracking.backend.logic.issue_mutations import auto_resolve_issues  # noqa: PLC0415

    retry_auto_resolve_sync(team_id)
    setting = ErrorTrackingSettings.objects.filter(team_id=team_id).first()
    if setting is None or setting.auto_resolve_after_days is None:
        return 0
    days = setting.auto_resolve_after_days
    cutoff = timezone.now() - timedelta(days=days)
    cursor_key = f"error_tracking:auto_resolve:cursor:v2:{team_id}"
    cursor: dict[str, str] | None = cache.get(cursor_key)
    candidates = _candidate_issues(team_id, cutoff)
    through = (
        UUID(cursor["through"])
        if cursor is not None
        else candidates.order_by("-id").values_list("id", flat=True).first()
    )
    page = candidates.filter(id__lte=through) if through is not None else candidates.none()
    if cursor is not None:
        page = page.filter(id__gt=UUID(cursor["after"]))
    candidate_ids = list(page.order_by("id").values_list("id", flat=True)[:MAX_ISSUES_PER_TEAM_RUN])
    if not candidate_ids and cursor is not None:
        through = candidates.order_by("-id").values_list("id", flat=True).first()
        candidate_ids = (
            list(
                candidates.filter(id__lte=through).order_by("id").values_list("id", flat=True)[:MAX_ISSUES_PER_TEAM_RUN]
            )
            if through is not None
            else []
        )
    if not candidate_ids:
        cache.delete(cursor_key)
        return 0

    inactive_ids = find_inactive_issue_ids(team_id, candidate_ids, cutoff)
    resolved = auto_resolve_issues(team_id, inactive_ids, cutoff=cutoff, days=days) if inactive_ids else []

    # Save progress only after the query and mutation succeed. Cache loss safely repeats work.
    if len(candidate_ids) == MAX_ISSUES_PER_TEAM_RUN and through is not None and candidate_ids[-1] < through:
        cache.set(cursor_key, {"after": str(candidate_ids[-1]), "through": str(through)}, timeout=CURSOR_TTL_SECONDS)
    else:
        cache.delete(cursor_key)
    logger.info(
        "error_tracking.auto_resolve.team_complete",
        team_id=team_id,
        days=days,
        candidates=len(candidate_ids),
        inactive=len(inactive_ids),
        resolved=len(resolved),
    )
    return len(resolved)
