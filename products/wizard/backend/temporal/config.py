from datetime import timedelta

from temporalio.common import RetryPolicy

FINALIZATION_TIMEOUT = timedelta(minutes=1)
PROVISION_TIMEOUT = timedelta(minutes=5)
PREPARATION_TIMEOUT = timedelta(minutes=10)
EXECUTION_TIMEOUT = timedelta(minutes=50)
HANDOFF_TIMEOUT = timedelta(minutes=5)
LOCAL_PACKAGE_PREPARATION_TIMEOUT = timedelta(minutes=20)
CLEANUP_TIMEOUT = timedelta(minutes=5)

FINALIZATION_RETRY_POLICY = RetryPolicy(maximum_attempts=3)
PROVISION_RETRY_POLICY = RetryPolicy(maximum_attempts=1)
PREPARATION_RETRY_POLICY = RetryPolicy(maximum_attempts=3)
EXECUTION_RETRY_POLICY = RetryPolicy(maximum_attempts=1)
# Permanent handoff failures are non-retryable, so this policy retries transient errors such as GitHub 5xx.
# The backoff spreads 5 attempts across about 5 minutes so a short GitHub outage does not discard a
# finished Wizard run. Publishing reuses the run's branch and pull request, so a repeat is safe.
# Keep the total under the sandbox TTL, because the sandbox must still exist on the last attempt.
HANDOFF_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=30),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=2),
    maximum_attempts=5,
)
LOCAL_PACKAGE_PREPARATION_RETRY_POLICY = RetryPolicy(maximum_attempts=1)
CLEANUP_RETRY_POLICY = RetryPolicy(maximum_attempts=3)
