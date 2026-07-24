import json
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_webfonts.google_webfonts import (
    GOOGLE_WEBFONTS_API_KEY_HEADER,
    google_webfonts_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_webfonts.settings import (
    ENDPOINTS,
    GOOGLE_WEBFONTS_ENDPOINTS,
)

# RESTClient builds its own tracked session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own probe session in the google_webfonts module.
GW_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.google_webfonts.google_webfonts.make_tracked_session"
# Neuter tenacity's backoff so retry tests don't actually sleep.
SLEEP_PATCH = "tenacity.nap.time.sleep"


def _catalog_response(items: list[dict[str, Any]]) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps({"kind": "webfonts#webfontList", "items": items}).encode()
    return resp


def _error_response(status: int) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps({"error": "boom"}).encode()
    resp.url = "https://www.googleapis.com/webfonts/v1/webfonts?sort=alpha"
    return resp


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's URL/params/auth AT SEND TIME.

    ``request.params`` is one dict mutated in place, so snapshot a copy per request.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        auth = request.auth
        snapshots.append(
            {
                "url": request.url,
                "params": dict(request.params or {}),
                "auth_name": getattr(auth, "name", None),
                "auth_key": getattr(auth, "api_key", None),
            }
        )
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestGetRows:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_request_yields_items_and_requests_stable_sort(self, MockSession) -> None:
        session = MockSession.return_value
        rows = [{"family": "Roboto"}, {"family": "Lato"}]
        snaps = _wire(session, [_catalog_response(rows)])

        result = _rows(google_webfonts_source("AIza-key", "webfonts", team_id=1, job_id="j"))

        assert result == rows
        # The catalog arrives in one unpaginated response — exactly one request.
        assert session.send.call_count == 1
        # requests applies params at prepare time; the mocked prepare leaves them separate.
        assert snaps[0]["url"] == "https://www.googleapis.com/webfonts/v1/webfonts"
        assert snaps[0]["params"]["sort"] == "alpha"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_catalog_yields_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_catalog_response([])])

        assert _rows(google_webfonts_source("AIza-key", "webfonts", team_id=1, job_id="j")) == []
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_key_rides_header_auth_and_never_lands_in_url(self, MockSession) -> None:
        # The key must ride the X-goog-api-key header (redacted by value), never the request URL.
        session = MockSession.return_value
        snaps = _wire(session, [_catalog_response([{"family": "Roboto"}])])

        _rows(google_webfonts_source("AIza-secret", "webfonts", team_id=1, job_id="j"))

        assert snaps[0]["auth_name"] == GOOGLE_WEBFONTS_API_KEY_HEADER
        assert snaps[0]["auth_key"] == "AIza-secret"
        assert "AIza-secret" not in snaps[0]["url"]
        # RESTClient builds its tracked session with the auth secret in redact_values.
        assert MockSession.call_args.kwargs["redact_values"] == ("AIza-secret",)

    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retries_retryable_status_then_succeeds(self, MockSession, _sleep) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [_error_response(500), _error_response(429), _catalog_response([{"family": "Roboto"}])],
        )

        result = _rows(google_webfonts_source("AIza-key", "webfonts", team_id=1, job_id="j"))

        assert result == [{"family": "Roboto"}]
        assert session.send.call_count == 3

    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retries_exhausted_raises(self, MockSession, _sleep) -> None:
        session = MockSession.return_value
        _wire(session, [_error_response(503) for _ in range(5)])

        with pytest.raises(RESTClientRetryableError):
            _rows(google_webfonts_source("AIza-key", "webfonts", team_id=1, job_id="j"))

        assert session.send.call_count == 5

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_error_surfaces_and_is_not_retried(self, MockSession) -> None:
        # A 400 (invalid key) is a permanent, non-retryable auth error — it must surface once
        # (get_non_retryable_errors matches on the "400 ... for url: <host>" message).
        session = MockSession.return_value
        _wire(session, [_error_response(400)])

        with pytest.raises(requests.HTTPError, match="400"):
            _rows(google_webfonts_source("AIza-key", "webfonts", team_id=1, job_id="j"))
        assert session.send.call_count == 1


class TestValidateCredentials:
    @parameterized.expand(
        [
            (200, True, None),
            (400, False, "Invalid Google API key"),
            (403, False, "Invalid Google API key"),
            (500, False, "Invalid Google API key"),
        ]
    )
    @mock.patch(GW_SESSION_PATCH)
    def test_status_mapping(self, status_code: int, expected_valid: bool, expected_msg, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)

        assert validate_credentials("AIza-key") == (expected_valid, expected_msg)

    @mock.patch(GW_SESSION_PATCH)
    def test_connection_failure_reported_distinctly(self, mock_session) -> None:
        # A transient network failure must not be reported as an invalid key, or the user wastes
        # time recreating a working credential.
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")

        assert validate_credentials("AIza-key") == (
            False,
            "Could not reach the Google Fonts API. Check your network connection and try again.",
        )

    @mock.patch(GW_SESSION_PATCH)
    def test_sends_key_in_header_not_url(self, mock_session) -> None:
        get = mock_session.return_value.get
        get.return_value = mock.MagicMock(status_code=200)

        validate_credentials("AIza-secret")

        assert get.call_args.kwargs["headers"][GOOGLE_WEBFONTS_API_KEY_HEADER] == "AIza-secret"
        url = get.call_args.args[0]
        assert "AIza-secret" not in url
        assert mock_session.call_args.kwargs["redact_values"] == ("AIza-secret",)


class TestGoogleWebfontsSourceResponse:
    @parameterized.expand([(endpoint,) for endpoint in ENDPOINTS])
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        config = GOOGLE_WEBFONTS_ENDPOINTS[endpoint]
        response = google_webfonts_source("AIza-key", endpoint, team_id=1, job_id="j")

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
        assert response.partition_count == 1
        assert response.partition_size == 1
        assert response.partition_mode is None
        assert response.partition_keys is None
