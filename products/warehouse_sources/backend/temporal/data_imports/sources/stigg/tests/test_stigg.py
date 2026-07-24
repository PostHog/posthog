import json
from typing import Any, Optional

import pytest
from unittest import mock

from parameterized import parameterized
from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.stigg.settings import ENDPOINTS, STIGG_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.stigg.stigg import (
    PAGE_SIZE,
    StiggResumeConfig,
    stigg_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the stigg module.
STIGG_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.stigg.stigg.make_tracked_session"
)
# Retryable paths sleep between attempts via tenacity; patch the sleep so failure-path tests are fast.
SLEEP_PATCH = "tenacity.nap.time.sleep"


def _response(
    items: Optional[list[dict[str, Any]]], next_cursor: Optional[str] = None, *, raw_body: Any = None
) -> Response:
    """Build a Stigg list-endpoint response: ``{"data": [...], "pagination": {"next": ...}}``.

    ``raw_body`` overrides the whole body for malformed-shape cases (a bare array, or a dict
    without ``data``).
    """
    if raw_body is not None:
        body: Any = raw_body
    else:
        body = {"data": items or [], "pagination": {"next": next_cursor, "prev": None}}
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _error_response(status: int) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = b""
    resp.url = f"https://api.stigg.io/api/v1/customers?limit={PAGE_SIZE}"
    return resp


def _make_manager(resume_state: Optional[StiggResumeConfig] = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list capturing each request's params AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(manager: mock.MagicMock, endpoint: str = "customers"):
    return stigg_source("stigg-key", endpoint, team_id=1, job_id="j", resumable_source_manager=manager)


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_page_null_next_yields_and_stops(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": "a"}, {"id": "b"}], next_cursor=None)])

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert rows == [{"id": "a"}, {"id": "b"}]
        assert session.send.call_count == 1
        # pagination.next is null, so we stop without persisting resume state.
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_next_cursor_until_null(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response([{"id": "1"}, {"id": "2"}], next_cursor="cursor-page-2"),
                _response([{"id": "3"}], next_cursor=None),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert rows == [{"id": "1"}, {"id": "2"}, {"id": "3"}]
        # First page carries only `limit`; the second sends the `after` cursor.
        assert params[0] == {"limit": PAGE_SIZE}
        assert params[1] == {"limit": PAGE_SIZE, "after": "cursor-page-2"}
        # State is saved after the first page (cursor advances to pagination.next), then we stop.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == StiggResumeConfig(cursor="cursor-page-2")

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": "5"}], next_cursor=None)])

        manager = _make_manager(StiggResumeConfig(cursor="cur-99"))
        rows = _rows(_source(manager))

        assert rows == [{"id": "5"}]
        # The initial (cursorless) page is never fetched on resume — the first request carries `after`.
        assert session.send.call_count == 1
        assert params[0] == {"limit": PAGE_SIZE, "after": "cur-99"}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], next_cursor=None)])

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert rows == []
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_with_cursor_stops_without_saving(self, MockSession) -> None:
        # Defensive: an empty page terminates even if the API still returns a next cursor,
        # so a buggy upstream cursor can't loop us forever.
        session = MockSession.return_value
        _wire(session, [_response([], next_cursor="phantom-cursor")])

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()


class TestErrorHandling:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_statuses_retry_then_raise(self, _name: str, status: int, MockSession, _sleep) -> None:
        session = MockSession.return_value
        _wire(session, [_error_response(status) for _ in range(5)])

        with pytest.raises(RESTClientRetryableError):
            _rows(_source(_make_manager()))
        # 429/5xx are retried up to the client's attempt cap.
        assert session.send.call_count == 5

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_errors_raise_for_status(self, _name: str, status: int, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_error_response(status)])

        # 4xx (other than 429) is a permanent failure — surfaced immediately, not retried.
        with pytest.raises(HTTPError):
            _rows(_source(_make_manager()))
        assert session.send.call_count == 1

    @parameterized.expand(
        [
            ("bare_array", [{"id": "1"}]),
            ("missing_data_key", {"pagination": {"next": None}}),
            ("data_not_a_list", {"data": {"id": "1"}, "pagination": {"next": None}}),
        ]
    )
    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_malformed_body_shape_is_retryable(self, _name: str, raw_body: Any, MockSession, _sleep) -> None:
        session = MockSession.return_value
        _wire(session, [_response(None, raw_body=raw_body) for _ in range(5)])

        # A 200 whose body isn't `{"data": [...]}` is transient — retried, then reraised.
        with pytest.raises(RESTClientRetryableError):
            _rows(_source(_make_manager()))
        assert session.send.call_count == 5


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, None),
            (
                "unauthorized",
                401,
                False,
                "Invalid Stigg API key. Use a server API key from Settings → Integrations → API keys.",
            ),
            (
                "forbidden",
                403,
                False,
                "Invalid Stigg API key. Use a server API key from Settings → Integrations → API keys.",
            ),
            ("server_error", 500, False, "Stigg returned HTTP 500"),
        ]
    )
    @mock.patch(STIGG_SESSION_PATCH)
    def test_status_mapping(
        self, _name: str, status: int, expected_valid: bool, expected_message: Optional[str], mock_session
    ) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)
        assert validate_credentials("stigg-key") == (expected_valid, expected_message)

    @mock.patch(STIGG_SESSION_PATCH)
    def test_connection_error_maps_to_generic_message(self, mock_session) -> None:
        # validate_via_probe swallows transport errors and returns (False, None).
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("stigg-key") == (False, "Could not validate Stigg API key")


class TestSourceResponseShape:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = _source(_make_manager(), endpoint)
        assert response.name == endpoint
        assert response.primary_keys == STIGG_ENDPOINTS[endpoint].primary_keys
        # createdAt is required on every list DTO and never changes, so it's a stable partition key.
        assert response.partition_mode == "datetime"
        assert response.partition_format == "month"
        assert response.partition_keys == ["createdAt"]

    @parameterized.expand([("plans",), ("addons",)])
    def test_versioned_packages_use_composite_primary_key(self, endpoint: str) -> None:
        # Plans and addons share their `id` slug across versions; dropping `versionNumber` from
        # the key would seed duplicate rows and multi-match every later merge.
        assert STIGG_ENDPOINTS[endpoint].primary_keys == ["id", "versionNumber"]
