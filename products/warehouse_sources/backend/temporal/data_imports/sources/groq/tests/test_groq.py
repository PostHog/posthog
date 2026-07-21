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
from products.warehouse_sources.backend.temporal.data_imports.sources.groq.groq import (
    GROQ_BASE_URL,
    _get_headers,
    groq_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the groq module.
GROQ_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.groq.groq.make_tracked_session"
# Backoff sleeps happen inside tenacity; patch its clock so retry tests don't actually wait.
SLEEP_PATCH = "tenacity.nap.time.sleep"


def _response(body: Any, *, status: int = 200, reason: str = "OK") -> Response:
    resp = Response()
    resp.status_code = status
    resp.reason = reason
    resp.url = f"{GROQ_BASE_URL}/batches"
    resp.headers["Content-Type"] = "application/json"
    resp._content = b"" if body is None else json.dumps(body).encode()
    return resp


def _wire(session: mock.MagicMock, responses: list[Response]) -> tuple[list[dict[str, Any]], list[Any]]:
    """Wire a mock session, snapshotting each request's params and auth AT PREPARE TIME.

    ``request.params`` is a single dict mutated in place across pages, so a copy is taken per page.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []
    auth_snapshots: list[Any] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        auth_snapshots.append(request.auth)
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots, auth_snapshots


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestGroq:
    def test_get_headers_uses_bearer_auth(self) -> None:
        headers = _get_headers("gsk_secret")
        assert headers["Authorization"] == "Bearer gsk_secret"
        assert headers["Accept"] == "application/json"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_batches_follows_cursor_across_pages(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params, auths = _wire(
            session,
            [
                _response({"data": [{"id": "batch_1"}], "paging": {"next_cursor": "cur1"}}),
                _response({"data": [{"id": "batch_2"}], "paging": {"next_cursor": "cur2"}}),
                _response({"data": [{"id": "batch_3"}]}),  # no cursor -> last page
            ],
        )

        rows = _rows(groq_source("gsk_k", "batches", team_id=1, job_id="j"))

        assert [r["id"] for r in rows] == ["batch_1", "batch_2", "batch_3"]
        assert session.send.call_count == 3
        # The cursor from each page must be forwarded as the `cursor` param on the next request.
        assert "cursor" not in params[0]
        assert params[1]["cursor"] == "cur1"
        assert params[2]["cursor"] == "cur2"
        # The bearer token rides on the framework auth, not a hand-built header.
        assert auths[0].token == "gsk_k"

    @parameterized.expand([("files",), ("models",)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_paginated_reads_single_page(self, endpoint: str, MockSession: mock.MagicMock) -> None:
        # files and models are flat `data` arrays; the transport must not attempt a second request
        # even if a stray cursor is present in the body.
        session = MockSession.return_value
        _wire(session, [_response({"data": [{"id": "a"}, {"id": "b"}], "paging": {"next_cursor": "x"}})])

        rows = _rows(groq_source("gsk_k", endpoint, team_id=1, job_id="j"))

        assert [r["id"] for r in rows] == ["a", "b"]
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_data_page_yields_no_rows(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"data": []})])

        rows = _rows(groq_source("gsk_k", "models", team_id=1, job_id="j"))

        assert rows == []
        assert session.send.call_count == 1

    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_dict_body_is_retried_then_reraises(self, MockSession: mock.MagicMock, _sleep: mock.MagicMock) -> None:
        # A non-object body (bare array) is an unexpected shape; the request is reissued and, if it
        # never recovers, surfaces as a retryable error after the attempt cap.
        session = MockSession.return_value
        _wire(session, [_response(["unexpected"])] * 5)

        with pytest.raises(RESTClientRetryableError):
            _rows(groq_source("gsk_k", "models", team_id=1, job_id="j"))
        assert session.send.call_count == 5

    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_list_data_is_retried_then_reraises(self, MockSession: mock.MagicMock, _sleep: mock.MagicMock) -> None:
        # A `data` field that isn't a list (error payload or changed API shape) must not be yielded as
        # rows; it is treated as a transient malformation and reissued.
        session = MockSession.return_value
        _wire(session, [_response({"data": {"unexpected": "object"}})] * 5)

        with pytest.raises(RESTClientRetryableError):
            _rows(groq_source("gsk_k", "models", team_id=1, job_id="j"))
        assert session.send.call_count == 5

    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_malformed_body_then_valid_recovers(self, MockSession: mock.MagicMock, _sleep: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response(["glitch"]), _response({"data": [{"id": "batch_1"}]})])

        rows = _rows(groq_source("gsk_k", "models", team_id=1, job_id="j"))

        assert [r["id"] for r in rows] == ["batch_1"]
        assert session.send.call_count == 2

    @parameterized.expand([("rate_limited", 429, "Too Many Requests"), ("server_error", 503, "Service Unavailable")])
    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_status_retries_then_raises(
        self, _name: str, status: int, reason: str, MockSession: mock.MagicMock, _sleep: mock.MagicMock
    ) -> None:
        session = MockSession.return_value
        _wire(session, [_response({}, status=status, reason=reason)] * 5)

        with pytest.raises(RESTClientRetryableError):
            _rows(groq_source("gsk_k", "models", team_id=1, job_id="j"))
        assert session.send.call_count == 5

    @parameterized.expand([("unauthorized", 401, "Unauthorized"), ("forbidden", 403, "Forbidden")])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_error_raises_http_error_without_retry(
        self, _name: str, status: int, reason: str, MockSession: mock.MagicMock
    ) -> None:
        # 401/403 are credential/permission failures — never retried, surfaced as an HTTPError whose
        # message carries the stable status text that get_non_retryable_errors matches on.
        session = MockSession.return_value
        _wire(session, [_response({"error": "denied"}, status=status, reason=reason)])

        with pytest.raises(requests.HTTPError) as exc_info:
            _rows(groq_source("gsk_k", "models", team_id=1, job_id="j"))
        assert f"{status} Client Error" in str(exc_info.value)
        assert "https://api.groq.com" in str(exc_info.value)
        assert session.send.call_count == 1

    @parameterized.expand(
        [
            ("batches", "created_at"),
            ("files", "created_at"),
            ("models", "created"),
        ]
    )
    def test_groq_source_maps_primary_keys_and_partitioning(self, endpoint: str, partition_key: str) -> None:
        # No network: SourceResponse metadata is built eagerly, rows only on iteration.
        response = groq_source("gsk_k", endpoint, team_id=1, job_id="j")
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == [partition_key]

    @parameterized.expand(
        [
            ("valid", 200, True, True, 200),
            ("invalid", 401, False, False, 401),
            ("forbidden", 403, False, False, 403),
        ]
    )
    def test_validate_credentials(
        self,
        _name: str,
        status: int,
        ok: bool,
        expected_ok: bool,
        expected_status: int | None,
    ) -> None:
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=status)
        with mock.patch(GROQ_SESSION_PATCH, return_value=session):
            result_ok, result_status = validate_credentials("gsk_ok")
        assert result_ok is expected_ok
        assert result_status == expected_status

    def test_validate_credentials_empty_key_skips_request(self) -> None:
        with mock.patch(GROQ_SESSION_PATCH) as make_session:
            ok, status = validate_credentials("   ")
        assert ok is False
        assert status is None
        make_session.assert_not_called()

    def test_validate_credentials_swallows_transport_error(self) -> None:
        session = mock.MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with mock.patch(GROQ_SESSION_PATCH, return_value=session):
            ok, status = validate_credentials("gsk_x")
        assert ok is False
        assert status is None
