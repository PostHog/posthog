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
from products.warehouse_sources.backend.temporal.data_imports.sources.justcall.settings import JUSTCALL_ENDPOINTS

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
    @pytest.mark.parametrize("endpoint, page_size", [("sales_dialer_campaigns", 50), ("calls_ai", 20)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_endpoint_page_size_cap_drives_short_page_detection(self, MockSession, endpoint, page_size):
        # A full page at the endpoint's lower cap must not be read as the last page.
        session = MockSession.return_value
        full_page = [{"id": i} for i in range(page_size)]
        rows, params = _run(session, [_response(full_page), _response([{"id": page_size}])], endpoint, _make_manager())

        assert len(rows) == page_size + 1
        assert session.send.call_count == 2
        assert params[0]["per_page"] == page_size

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


class TestJustCallSourceResponse:
    @pytest.mark.parametrize("config", list(JUSTCALL_ENDPOINTS.values()))
    def test_partition_keys_are_stable_user_date_fields(self, config):
        if config.incremental_cursor:
            assert config.incremental_cursor in {"call_user_date", "sms_user_date"}
