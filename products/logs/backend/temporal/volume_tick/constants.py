import os
from datetime import timedelta

from temporalio.common import RetryPolicy

from products.apm.backend.facade.api import BUCKET_MINUTES

# Workflow
WORKFLOW_NAME = "logs-volume-tick"

# Schedule
SCHEDULE_ID = "logs-volume-tick-schedule"
SCHEDULE_CRON = "* * * * *"

# Activity
ACTIVITY_TIMEOUT = timedelta(minutes=1)
TEAMS_WITH_LOGS_WINDOW = timedelta(minutes=5)

# The detector's fixed UTC grid, shared through the APM facade: bucket identities
# must stay stable across ticks, backfills, and recomputes, so this is
# deliberately not env-tunable.
BUCKET_SECONDS = BUCKET_MINUTES * 60
# One team cohort per minute of the bucket cadence: the every-minute schedule
# smears teams across the bucket's minutes (team_id % MINUTE_SHARDS), so each
# team is processed once per bucket and the write burst spreads out.
MINUTE_SHARDS = BUCKET_MINUTES
# A bucket only becomes due this long after it closes, so late-arriving logs are
# already in place when it is counted. Sized from measured prod ingestion lag:
# 99.96% of rows land within 10 minutes; the residual tail is reconciliation's job.
# A dial, not grid identity, so env-tunable without a deploy.
FINALIZATION_ALLOWANCE = timedelta(minutes=int(os.environ.get("LOGS_VOLUME_TICK_FINALIZATION_ALLOWANCE_MINUTES", "10")))
ACTIVITY_RETRY_POLICY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=5),
    maximum_interval=timedelta(seconds=30),
    backoff_coefficient=2.0,
)
