from datetime import timedelta
from uuid import UUID

from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.models.activity_logging.activity_log import ActivityContextBase, Detail, log_activity

from products.error_tracking.backend.logic.team_flags import AUTO_RESOLVE_FLAG, team_flag_enabled
from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueFingerprintV2,
    ErrorTrackingSettings,
    sync_issues_to_clickhouse,
)

# These must cover Cymbal's fixed receipt and opt-in cache lifetimes respectively.
RECEIPT_CACHE_WINDOW = timedelta(hours=1)
OBSERVATION_WARMUP = timedelta(minutes=1)
ISSUES_PER_SWEEP = 500
ISSUES_PER_SYNC = 100


@frozen(slots=False)
class AutoResolveActivityContext(ActivityContextBase):
    after_days: int


def auto_resolve_team_ids() -> list[int]:
    return list(
        ErrorTrackingSettings.objects.filter(
            auto_resolve_after_days__isnull=False, auto_resolve_observation_started_at__isnull=False
        )
        .order_by("team_id")
        .values_list("team_id", flat=True)
    )


def pending_auto_resolve_sync_team_ids() -> list[int]:
    return list(
        ErrorTrackingIssue.objects.filter(auto_resolve_sync_requested_at__isnull=False)
        .order_by("team_id")
        .values_list("team_id", flat=True)
        .distinct()
    )


def auto_resolve_issues(team_id: int, *, dry_run: bool = False) -> int:
    if not team_flag_enabled(AUTO_RESOLVE_FLAG, team_id, only_evaluate_locally=True):
        return 0

    with transaction.atomic():
        config = (
            ErrorTrackingSettings.objects.select_for_update(of=("self",))
            .select_related("team")
            .filter(team_id=team_id)
            .first()
        )
        if (
            config is None
            or config.auto_resolve_after_days is None
            or config.auto_resolve_observation_started_at is None
        ):
            return 0

        now = timezone.now()
        days = config.auto_resolve_after_days
        cutoff = now - timedelta(days=days)
        if config.auto_resolve_observation_started_at + OBSERVATION_WARMUP > cutoff:
            return 0

        candidates = (
            ErrorTrackingIssue.objects.filter(
                team_id=team_id, status=ErrorTrackingIssue.Status.ACTIVE, created_at__lte=cutoff
            )
            .filter(Q(state_updated_at__isnull=True) | Q(state_updated_at__lte=cutoff))
            .filter(Q(last_received_at__isnull=True) | Q(last_received_at__lte=cutoff - RECEIPT_CACHE_WINDOW))
            .filter(Exists(ErrorTrackingIssueFingerprintV2.objects.filter(team_id=team_id, issue_id=OuterRef("pk"))))
            .order_by("created_at", "pk")
        )
        if dry_run:
            return candidates[:ISSUES_PER_SWEEP].count()

        # Cymbal updates receipt time under the same lock; skip issues ingestion is updating.
        issues = list(candidates.select_for_update(skip_locked=True, of=("self",))[:ISSUES_PER_SWEEP])
        if not issues:
            return 0

        ErrorTrackingIssue.objects.filter(team_id=team_id, pk__in=[issue.pk for issue in issues]).update(
            status=ErrorTrackingIssue.Status.RESOLVED,
            state_updated_at=now,
            auto_resolved=True,
            auto_resolve_sync_requested_at=now,
        )
        for issue in issues:
            log_activity(
                organization_id=config.team.organization_id,
                team_id=team_id,
                user=None,
                item_id=issue.pk,
                scope="ErrorTrackingIssue",
                activity="auto_resolved",
                detail=Detail(name=issue.name, context=AutoResolveActivityContext(after_days=days)),
                was_impersonated=False,
                strict=True,
            )
        return len(issues)


def sync_pending_auto_resolve_issues(team_id: int) -> int:
    pending = list(
        ErrorTrackingIssue.objects.filter(team_id=team_id, auto_resolve_sync_requested_at__isnull=False)
        .order_by("pk")
        .values_list("pk", "auto_resolve_sync_requested_at")[:ISSUES_PER_SYNC]
    )
    if not pending:
        return 0

    issue_ids: list[UUID] = [issue_id for issue_id, _ in pending]
    sync_issues_to_clickhouse(issue_ids=issue_ids, team_id=team_id, wait_for_delivery=True)

    # A reopen may request a new sync while Kafka acknowledges this one.
    unchanged = Q.create(
        [Q(pk=issue_id, auto_resolve_sync_requested_at=requested_at) for issue_id, requested_at in pending],
        connector=Q.OR,
    )
    return ErrorTrackingIssue.objects.filter(unchanged, team_id=team_id).update(auto_resolve_sync_requested_at=None)
