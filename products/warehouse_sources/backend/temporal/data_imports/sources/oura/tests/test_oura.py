import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.oura import oura
from products.warehouse_sources.backend.temporal.data_imports.sources.oura.oura import (
    DEFAULT_START_DATE,
    DEFAULT_START_DATETIME,
    OuraResumeConfig,
    _format_date,
    _format_datetime,
    oura_source,
    probe_endpoint,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"


def _collection(items: list[dict[str, Any]], next_token: str | None = None, *, drop_data: bool = False) -> Response:
    body: dict[str, Any] = {"next_token": next_token}
    if not drop_data:
        body["data"] = items
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: OuraResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list capturing each request's params AT SEND TIME.

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


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _pages(source_response: Any) -> list[list[dict[str, Any]]]:
    return [list(page) for page in source_response.items()]


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any) -> Any:
    return oura_source("tok", endpoint, team_id=1, job_id="j", resumable_source_manager=manager, **kwargs)


class TestFormatHelpers:
    @parameterized.expand(
        [
            ("datetime", datetime(2021, 5, 1, 12, 30, tzinfo=UTC), "2021-05-01"),
            ("date", date(2021, 5, 1), "2021-05-01"),
            ("iso_string", "2021-05-01T00:00:00+00:00", "2021-05-01"),
        ]
    )
    def test_format_date(self, _name: str, value: Any, expected: str) -> None:
        assert _format_date(value) == expected

    @parameterized.expand(
        [
            ("aware_datetime", datetime(2021, 5, 1, 12, 0, tzinfo=UTC), "2021-05-01T12:00:00+00:00"),
            ("naive_datetime_assumed_utc", datetime(2021, 5, 1, 12, 0), "2021-05-01T12:00:00+00:00"),
            ("date_to_midnight", date(2021, 5, 1), "2021-05-01T00:00:00+00:00"),
        ]
    )
    def test_format_datetime(self, _name: str, value: Any, expected: str) -> None:
        assert _format_datetime(value) == expected


class TestDateWindowParams:
    """The server-side date window is injected as a request param before pagination begins."""

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_datetime_endpoint_first_sync_uses_default(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_collection([{"timestamp": "t", "source": "s"}])])
        _rows(_source("heartrate", _make_manager(), should_use_incremental_field=False))
        assert params[0]["start_datetime"] == DEFAULT_START_DATETIME


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_next_token_pagination(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _collection([{"id": "a"}, {"id": "b"}], next_token="tok1"),
                _collection([{"id": "c"}], next_token=None),
            ],
        )
        pages = _pages(_source("daily_sleep", _make_manager()))
        assert pages == [[{"id": "a"}, {"id": "b"}], [{"id": "c"}]]
        assert "next_token" not in params[0]
        assert params[1]["next_token"] == "tok1"
        # The date window is carried forward on every page.
        assert params[1]["start_date"] == DEFAULT_START_DATE

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_next_token(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_collection([{"id": "z"}], next_token=None)])
        rows = _rows(_source("daily_sleep", _make_manager(OuraResumeConfig(next_token="saved"))))
        assert rows == [{"id": "z"}]
        assert params[0]["next_token"] == "saved"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_data_key_raises_loudly(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_collection([], drop_data=True)])
        # A 200 body without "data" means the response shape changed — fail loud, not silently 0 rows.
        with pytest.raises(ValueError, match="matched nothing"):
            _rows(_source("daily_sleep", _make_manager()))


class TestProbeEndpoint:
    @parameterized.expand([(200,), (401,), (403,), (404,)])
    def test_returns_status_code(self, status: int) -> None:
        response = MagicMock(status_code=status)
        session = MagicMock()
        session.get.return_value = response
        with patch.object(oura, "make_tracked_session", return_value=session):
            assert probe_endpoint("tok", "/usercollection/personal_info") == status


class TestOuraSourceResponse:
    @parameterized.expand([("personal_info",), ("ring_configuration",)])
    def test_full_refresh_endpoints_are_unpartitioned(self, endpoint: str) -> None:
        response = _source(endpoint, _make_manager())
        assert response.partition_keys is None
        assert response.partition_mode is None
