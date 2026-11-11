from dataclasses import replace

from django.db import transaction
from django.utils import timezone

from temporalio import activity

from products.replay_vision.backend.billing import observation_credits_for_model
from products.replay_vision.backend.models.replay_observation import ObservationTrigger
from products.replay_vision.backend.models.replay_scanner import (
    ReplayScanner,
    ScannerDisabledReason,
    ScannerType,
    SweepPauseReason,
    skipped_window_watermarks,
)
from products.replay_vision.backend.models.replay_scanner_backfill import (
    ACTIVE_BACKFILL_STATUSES,
    BackfillStatus,
    ReplayScannerBackfill,
)
from products.replay_vision.backend.quota import (
    BillingPeriod,
    OrgCreditCap,
    compute_scanner_budget,
    org_credit_cap_for,
    quota_state_for_cap,
)
from products.replay_vision.backend.scanner_access import unrunnable_reason
from products.replay_vision.backend.temporal.activities.create_observation import capture_scan_blocked
from products.replay_vision.backend.temporal.activities.find_scanner_candidates import stop_variant_analysis
from products.replay_vision.backend.temporal.constants import CHECK_SCANNER_BUDGET_TIMEOUT
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.metrics import record_sweep_outcome
from products.replay_vision.backend.temporal.query_budget import bounded_queries
from products.replay_vision.backend.temporal.sweep_cadence import SWEEP_PAUSE_RECHECK, SWEEP_PAUSE_RECHECK_SOON
from products.replay_vision.backend.temporal.sweep_pause import pause_sweep
from products.replay_vision.backend.temporal.sweep_types import CheckScannerBudgetInputs, CheckScannerBudgetOutput


def _notify_scanner_viewers(scanner: ReplayScanner, title: str, body: str) -> bool:
    """Best-effort notification; False only when the send raised. A deliberate skip inside the
    pipeline (flag off, nobody to notify) counts as sent so it is not retried every tick."""
    try:
        from posthog.models import User  # noqa: PLC0415

        from products.access_control.backend.facade.user_access_control import UserAccessControl  # noqa: PLC0415
        from products.notifications.backend.facade.api import (  # noqa: PLC0415 (keeps the heavy dep off the import path)
            NotificationData,
            NotificationType,
            Priority,
            RecipientsResolver,
            TargetType,
            create_notification,
        )

        class ScannerViewersResolver(RecipientsResolver):
            """The pipeline's built-in access filter is resource-type wide; keep only per-scanner viewers."""

            def resolve(self, target_type: TargetType, target_id: str, team_id: int | None) -> list[int]:
                user_ids = super().resolve(target_type, target_id, team_id)
                if not user_ids:
                    return user_ids
                # One probe user answers the org-wide support question; don't load every recipient for it.
                probe = User.objects.filter(id__in=user_ids).first()
                if probe is None or not UserAccessControl(probe, scanner.team).access_controls_supported:
                    return user_ids
                # Per-user checks cost several queries each; without object-level rows on this scanner
                # the resource-wide filter already applied is the whole answer, so skip them.
                from products.access_control.backend.models.access_control import AccessControl  # noqa: PLC0415

                has_object_rules = AccessControl.objects.filter(
                    team=scanner.team, resource="replay_scanner", resource_id=str(scanner.id)
                ).exists()
                if not has_object_rules:
                    return user_ids
                return [
                    user.id
                    for user in User.objects.filter(id__in=user_ids)
                    if UserAccessControl(user, scanner.team).check_access_level_for_object(
                        scanner, required_level="viewer"
                    )
                ]

        create_notification(
            NotificationData(
                team_id=scanner.team_id,
                # A cap is a usage event, not breakage; it must not surface as a pipeline failure.
                notification_type=NotificationType.USAGE_SPIKE,
                priority=Priority.NORMAL,
                title=title,
                body=body,
                target_type=TargetType.TEAM,
                target_id=str(scanner.team_id),
                resource_type="replay_scanner",
                resource_id=str(scanner.id),
                resolver=ScannerViewersResolver(),
                source_url=f"/project/{scanner.team.project_id}/replay-vision/{scanner.id}",
            )
        )
    except Exception:
        activity.logger.warning(
            "Failed to send scanner credit limit notification",
            extra={"scanner_id": str(scanner.id), "team_id": scanner.team_id},
            exc_info=True,
        )
        return False
    return True


