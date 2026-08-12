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

# How long the per-cohort flush barrier waits for the Kafka broker to ack
# dispatched notifications before treating them as undelivered (state rolls
# back and the next cycle retries). The flush drains the process-wide internal
# events producer, so concurrent cohorts' flushes piggyback on each other
# rather than stacking up.
NOTIFICATION_FLUSH_TIMEOUT_SECONDS = float(os.environ.get("LOGS_ALERTING_NOTIFICATION_FLUSH_TIMEOUT_SECONDS", "10"))

# Bounded concurrency for fanning out emit_signal in emit_alert_signals_activity.
# emit_signal is expensive (Postgres reads + Temporal workflow start), so this runs
# off the eval hot path in its own activity with bounded parallelism.
EMIT_SIGNAL_CONCURRENCY = int(os.environ.get("LOGS_ALERTING_EMIT_SIGNAL_CONCURRENCY", "20"))

# How many notified alerts to send to one emit_alert_signals_activity invocation.
# The whole list crosses the workflow->activity gRPC boundary as a single payload
# (Temporal ~2 MiB hard limit), so a platform-wide spike that notifies thousands of
# alerts in one cycle must be chunked. Also bounds retry blast radius per chunk.
EMIT_SIGNAL_BATCH_SIZE = int(os.environ.get("LOGS_ALERTING_EMIT_SIGNAL_BATCH_SIZE", "500"))
