import datetime as dt

from temporalio.common import RetryPolicy

SUBSCRIPTION_RECORD_LIFECYCLE_RETRY_POLICY = RetryPolicy(
    initial_interval=dt.timedelta(seconds=5),
    maximum_interval=dt.timedelta(minutes=1),
    maximum_attempts=3,
)

SUBSCRIPTION_VALIDATE_RETRY_POLICY = RetryPolicy(
    initial_interval=dt.timedelta(seconds=5),
    maximum_interval=dt.timedelta(seconds=30),
    maximum_attempts=3,
)

SUBSCRIPTION_DELIVER_RETRY_POLICY = RetryPolicy(
    initial_interval=dt.timedelta(seconds=10),
    maximum_interval=dt.timedelta(minutes=5),
    maximum_attempts=5,
)

# One attempt of the delivery activity. Temporal stops waiting once this elapses and retries the
# activity while the send it gave up on can still be running, so each channel derives its own send
# timeout from this and stays below it.
SUBSCRIPTION_DELIVER_ATTEMPT_TIMEOUT = dt.timedelta(minutes=5)
