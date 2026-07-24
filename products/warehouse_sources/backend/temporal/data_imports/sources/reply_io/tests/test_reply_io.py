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
from products.warehouse_sources.backend.temporal.data_imports.sources.reply_io import reply_io
from products.warehouse_sources.backend.temporal.data_imports.sources.reply_io.reply_io import (
    PAGE_SIZE,
    ReplyIoResumeConfig,
    check_access,
    check_endpoint_permissions,
    reply_io_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.reply_io.settings import (
    ENDPOINTS,
    REPLY_IO_ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# check_access / validate_credentials build their own tracked session in the reply_io module.
REPLY_IO_SESSION_PATCH = f"{reply_io.__name__}.make_tracked_session"


def _paged(items: list[dict[str, Any]], has_more: bool) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps({"items": items, "hasMore": has_more}).encode()
    return resp


def _bare(body: Any) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: ReplyIoResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list that captures each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the
    run shows only the final state — snapshot a copy when each request is prepared instead.
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


def _source(endpoint: str, manager: mock.MagicMock):
    return reply_io_source(
        api_key="reply-key", endpoint=endpoint, team_id=1, job_id="j", resumable_source_manager=manager
    )


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_offset_pagination_until_hasmore_false(self, MockSession) -> None:
        # A short page (< PAGE_SIZE) with hasMore=True must continue — Reply's hasMore is
        # authoritative, so unlike the built-in OffsetPaginator we don't stop on a short page.
        session = MockSession.return_value
        params = _wire(
            session,
            [_paged([{"id": 1}, {"id": 2}, {"id": 3}], has_more=True), _paged([{"id": 4}, {"id": 5}], has_more=False)],
        )

        manager = _make_manager()
        rows = _rows(_source("contacts", manager))

        assert [r["id"] for r in rows] == [1, 2, 3, 4, 5]
        assert params[0] == {"top": PAGE_SIZE, "skip": 0}
        # Offset advances by rows RECEIVED (3), not PAGE_SIZE — robust to a server-side page cap.
        assert params[1]["skip"] == 3
        # Checkpoint saved once after the first page (points at the next page); hasMore=false ends it.
        manager.save_state.assert_called_once_with(ReplyIoResumeConfig(skip=3))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_page_hasmore_false_makes_one_request_and_no_checkpoint(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_paged([{"id": 1}, {"id": 2}], has_more=False)])

        manager = _make_manager()
        rows = _rows(_source("contacts", manager))

        assert [r["id"] for r in rows] == [1, 2]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing_and_no_checkpoint(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_paged([], has_more=False)])

        manager = _make_manager()
        rows = _rows(_source("contacts", manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_offset(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_paged([{"id": 201}], has_more=False)])

        manager = _make_manager(ReplyIoResumeConfig(skip=200))
        rows = _rows(_source("contacts", manager))

        assert [r["id"] for r in rows] == [201]
        # The initial (skip=0) page is never fetched on resume.
        assert params[0]["skip"] == 200

    @parameterized.expand([("custom_fields",), ("email_template_folders",)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_unpaginated_endpoint_fetches_bare_array_once_without_state(self, endpoint: str, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_bare([{"id": 1}, {"id": 2}])])

        manager = _make_manager()
        rows = _rows(_source(endpoint, manager))

        assert [r["id"] for r in rows] == [1, 2]
        assert session.send.call_count == 1
        # Bare-array endpoints take no pagination params and never persist resume state.
        assert "top" not in params[0] and "skip" not in params[0]
        manager.save_state.assert_not_called()

    @mock.patch("time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_malformed_paginated_body_is_retried_then_recovers(self, MockSession, _sleep) -> None:
        # A 200 whose body isn't {"items": [...]} is transient: retry (re-issue), don't fail loud.
        session = MockSession.return_value
        _wire(session, [_bare([{"id": 1}]), _paged([{"id": 1}], has_more=False)])

        rows = _rows(_source("contacts", _make_manager()))
        assert [r["id"] for r in rows] == [1]
        assert session.send.call_count == 2

    @mock.patch("time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_malformed_body_exhausts_retries_and_raises_retryable(self, MockSession, _sleep) -> None:
        session = MockSession.return_value
        _wire(session, [_bare([{"id": 1}]) for _ in range(5)])

        with pytest.raises(RESTClientRetryableError):
            _rows(_source("contacts", _make_manager()))

    @mock.patch("time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_unpaginated_non_array_body_is_retryable(self, MockSession, _sleep) -> None:
        session = MockSession.return_value
        _wire(session, [_bare({"items": []}) for _ in range(5)])

        with pytest.raises(RESTClientRetryableError):
            _rows(_source("custom_fields", _make_manager()))


class TestCredentials:
    @staticmethod
    def _session(response: Any) -> mock.MagicMock:
        session = mock.MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        return session

    @staticmethod
    def _response(status: int) -> mock.MagicMock:
        response = mock.MagicMock()
        response.status_code = status
        response.ok = status < 400
        return response

    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid Reply API key"),
            ("forbidden", 403, False, "Invalid Reply API key"),
            ("server_error", 500, False, "Reply returned HTTP 500"),
        ]
    )
    @mock.patch(REPLY_IO_SESSION_PATCH)
    def test_validate_credentials_at_source_create(
        self,
        _name: str,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
        mock_session: mock.MagicMock,
    ) -> None:
        mock_session.return_value = self._session(self._response(status))
        assert validate_credentials("reply-key") == (expected_valid, expected_message)

    @mock.patch(REPLY_IO_SESSION_PATCH)
    def test_validate_credentials_for_endpoint_names_missing_scope(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value = self._session(self._response(403))
        valid, message = validate_credentials("reply-key", endpoint="sequences")
        assert valid is False
        assert message == "Your Reply API key is missing the `sequences:read` scope"

    @mock.patch(REPLY_IO_SESSION_PATCH)
    def test_check_access_connection_error_maps_to_zero(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value = self._session(requests.ConnectionError("boom"))
        status, message = check_access("reply-key", "/whoami")
        assert status == 0
        assert message is not None and "boom" in message


class TestEndpointPermissions:
    @mock.patch(f"{reply_io.__name__}.check_access")
    def test_endpoints_sharing_a_scope_share_one_probe(self, mock_access: mock.MagicMock) -> None:
        mock_access.return_value = (200, None)
        results = check_endpoint_permissions("reply-key", list(ENDPOINTS))
        assert results == dict.fromkeys(ENDPOINTS)
        distinct_scopes = {config.scope for config in REPLY_IO_ENDPOINTS.values()}
        assert mock_access.call_count == len(distinct_scopes)

    @mock.patch(f"{reply_io.__name__}.check_access")
    def test_missing_scope_marks_every_endpoint_behind_it(self, mock_access: mock.MagicMock) -> None:
        def by_path(api_key: str, path: str, paginated: bool = False) -> tuple[int, None]:
            return (403, None) if path == REPLY_IO_ENDPOINTS["contacts"].path else (200, None)

        mock_access.side_effect = by_path
        results = check_endpoint_permissions("reply-key", list(ENDPOINTS))
        denied = {name for name, reason in results.items() if reason is not None}
        assert denied == {name for name, config in REPLY_IO_ENDPOINTS.items() if config.scope == "contacts:read"}
        assert results["contacts"] == "Your Reply API key is missing the `contacts:read` scope"

    @parameterized.expand([("throttled", 429), ("server_error", 500), ("connection_error", 0)])
    @mock.patch(f"{reply_io.__name__}.check_access")
    def test_transient_errors_do_not_block_the_picker(
        self, _name: str, status: int, mock_access: mock.MagicMock
    ) -> None:
        mock_access.return_value = (status, None)
        results = check_endpoint_permissions("reply-key", ["contacts"])
        assert results == {"contacts": None}

    @mock.patch(f"{reply_io.__name__}.check_access")
    def test_unknown_endpoint_reported_reachable_without_probe(self, mock_access: mock.MagicMock) -> None:
        results = check_endpoint_permissions("reply-key", ["not_a_table"])
        assert results == {"not_a_table": None}
        mock_access.assert_not_called()


class TestReplyIoSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = _source(endpoint, _make_manager())
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # Most Reply resources expose no stable creation timestamp, so we don't partition.
        assert response.partition_mode is None
