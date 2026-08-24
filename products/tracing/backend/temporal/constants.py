import os
from datetime import timedelta

from temporalio.common import RetryPolicy

# Workflow
WORKFLOW_NAME = "tracing-alert-check"

# Schedule
SCHEDULE_ID = "tracing-alert-check-schedule"
SCHEDULE_CRON = "* * * * *"

# Activity
ACTIVITY_TIMEOUT = timedelta(minutes=5)
ACTIVITY_RETRY_POLICY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=5),
    maximum_interval=timedelta(seconds=30),
    backoff_coefficient=2.0,
)

# Number of due alerts assigned to one `evaluate_alert_batch_activity` invocation.
# Unlike logs, tracing v1 has no cohort query batching (see alert_check_query.py) —
# each alert in a batch still runs its own ClickHouse query — so this dial only
# controls Temporal fan-out granularity (activities per cycle vs. blast radius on
# retry), not ClickHouse query count.
MAX_ALERTS_PER_BATCH = int(os.environ.get("TRACING_ALERTING_MAX_ALERTS_PER_BATCH", "20"))

# How long the per-batch flush barrier waits for the Kafka broker to ack dispatched
# notifications before treating them as undelivered (state rolls back and the next
# cycle retries).
NOTIFICATION_FLUSH_TIMEOUT_SECONDS = float(os.environ.get("TRACING_ALERTING_NOTIFICATION_FLUSH_TIMEOUT_SECONDS", "10"))
