from datetime import timedelta

from temporalio import common

ACTIVITY_RETRY_POLICY = common.RetryPolicy(
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(seconds=15),
    maximum_attempts=10,
)
ACTIVITY_START_TO_CLOSE_TIMEOUT = timedelta(minutes=5)
ALERT_DISPATCH_PATCH = "error-tracking-alert-dispatch-activity"
# Unlimited attempts inside the window: the start is cheap and idempotent, and only a
# Temporal outage longer than this loses the alert.
ALERT_DISPATCH_RETRY_POLICY = common.RetryPolicy(
    initial_interval=timedelta(seconds=5),
    maximum_interval=timedelta(minutes=1),
    maximum_attempts=0,
)
ALERT_DISPATCH_SCHEDULE_TO_CLOSE_TIMEOUT = timedelta(hours=1)
