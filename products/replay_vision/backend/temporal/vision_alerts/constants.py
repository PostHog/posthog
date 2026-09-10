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
MATCH_SUMMARY_LINES = 10
# Caps one bundled event so a backlog can never build an unproducible payload.
MAX_MATCHES_PER_BUNDLE = 500
# Caps the rows one drain tick loads into memory; a larger backlog drains over later ticks.
MAX_DRAIN_ALERTS_PER_TICK = 100
MATCH_DESCRIPTOR_MAX_CHARS = 200
