import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.chartmogul.chartmogul import (
    ChartMogulResumeConfig,
    _format_start_date,
    chartmogul_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the chartmogul module.
CHARTMOGUL_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.chartmogul.chartmogul.make_tracked_session"
)


def _response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    return resp


def _page(
    data_key: str,
    items: list[dict[str, Any]],
    *,
    has_more: bool = False,
    cursor: str | None = None,
) -> Response:
    return _response({data_key: items, "has_more": has_more, "cursor": cursor})


def _make_manager(resume_state: ChartMogulResumeConfig | None = None) -> mock.MagicMock:
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


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(
    endpoint: str,
    manager: mock.MagicMock,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
):
    return chartmogul_source(
        "key",
        endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
    )


class TestFormatStartDate:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14"),
            (date(2026, 3, 4), "2026-03-04"),
            ("2026-03-04", "2026-03-04"),
        ],
    )
    def test_format_start_date(self, value: object, expected: str) -> None:
        assert _format_start_date(value) == expected

    def test_no_tz_offset_in_output(self) -> None:
        assert "+00:00" not in _format_start_date(datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC))


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_across_cursors(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _page("entries", [{"uuid": "a"}], has_more=True, cursor="c1"),
                _page("entries", [{"uuid": "b"}]),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("customers", manager))

        assert [r["uuid"] for r in rows] == ["a", "b"]
        assert params[0]["per_page"] == 200
        assert "cursor" not in params[0]
        assert params[1]["cursor"] == "c1"
        # Checkpoint saved after the first page (points at the next page); final page ends it.
        manager.save_state.assert_called_once_with(ChartMogulResumeConfig(cursor="c1"))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_when_has_more_false_even_with_cursor(self, MockSession) -> None:
        # ChartMogul may still return a cursor on the last page; termination is
        # gated on has_more, not cursor presence.
        session = MockSession.return_value
        _wire(session, [_page("entries", [{"uuid": "a"}], has_more=False, cursor="c9")])

        manager = _make_manager()
        rows = _rows(_source("customers", manager))

        assert [r["uuid"] for r in rows] == ["a"]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_page("entries", [{"uuid": "b"}])])

        manager = _make_manager(ChartMogulResumeConfig(cursor="resume-cursor"))
        _rows(_source("customers", manager))

        assert params[0]["cursor"] == "resume-cursor"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_paginated_endpoint_fetches_once(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_page("data_sources", [{"uuid": "ds1"}], has_more=True, cursor="ignored")])

        manager = _make_manager()
        rows = _rows(_source("data_sources", manager))

        assert [r["uuid"] for r in rows] == ["ds1"]
        assert session.send.call_count == 1
        assert "per_page" not in params[0]
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_yields_no_rows(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page("plans", [])])

        rows = _rows(_source("plans", _make_manager()))

        assert rows == []

    @pytest.mark.parametrize("status", [429, 503])
    @mock.patch("tenacity.nap.time.sleep", return_value=None)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_status_codes_recover(self, MockSession, _mock_sleep, status: int) -> None:
        # A single retryable response then success: the client retry should
        # recover and still yield the data. The backoff sleep is patched out to
        # keep the test fast and deterministic.
        session = MockSession.return_value
        _wire(session, [_response({}, status_code=status), _page("plans", [{"uuid": "p1"}])])

        rows = _rows(_source("plans", _make_manager()))

        assert [r["uuid"] for r in rows] == ["p1"]


class TestIncrementalParams:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_activities_incremental_sets_start_date(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_page("entries", [{"uuid": "a"}])])

        _rows(
            _source(
                "activities",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
            )
        )

        assert params[0]["start-date"] == "2026-01-01T00:00:00"
        assert params[0]["per_page"] == 200

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_no_start_date_when_incremental_disabled(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_page("entries", [{"uuid": "a"}])])

        _rows(
            _source(
                "activities",
                _make_manager(),
                should_use_incremental_field=False,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )

        assert "start-date" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_incremental_endpoint_never_sets_start_date(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_page("entries", [{"uuid": "a"}])])

        _rows(
            _source(
                "customers",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )

        assert "start-date" not in params[0]


class TestValidateCredentials:
    @pytest.mark.parametrize("status,expected", [(200, True), (401, False), (403, False)])
    @mock.patch(CHARTMOGUL_SESSION_PATCH)
    def test_status_mapping(self, mock_session, status: int, expected: bool) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)
        assert validate_credentials("key") is expected

    @mock.patch(CHARTMOGUL_SESSION_PATCH)
    def test_exception_returns_false(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("key") is False


class TestChartmogulSource:
    @pytest.mark.parametrize(
        "endpoint,primary_keys,partition_key",
        [
            ("customers", ["uuid"], None),
            ("plans", ["uuid"], None),
            ("plan_groups", ["uuid"], None),
            ("invoices", ["uuid"], "date"),
            ("activities", ["uuid"], "date"),
            ("data_sources", ["uuid"], "created_at"),
        ],
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_source_response_shape(
        self, MockSession, endpoint: str, primary_keys: list[str], partition_key: str | None
    ) -> None:
        response = _source(endpoint, _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.sort_mode == "asc"
        if partition_key:
            assert response.partition_keys == [partition_key]
            assert response.partition_mode == "datetime"
        else:
            assert response.partition_keys is None
            assert response.partition_mode is None
