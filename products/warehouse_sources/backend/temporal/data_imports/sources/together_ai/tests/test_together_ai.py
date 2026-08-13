import json
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized
from requests import Response
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.together_ai import together_ai
from products.warehouse_sources.backend.temporal.data_imports.sources.together_ai.settings import TOGETHER_AI_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.together_ai.together_ai import (
    TOGETHER_AI_BASE_URL,
    get_status_code,
    together_ai_source,
)

# RESTClient builds its request session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# Neutralize tenacity's backoff sleeps so the retry path runs instantly.
SLEEP_PATCH = "tenacity.nap.time.sleep"


def _response(body: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    return resp


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and snapshot each request's url/params/auth AT SEND TIME.

    The framework builds a single ``Request`` and mutates it in place across pages, so inspecting it
    after the run shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append(
            {
                "method": request.method,
                "url": request.url,
                "params": dict(request.params or {}),
                "auth": request.auth,
            }
        )
        prepared = mock.MagicMock()
        prepared.url = request.url
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestRequests:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_yields_rows_from_wrapped_endpoint(self, MockSession) -> None:
        # fine_tunes wraps rows in {"data": [...]}; the data_selector unwraps them.
        session = MockSession.return_value
        snaps = _wire(session, [_response({"data": [{"id": "ft-1"}, {"id": "ft-2"}]})])

        rows = _rows(together_ai_source("together_test", "fine_tunes", team_id=1, job_id="j"))

        assert rows == [{"id": "ft-1"}, {"id": "ft-2"}]
        assert session.send.call_count == 1
        assert snaps[0]["method"] == "GET"
        assert snaps[0]["url"] == f"{TOGETHER_AI_BASE_URL}/fine-tunes"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_yields_rows_from_bare_array_endpoint(self, MockSession) -> None:
        # batches returns a bare JSON array (no data_selector).
        session = MockSession.return_value
        _wire(session, [_response([{"id": "batch-1"}, {"id": "batch-2"}])])

        rows = _rows(together_ai_source("together_test", "batches", team_id=1, job_id="j"))

        assert rows == [{"id": "batch-1"}, {"id": "batch-2"}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_auth_uses_bearer_token_and_accept_header(self, MockSession) -> None:
        session = MockSession.return_value
        snaps = _wire(session, [_response({"data": [{"id": "ft-1"}]})])

        _rows(together_ai_source("secret-key", "fine_tunes", team_id=1, job_id="j"))

        # The Bearer token rides on the redacted framework auth, not a hand-built header.
        assert snaps[0]["auth"].token == "secret-key"
        assert session.headers.get("Accept") == "application/json"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_endpoints_table_only_requests_dedicated_deployments(self, MockSession) -> None:
        # Without the filter the response also contains every public serverless model,
        # flooding the table with rows that duplicate the models catalog.
        session = MockSession.return_value
        snaps = _wire(session, [_response({"data": []})])

        _rows(together_ai_source("together_test", "endpoints", team_id=1, job_id="j"))

        assert snaps[0]["params"] == {"type": "dedicated"}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_top_level_endpoints_send_no_params(self, MockSession) -> None:
        session = MockSession.return_value
        snaps = _wire(session, [_response([])])

        _rows(together_ai_source("together_test", "models", team_id=1, job_id="j"))

        assert snaps[0]["params"] == {}

    @parameterized.expand([("wrapped_empty", "files", {"data": []}), ("bare_empty", "evaluations", [])])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_collection_yields_nothing(self, _name: str, endpoint: str, body: Any, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response(body)])

        assert _rows(together_ai_source("together_test", endpoint, team_id=1, job_id="j")) == []

    @parameterized.expand(
        [
            # A wrapped endpoint whose "data" key vanished means the response shape changed.
            ("wrapped_missing_data_key", "fine_tunes", {"unexpected": "shape"}),
            ("wrapped_bare_string", "files", "error"),
            # A bare-array endpoint that returned an object instead of a list.
            ("bare_object_body", "batches", {"id": "batch-1"}),
            ("bare_string_body", "models", "error"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_unexpected_shape_fails_loud(self, _name: str, endpoint: str, body: Any, MockSession) -> None:
        # A silently-swallowed shape change would sync an empty table and look like data loss.
        session = MockSession.return_value
        _wire(session, [_response(body)])

        with pytest.raises(ValueError):
            _rows(together_ai_source("together_test", endpoint, team_id=1, job_id="j"))


class TestRetryAndErrorClassification:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 502)])
    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_statuses_are_retried_then_succeed(self, _name, status_code, MockSession, _sleep) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"error": "transient"}, status_code), _response({"data": [{"id": "ft-1"}]})])

        rows = _rows(together_ai_source("together_test", "fine_tunes", team_id=1, job_id="j"))

        assert rows == [{"id": "ft-1"}]
        # First attempt hit the retryable status, second attempt succeeded.
        assert session.send.call_count == 2

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_errors_raise_without_retry(self, _name, status_code, MockSession, _sleep) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"error": "nope"}, status_code)])

        with pytest.raises(HTTPError):
            _rows(together_ai_source("together_test", "fine_tunes", team_id=1, job_id="j"))

        assert session.send.call_count == 1

    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_error_does_not_leak_bearer_token(self, MockSession, _sleep) -> None:
        # The token rides in the Authorization header (never the URL), and the framework scrubs
        # configured secrets from raised error messages — so it can't reach a stored latest_error.
        session = MockSession.return_value
        _wire(session, [_response({"error": "nope"}, 401)])

        with pytest.raises(HTTPError) as exc_info:
            _rows(together_ai_source("super-secret-key", "fine_tunes", team_id=1, job_id="j"))

        assert "super-secret-key" not in str(exc_info.value)


