from datetime import timedelta

from temporalio.common import RetryPolicy

from products.mcp_analytics.backend.wrapped.queries import MAX_EXECUTION_TIME_SECONDS

COORDINATOR_WORKFLOW_NAME = "mcpa-wrapped-coordinator"

MAX_CONCURRENT_TEAMS = 4
# Every project adds a few events to the workflow history, so a long run starts afresh well before Temporal's limit.
TEAMS_PER_RUN = 500

DISCOVERY_ACTIVITY_TIMEOUT = timedelta(minutes=5)
DISCOVERY_RETRY_POLICY = RetryPolicy(maximum_attempts=2, initial_interval=timedelta(seconds=5))

# An eligible project runs the monthly query and then the aggregate query, each capped at the query budget,
# so one attempt fits both with room for the Postgres write.
GENERATE_ACTIVITY_TIMEOUT = timedelta(seconds=2 * MAX_EXECUTION_TIME_SECONDS) + timedelta(minutes=5)
GENERATE_HEARTBEAT_TIMEOUT = timedelta(minutes=2)
# Offline replicas are busier and fail more often, so a project gets a few spaced retries before it counts as failed.
# A query that hits its own time or memory limit hits it again on every attempt, and each attempt rescans the
# project's whole year, so those errors fail at once. Cluster-wide memory pressure keeps its retries because it passes.
# A deleted project raises DoesNotExist, which no retry can fix.
GENERATE_RETRY_POLICY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=30),
    maximum_interval=timedelta(minutes=5),
    backoff_coefficient=3.0,
    non_retryable_error_types=[
        "ValueError",
        "TypeError",
        "DoesNotExist",
        "ClickHouseQueryTimeOut",
        "ClickHouseEstimatedQueryExecutionTimeTooLong",
        "ClickHouseQueryMemoryLimitExceeded",
    ],
)
