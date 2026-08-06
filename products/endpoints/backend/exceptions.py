from rest_framework import status
from rest_framework.exceptions import APIException


class EndpointQueryTooExpensive(APIException):
    """A customer query hit a ClickHouse cost guardrail — deterministic, so 400 (not a retry-inviting 5xx)."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "query_performance_limit"
    default_detail = "This query is too expensive to run inline. Narrow its scope or materialize the endpoint."


class EndpointAtCapacity(APIException):
    """Shared ClickHouse pool momentarily at capacity — transient; materializing gives isolated compute."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_code = "query_capacity"
    default_detail = (
        "Queries are momentarily at capacity — please retry shortly. For consistently heavy "
        "endpoints, materialize to run on dedicated endpoint compute that isn't affected by shared query load."
    )
