import json

import pytest
import unittest.mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.salesforce import auth


def test_salesforce_refresh_access_token_raises_on_client_failure():
    """Test whether an exception is raised when failing with a client error."""
    status_code = 400
    error_description = "Bad client!"

    response = requests.Response()
    response.status_code = status_code
    response._content = json.dumps({"error_description": error_description}).encode("utf-8")

    with (
        unittest.mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.salesforce.auth.make_tracked_session",
            return_value=type("_S", (), {"post": staticmethod(lambda *a, **k: response)})(),
        ),
        pytest.raises(auth.SalesforceAuthRequestError) as exc,
    ):
        _ = auth.salesforce_refresh_access_token("something", "https://login.salesforce.com")

    assert exc.value.response == response
    assert "Client Error" in str(exc.value)
    assert error_description in str(exc.value)


def test_salesforce_refresh_access_token_raises_on_server_failure():
    """Test whether an exception is raised when failing with a server error."""
    status_code = 500
    response_body = "something went terribly wrong"

    response = requests.Response()
    response.status_code = status_code
    response._content = response_body.encode("utf-8")

    with (
        unittest.mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.salesforce.auth.make_tracked_session",
            return_value=type("_S", (), {"post": staticmethod(lambda *a, **k: response)})(),
        ),
        pytest.raises(auth.SalesforceAuthRequestError) as exc,
    ):
        _ = auth.salesforce_refresh_access_token("something", "https://login.salesforce.com")

    assert exc.value.response == response
    assert "Server Error" in str(exc.value)
    assert response_body in str(exc.value)


def test_get_salesforce_access_token_from_code_raises_on_client_failure():
    """Test whether an exception is raised when failing with a client error."""
    status_code = 400
    error_description = "Bad client!"

    response = requests.Response()
    response.status_code = status_code
    response._content = json.dumps({"error_description": error_description}).encode("utf-8")

    with (
        unittest.mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.salesforce.auth.make_tracked_session",
            return_value=type("_S", (), {"post": staticmethod(lambda *a, **k: response)})(),
        ),
        pytest.raises(auth.SalesforceAuthRequestError) as exc,
    ):
        _ = auth.get_salesforce_access_token_from_code("something", "something", "https://login.salesforce.com")

    assert exc.value.response == response
    assert "Client Error" in str(exc.value)
    assert error_description in str(exc.value)


def test_get_salesforce_access_token_from_code_raises_on_server_failure():
    """Test whether an exception is raised when failing with a server error."""
    status_code = 500
    response_body = "something went terribly wrong"

    response = requests.Response()
    response.status_code = status_code
    response._content = response_body.encode("utf-8")

    with (
        unittest.mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.salesforce.auth.make_tracked_session",
            return_value=type("_S", (), {"post": staticmethod(lambda *a, **k: response)})(),
        ),
        pytest.raises(auth.SalesforceAuthRequestError) as exc,
    ):
        _ = auth.get_salesforce_access_token_from_code("something", "something", "https://login.salesforce.com")

    assert exc.value.response == response
    assert "Server Error" in str(exc.value)
    assert response_body in str(exc.value)


def _token_response(status_code: int, body: dict) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response._content = json.dumps(body).encode("utf-8")
    return response


def _session_returning(responses: list[requests.Response]):
    it = iter(responses)
    return type("_S", (), {"post": staticmethod(lambda *a, **k: next(it))})()


def test_refresh_retries_transient_token_request_then_succeeds():
    # Salesforce locks concurrent token requests with a 400 "token request is already being
    # processed"; the lock clears, so a retry should recover instead of failing the sync.
    responses = [
        _token_response(400, {"error_description": "token request is already being processed"}),
        _token_response(400, {"error_description": "token request is already being processed"}),
        _token_response(200, {"access_token": "fresh-token"}),
    ]

    with (
        unittest.mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.salesforce.auth.make_tracked_session",
            return_value=_session_returning(responses),
        ),
        unittest.mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.salesforce.auth.time.sleep"
        ) as mock_sleep,
    ):
        token = auth.salesforce_refresh_access_token("something", "https://login.salesforce.com")

    assert token == "fresh-token"
    assert mock_sleep.call_count == 2


def test_refresh_raises_transient_token_request_after_exhausting_retries():
    responses = [
        _token_response(400, {"error_description": "token request is already being processed"})
        for _ in range(auth._MAX_TOKEN_REFRESH_ATTEMPTS)
    ]

    with (
        unittest.mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.salesforce.auth.make_tracked_session",
            return_value=_session_returning(responses),
        ),
        unittest.mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.salesforce.auth.time.sleep"
        ) as mock_sleep,
        pytest.raises(auth.SalesforceAuthRequestError) as exc,
    ):
        _ = auth.salesforce_refresh_access_token("something", "https://login.salesforce.com")

    assert "token request is already being processed" in str(exc.value)
    assert mock_sleep.call_count == auth._MAX_TOKEN_REFRESH_ATTEMPTS - 1


def test_refresh_does_not_retry_non_transient_error():
    # A permanent auth failure must not be retried — it surfaces immediately for the
    # non-retryable classifier to catch.
    responses = [
        _token_response(400, {"error_description": "expired access/refresh token"}),
        _token_response(200, {"access_token": "should-not-be-reached"}),
    ]

    with (
        unittest.mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.salesforce.auth.make_tracked_session",
            return_value=_session_returning(responses),
        ),
        unittest.mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.salesforce.auth.time.sleep"
        ) as mock_sleep,
        pytest.raises(auth.SalesforceAuthRequestError) as exc,
    ):
        _ = auth.salesforce_refresh_access_token("something", "https://login.salesforce.com")

    assert "expired access/refresh token" in str(exc.value)
    assert mock_sleep.call_count == 0


@pytest.mark.parametrize(
    "error_description",
    [
        "expired access/refresh token",
        "inactive user",
    ],
)
def test_auth_error_is_non_retryable(error_description: str):
    """SalesforceAuthRequestErrors raised for permanent auth failures (expired/revoked token,
    deactivated user) must match a non-retryable pattern, otherwise the job retries forever."""
    from products.warehouse_sources.backend.temporal.data_imports.sources.salesforce.source import SalesforceSource

    response = requests.Response()
    response.status_code = 400
    response._content = json.dumps({"error_description": error_description}).encode("utf-8")

    with (
        unittest.mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.salesforce.auth.make_tracked_session",
            return_value=type("_S", (), {"post": staticmethod(lambda *a, **k: response)})(),
        ),
        pytest.raises(auth.SalesforceAuthRequestError) as exc,
    ):
        _ = auth.salesforce_refresh_access_token("something", "https://login.salesforce.com")

    error_message = str(exc.value)
    patterns = SalesforceSource().get_non_retryable_errors()
    assert any(pattern in error_message for pattern in patterns), (
        f"Salesforce auth error {error_message!r} did not match any non-retryable pattern"
    )
