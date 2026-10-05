import os
from datetime import timedelta

from temporalio.common import RetryPolicy

from products.apm.backend.facade.constants import BUCKET_MINUTES

# Workflow
WORKFLOW_NAME = "logs-volume-tick"

# Schedule
SCHEDULE_ID = "logs-volume-tick-schedule"
SCHEDULE_CRON = "* * * * *"

# Activity
ACTIVITY_TIMEOUT = timedelta(minutes=1)
# Discovery heuristic only ("has this team logged recently"), independent of the
# grid; it equals one bucket length by coincidence.
TEAMS_WITH_LOGS_WINDOW = timedelta(minutes=5)

# The detector's fixed UTC grid, shared through the APM facade: bucket identities
# must stay stable across ticks, backfills, and recomputes, so this is
# deliberately not env-tunable.
BUCKET_SECONDS = BUCKET_MINUTES * 60
# Teams the rollup runs over, as comma-separated ids. Empty means no team: an
# unset variable does nothing rather than sweeping the whole fleet, so a wrong
# query costs one team's scan — and later one team's rows — not 3,000.
# Discovery is unaffected: it stays fleet-wide, because its scan is what
# measures per-tick compute.
TEAM_ALLOWLIST: tuple[int, ...] = tuple(
    int(team_id) for team_id in os.environ.get("LOGS_VOLUME_TICK_TEAM_ALLOWLIST", "").split(",") if team_id.strip()
)
# Starts as a mirror of the alerting policy but is tuned independently.
ACTIVITY_RETRY_POLICY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=5),
    maximum_interval=timedelta(seconds=30),
    backoff_coefficient=2.0,
)
