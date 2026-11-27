from datetime import datetime, timedelta
from uuid import UUID

from django.db import transaction
from django.db.models import Exists, OuterRef, Q, QuerySet
from django.utils import timezone

import structlog
from dateutil.relativedelta import relativedelta

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.query_tagging import Product, tag_queries
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.models.activity_logging.activity_log import ActivityContextBase, Detail, log_activity
from posthog.models.team.team import Team

from products.error_tracking.backend.logic import is_exception_ingestion_enabled
from products.error_tracking.backend.logic.team_flags import AUTO_RESOLVE_FLAG, team_flag_enabled
from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueFingerprintV2,
    ErrorTrackingSettings,
    sync_issues_to_clickhouse,
)

logger = structlog.get_logger(__name__)

# Cymbal suppresses receipt writes for up to one hour after a successful write.
RECEIPT_CACHE_WINDOW = timedelta(hours=1)
ISSUES_PER_SWEEP = 500
CANDIDATES_PER_QUERY = 5000


@frozen(slots=False)
class AutoResolveActivityContext(ActivityContextBase):
    after_days: int


def auto_resolve_team_ids() -> list[int]:
    return list(
        ErrorTrackingSettings.objects.filter(auto_resolve_after_days__isnull=False)
        .order_by("team_id")
        .values_list("team_id", flat=True)
    )


def _quiet_issue_candidates(team_id: int, cutoff: datetime) -> QuerySet[ErrorTrackingIssue]:
    return (
        ErrorTrackingIssue.objects.filter(
            team_id=team_id, status=ErrorTrackingIssue.Status.ACTIVE, created_at__lt=cutoff
        )
        .filter(Q(state_updated_at__isnull=True) | Q(state_updated_at__lt=cutoff))
        .filter(Q(last_received_at__isnull=True) | Q(last_received_at__lt=cutoff - RECEIPT_CACHE_WINDOW))
        .filter(Exists(ErrorTrackingIssueFingerprintV2.objects.filter(team_id=team_id, issue_id=OuterRef("pk"))))
        .order_by("pk")
    )


def _issues_seen_since(team: Team, cutoff: datetime, issue_ids: list[UUID]) -> set[UUID]:
    tag_queries(product=Product.ERROR_TRACKING, team_id=team.pk, name="auto_resolve:recent_issues")
    result = execute_hogql_query(
        query="""
            SELECT DISTINCT issue_id
            FROM events
            WHERE event = '$exception' AND timestamp >= {cutoff} AND issue_id IN {issue_ids}
            LIMIT {limit}
        """,
        team=team,
        placeholders={
            "cutoff": ast.Constant(value=cutoff),
            "issue_ids": ast.Tuple(exprs=[ast.Constant(value=str(issue_id)) for issue_id in issue_ids]),
            "limit": ast.Constant(value=len(issue_ids)),
        },
        workload=Workload.OFFLINE,
        ch_user=ClickHouseUser.ERROR_TRACKING,
        settings=HogQLGlobalSettings(max_execution_time=60),
    )
    return {UUID(str(row[0])) for row in result.results or []}


def _resolve_batch(team: Team, days: int, cutoff: datetime, issue_ids: list[UUID], *, limit: int, dry_run: bool) -> int:
    candidates = _quiet_issue_candidates(team.pk, cutoff).filter(pk__in=issue_ids)
    if dry_run:
        return candidates[:limit].count()

    with transaction.atomic():
        if (
            not ErrorTrackingSettings.objects.select_for_update()
            .filter(team_id=team.pk, auto_resolve_after_days=days)
            .exists()
        ):
            return 0
        if not is_exception_ingestion_enabled(team.pk):
            return 0
        # An exception can arrive after the history query. Cymbal updates receipt time under this same lock.
        issues = list(candidates.select_for_update(skip_locked=True, of=("self",))[:limit])
        resolved_ids = [issue.pk for issue in issues]
        ErrorTrackingIssue.objects.filter(team_id=team.pk, pk__in=resolved_ids).update(
            status=ErrorTrackingIssue.Status.RESOLVED, state_updated_at=timezone.now()
        )
        for issue in issues:
            log_activity(
                organization_id=team.organization_id,
                team_id=team.pk,
                user=None,
                item_id=issue.pk,
                scope="ErrorTrackingIssue",
                activity="auto_resolved",
                detail=Detail(name=issue.name, context=AutoResolveActivityContext(after_days=days)),
                was_impersonated=False,
                strict=True,
            )

    if resolved_ids:
        try:
            sync_issues_to_clickhouse(issue_ids=resolved_ids, team_id=team.pk)
        except Exception:
            logger.exception("error_tracking.auto_resolve.status_sync_failed", team_id=team.pk, count=len(resolved_ids))
    return len(resolved_ids)


def auto_resolve_issues(team_id: int, *, dry_run: bool = False) -> int:
    if not team_flag_enabled(AUTO_RESOLVE_FLAG, team_id, only_evaluate_locally=True):
        return 0
    config = ErrorTrackingSettings.objects.select_related("team").filter(team_id=team_id).first()
    if config is None or config.auto_resolve_after_days is None or not is_exception_ingestion_enabled(team_id):
        return 0

    days = config.auto_resolve_after_days
    now = timezone.now()
    cutoff = now - timedelta(days=days)
    if cutoff < now - relativedelta(months=config.team.event_retention_months):
        logger.info("error_tracking.auto_resolve.insufficient_history", team_id=team_id, after_days=days)
        return 0

    candidates = _quiet_issue_candidates(team_id, cutoff)
    after_id = None
    resolved = 0
    while resolved < ISSUES_PER_SWEEP:
        page = candidates if after_id is None else candidates.filter(pk__gt=after_id)
        issue_ids = list(page.values_list("pk", flat=True)[:CANDIDATES_PER_QUERY])
        if not issue_ids:
            break
        after_id = issue_ids[-1]
        seen = _issues_seen_since(config.team, cutoff, issue_ids)
        quiet = [issue_id for issue_id in issue_ids if issue_id not in seen]
        if quiet:
            resolved += _resolve_batch(
                config.team, days, cutoff, quiet, limit=ISSUES_PER_SWEEP - resolved, dry_run=dry_run
            )
    return resolved
