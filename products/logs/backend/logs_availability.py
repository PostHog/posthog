from clickhouse_driver.errors import NetworkError, SocketTimeoutError
from rest_framework import status
from rest_framework.exceptions import APIException

from posthog.errors import InternalCHQueryError

# UNKNOWN_TABLE and UNKNOWN_DATABASE. A deployment that never provisioned the logs schema
# answers every logs query with one of these. Matching on the code rather than on a class,
# because only UNKNOWN_TABLE has a named exception in posthog.errors.
_MISSING_LOGS_SCHEMA_CODES = frozenset({60, 81})


class LogsNotAvailable(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = (
        "Logs aren't set up on this PostHog instance. See https://posthog.com/docs/logs/installation to set them up."
    )
    default_code = "logs_not_available"


class LogsWorkloadUnreachable(APIException):
    # A 5xx, so a real logs-cluster outage still reaches 5xx alerting, and so callers that retry
    # transient failures keep retrying. The logs cluster is configured separately from the main
    # ClickHouse, so a deployment that never configured it fails every logs query here.
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = (
        "Couldn't reach the logs storage. Try again, and if it keeps happening "
        "check this instance's ClickHouse logs cluster settings."
    )
    default_code = "logs_workload_unreachable"


def logs_unavailable_reason(err: Exception) -> type[APIException] | None:
    """The typed answer for a logs workload that holds no schema or cannot be reached, else None.

    Logs storage is provisioned per deployment, so an instance that never set it up fails every
    logs query this way. That is a state to report, not a defect to raise on.
    """
    # The two clickhouse_driver classes raised while a connection is being opened, so an unset
    # CLICKHOUSE_LOGS_CLUSTER_HOST lands here rather than on a ClickHouse error code.
    if isinstance(err, NetworkError | SocketTimeoutError):
        return LogsWorkloadUnreachable
    if isinstance(err, InternalCHQueryError) and err.code in _MISSING_LOGS_SCHEMA_CODES:
        return LogsNotAvailable
    return None
