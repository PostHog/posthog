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

# Cap on alerts in a single cohort. Larger groups (same team / window / cadence /
# projection / date_to) split at cohort-build time into multiple cohorts of this
# size, each of which becomes its own task in the outer evaluation loop and
# competes for a `MAX_CONCURRENT_ALERT_EVALS` slot. Bounds per-query CH read
# bytes and worker-side result materialization. The production per-team cap (20)
# already keeps cohorts under this; the limit only matters for bypass-list teams.
MAX_ALERT_COHORT_SIZE = int(os.environ.get("LOGS_ALERTING_MAX_ALERT_COHORT_SIZE", "50"))
