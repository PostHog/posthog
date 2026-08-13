from temporalio import activity

from products.replay_vision.backend.models.replay_scanner import ReplayScanner, initial_watermark
from products.replay_vision.backend.quota import compute_scanner_budget
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.metrics import record_sweep_outcome
from products.replay_vision.backend.temporal.sweep_types import CheckScannerBudgetInputs, CheckScannerBudgetOutput


@activity.defn
@track_activity()
def check_scanner_budget_activity(inputs: CheckScannerBudgetInputs) -> CheckScannerBudgetOutput:
    """Whether this scanner has room for another observation under its own credit limit.

    On a cap, advances the watermark past the window the scanner is skipping. Freezing it instead would
    make the first uncapped tick fetch a candidate window stretching back to when the limit was hit and
    burn the fresh period's budget on stale recordings, so a spend limit would become a spend spike.
    Mirrors what re-enabling a disabled scanner already does. The reset lives here, not in the workflow,
    because it needs the real clock.

    The watermark only advances when settled credits alone exceed the limit. In-flight reservations are
    transient (a failed observation releases its reservation without ever writing a receipt), so a
    transient in-flight spike must not permanently skip a window the scanner could actually afford once
    those reservations clear.
    """
    scanner = ReplayScanner.objects.filter(pk=inputs.scanner_id, team_id=inputs.team_id).select_related("team").first()
    if scanner is None:
        # The reconciler removes schedules for deleted scanners. A racing tick just stops here.
        return CheckScannerBudgetOutput(capped=False)
    if scanner.credit_limit is None:
        return CheckScannerBudgetOutput(capped=False)
    budget = compute_scanner_budget(scanner)
    if not budget.blocked:
        return CheckScannerBudgetOutput(capped=False)
    if not budget.blocked_by_settled_spend:
        # Only the in-flight portion pushes this over: capped for now, but don't advance the
        # watermark, since those reservations may release without ever settling.
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
    # `.update` bypasses the model's version-tracking save(), matching how the watermark is advanced.
    watermark = initial_watermark()
    ReplayScanner.objects.filter(pk=scanner.pk).update(
        last_swept_at=watermark,
        last_seen_session_id="",
        # The deep pass walks from its own watermark up to the fast one, so leaving it behind would
        # hand the first uncapped deep sweep exactly the window this reset skips.
        last_deep_swept_at=watermark,
    )
    activity.logger.info(
        "Sweep skipped: scanner credit limit reached",
        extra={
            "scanner_id": str(inputs.scanner_id),
            "team_id": inputs.team_id,
            "credit_limit": budget.credit_limit,
            "credits_used": budget.credits_used,
        },
    )
    return CheckScannerBudgetOutput(capped=True)