class TestGetStatusCode:
    def test_default_probe_hits_files_with_bearer_auth(self) -> None:
        response = mock.MagicMock()
        response.status_code = 200
        session = mock.MagicMock()
        session.get.return_value = response

        with mock.patch.object(together_ai, "make_tracked_session", return_value=session):
            status = get_status_code("together_test")

        assert status == 200
        args, kwargs = session.get.call_args
        assert args[0] == f"{TOGETHER_AI_BASE_URL}/files"
        assert kwargs["headers"]["Authorization"] == "Bearer together_test"

    def test_schema_probe_hits_that_endpoint_with_its_params(self) -> None:
        response = mock.MagicMock()
        response.status_code = 200
        session = mock.MagicMock()
        session.get.return_value = response

        with mock.patch.object(together_ai, "make_tracked_session", return_value=session):
            get_status_code("together_test", "endpoints")

        args, kwargs = session.get.call_args
        assert args[0] == f"{TOGETHER_AI_BASE_URL}/endpoints"
        assert kwargs["params"] == {"type": "dedicated"}

    def test_unknown_schema_falls_back_to_files_probe(self) -> None:
        response = mock.MagicMock()
        response.status_code = 200
        session = mock.MagicMock()
        session.get.return_value = response

        with mock.patch.object(together_ai, "make_tracked_session", return_value=session):
            get_status_code("together_test", "not_a_table")

        args, _kwargs = session.get.call_args
        assert args[0] == f"{TOGETHER_AI_BASE_URL}/files"


class TestTogetherAISourceResponse:
    @parameterized.expand(list(TOGETHER_AI_ENDPOINTS.keys()))
    def test_source_response_uses_endpoint_primary_keys_and_stable_partition(self, endpoint: str) -> None:
        response = together_ai_source("together_test", endpoint, team_id=1, job_id="j")
        cfg = TOGETHER_AI_ENDPOINTS[endpoint]
        assert response.name == endpoint
        assert response.primary_keys == cfg.primary_keys
        # Partition on the stable creation timestamp — never updated_at — so partitions
        # don't rewrite on every sync.
        assert response.partition_keys == [cfg.partition_key]
        assert response.partition_mode == "datetime"
        assert response.partition_format == "month"
