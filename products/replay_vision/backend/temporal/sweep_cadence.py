"""How often a scanner's sweep schedule fires, or whether it fires at all.

Temporal bills every schedule fire whether or not the sweep finds anything, so the schedule interval is
where a scanner's cadence is decided. Scanners that rarely find sessions are swept less often, scanners
over their ClickHouse read budget are swept less often, and scanners that cannot scan are not swept.
"""

import datetime as dt

from posthog.dataclasses import frozen

from products.replay_vision.backend.temporal.constants import SCANNER_SCHEDULE_INTERVAL

SWEEP_INTERVALS = (
    SCANNER_SCHEDULE_INTERVAL,
    dt.timedelta(minutes=15),
    dt.timedelta(minutes=30),
    dt.timedelta(minutes=60),
)

# A scanner someone just created or edited gets results fast, so they can judge their filter and prompt.
EDIT_GRACE = dt.timedelta(hours=24)
# These windows measure time since the last find, not finds per tick. A slower interval covers more
# recordings per tick, so a count of productive ticks would rise just because the scanner slowed down.
BUSY_WINDOW = dt.timedelta(hours=1)
WARM_WINDOW = dt.timedelta(hours=6)

# How long a paused scanner waits before a sweep checks again whether it still cannot scan. Used when
# the unblocking change does not save the scanner, such as an org buying credits or an experiment
# resuming, because a save already resumes the sweep at once.
SWEEP_PAUSE_RECHECK = dt.timedelta(hours=6)
# For blocks that can lift at any moment and save no scanner, such as an org raising its limit.
SWEEP_PAUSE_RECHECK_SOON = dt.timedelta(hours=1)
# A resumed experiment's sweep starts from the paused tick's watermark, so this bounds how much of the pause it reads.
SWEEP_PAUSE_RECHECK_EXPERIMENT_PAUSED = dt.timedelta(minutes=15)


@frozen
class SweepCadenceInputs:
    created_at: dt.datetime
    updated_at: dt.datetime
    last_found_candidates_at: dt.datetime | None
    sweep_paused_until: dt.datetime | None
    throttle_factor: int
    has_enabled_alert: bool


def sweep_interval(inputs: SweepCadenceInputs, now: dt.datetime) -> dt.timedelta | None:
    """The schedule interval for an enabled scanner, or None when its schedule should not exist."""
    if inputs.sweep_paused_until is not None and inputs.sweep_paused_until > now:
        return None
    wanted = max(_yield_interval(inputs, now), SCANNER_SCHEDULE_INTERVAL * max(1, inputs.throttle_factor))
    # Rounds up so the read budget holds. The throttle factor tops out at an hour, as does the last step.
    return next((interval for interval in SWEEP_INTERVALS if interval >= wanted), SWEEP_INTERVALS[-1])


def _yield_interval(inputs: SweepCadenceInputs, now: dt.datetime) -> dt.timedelta:
    # A rare match can be the one an alert exists for, so alerting scanners never slow down for low yield.
    if inputs.has_enabled_alert or now - max(inputs.created_at, inputs.updated_at) < EDIT_GRACE:
        return SCANNER_SCHEDULE_INTERVAL
    if inputs.last_found_candidates_at is None:
        return SWEEP_INTERVALS[-1]
    since_found = now - inputs.last_found_candidates_at
    if since_found < BUSY_WINDOW:
        return SCANNER_SCHEDULE_INTERVAL
    if since_found < WARM_WINDOW:
        return dt.timedelta(minutes=15)
    return SWEEP_INTERVALS[-1]
