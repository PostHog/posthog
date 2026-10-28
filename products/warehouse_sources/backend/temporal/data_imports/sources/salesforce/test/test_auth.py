import socket

import pytest
import unittest.mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.salesforce import auth
from products.warehouse_sources.backend.temporal.data_imports.sources.salesforce.source import SalesforceSource

# The waits between attempts of the token refresh loop: 0.5s, 1.0s and 1.5s.
REFRESH_BACKOFF_SECONDS = 3.0


def _token_response(status_code: int, body: dict) -> ScriptedResponse:
    return ScriptedResponse(status=status_code, json=body)


def _html_error_response(status_code: int, text: str) -> ScriptedResponse:
    # Salesforce's maintenance/outage pages come back as HTML, not JSON.
    return ScriptedResponse(status=status_code, body=text.encode("utf-8"))


def test_salesforce_refresh_access_token_raises_on_client_failure():
    error_description = "Bad client!"

    with (
        scripted_network([_token_response(400, {"error_description": error_description})]),
        pytest.raises(auth.SalesforceAuthRequestError) as exc,
    ):
        _ = auth.salesforce_refresh_access_token("something", "https://login.salesforce.com")

    assert exc.value.response.status_code == 400
    assert "Client Error" in str(exc.value)
    assert error_description in str(exc.value)


def test_salesforce_refresh_access_token_raises_on_server_failure():
    # A 5xx is retried like a transient outage (see test_refresh_retries_transient_server_error_*
    # below), so a session that always returns 500 exhausts the retry budget before raising.
    response_body = "something went terribly wrong"

    with (
        scripted_network(always(_html_error_response(500, response_body))),
        pytest.raises(auth.SalesforceAuthRequestError) as exc,
    ):
        _ = auth.salesforce_refresh_access_token("something", "https://login.salesforce.com")

    assert exc.value.response.status_code == 500
    assert "Server Error" in str(exc.value)
    assert response_body in str(exc.value)


def test_get_salesforce_access_token_from_code_raises_on_client_failure():
    error_description = "Bad client!"

    with (
        scripted_network([_token_response(400, {"error_description": error_description})]),
        pytest.raises(auth.SalesforceAuthRequestError) as exc,
    ):
        _ = auth.get_salesforce_access_token_from_code("something", "something", "https://login.salesforce.com")

    assert exc.value.response.status_code == 400
    assert "Client Error" in str(exc.value)
    assert error_description in str(exc.value)


def test_get_salesforce_access_token_from_code_raises_on_server_failure():
    response_body = "something went terribly wrong"

    with (
        scripted_network(always(_html_error_response(500, response_body))),
        pytest.raises(auth.SalesforceAuthRequestError) as exc,
    ):
        _ = auth.get_salesforce_access_token_from_code("something", "something", "https://login.salesforce.com")

    assert exc.value.response.status_code == 500
    assert "Server Error" in str(exc.value)
    assert response_body in str(exc.value)


@pytest.mark.parametrize(
    "lookup_error",
    [
        None,
        socket.gaierror(socket.EAI_AGAIN, "Temporary failure in name resolution"),
        socket.gaierror(socket.EAI_FAIL, "Non-recoverable failure in name resolution"),
    ],
    ids=["host_resolves", "resolver_blip", "resolver_failure"],
)
def test_refresh_raises_transport_error_after_exhausting_retries(lookup_error):
    with (
        scripted_network(always(ConnectionResetError("reset"))) as network,
        unittest.mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.salesforce.auth.socket.getaddrinfo",
            side_effect=lookup_error,
        ),
        pytest.raises(requests.exceptions.ConnectionError),
    ):
        _ = auth.salesforce_refresh_access_token("something", "https://login.salesforce.com")

    assert len(network.requests_log) >= auth._MAX_TOKEN_REFRESH_ATTEMPTS
    assert network.elapsed >= REFRESH_BACKOFF_SECONDS


