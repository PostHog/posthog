from rest_framework import status
from rest_framework.exceptions import APIException


class EndpointQueryTooExpensive(APIException):
    """A customer query hit a ClickHouse cost guardrail (execution time, memory, or size).

    Deterministic: the query keeps failing until the customer narrows its scope or
    materializes the endpoint, so we answer 400 (rather than a 5xx that invites blind
    retries) with an actionable `code` the client can branch on.
    """

    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "query_performance_limit"
    default_detail = "This query is too expensive to run inline. Narrow its scope or materialize the endpoint."


class EndpointAtCapacity(APIException):
    """The shared ClickHouse query pool was momentarily at capacity.

    Transient and retryable, but materializing moves the endpoint onto dedicated endpoint
    compute that isn't affected by shared-pool load — so we recommend it as the durable fix.
    """

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_code = "query_capacity"
    default_detail = (
        "Queries are momentarily at capacity — please retry shortly. For consistently heavy "
        "endpoints, materialize to run on dedicated endpoint compute that isn't affected by shared query load."
    )