def _notify_limit_reached(scanner: ReplayScanner) -> bool:
    body = "It stopped scanning until its billing period resets. Sessions skipped while capped are not scanned later."
    # The cap also holds a running backfill without changing its status; without this line the
    # notification leaves that backfill looking stalled for no reason.
    if (
        ReplayScannerBackfill.objects.for_team(scanner.team_id)
        .filter(scanner_id=scanner.id, status=BackfillStatus.RUNNING)
        .exists()
    ):
        body += " Its running backfill is on hold and resumes when the limit resets."
    return _notify_scanner_viewers(scanner, f'"{scanner.name}" reached its credit limit', body)


def _turn_off_free_only_scanner(scanner: ReplayScanner) -> None:
    """Turn a free-only scanner off once the free credits run out, so it doesn't start again when they reset.

    Its backfills are cancelled with it: one paused on the same free credits would otherwise resume
    on its own next period, which is the restart this turn-off exists to prevent. An experiment scanner's
    scouts are paused first, because once it is off nothing retries a failed pause.
    """
    with bounded_queries(CHECK_SCANNER_BUDGET_TIMEOUT), transaction.atomic():
        # One racing tick wins the lock, and a concurrent switch off "Free credits only" wins over the turn-off.
        locked = ReplayScanner.objects.select_for_update().filter(pk=scanner.pk, enabled=True, free_only=True).first()
        if locked is None:
            return
        if locked.scanner_type == ScannerType.EXPERIMENT and not stop_variant_analysis(locked):
            record_sweep_outcome(f"{ScannerDisabledReason.FREE_CREDITS_USED}_pause_failed")
            return
        locked.turn_off(ScannerDisabledReason.FREE_CREDITS_USED)
        cancelled_backfills = (
            ReplayScannerBackfill.objects.for_team(scanner.team_id)
            .filter(scanner_id=scanner.id, status__in=ACTIVE_BACKFILL_STATUSES)
            .update(status=BackfillStatus.CANCELLED, finished_at=timezone.now())
        )
    record_sweep_outcome(ScannerDisabledReason.FREE_CREDITS_USED)
    activity.logger.info(
        "replay_vision.sweep.disabled_free_only_scanner scanner_id=%s cancelled_backfills=%s",
        scanner.id,
        cancelled_backfills,
    )
    body = "Your organization used its free credits for this billing period."
    if cancelled_backfills:
        body += " Its backfill was canceled."
    # Best effort: a turned-off scanner has no next tick to retry a failed send.
    _notify_scanner_viewers(scanner, f'"{scanner.name}" stopped: free credits used', body)


@activity.defn
@track_activity()
def check_scanner_budget_activity(inputs: CheckScannerBudgetInputs) -> CheckScannerBudgetOutput:
    """Whether this scanner has room for another observation under its own credit limit.

    On a cap, advances the watermark past the skipped window (as re-enabling a disabled scanner does);
    freezing it would make the first uncapped tick burn the fresh period's budget on stale recordings.
    Lives here rather than in the workflow because it needs the real clock. Only settled spend advances
    the watermark: in-flight reservations can release without settling and must not permanently skip
    a window the scanner could still afford. A free-only scanner whose free credits fill with
    settled spend is turned off instead of capped.
    """
    scanner = (
        ReplayScanner.objects.filter(pk=inputs.scanner_id, team_id=inputs.team_id)
        .select_related("team__organization", "created_by")
        .first()
    )
    if scanner is None:
        # The reconciler removes schedules for deleted scanners. A racing tick just stops here.
        return CheckScannerBudgetOutput(capped=False)
    # Resolve the period once so the cap decisions and the notification stamp cannot straddle a rollover.
    cap = org_credit_cap_for(scanner.team.organization, scanner.team.organization_id)
    # The scanner's own limit goes first, so its limit notification still goes out when the org is capped too.
    if scanner.has_spend_ceiling:
        # Not capped, so the sweep reaches the step that turns an unrunnable scanner off.
        if unrunnable_reason(scanner):
            return CheckScannerBudgetOutput(capped=False)
        if _scanner_capped(scanner, cap.period):
            return CheckScannerBudgetOutput(capped=True)
    return CheckScannerBudgetOutput(capped=_org_capped(scanner, cap))


