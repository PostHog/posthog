import json
from datetime import date, datetime
from typing import Any

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.justcall.justcall import (
    JustCallResumeConfig,
    _format_cursor,
    justcall_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.justcall.settings import (
    ENDPOINTS,
    JUSTCALL_ENDPOINTS,
)

# validate_credentials builds its own tracked session in the justcall module.
JUSTCALL_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.justcall.justcall"
# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"


def _response(items: list[dict[str, Any]]) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps({"data": items, "next_page_link": None}).encode()
    return resp


def _make_manager(resume_state: JustCallResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params AT SEND TIME.

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


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _run(
    session: mock.MagicMock,
    responses: list[Response],
    endpoint: str,
    manager: mock.MagicMock,
    **kwargs: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    params = _wire(session, responses)
    rows = _rows(
        justcall_source("key", "secret", endpoint, team_id=1, job_id="j", resumable_source_manager=manager, **kwargs)
    )
    return rows, params


class TestFormatCursor:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            ("", None),
            ("   ", None),
            ("2021-08-25", "2021-08-25"),
            ("2021-08-25 10:30:00", "2021-08-25"),
            ("2021-08-25T10:30:00", "2021-08-25"),
            (date(2021, 8, 25), "2021-08-25"),
            (datetime(2021, 8, 25, 10, 30, 0), "2021-08-25"),
        ],
    )
    def test_format_cursor(self, value, expected):
        assert _format_cursor(value) == expected


class TestRequestParams:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_endpoint_sorts_by_datetime_ascending(self, MockSession):
        session = MockSession.return_value
        _, params = _run(session, [_response([{"id": 1}])], "calls", _make_manager())

        assert params[0]["sort"] == "datetime"
        assert params[0]["order"] == "asc"
        assert params[0]["per_page"] == 100
        assert params[0]["page"] == 0
        # No watermark passed → no server-side time filter on the request.
        assert "from_datetime" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_endpoint_has_no_sort_or_filter(self, MockSession):
        # `users` has no server-side time filter, so an incremental value must not leak into the request.
        session = MockSession.return_value
        _, params = _run(
            session,
            [_response([{"id": 1}])],
            "users",
            _make_manager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value="2021-08-25",
        )

        assert "sort" not in params[0]
        assert "from_datetime" not in params[0]
        assert params[0]["order"] == "asc"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_phone_numbers_uses_uppercase_order(self, MockSession):
        session = MockSession.return_value
        _, params = _run(session, [_response([{"id": 1}])], "phone_numbers", _make_manager())

        assert params[0]["order"] == "ASC"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_request_carries_from_datetime(self, MockSession):
        session = MockSession.return_value
        _, params = _run(
            session,
            [_response([{"id": 1, "call_user_date": "2021-08-25"}])],
            "calls",
            _make_manager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value="2021-08-25",
        )

        assert params[0]["from_datetime"] == "2021-08-25"
        assert params[0]["sort"] == "datetime"


class TestPagination:
    @mock.patch(f"{JUSTCALL_MODULE}.PAGE_SIZE", 2)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_short_page(self, MockSession):
        # A full page (== PAGE_SIZE) continues; a short page ends pagination with no extra request.
        session = MockSession.return_value
        rows, params = _run(
            session,
            [_response([{"id": 1}, {"id": 2}]), _response([{"id": 3}])],
            "users",
            _make_manager(),
        )

        assert [r["id"] for r in rows] == [1, 2, 3]
        assert session.send.call_count == 2
        assert params[0]["page"] == 0
        assert params[1]["page"] == 1

    @mock.patch(f"{JUSTCALL_MODULE}.PAGE_SIZE", 2)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_page_then_short_page_checkpoints_next_page(self, MockSession):
        # The first full page checkpoints the next page to fetch; the terminal short page does not.
        session = MockSession.return_value
        manager = _make_manager()
        _run(session, [_response([{"id": 1}, {"id": 2}]), _response([{"id": 3}])], "users", manager)

        manager.save_state.assert_called_once_with(JustCallResumeConfig(page=1))

    @mock.patch(f"{JUSTCALL_MODULE}.PAGE_SIZE", 2)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_stops_without_saving(self, MockSession):
        session = MockSession.return_value
        manager = _make_manager()
        rows, _ = _run(session, [_response([])], "calls", manager)

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession):
        session = MockSession.return_value
        _, params = _run(session, [_response([{"id": 9}])], "calls", _make_manager(JustCallResumeConfig(page=5)))

        assert params[0]["page"] == 5


class TestValidateCredentials:
    @pytest.mark.parametrize("status_code, expected", [(200, True), (401, False), (403, False), (500, False)])
    @mock.patch(f"{JUSTCALL_MODULE}.make_tracked_session")
    def test_status_mapping(self, mock_session, status_code, expected):
        response = mock.MagicMock(status_code=status_code)
        mock_session.return_value.get.return_value = response
        assert validate_credentials("key", "secret") is expected

    @mock.patch(f"{JUSTCALL_MODULE}.make_tracked_session")
    def test_swallows_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("key", "secret") is False


class TestJustCallSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = JUSTCALL_ENDPOINTS[endpoint]
        response = justcall_source(
            "key", "secret", endpoint, team_id=1, job_id="j", resumable_source_manager=_make_manager()
        )

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        assert response.sort_mode == "asc"
        if config.incremental_cursor:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.incremental_cursor]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("config", list(JUSTCALL_ENDPOINTS.values()))
    def test_partition_keys_are_stable_user_date_fields(self, config):
        if config.incremental_cursor:
            assert config.incremental_cursor in {"call_user_date", "sms_user_date"}