def test_refresh_stops_retrying_when_instance_host_does_not_exist():
    with (
        scripted_network(always(ConnectionResetError("reset"))),
        unittest.mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.salesforce.auth.socket.getaddrinfo",
            side_effect=socket.gaierror(socket.EAI_NONAME, "Name or service not known"),
        ),
        pytest.raises(auth.SalesforceInstanceNotFoundError) as exc,
    ):
        _ = auth.salesforce_refresh_access_token("something", "https://deleted-org.my.salesforce.com")

    patterns = SalesforceSource().get_non_retryable_errors()
    assert any(pattern in str(exc.value) for pattern in patterns)
    assert "deleted-org" not in str(exc.value)


def test_refresh_raises_transient_token_request_after_exhausting_retries():
    transient = _token_response(400, {"error_description": "token request is already being processed"})

    with (
        scripted_network(always(transient)) as network,
        pytest.raises(auth.SalesforceAuthRequestError) as exc,
    ):
        _ = auth.salesforce_refresh_access_token("something", "https://login.salesforce.com")

    assert "token request is already being processed" in str(exc.value)
    assert len(network.requests_log) == auth._MAX_TOKEN_REFRESH_ATTEMPTS
    assert network.elapsed == REFRESH_BACKOFF_SECONDS


def test_refresh_retries_transient_retry_request_error_then_succeeds():
    # Salesforce's identity service occasionally answers a momentary hiccup with a 400 asking the
    # caller to retry; that should recover in-process instead of failing the sync.
    responses = [
        _token_response(400, {"error_description": "retry your request"}),
        _token_response(200, {"access_token": "fresh-token"}),
    ]

    with scripted_network(responses) as network:
        token = auth.salesforce_refresh_access_token("something", "https://login.salesforce.com")

    assert token == "fresh-token"
    assert len(network.requests_log) == 2
    assert network.elapsed == 0.5


def test_refresh_retries_transient_server_error_then_succeeds():
    # Salesforce's token endpoint occasionally returns a 503 during scheduled maintenance; the
    # request never minted a token, so a retry should recover instead of failing the sync.
    responses = [
        _html_error_response(503, "We are down for maintenance."),
        _html_error_response(503, "We are down for maintenance."),
        _token_response(200, {"access_token": "fresh-token"}),
    ]

    with scripted_network(responses) as network:
        token = auth.salesforce_refresh_access_token("something", "https://login.salesforce.com")

    assert token == "fresh-token"
    assert len(network.requests_log) == 3
    assert network.elapsed == 0.5 + 1.0


def test_refresh_raises_transient_server_error_after_exhausting_retries():
    with (
        scripted_network(always(_html_error_response(503, "We are down for maintenance."))) as network,
        pytest.raises(auth.SalesforceAuthRequestError) as exc,
    ):
        _ = auth.salesforce_refresh_access_token("something", "https://login.salesforce.com")

    assert "Server Error" in str(exc.value)
    assert len(network.requests_log) == auth._MAX_TOKEN_REFRESH_ATTEMPTS
    assert network.elapsed == REFRESH_BACKOFF_SECONDS


def test_refresh_does_not_retry_non_transient_error():
    # A permanent auth failure must not be retried — it surfaces immediately for the
    # non-retryable classifier to catch.
    responses = [
        _token_response(400, {"error_description": "expired access/refresh token"}),
        _token_response(200, {"access_token": "should-not-be-reached"}),
    ]

    with (
        scripted_network(responses) as network,
        pytest.raises(auth.SalesforceAuthRequestError) as exc,
    ):
        _ = auth.salesforce_refresh_access_token("something", "https://login.salesforce.com")

    assert "expired access/refresh token" in str(exc.value)
    assert len(network.requests_log) == 1
    assert network.elapsed == 0


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
    with (
        scripted_network([_token_response(400, {"error_description": error_description})]),
        pytest.raises(auth.SalesforceAuthRequestError) as exc,
    ):
        _ = auth.salesforce_refresh_access_token("something", "https://login.salesforce.com")

    error_message = str(exc.value)
    patterns = SalesforceSource().get_non_retryable_errors()
    assert any(pattern in error_message for pattern in patterns), (
        f"Salesforce auth error {error_message!r} did not match any non-retryable pattern"
    )
