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

# Cap on alerts in a single cohort. Larger groups (same team / window / cadence /
# projection / date_to) split at manifest-build time into multiple cohorts of
# this size, each of which becomes its own activity-level unit. Bounds per-query
# CH read bytes and worker-side result materialization. The production per-team
# cap (20) already keeps cohorts under this; the limit only matters for
# bypass-list teams.
MAX_ALERT_COHORT_SIZE = int(os.environ.get("LOGS_ALERTING_MAX_ALERT_COHORT_SIZE", "50"))

# Number of cohorts assigned to one `evaluate_cohort_batch_activity` invocation.
# Larger batches → fewer activities per cycle (lower Temporal cost), bigger blast
# radius on failure (more cohorts re-run on retry), longer per-activity wall time.
# At ~4s per cohort with intra-batch concurrency 5, batch=20 ≈ 16s wall time
# (well under the 5-min activity timeout). Tune the cost/latency dial here.
MAX_COHORTS_PER_BATCH = int(os.environ.get("LOGS_ALERTING_MAX_COHORTS_PER_BATCH", "20"))

# How many cohorts within one batch activity run in parallel via asyncio.Semaphore +
# asyncio.gather. Pure asyncio (NOT a thread pool — the previous nested
# ThreadPoolExecutor inside asgiref's pool deadlocked under Temporal cancellation).
# Per-pod CH parallelism = max_concurrent_activities × MAX_CONCURRENT_COHORTS_PER_BATCH.
MAX_CONCURRENT_COHORTS_PER_BATCH = int(os.environ.get("LOGS_ALERTING_MAX_CONCURRENT_COHORTS_PER_BATCH", "5"))
