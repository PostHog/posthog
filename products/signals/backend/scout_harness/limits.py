from __future__ import annotations

# A scout run's hard runtime cap. Enforced via the Temporal activity's
# `start_to_close_timeout` in `scout_scheduler.py` — if the agent is still going
# at this point, the activity is killed and the run row is marked failed by the
# bridge. Also passed to `MultiTurnSession` as the per-turn poll budget
# (`max_poll_seconds`) so the dropped-finalization salvage fires before the activity's
# timeout — keep it below `WORKFLOW_HARD_CEILING_S`. Tuning this is a config decision,
# not a per-run override knob.
DEFAULT_MAX_RUNTIME_S = 15 * 60

# Slack added on top of `DEFAULT_MAX_RUNTIME_S` for the Temporal activity
# `start_to_close_timeout`, so heartbeat-based failures get a chance to surface
# before Temporal's own timeout fires.
ACTIVITY_SLACK_S = 60

# Hard ceiling on how long a single agent activity can actually be running. The
# workflow always sets `start_to_close_timeout = DEFAULT_MAX_RUNTIME_S + ACTIVITY_SLACK_S`,
# providing a heartbeat window before Temporal's own timeout fires. The stale-RUNNING
# self-heal in `runner.py` uses this as the staleness base.
WORKFLOW_HARD_CEILING_S = DEFAULT_MAX_RUNTIME_S + ACTIVITY_SLACK_S

# Age past which an in-flight scout run is treated as orphaned and reaped by the
# stale-run self-heal in `runner.py`. A run older than the activity's hard ceiling cannot
# still be legitimately executing — Temporal kills the activity at `WORKFLOW_HARD_CEILING_S`
# — so a `QUEUED`/`IN_PROGRESS` TaskRun past this cutoff is an orphan left behind by a
# crashed worker/sandbox that never wrote a terminal status. Set to a generous multiple of
# the ceiling so a run merely at the wall (about to fail or finish) is never reaped out from
# under itself; a lane blocked by an orphan then self-clears within one or two coordinator
# ticks.
STALE_RUN_CUTOFF_S = 2 * WORKFLOW_HARD_CEILING_S

# Consecutive failed runs after which a scout config trips its circuit breaker and is
# auto-paused (`SignalScoutConfig.auto_paused_at`). Nothing else in the harness notices a
# scout that has never once succeeded: every dispatch takes a fresh sandbox lease for the
# full runtime cap, produces nothing, and books a `failed` run — so a permanently broken
# (team, skill) lane costs a lease per interval forever. Five in a row is well past any
# plausible run of bad luck (a flaky sandbox spawn, one upstream provider error), and on the
# default daily cadence it is also the whole story: a multi-hour platform outage can cost
# such a lane at most one run, so nothing wider buys it outage tolerance — it only buys a
# permanently broken lane more leases before the breaker notices.
FAILURE_STREAK_MIN_RUNS = 5

# A lane on a tight cadence is the case the run count alone gets wrong: an outage fails
# every run fleet-wide, so at one run an hour five failures land inside an outage most of a
# workday shorter than the 24h probe cooldown the pause then costs — the healthy scouts the
# breaker exists to leave alone are exactly the ones it trips first. So the streak also has
# to span this much wall clock before it counts as a wedge, which is what
# `failure_streak_pause_threshold` converts into a per-lane run count.
FAILURE_STREAK_MIN_SPAN_MINUTES = 12 * 60

# Ceiling on the derived threshold, so a lane that runs constantly can never turn the span
# into an unbounded lease budget. The 30-minute floor on `run_interval_minutes` (and on the
# minimum gap between cron occurrences) puts the densest real lane exactly here.
FAILURE_STREAK_MAX_RUNS = 24


def failure_streak_pause_threshold(runs_in_tolerance_window: int) -> int:
    """Consecutive failures this lane has to reach before the breaker pauses it.

    Deliberately not a fleet-wide number: the same count means hours on an hourly scout and
    weeks on a monthly one, so one constant either trips healthy tight lanes during an outage
    or lets broken slow lanes burn leases for months.

    Callers pass how many runs the lane's schedule actually fits inside
    `FAILURE_STREAK_MIN_SPAN_MINUTES` — the most an outage of that length can consume, and so
    the most the breaker has to sit through before a streak means "wedged" rather than "the
    platform was down". Deliberately not derived from one gap between runs: a bursty schedule
    can pair a tight gap with only a couple of runs a day, and sizing off the gap would hand
    it the tolerance of a lane that runs all day, i.e. weeks of lease burn.
    """
    return max(FAILURE_STREAK_MIN_RUNS, min(FAILURE_STREAK_MAX_RUNS, runs_in_tolerance_window))


def interval_runs_in_tolerance_window(interval_minutes: int) -> int:
    """Runs a rolling-interval lane fits in the tolerance window — the evenly spaced case.

    Cron lanes count occurrences instead (`runner._failure_streak_runs_in_window`), since
    their gaps are uneven and no single one stands for the window's worth of runs.
    """
    if interval_minutes <= 0:
        return 1
    return -(-FAILURE_STREAK_MIN_SPAN_MINUTES // interval_minutes)  # ceil


# Cooldown a paused lane holds before the coordinator dispatches one probe — the half-open
# state. A pause is not a tombstone: whatever wedged the lane (a broken sandbox env, a skill
# the model can't work through) usually gets fixed without anyone thinking to un-pause a
# scout, so the breaker has to re-test itself. A successful probe resumes the lane; a failed
# one restarts the cooldown through its own `last_run_at` stamp. Set to a day so a wedged
# lane costs one lease per day instead of one per interval. Deliberately independent of the
# scout's own schedule: for a scout on a slower-than-daily cadence the probe IS more frequent
# than its healthy schedule, which trades at most one lease per day for recovery within a day
# rather than up to a full (possibly 30-day) interval after the underlying cause is fixed.
AUTO_PAUSE_PROBE_INTERVAL_S = 24 * 60 * 60

# Per-team ceiling on ENABLED scout configs — the per-team cost cap. Each enabled scout
# is a recurring LLM sandbox run, so this bounds what one team can switch on. Set high so
# teams can freely author scouts with minimal friction; it's a backstop against runaway
# spend, not a routine limit (the canonical fleet is ~16 scouts). Enforced at the write
# surfaces (config create/update) and in auto-registration, which falls back to registering
# new scouts disabled once the team is at the cap.
MAX_ENABLED_SCOUTS_PER_TEAM = 250
