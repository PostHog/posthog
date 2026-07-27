import json
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from tenacity import wait_none

from products.warehouse_sources.backend.temporal.data_imports.sources.browserbase.browserbase import (
    BROWSERBASE_BASE_URL,
    browserbase_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.browserbase.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClient,
    RESTClientRetryableError,
)

# Both the sync transport and the credential probe build their session via the
# browserbase module's make_tracked_session (passed into the client config).
SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.browserbase.browserbase.make_tracked_session"
)


def _response(status_code: int, json_body: Any = None) -> requests.Response:
    resp = requests.Response()
    resp.status_code = status_code
    resp.url = f"{BROWSERBASE_BASE_URL}/sessions"
    resp._content = json.dumps(json_body if json_body is not None else []).encode()
    return resp


def _wire(session: mock.MagicMock, responses: list[requests.Response]) -> list[requests.PreparedRequest]:
    """Wire a mock session and capture each request AS PREPARED (auth applied, URL resolved)."""
    session.headers = {}
    prepared_requests: list[requests.PreparedRequest] = []

    def _prepare(request: requests.Request) -> requests.PreparedRequest:
        prepared = request.prepare()
        prepared_requests.append(prepared)
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return prepared_requests


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestGetRows:
    def setup_method(self) -> None:
        # Drop the exponential backoff so retryable-status tests don't actually sleep.
        # Saved and restored in teardown_method — this attribute is process-global, and leaving
        # wait_none in place breaks rest_client's own retry-wait tests in the same run.
        self._original_wait = RESTClient._send_request.retry.wait  # type: ignore[attr-defined]
        RESTClient._send_request.retry.wait = wait_none()  # type: ignore[attr-defined]

    def teardown_method(self) -> None:
        RESTClient._send_request.retry.wait = self._original_wait  # type: ignore[attr-defined]

    @mock.patch(SESSION_PATCH)
    def test_single_request_yields_all_rows(self, MockSession) -> None:
        session = MockSession.return_value
        rows_body = [{"id": "sess_1"}, {"id": "sess_2"}]
        prepared = _wire(session, [_response(200, rows_body)])

        rows = _rows(browserbase_source("bb_key", "sessions", team_id=1, job_id="j"))

        assert rows == rows_body
        # No pagination params exist - the whole collection comes back in one request.
        assert session.send.call_count == 1
        assert prepared[0].url == f"{BROWSERBASE_BASE_URL}/sessions"

    @mock.patch(SESSION_PATCH)
    def test_empty_list_yields_no_rows(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response(200, [])])

        assert _rows(browserbase_source("bb_key", "sessions", team_id=1, job_id="j")) == []

    @mock.patch(SESSION_PATCH)
    def test_non_list_response_raises(self, MockSession) -> None:
        # Browserbase list endpoints return arrays; a dict means an unexpected/error shape. Raise so
        # the sync fails loudly instead of finishing "successfully" with zero rows.
        session = MockSession.return_value
        _wire(session, [_response(200, {"statusCode": 500})])

        with pytest.raises(ValueError, match="Required a list response body"):
            _rows(browserbase_source("bb_key", "sessions", team_id=1, job_id="j"))

    @mock.patch(SESSION_PATCH)
    def test_requests_the_endpoint_path(self, MockSession) -> None:
        session = MockSession.return_value
        prepared = _wire(session, [_response(200, [{"id": "proj_1"}])])

        _rows(browserbase_source("bb_key", "projects", team_id=1, job_id="j"))

        assert prepared[0].url == f"{BROWSERBASE_BASE_URL}/projects"

    @mock.patch(SESSION_PATCH)
    def test_api_key_sent_via_header_auth(self, MockSession) -> None:
        session = MockSession.return_value
        prepared = _wire(session, [_response(200, [{"id": "sess_1"}])])

        _rows(browserbase_source("bb_test_key", "sessions", team_id=1, job_id="j"))

        assert prepared[0].headers["X-BB-API-Key"] == "bb_test_key"
        assert session.headers.get("Accept") == "application/json"

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    @mock.patch(SESSION_PATCH)
    def test_retryable_status_raises_after_retries(self, _name: str, status_code: int, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response(status_code, {"error": "nope"})] * 5)

        with pytest.raises(RESTClientRetryableError):
            _rows(browserbase_source("bb_key", "sessions", team_id=1, job_id="j"))

        # 5 attempts before giving up.
        assert session.send.call_count == 5

    @mock.patch(SESSION_PATCH)
    def test_recovers_after_transient_error(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response(500, {}), _response(200, [{"id": "sess_1"}])])

        rows = _rows(browserbase_source("bb_key", "sessions", team_id=1, job_id="j"))

        assert rows == [{"id": "sess_1"}]
        assert session.send.call_count == 2

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    @mock.patch(SESSION_PATCH)
    def test_client_error_raises_immediately(self, _name: str, status_code: int, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response(status_code, {"error": "nope"})] * 5)

        with pytest.raises(requests.HTTPError):
            _rows(browserbase_source("bb_key", "sessions", team_id=1, job_id="j"))

        # Client errors are not retried - they can never succeed on retry.
        assert session.send.call_count == 1


class TestKeyRedaction:
    @mock.patch(SESSION_PATCH)
    def test_source_session_redacts_key(self, MockSession) -> None:
        # The API key must be masked in tracked HTTP logs/samples, not left recoverable from a bucket.
        session = MockSession.return_value
        _wire(session, [_response(200, [])])

        _rows(browserbase_source("bb_secret", "sessions", team_id=1, job_id="j"))

        assert MockSession.call_args.kwargs["redact_values"] == ("bb_secret",)
        # Response bodies carry arbitrary customer userMetadata the scrubbers can't recognise.
        assert MockSession.call_args.kwargs["capture"] is False

    @mock.patch(SESSION_PATCH)
    def test_validate_credentials_redacts_key(self, MockSession) -> None:
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=200)
        MockSession.return_value = session

        validate_credentials("bb_secret")

        assert MockSession.call_args.kwargs["redact_values"] == ("bb_secret",)
        assert MockSession.call_args.kwargs["capture"] is False


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    @mock.patch(SESSION_PATCH)
    def test_maps_status_to_bool(self, _name: str, status_code: int, expected: bool, MockSession) -> None:
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=status_code)
        MockSession.return_value = session

        assert validate_credentials("bb_key") is expected

    @mock.patch(SESSION_PATCH)
    def test_probes_projects_with_key_header(self, MockSession) -> None:
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=200)
        MockSession.return_value = session

        validate_credentials("bb_key")

        assert session.get.call_args.args[0] == f"{BROWSERBASE_BASE_URL}/projects"
        assert session.get.call_args.kwargs["headers"]["X-BB-API-Key"] == "bb_key"

    @mock.patch(SESSION_PATCH)
    def test_network_error_maps_to_not_validated(self, MockSession) -> None:
        # The probe must never raise out of validate_credentials - an unreachable API means
        # "not validated", not a crashed source-create request.
        session = mock.MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        MockSession.return_value = session

        assert validate_credentials("bb_key") is False


class TestBrowserbaseSource:
    @parameterized.expand([(endpoint,) for endpoint in ENDPOINTS])
    @mock.patch(SESSION_PATCH)
    def test_source_response_shape(self, endpoint: str, MockSession) -> None:
        response = browserbase_source("bb_key", endpoint, team_id=1, job_id="j")

        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # Partition on the stable creation timestamp, never updatedAt.
        assert response.partition_keys == ["createdAt"]
        assert response.partition_mode == "datetime"
