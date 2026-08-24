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

# Once this elapses Temporal stops waiting for the delivery activity and retries it, while the send
# it gave up on can still be running. Webhook deliveries carry no idempotency key, so a send still in
# flight at that point posts the card to the channel a second time. Keeping this well above the
# webhook HTTP timeouts (`_WEBHOOK_TIMEOUT_SECONDS` in `delivery_common`) makes a stuck send fail
# inside the activity instead. `test_webhook_delivery` holds the two to that order.
SUBSCRIPTION_DELIVER_START_TO_CLOSE_TIMEOUT = dt.timedelta(minutes=5)