def _scanner_capped(scanner: ReplayScanner, period: BillingPeriod) -> bool:
    with bounded_queries(CHECK_SCANNER_BUDGET_TIMEOUT):
        budget = compute_scanner_budget(scanner, period)
    if not budget.blocked:
        return False
    if not budget.blocked_by_settled_spend:
        # In-flight-only overage: capped for now, but those reservations may release without settling.
        record_sweep_outcome("scanner_capped_in_flight")
        activity.logger.info(
            "Sweep skipped: scanner credit limit reached by in-flight reservations only",
            extra={
                "scanner_id": str(scanner.id),
                "team_id": scanner.team_id,
                "credit_limit": budget.credit_limit,
                "credits_used": budget.credits_used,
            },
        )
        return True
    if scanner.free_only and budget.free_credits_filled_by_settled_spend:
        _turn_off_free_only_scanner(scanner)
        return True
    record_sweep_outcome("scanner_capped_settled")
    # The WHERE claims the notification stamp: of two racing ticks exactly one wins the send, and a
    # crash before the send below can only skip a notification, never send an unrecorded one.
    reset = skipped_window_watermarks()
    stamped = (
        ReplayScanner.objects.filter(pk=scanner.pk)
        .exclude(limit_notified_period_start=period.start)
        .update(**reset, limit_notified_period_start=period.start)
    )
    if not stamped:
        # Already notified this period; still advance the watermark past the skipped window.
        ReplayScanner.objects.filter(pk=scanner.pk).update(**reset)
    activity.logger.info(
        "Sweep skipped: scanner credit limit reached",
        extra={
            "scanner_id": str(scanner.id),
            "team_id": scanner.team_id,
            "credit_limit": budget.credit_limit,
            "credits_used": budget.credits_used,
        },
    )
    # The period end is the known resume point. The recheck covers what saves no scanner, such as the org
    # buying credits. A raised scanner limit is a save, which resumes the sweep at once.
    pause_sweep(scanner, SweepPauseReason.CREDIT_LIMIT, min(period.end, timezone.now() + SWEEP_PAUSE_RECHECK))
    # Sent only after the stamp commits: a push can't be un-sent, so it must never precede its record.
    if stamped and not _notify_limit_reached(scanner):
        # Hand the claim back so a transient outage delays the notification instead of consuming it.
        ReplayScanner.objects.filter(pk=scanner.pk, limit_notified_period_start=period.start).update(
            limit_notified_period_start=None
        )
    return True


def _org_capped(scanner: ReplayScanner, cap: OrgCreditCap) -> bool:
    """Whether the organization's credit limit refuses this scanner's next observation.

    Admission in `create_observation` refuses each session on its own, so without this gate a capped
    organization still starts one apply workflow per candidate, and every one of them exits at once.
    """
    if cap.credit_limit is None:
        return False
    cost = observation_credits_for_model(scanner.model)
    with bounded_queries(CHECK_SCANNER_BUDGET_TIMEOUT):
        quota = quota_state_for_cap(scanner.team.organization_id, cap)
    if not quota.would_exceed(cost):
        return False
    if not replace(quota, credits_used=quota.credits_settled).would_exceed(cost):
        # Reservations can release without settling, so an in-flight-only overage skips this tick only.
        record_sweep_outcome("org_capped_in_flight")
        return True
    record_sweep_outcome("org_capped_settled")
    capture_scan_blocked(scanner=scanner, reason="quota", triggered_by=ObservationTrigger.SCHEDULE, quota=quota)
    ReplayScanner.objects.filter(pk=scanner.pk).update(**skipped_window_watermarks())
    # An organization raising its limit saves no scanner, so the pause rechecks sooner than a scanner cap does.
    pause_sweep(scanner, SweepPauseReason.CREDIT_LIMIT, min(cap.period.end, timezone.now() + SWEEP_PAUSE_RECHECK_SOON))
    return True
