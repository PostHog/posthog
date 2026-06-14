from __future__ import annotations

# A scout run's hard runtime cap. Enforced via the Temporal activity's
# `start_to_close_timeout` in `scout_scheduler.py` — if the agent is still going
# at this point, the activity is killed and the run row is marked failed by the
# bridge. Tuning this is a config decision, not a per-run override knob.
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

# Per-team ceiling on ENABLED scout configs — the per-team cost cap. Each enabled scout
# is a recurring LLM sandbox run, so this bounds what one team can switch on. Set high so
# teams can freely author scouts with minimal friction; it's a backstop against runaway
# spend, not a routine limit (the canonical fleet is ~16 scouts). Enforced at the write
# surfaces (config create/update) and in auto-registration, which falls back to registering
# new scouts disabled once the team is at the cap.
MAX_ENABLED_SCOUTS_PER_TEAM = 100
