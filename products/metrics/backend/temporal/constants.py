import os
from datetime import timedelta

from temporalio.common import RetryPolicy

# Workflow
WORKFLOW_NAME = "metrics-alert-check"

# Schedule
SCHEDULE_ID = "metrics-alert-check-schedule"
SCHEDULE_CRON = "* * * * *"

# Activity
ACTIVITY_TIMEOUT = timedelta(minutes=5)
ACTIVITY_RETRY_POLICY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=5),
    maximum_interval=timedelta(seconds=30),
    backoff_coefficient=2.0,
)

# How long the flush barrier waits for the Kafka broker to ack a dispatched
# notification before treating it as undelivered (state rolls back and the next
# cycle retries).
NOTIFICATION_FLUSH_TIMEOUT_SECONDS = float(os.environ.get("METRICS_ALERTING_NOTIFICATION_FLUSH_TIMEOUT_SECONDS", "10"))
