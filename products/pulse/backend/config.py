import datetime as dt

from products.pulse.backend.temporal.inputs import (
    GATHER_BRIEF_ATTEMPTS,
    GATHER_BRIEF_TIMEOUT,
    MARK_STATUS_ATTEMPTS,
    MARK_STATUS_TIMEOUT,
    PREPARE_MISSION_ATTEMPTS,
    PREPARE_MISSION_TIMEOUT,
    RUN_AGENT_ATTEMPTS,
    RUN_AGENT_TIMEOUT,
    SYNTHESIZE_ATTEMPTS,
    SYNTHESIZE_TIMEOUT,
    VALIDATE_PERSIST_ATTEMPTS,
    VALIDATE_PERSIST_TIMEOUT,
)

# Centralized pulse constants shared across the API and temporal layers.

PULSE_FEATURE_FLAG = "pulse"

# Soft rolling-24h cap on sandbox agent runs per team: the count is deliberately cheap and
# unlocked, so concurrent requests can slip slightly past it. Single-flight per team+config
# plus the 30-min run_agent activity timeout bound the worst case. 50 is generous enough for
# interactive dogfooding while still capping per-team sandbox spend at a sane daily ceiling.
AGENT_DAILY_RUN_CAP = 50

# Execution-timeout ceilings cap total wall-clock across Temporal retries/re-executions. Each is
# the worst-case sequential activity budget plus a margin, so the ceiling always exceeds the budget
# and a mid-run timeout can't fire before the in-workflow mark_brief_failed handler runs (which
# would strand the brief in GENERATING). Derived from the per-activity budgets in inputs.py so the
# two stay in sync automatically — no hand-maintained magic number to drift.
_EXECUTION_TIMEOUT_MARGIN = dt.timedelta(minutes=2)
# Synthesize path: gather -> synthesize (-> mark-failed on error). ~20min.
WORKFLOW_EXECUTION_TIMEOUT = (
    GATHER_BRIEF_TIMEOUT * GATHER_BRIEF_ATTEMPTS
    + SYNTHESIZE_TIMEOUT * SYNTHESIZE_ATTEMPTS
    + MARK_STATUS_TIMEOUT * MARK_STATUS_ATTEMPTS
    + _EXECUTION_TIMEOUT_MARGIN
)
# Agent path: prepare_mission -> run_agent -> validate_and_persist (-> mark-failed on error). ~55min.
AGENT_WORKFLOW_EXECUTION_TIMEOUT = (
    PREPARE_MISSION_TIMEOUT * PREPARE_MISSION_ATTEMPTS
    + RUN_AGENT_TIMEOUT * RUN_AGENT_ATTEMPTS
    + VALIDATE_PERSIST_TIMEOUT * VALIDATE_PERSIST_ATTEMPTS
    + MARK_STATUS_TIMEOUT * MARK_STATUS_ATTEMPTS
    + _EXECUTION_TIMEOUT_MARGIN
)
