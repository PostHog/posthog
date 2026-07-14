import datetime as dt

# Centralized pulse constants shared across the API and temporal layers.

PULSE_FEATURE_FLAG = "pulse"

# Soft rolling-24h cap on sandbox agent runs per team: the count is deliberately cheap and
# unlocked, so concurrent requests can slip slightly past it. Single-flight per team+config
# plus the 30-min run_agent activity timeout bound the worst case. 50 is generous enough for
# interactive dogfooding while still capping per-team sandbox spend at a sane daily ceiling.
AGENT_DAILY_RUN_CAP = 50

# Caps total wall-clock across Temporal retries/re-executions. Worst-case activity budget in
# temporal/workflow.py for the synthesize path is ~18min (gather 2x5min + synthesize 5min +
# mark-failed 3x1min); 20 keeps the in-workflow failure path authoritative.
WORKFLOW_EXECUTION_TIMEOUT = dt.timedelta(minutes=20)
# The agent path budgets differently: prepare 2x5min + run_agent 30min + validate 2x5min +
# mark-failed 3x1min = 53min worst case. The ceiling must exceed that full budget, or a mid-run
# timeout terminates the workflow externally before the in-workflow mark_brief_failed handler runs
# and the brief strands in GENERATING; 55 keeps the in-workflow failure path authoritative.
AGENT_WORKFLOW_EXECUTION_TIMEOUT = dt.timedelta(minutes=55)
