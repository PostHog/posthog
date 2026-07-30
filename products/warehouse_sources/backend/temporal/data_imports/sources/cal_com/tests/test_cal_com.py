import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.cal_com.cal_com import (
    CAL_COM_BASE_URL,
    CalComResumeConfig,
    cal_com_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cal_com.settings import (
    CAL_COM_ENDPOINTS,
    ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the cal_com module.
CAL_COM_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.cal_com.cal_com.make_tracked_session"
)


def _response(body: Any, status_code: int = 200, url: str | None = None, reason: str = "OK") -> Response:
    resp = Response()
    resp.status_code = status_code
    resp.reason = reason
    resp.url = url or f"{CAL_COM_BASE_URL}/bookings"
    resp._content = json.dumps(body).encode()
    return resp


def _page(items: Any, next_cursor: str | None = None, has_more: bool = False) -> Response:
    return _response(
        {"status": "success", "data": items, "pagination": {"nextCursor": next_cursor, "hasMore": has_more}}
    )


def _make_manager(resume_state: CalComResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list that captures each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the run
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


def _source(endpoint: str, manager: mock.MagicMock | None = None, **kwargs: Any):
    return cal_com_source(
        api_key="cal_live_key",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager if manager is not None else _make_manager(),
        **kwargs,
    )


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestBookingsCursorPagination:
    def _pages(self) -> list[Response]:
        return [
            _page([{"id": 1}], next_cursor="c2", has_more=True),
            _page([{"id": 2}], next_cursor=None, has_more=False),
        ]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_next_cursor_until_exhausted(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, self._pages())

        manager = _make_manager()
        rows = _rows(_source("bookings", manager))

        assert rows == [{"id": 1}, {"id": 2}]
        # Bookings `limit` maxes at 100; a larger value is rejected with 400 Bad Request.
        assert params[0] == {"limit": 100}
        assert params[1] == {"limit": 100, "cursor": "c2"}
        # State is saved once — after the first page, pointing at the next cursor — then we stop.
        assert [call.args[0].cursor for call in manager.save_state.call_args_list] == ["c2"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_page([{"id": 2}], next_cursor=None, has_more=False)])

        manager = _make_manager(CalComResumeConfig(cursor="c2"))
        rows = _rows(_source("bookings", manager))

        # The first page must never be re-fetched on resume.
        assert rows == [{"id": 2}]
        assert session.send.call_count == 1
        assert params[0]["cursor"] == "c2"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page([], next_cursor=None, has_more=False)])

        manager = _make_manager()
        rows = _rows(_source("bookings", manager))

        assert rows == []
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_filter_param_sent_on_every_page(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, self._pages())

        _rows(
            _source(
                "bookings",
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
                incremental_field="updatedAt",
            )
        )

        for call_params in params:
            assert call_params["afterUpdatedAt"] == "2026-01-02T03:04:05.000Z"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_created_at_maps_to_after_created_at(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, self._pages())

        _rows(
            _source(
                "bookings",
                should_use_incremental_field=True,
                db_incremental_field_last_value=date(2026, 1, 2),
                incremental_field="createdAt",
            )
        )

        assert params[0]["afterCreatedAt"] == "2026-01-02T00:00:00.000Z"
        assert "afterUpdatedAt" not in params[0]

    def test_unknown_incremental_field_raises(self) -> None:
        with pytest.raises(ValueError, match="no server-side filter"):
            _source(
                "bookings",
                should_use_incremental_field=True,
                db_incremental_field_last_value="2026-01-01",
                incremental_field="startTime",
            )

    @parameterized.expand(
        [
            ("incremental_disabled", False, "2026-01-01"),
            ("no_last_value", True, None),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_no_filter_param_without_watermark(
        self, _name: str, should_use: bool, last_value: Any, MockSession
    ) -> None:
        session = MockSession.return_value
        params = _wire(session, self._pages())

        _rows(
            _source(
                "bookings",
                should_use_incremental_field=should_use,
                db_incremental_field_last_value=last_value,
                incremental_field="updatedAt",
            )
        )

        assert "afterUpdatedAt" not in params[0]


class TestWebhooksOffsetPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_advances_skip_until_short_page(self, MockSession) -> None:
        session = MockSession.return_value
        page_size = CAL_COM_ENDPOINTS["webhooks"].page_size
        full_page = [{"id": i} for i in range(page_size)]
        params = _wire(session, [_response({"data": full_page}), _response({"data": [{"id": "last"}]})])

        manager = _make_manager()
        rows = _rows(_source("webhooks", manager))

        assert len(rows) == page_size + 1
        # Webhooks `take` maxes at 250; a larger value is rejected with 400 Bad Request.
        assert params[0]["take"] == 250
        assert [p["skip"] for p in params] == [0, page_size]
        assert [call.args[0].skip for call in manager.save_state.call_args_list] == [page_size]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_offset(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response({"data": [{"id": "resumed"}]})])

        manager = _make_manager(CalComResumeConfig(skip=500))
        rows = _rows(_source("webhooks", manager))

        assert rows == [{"id": "resumed"}]
        assert params[0]["skip"] == 500


class TestSingleFetchEndpoints:
    @parameterized.expand([("event_types",), ("schedules",), ("teams",)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_list_endpoints_yield_single_batch(self, endpoint: str, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"data": [{"id": 1}, {"id": 2}]})])

        manager = _make_manager()
        rows = _rows(_source(endpoint, manager))

        assert rows == [{"id": 1}, {"id": 2}]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_me_wraps_single_object_in_list(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"data": {"id": 42, "username": "tom"}})])

        rows = _rows(_source("me"))
        assert rows == [{"id": 42, "username": "tom"}]

    @parameterized.expand(
        [
            ("bookings", "2026-05-01"),
            ("event_types", "2024-06-14"),
            ("schedules", "2024-06-11"),
            ("teams", None),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_endpoint_versions_pinned_in_headers(
        self, endpoint: str, expected_version: str | None, MockSession
    ) -> None:
        # Omitting cal-api-version silently falls back to legacy endpoint behavior, so the
        # versioned endpoints must pin it.
        session = MockSession.return_value
        session.headers = {}

        _source(endpoint)

        assert session.headers.get("cal-api-version") == expected_version


class TestErrorHandling:
    @parameterized.expand(
        [
            ("bare_list", [{"id": 1}]),
            ("missing_data", {"status": "success"}),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_unexpected_payload_shape_fails_loudly(self, _name: str, body: Any, MockSession) -> None:
        # A 200 body without `data` means the response shape changed — fail loud, not silently 0 rows.
        session = MockSession.return_value
        _wire(session, [_response(body)])

        with pytest.raises(ValueError, match="matched nothing"):
            _rows(_source("me"))

    @parameterized.expand(
        [
            ("unauthorized", 401, "Unauthorized"),
            ("forbidden", 403, "Forbidden"),
            ("not_found", 404, "Not Found"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_errors_raise_http_error_with_base_url(
        self, _name: str, status: int, reason: str, MockSession
    ) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [_response({}, status_code=status, url=f"{CAL_COM_BASE_URL}/bookings?limit=100", reason=reason)],
        )

        with pytest.raises(requests.HTTPError) as exc_info:
            _rows(_source("bookings"))

        # The base URL must be in the message so `get_non_retryable_errors()` can match on it.
        assert f"{status} Client Error: {reason} for url: {CAL_COM_BASE_URL}/bookings" in str(exc_info.value)


class TestValidateCredentials:
    def _session(self, response: Any) -> mock.MagicMock:
        session = mock.MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        return session

    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid Cal.com API key"),
            ("forbidden", 403, False, "Invalid Cal.com API key"),
            ("server_error", 500, False, "Cal.com returned HTTP 500"),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected_valid: bool, expected_message: str | None) -> None:
        response = mock.MagicMock(status_code=status)
        with mock.patch(CAL_COM_SESSION_PATCH, return_value=self._session(response)):
            assert validate_credentials("cal_live_key") == (expected_valid, expected_message)

    def test_connection_error_is_swallowed(self) -> None:
        session = self._session(requests.ConnectionError("boom"))
        with mock.patch(CAL_COM_SESSION_PATCH, return_value=session):
            assert validate_credentials("cal_live_key") == (False, "Could not connect to Cal.com")


class TestCalComSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_source_response_shape(self, endpoint: str, MockSession) -> None:
        MockSession.return_value.headers = {}
        response = _source(endpoint)
        assert response.name == endpoint
        assert response.primary_keys == ["id"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_bookings_partitions_on_stable_created_at(self, MockSession) -> None:
        MockSession.return_value.headers = {}
        response = _source("bookings")
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["createdAt"]
        # Bookings arrive newest-first, so the watermark must only commit after a complete sync.
        assert response.sort_mode == "desc"

    @parameterized.expand([(e,) for e in ENDPOINTS if e != "bookings"])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_endpoints_do_not_partition(self, endpoint: str, MockSession) -> None:
        MockSession.return_value.headers = {}
        response = _source(endpoint)
        assert response.partition_mode is None
        assert response.sort_mode == "asc"
