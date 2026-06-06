from __future__ import annotations

# A scout run's hard runtime cap. Enforced via the Temporal activity's
# `start_to_close_timeout` in `scout_scheduler.py` — if the agent is still going
# at this point, the activity is killed and the run row is marked failed by the
# bridge. Tuning this is a config decision, not a per-run override knob.
DEFAULT_MAX_RUNTIME_S = 30 * 60
