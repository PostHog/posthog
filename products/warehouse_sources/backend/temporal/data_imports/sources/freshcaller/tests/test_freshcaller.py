import json
from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from unittest import mock

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.freshcaller.freshcaller import (
    FreshcallerResumeConfig,
    _format_datetime,
    freshcaller_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.freshcaller.settings import DEFAULT_START_DATETIME

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the freshcaller module.
FRESHCALLER_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.freshcaller.freshcaller.make_tracked_session"
)


def _page(
    data_key: str, items: list[dict], *, current: Optional[int] = None, total_pages: Optional[int] = None
) -> Response:
    body: dict[str, Any] = {data_key: items}
    if total_pages is not None:
        body["meta"] = {"current": current, "total_pages": total_pages, "total_count": 999}
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _error(status_code: int) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps({"error": "boom"}).encode()
    return resp


def _make_manager(resume_state: Optional[FreshcallerResumeConfig] = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so a copy must be snapshotted when
    each request is prepared rather than read after the run.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        prepared = mock.MagicMock()
        prepared.url = "https://acme.freshcaller.com/api/v1/x"
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any):
    return freshcaller_source(
        "key", "acme", endpoint, team_id=1, job_id="j", resumable_source_manager=manager, **kwargs
    )


class TestFormatDatetime:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            (date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("2022-01-01T00:00:00Z", "2022-01-01T00:00:00Z"),
        ],
    )
    def test_format_datetime(self, value: Any, expected: str) -> None:
        assert _format_datetime(value) == expected


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_by_page_number_and_saves_state(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _page("calls", [{"id": 1}], current=1, total_pages=2),
                _page("calls", [{"id": 2}], current=2, total_pages=2),
            ],
        )
        manager = _make_manager()

        rows = _rows(_source("calls", manager))

        assert rows == [{"id": 1}, {"id": 2}]
        assert params[0]["page"] == 1
        assert params[1]["page"] == 2
        # State saved once, pointing at page 2 (the next page after the first was written).
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == FreshcallerResumeConfig(page=2)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_page("calls", [{"id": 50}], current=5, total_pages=5)])
        manager = _make_manager(FreshcallerResumeConfig(page=5))

        _rows(_source("calls", manager))

        # First request must hit the resumed page, not page 1.
        assert params[0]["page"] == 5

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_terminates(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page("calls", [], current=1, total_pages=3)])
        manager = _make_manager()

        rows = _rows(_source("calls", manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_page_without_meta_continues_then_short_page_stops(self, MockSession) -> None:
        # With no usable meta, a full (per_page-sized) page implies more; a short page ends it.
        session = MockSession.return_value
        full = [{"id": i} for i in range(1000)]
        _wire(session, [_page("users", full), _page("users", [{"id": 1000}])])
        manager = _make_manager()

        rows = _rows(_source("users", manager))

        assert len(rows) == 1001
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_session_redacts_api_key(self, MockSession) -> None:
        # The key rides in the X-Api-Auth header; the tracked session must value-redact it so it
        # can't leak into captured HTTP samples.
        session = MockSession.return_value
        _wire(session, [_page("users", [{"id": 1}], current=1, total_pages=1)])

        _rows(_source("users", _make_manager()))

        assert MockSession.call_args.kwargs.get("redact_values") == ("key",)

    @pytest.mark.parametrize("status_code", [401, 403, 404])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_retryable_status_raises(self, MockSession, status_code: int) -> None:
        session = MockSession.return_value
        _wire(session, [_error(status_code)])
        manager = _make_manager()

        with pytest.raises(requests.HTTPError):
            _rows(_source("calls", manager))


class TestIncremental:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_call_metrics_includes_life_cycle(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_page("call_metrics", [{"id": 1}], current=1, total_pages=1)])

        _rows(
            _source(
                "call_metrics",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=None,
            )
        )

        assert params[0]["include"] == "life_cycle"
        assert params[0]["by_time[from]"] == DEFAULT_START_DATETIME


class TestValidateCredentials:
    @mock.patch(FRESHCALLER_SESSION_PATCH)
    def test_connection_error_returns_none(self, mock_make) -> None:
        mock_make.return_value.get.side_effect = requests.ConnectionError("nope")
        assert validate_credentials("acme", "key") is None

    @mock.patch(FRESHCALLER_SESSION_PATCH)
    def test_session_redacts_api_key(self, mock_make) -> None:
        mock_make.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("acme", "secret-key")
        assert mock_make.call_args.kwargs.get("redact_values") == ("secret-key",)
