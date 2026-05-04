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

# Cap on alerts evaluated by a single batched ClickHouse query. Cohorts larger
# than this run as multiple sub-queries whose results merge back into one cohort
# result. Bounds CH read bytes and worker-side result materialization at high
# cohort sizes; at the production per-team cap (20) this never triggers.
MAX_COHORT_CHUNK_SIZE = int(os.environ.get("LOGS_ALERTING_MAX_COHORT_CHUNK_SIZE", "50"))

# Concurrency for chunked cohort sub-queries. 1 = sequential. Worst-case CH load
# from this worker is `MAX_CONCURRENT_ALERT_EVALS * MAX_CHUNK_CONCURRENCY`.
# At production cap (20 alerts/team) cohorts never chunk, so this only affects
# bypass-list teams. Override via env when CH has spare capacity.
MAX_CHUNK_CONCURRENCY = int(os.environ.get("LOGS_ALERTING_MAX_CHUNK_CONCURRENCY", "5"))
