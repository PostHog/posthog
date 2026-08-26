from datetime import timedelta

from temporalio.common import RetryPolicy

WORKFLOW_NAME = "replay-vision-alert-check"
SCHEDULE_ID = "replay-vision-alert-check-schedule"
SCHEDULE_CRON = "* * * * *"

ACTIVITY_TIMEOUT = timedelta(minutes=2)
ACTIVITY_RETRY_POLICY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=5),
    maximum_interval=timedelta(seconds=30),
    backoff_coefficient=2.0,
)

MAX_ALERTS_PER_BATCH = 25
# Caps the discovery result so the workflow payload stays bounded; overflow runs next tick.
MAX_ALERTS_PER_TICK = 500
NOTIFICATION_FLUSH_TIMEOUT_SECONDS = 10.0
CLEANUP_BATCH_SIZE = 1000
