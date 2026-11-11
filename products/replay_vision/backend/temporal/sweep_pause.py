import datetime as dt

from products.replay_vision.backend.models.replay_scanner import (
    ReplayScanner,
    SweepPauseReason,
    skipped_window_watermarks,
)
from products.replay_vision.backend.temporal.metrics import record_sweep_outcome

# Reasons whose sweeps used to move the watermark to now on every blocked tick, so that nothing the scanner
# could not scan is billed later. A paused scanner has no ticks, so the first sweep after the pause makes the
# same move once.
_SKIPS_PAUSED_WINDOW = frozenset({SweepPauseReason.CREDIT_LIMIT, SweepPauseReason.EXPERIMENT_NOT_RUNNING})


def pause_sweep(scanner: ReplayScanner, reason: SweepPauseReason, until: dt.datetime) -> None:
    """Have the reconciler remove the scanner's schedule until `until`, or until the scanner is saved."""
    # Matched on `updated_at`, so an edit saved since this tick loaded the scanner keeps the sweep running.
    paused = ReplayScanner.objects.filter(pk=scanner.pk, updated_at=scanner.updated_at).update(
        sweep_paused_until=until, sweep_pause_reason=reason
    )
    if paused:
        record_sweep_outcome(f"paused_{reason}")


def resume_after_pause(scanner: ReplayScanner) -> None:
    """Settle the first sweep after a pause. Updates `scanner` in place so the caller sweeps from the result."""
    if not scanner.sweep_pause_reason:
        return
    # A tick can still fire in the minute before the reconciler removes a new pause's schedule. That tick
    # must not settle the pause, or the real resume would no longer know to skip the paused window.
    if scanner.sweep_paused_until is not None and scanner.sweep_paused_until > dt.datetime.now(dt.UTC):
        return
    updates: dict[str, object] = {"sweep_pause_reason": ""}
    if scanner.sweep_pause_reason in _SKIPS_PAUSED_WINDOW:
        updates |= skipped_window_watermarks()
    ReplayScanner.objects.filter(pk=scanner.pk).update(**updates)
    for field, value in updates.items():
        setattr(scanner, field, value)
