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

# Per-team ceiling on ENABLED scout configs — the per-team cost cap. Each enabled scout
# is a recurring LLM sandbox run, so this bounds what one team can switch on. Set high so
# teams can freely author scouts with minimal friction; it's a backstop against runaway
# spend, not a routine limit (the canonical fleet is ~16 scouts). Enforced at the write
# surfaces (config create/update) and in auto-registration, which falls back to registering
# new scouts disabled once the team is at the cap.
MAX_ENABLED_SCOUTS_PER_TEAM = 100
