import pytest

import requests

from products.warehouse_sources.sources.infisical.source import InfisicalSource


def _http_error_message(status_code: int, reason: str) -> str:
    # Build the exact string requests.raise_for_status produces, so the test breaks if
    # the match substring ever drifts from the real message format.
    response = requests.models.Response()
    response.status_code = status_code
    response.reason = reason
    response.url = "https://app.infisical.com/api/v1/organization/audit-logs?limit=1000&offset=0"
    with pytest.raises(requests.HTTPError) as exc_info:
        response.raise_for_status()
    return str(exc_info.value)


def test_plan_restricted_table_is_non_retryable():
    # Infisical rejects audit-logs (and secret-scanning-findings) with a 400, not a 403, when the
    # org's plan doesn't include that table. No request param we send can change that outcome.
    error_message = _http_error_message(400, "Bad Request")
    patterns = InfisicalSource().get_non_retryable_errors()
    assert any(pattern in error_message for pattern in patterns), (
        f"plan-restricted error '{error_message}' should match a non-retryable pattern"
    )


@pytest.mark.parametrize(
    "status_code,reason",
    [
        (429, "Too Many Requests"),
        (500, "Internal Server Error"),
        (503, "Service Unavailable"),
    ],
)
def test_transient_http_errors_stay_retryable(status_code, reason):
    error_message = _http_error_message(status_code, reason)
    patterns = InfisicalSource().get_non_retryable_errors()
    assert not any(pattern in error_message for pattern in patterns), (
        f"transient error '{error_message}' should remain retryable"
    )
