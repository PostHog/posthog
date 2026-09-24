"""Auto-resolve: resolve active issues that stopped receiving exceptions.

Teams opt in with `ErrorTrackingSettings.auto_resolve_after_days`. A daily Temporal sweep
(`temporal/auto_resolve`) calls `auto_resolve_team` for each opted-in team. A wrong call is
cheap: cymbal reopens a resolved issue as soon as its next exception is ingested.
"""

from datetime import datetime, timedelta
from uuid import UUID

from django.core.cache import cache
from django.db.models import DateTimeField
from django.db.models.functions import Coalesce
from django.utils import timezone

import structlog

from posthog.schema import ProductKey

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.clickhouse.workload import Workload

from products.error_tracking.backend.logic.recommendations.long_running_issues import exception_fingerprint_expr
from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueFingerprintV2,
    ErrorTrackingSettings,
)

logger = structlog.get_logger(__name__)

# A saved cursor lets later issues progress even when an earlier page stays active.
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


def get_auto_resolve_team_settings() -> list[tuple[int, int]]:
    """(team_id, auto_resolve_after_days) for every team with auto-resolve on."""
    return list(
        ErrorTrackingSettings.objects.filter(auto_resolve_after_days__isnull=False)
        .order_by("team_id")
        .values_list("team_id", "auto_resolve_after_days")
    )


def _candidate_issue_ids(team_id: int, cutoff: datetime, after: UUID | None = None) -> list[UUID]:
    # `state_updated_at` is null on issues whose state never changed, so fall back to creation.
    # Requiring the issue to have been in its current state for the whole window keeps a
    # freshly created or manually reactivated issue from being resolved on its first sweep.
    candidates = (
        ErrorTrackingIssue.objects.filter(team_id=team_id, status=ErrorTrackingIssue.Status.ACTIVE)
        .annotate(last_state_change=Coalesce("state_updated_at", "created_at", output_field=DateTimeField()))
        .filter(last_state_change__lt=cutoff)
    )
    if after is not None:
        candidates = candidates.filter(id__gt=after)
    return list(candidates.order_by("id").values_list("id", flat=True)[:MAX_ISSUES_PER_TEAM_RUN])


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


def auto_resolve_team(team_id: int, days: int) -> int:
    # issue_mutations -> lifecycle_events -> the temporal package, which imports this module
    # back through the auto-resolve activities, so the import can't sit at module level.
    from products.error_tracking.backend.logic.issue_mutations import auto_resolve_issues  # noqa: PLC0415

    cutoff = timezone.now() - timedelta(days=days)
    cursor_key = f"error_tracking:auto_resolve:cursor:{team_id}"
    cursor = cache.get(cursor_key)
    candidate_ids = _candidate_issue_ids(team_id, cutoff, UUID(cursor) if cursor is not None else None)
    if not candidate_ids and cursor is not None:
        candidate_ids = _candidate_issue_ids(team_id, cutoff)
    if not candidate_ids:
        cache.delete(cursor_key)
        return 0

    inactive_ids = find_inactive_issue_ids(team_id, candidate_ids, cutoff)
    resolved = auto_resolve_issues(team_id, inactive_ids, cutoff=cutoff) if inactive_ids else []

    # Keep the page on failure so a later sweep retries it. Losing the cache only repeats work.
    if len(candidate_ids) == MAX_ISSUES_PER_TEAM_RUN:
        cache.set(cursor_key, str(candidate_ids[-1]), timeout=CURSOR_TTL_SECONDS)
    else:
        cache.delete(cursor_key)
    logger.info(
        "error_tracking.auto_resolve.team_complete",
        team_id=team_id,
        days=days,
        candidates=len(inactive_ids),
        resolved=len(resolved),
    )
    return len(resolved)
