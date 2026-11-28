"""The one status a scanner reports, worked out from its own fields.

Project-wide causes (session replay off, no recent recordings, the organization's credits used up) and the
no-matches check, which needs observation stats, are left to the caller, which knows them.
"""

import datetime as dt

from django.db import models

from posthog.dataclasses import frozen

from products.replay_vision.backend.models.replay_scanner import ScannerDisabledReason, SweepPauseReason

# The sweep reads recordings that ended at least this long ago, so the watermark trails the wall clock by it.
SWEEP_SETTLE = dt.timedelta(minutes=35)
# Slack past the expected watermark lag before a late sweep counts as delayed, so one slow tick doesn't flag it.
DELAYED_GRACE = dt.timedelta(minutes=60)
# Past this age a first sweep that never finished reads as delayed instead of starting.
STARTING_MAX_AGE = dt.timedelta(minutes=60)


class ScannerStatus(models.TextChoices):
    OFF = "off", "Off"
    NO_SAMPLING = "no_sampling", "Sampling is 0%"
    LIMIT_REACHED = "limit_reached", "Credit limit reached"
    FILTER_ERROR = "filter_error", "Filter error"
    PAUSED = "paused", "Paused"
    STARTING = "starting", "Starting"
    DELAYED = "delayed", "Delayed"
    THROTTLED = "throttled", "Throttled"
    RUNNING = "running", "Running"


class ScannerStatusReason(models.TextChoices):
    MANUAL = ScannerDisabledReason.MANUAL.value, ScannerDisabledReason.MANUAL.label
    FREE_CREDITS_USED = ScannerDisabledReason.FREE_CREDITS_USED.value, ScannerDisabledReason.FREE_CREDITS_USED.label
    NO_AI_CONSENT = ScannerDisabledReason.NO_AI_CONSENT.value, ScannerDisabledReason.NO_AI_CONSENT.label
    CREATOR_LOST_ACCESS = (
        ScannerDisabledReason.CREATOR_LOST_ACCESS.value,
        ScannerDisabledReason.CREATOR_LOST_ACCESS.label,
    )
    EXPERIMENT_DELETED = ScannerDisabledReason.EXPERIMENT_DELETED.value, ScannerDisabledReason.EXPERIMENT_DELETED.label
    CREDIT_LIMIT = SweepPauseReason.CREDIT_LIMIT.value, SweepPauseReason.CREDIT_LIMIT.label
    EXPERIMENT_NOT_RUNNING = (
        SweepPauseReason.EXPERIMENT_NOT_RUNNING.value,
        SweepPauseReason.EXPERIMENT_NOT_RUNNING.label,
    )
    FILTER_ERROR = SweepPauseReason.FILTER_ERROR.value, SweepPauseReason.FILTER_ERROR.label
    NO_PRINCIPAL = SweepPauseReason.NO_PRINCIPAL.value, SweepPauseReason.NO_PRINCIPAL.label


@frozen
class ScannerStatusInputs:
    enabled: bool
    disabled_reason: str | None
    sampling_rate: float
    limit_reached: bool
    stopped_by_free_credits: bool
    has_filter_error: bool
    sweep_interval: dt.timedelta | None
    sweep_pause_reason: str
    created_at: dt.datetime
    last_swept_at: dt.datetime
    throttle_factor: int


@frozen
class ScannerStatusResult:
    status: ScannerStatus
    reason: ScannerStatusReason | None = None


def _reason(value: str | None) -> ScannerStatusReason | None:
    return ScannerStatusReason(value) if value in ScannerStatusReason.values else None


def scanner_status(inputs: ScannerStatusInputs, now: dt.datetime) -> ScannerStatusResult:
    """Earlier checks win, so a scanner that is off never also reads as stopped."""
    if not inputs.enabled:
        return ScannerStatusResult(status=ScannerStatus.OFF, reason=_reason(inputs.disabled_reason))
    if inputs.sampling_rate == 0:
        return ScannerStatusResult(status=ScannerStatus.NO_SAMPLING)
    if inputs.limit_reached:
        return ScannerStatusResult(
            status=ScannerStatus.LIMIT_REACHED,
            reason=ScannerStatusReason.FREE_CREDITS_USED
            if inputs.stopped_by_free_credits
            else ScannerStatusReason.CREDIT_LIMIT,
        )
    if inputs.has_filter_error:
        return ScannerStatusResult(status=ScannerStatus.FILTER_ERROR)
    # The backend removes an enabled scanner's schedule while it cannot scan.
    if inputs.sweep_interval is None:
        return ScannerStatusResult(status=ScannerStatus.PAUSED, reason=_reason(inputs.sweep_pause_reason or None))
    # The watermark is seeded before created_at and only advances when a sweep tick finishes.
    if inputs.last_swept_at < inputs.created_at and now - inputs.created_at < STARTING_MAX_AGE:
        return ScannerStatusResult(status=ScannerStatus.STARTING)
    # Capped at now, so clock skew can't make the last check read as in the future.
    last_checked_at = min(inputs.last_swept_at + SWEEP_SETTLE, now)
    if now - last_checked_at > inputs.sweep_interval + DELAYED_GRACE:
        return ScannerStatusResult(status=ScannerStatus.DELAYED)
    if inputs.throttle_factor > 1:
        return ScannerStatusResult(status=ScannerStatus.THROTTLED)
    return ScannerStatusResult(status=ScannerStatus.RUNNING)
