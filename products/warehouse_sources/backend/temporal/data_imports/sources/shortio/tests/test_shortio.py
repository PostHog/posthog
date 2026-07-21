import json
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shortio.settings import (
    ENDPOINTS,
    SHORTIO_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shortio.shortio import (
    SHORTIO_BASE_URL,
    shortio_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the shortio module.
SHORTIO_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.shortio.shortio.make_tracked_session"
)
# tenacity sleeps between client retries; patch it so failure-path tests don't wait.
SLEEP_PATCH = "tenacity.nap.time.sleep"

DOMAINS_URL = f"{SHORTIO_BASE_URL}/api/domains"

_REASONS = {
    200: "OK",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    429: "Too Many Requests",
    500: "Internal Server Error",
    503: "Service Unavailable",
}


def _response(body: Any, status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp.reason = _REASONS.get(status, "Error")
    resp.url = DOMAINS_URL
    resp._content = json.dumps(body).encode()
    return resp


def _wire(session: mock.MagicMock, responses: list[Response]) -> None:
    session.headers = {}
    session.prepare_request.side_effect = lambda request: mock.MagicMock(url=DOMAINS_URL, is_redirect=False)
    session.send.side_effect = responses


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestShortioSource:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_yields_all_rows_in_a_single_batch(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": 1}, {"id": 2}])])

        rows = _rows(shortio_source("sk-key", "domains", team_id=1, job_id="j"))

        assert rows == [{"id": 1}, {"id": 2}]
        # The domain list has no pagination — a single request returns the whole collection.
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_response_yields_nothing(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response([])])

        assert _rows(shortio_source("sk-key", "domains", team_id=1, job_id="j")) == []

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_list_body_fails_fast(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"error": "nope"})])

        # A non-list 200 means the schema changed under us — fail loud, never sync the object as a row.
        with pytest.raises(ValueError):
            _rows(shortio_source("sk-key", "domains", team_id=1, job_id="j"))

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_errors_raise_http_error_with_url(
        self, _name: str, status: int, MockSession: mock.MagicMock, _sleep: mock.MagicMock
    ) -> None:
        session = MockSession.return_value
        _wire(session, [_response({}, status=status)])

        with pytest.raises(HTTPError) as exc:
            _rows(shortio_source("sk-key", "domains", team_id=1, job_id="j"))
        # The raised message carries the status + endpoint URL so get_non_retryable_errors can match it.
        assert f"{status}" in str(exc.value)
        assert DOMAINS_URL in str(exc.value)
        # A 4xx is permanent — it must not be retried.
        assert session.send.call_count == 1

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_statuses_are_retried_then_raise(
        self, _name: str, status: int, MockSession: mock.MagicMock, _sleep: mock.MagicMock
    ) -> None:
        session = MockSession.return_value
        session.headers = {}
        session.prepare_request.side_effect = lambda request: mock.MagicMock(url=DOMAINS_URL, is_redirect=False)
        session.send.side_effect = lambda *a, **k: _response({}, status=status)

        with pytest.raises(RESTClientRetryableError):
            _rows(shortio_source("sk-key", "domains", team_id=1, job_id="j"))
        # The client exhausts its full retry budget on a persistently-erroring endpoint.
        assert session.send.call_count == 5

    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_transient_error_then_success_recovers(self, MockSession: mock.MagicMock, _sleep: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response({}, status=429), _response([{"id": 1}])])

        rows = _rows(shortio_source("sk-key", "domains", team_id=1, job_id="j"))

        assert rows == [{"id": 1}]
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_api_key_sent_raw_in_authorization_header(self, MockSession: mock.MagicMock) -> None:
        # Short.io uses the raw secret key in Authorization — no 'Bearer' prefix.
        session = MockSession.return_value
        session.headers = {}
        real_session = requests.Session()
        captured: dict[str, Any] = {}

        def _prepare(request: Any) -> Any:
            prepared = real_session.prepare_request(request)
            captured["authorization"] = prepared.headers.get("Authorization")
            return prepared

        session.prepare_request.side_effect = _prepare
        session.send.side_effect = [_response([{"id": 1}])]

        _rows(shortio_source("sk-key", "domains", team_id=1, job_id="j"))
        assert captured["authorization"] == "sk-key"

    @parameterized.expand([(e,) for e in ENDPOINTS])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_source_response_shape(self, endpoint: str, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response([])])

        response = shortio_source("sk-key", endpoint, team_id=1, job_id="j")
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # The domain list carries no stable creation timestamp guarantee, so we don't partition.
        assert response.partition_mode is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["id"] for config in SHORTIO_ENDPOINTS.values())
        assert set(SHORTIO_ENDPOINTS) == set(ENDPOINTS)


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid Short.io API key"),
            ("forbidden", 403, False, "Invalid Short.io API key"),
            ("server_error", 500, False, "Short.io returned HTTP 500"),
        ]
    )
    @mock.patch(SHORTIO_SESSION_PATCH)
    def test_status_mapping(
        self, _name: str, status: int, expected_valid: bool, expected_message: str | None, mock_session: mock.MagicMock
    ) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)
        assert validate_credentials("sk-key") == (expected_valid, expected_message)

    @mock.patch(SHORTIO_SESSION_PATCH)
    def test_connection_error_is_invalid(self, mock_session: mock.MagicMock) -> None:
        # validate_via_probe swallows transport errors and reports no status — surfaced as a
        # connection message so source creation reports "not validated" rather than crashing.
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")
        assert validate_credentials("sk-key") == (False, "Could not connect to Short.io. Please try again.")

    @mock.patch(SHORTIO_SESSION_PATCH)
    def test_api_key_sent_raw_in_probe_authorization_header(self, mock_session: mock.MagicMock) -> None:
        captured: dict[str, Any] = {}

        def _get(url: str, **kwargs: Any) -> mock.MagicMock:
            captured.update(kwargs)
            return mock.MagicMock(status_code=200)

        mock_session.return_value.get.side_effect = _get
        validate_credentials("sk-key")
        assert captured["headers"]["Authorization"] == "sk-key"
