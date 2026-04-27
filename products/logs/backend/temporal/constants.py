import os
from datetime import timedelta

from temporalio.common import RetryPolicy

# Workflow
WORKFLOW_NAME = "logs-alert-check"

# Schedule
SCHEDULE_ID = "logs-alert-check-schedule"
SCHEDULE_CRON = "* * * * *"

# Activity
ACTIVITY_TIMEOUT = timedelta(minutes=5)
ACTIVITY_RETRY_POLICY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=5),
    maximum_interval=timedelta(seconds=30),
    backoff_coefficient=2.0,
)

# Bounded concurrency for the per-alert evaluation loop. Each eval blocks on a
# ~1.3-3.7s ClickHouse query post-stateless-eval; sequential execution overruns
# the 60s cron interval past ~40 alerts at canonical-grid-aligned cadence.
# Override via env when scaling the alert population without redeploying.
MAX_CONCURRENT_ALERT_EVALS = int(os.environ.get("LOGS_ALERTING_MAX_CONCURRENT_EVALS", "5"))
