from temporalio import activity

from products.replay_vision.backend.models.replay_scanner import ReplayScanner, initial_watermark
from products.replay_vision.backend.models.replay_scanner_backfill import BackfillStatus, ReplayScannerBackfill
from products.replay_vision.backend.quota import compute_scanner_budget, current_period_bounds
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.metrics import record_sweep_outcome
from products.replay_vision.backend.temporal.sweep_types import CheckScannerBudgetInputs, CheckScannerBudgetOutput


def _notify_limit_reached(scanner: ReplayScanner) -> bool:
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

        body = (
            "It stopped scanning until its billing period resets. Sessions skipped while capped are not scanned later."
        )
        # The cap also holds a running backfill without changing its status; without this line the
        # notification leaves that backfill looking stalled for no reason.
        if (
            ReplayScannerBackfill.objects.for_team(scanner.team_id)
            .filter(scanner_id=scanner.id, status=BackfillStatus.RUNNING)
            .exists()
        ):
            body += " Its running backfill is on hold and resumes when the limit resets."

        create_notification(
            NotificationData(
                team_id=scanner.team_id,
                # A cap is a usage event, not breakage; it must not surface as a pipeline failure.
                notification_type=NotificationType.USAGE_SPIKE,
                priority=Priority.NORMAL,
                title=f'"{scanner.name}" reached its credit limit',
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


@activity.defn
@track_activity()
def check_scanner_budget_activity(inputs: CheckScannerBudgetInputs) -> CheckScannerBudgetOutput:
    """Whether this scanner has room for another observation under its own credit limit.

    On a cap, advances the watermark past the skipped window (as re-enabling a disabled scanner does);
    freezing it would make the first uncapped tick burn the fresh period's budget on stale recordings.
    Lives here rather than in the workflow because it needs the real clock. Only settled spend advances
    the watermark: in-flight reservations can release without settling and must not permanently skip
    a window the scanner could still afford.
    """
    scanner = ReplayScanner.objects.filter(pk=inputs.scanner_id, team_id=inputs.team_id).select_related("team").first()
    if scanner is None:
        # The reconciler removes schedules for deleted scanners. A racing tick just stops here.
        return CheckScannerBudgetOutput(capped=False)
    if scanner.credit_limit is None:
        return CheckScannerBudgetOutput(capped=False)
    # Resolve the period once so the cap decision and the notification stamp cannot straddle a rollover.
    period = current_period_bounds(scanner.team.organization_id)
    budget = compute_scanner_budget(scanner, period)
    if not budget.blocked:
        return CheckScannerBudgetOutput(capped=False)
    if not budget.blocked_by_settled_spend:
        # In-flight-only overage: capped for now, but those reservations may release without settling.
        record_sweep_outcome("scanner_capped_in_flight")
        activity.logger.info(
            "Sweep skipped: scanner credit limit reached by in-flight reservations only",
            extra={
                "scanner_id": str(inputs.scanner_id),
                "team_id": inputs.team_id,
                "credit_limit": budget.credit_limit,
                "credits_used": budget.credits_used,
            },
        )
        return CheckScannerBudgetOutput(capped=True)
    record_sweep_outcome("scanner_capped_settled")
    # The WHERE claims the notification stamp: of two racing ticks exactly one wins the send, and a
    # crash before the send below can only skip a notification, never send an unrecorded one.
    watermark = initial_watermark()
    # The deep pass walks from its own watermark up to the fast one, so leaving it behind would hand
    # the first uncapped deep sweep exactly the window this reset skips. The cursor is cleared with
    # it: it points partway into ground nobody swept.
    reset = {
        "last_swept_at": watermark,
        "last_seen_session_id": "",
        "deep_swept_through": watermark,
        "deep_seen_session_id": "",
    }
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
            "scanner_id": str(inputs.scanner_id),
            "team_id": inputs.team_id,
            "credit_limit": budget.credit_limit,
            "credits_used": budget.credits_used,
        },
    )
    # Sent only after the stamp commits: a push can't be un-sent, so it must never precede its record.
    if stamped and not _notify_limit_reached(scanner):
        # Hand the claim back so a transient outage delays the notification instead of consuming it.
        ReplayScanner.objects.filter(pk=scanner.pk, limit_notified_period_start=period.start).update(
            limit_notified_period_start=None
        )
    return CheckScannerBudgetOutput(capped=True)
