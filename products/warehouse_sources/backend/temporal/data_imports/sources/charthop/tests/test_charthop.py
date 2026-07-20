import json
from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from unittest import mock

from parameterized import parameterized
from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.charthop.charthop import (
    CHARTHOP_BASE_URL,
    PAGE_SIZE,
    ChartHopAPIError,
    ChartHopResumeConfig,
    _to_charthop_date,
    charthop_source,
    resolve_org_id,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.charthop.settings import ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# resolve_org_id builds its own tracked session in the charthop module.
CHARTHOP_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.charthop.charthop.make_tracked_session"
)


def _response(
    items: Optional[list[dict[str, Any]]], *, next_token: Optional[str] = None, status_code: int = 200
) -> Response:
    body: dict[str, Any] = {"data": items or []}
    if next_token is not None:
        body["next"] = next_token
    resp = Response()
    resp.status_code = status_code
    resp.url = f"{CHARTHOP_BASE_URL}/v2/org/org-1/job"
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: Optional[ChartHopResumeConfig] = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> tuple[list[dict[str, Any]], list[str]]:
    """Wire a mock session, capturing each request's params and URL AT PREPARE TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the
    run shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []
    url_snapshots: list[str] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        url_snapshots.append(request.url)
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots, url_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any):
    return charthop_source("key", "org-1", endpoint, team_id=1, job_id="j", resumable_source_manager=manager, **kwargs)


class TestToChartHopDate:
    @parameterized.expand(
        [
            ("date", date(2026, 1, 15), "2026-01-15"),
            ("aware_datetime", datetime(2026, 1, 15, 12, 30, tzinfo=UTC), "2026-01-15"),
            ("naive_datetime", datetime(2026, 1, 15, 12, 30), "2026-01-15"),
            ("date_string", "2026-01-15", "2026-01-15"),
            ("datetime_string", "2026-01-15T12:30:00Z", "2026-01-15"),
            ("garbage_string", "not-a-date", None),
            ("non_date_type", 12345, None),
        ]
    )
    def test_coercion(self, _name: str, value: Any, expected: Optional[str]) -> None:
        assert _to_charthop_date(value) == expected

    def test_future_date_clamped_to_today(self) -> None:
        future = date.today().replace(year=date.today().year + 1)
        assert _to_charthop_date(future) == datetime.now(UTC).date().isoformat()


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_forwarding_from_token(self, MockSession) -> None:
        session = MockSession.return_value
        params, urls = _wire(session, [_response([{"id": "1"}], next_token="1"), _response([{"id": "2"}])])

        manager = _make_manager()
        rows = _rows(_source("jobs", manager))

        assert [r["id"] for r in rows] == ["1", "2"]
        assert urls[0] == f"{CHARTHOP_BASE_URL}/v2/org/org-1/job"
        assert params[0] == {"limit": PAGE_SIZE}
        assert params[1] == {"limit": PAGE_SIZE, "from": "1"}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_next_token_makes_one_request_and_no_checkpoint(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": "a"}])])

        manager = _make_manager()
        rows = _rows(_source("jobs", manager))

        assert [r["id"] for r in rows] == ["a"]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_org_id_is_encoded_as_single_path_segment(self, MockSession) -> None:
        session = MockSession.return_value
        _params, urls = _wire(session, [_response([])])

        list(
            charthop_source(
                "key", "org/../evil?x=1", "jobs", team_id=1, job_id="j", resumable_source_manager=_make_manager()
            ).items()
        )

        assert urls[0] == f"{CHARTHOP_BASE_URL}/v2/org/org%2F..%2Fevil%3Fx%3D1/job"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_state_after_yielding_each_page(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": "1"}], next_token="1"), _response([{"id": "2"}])])

        manager = _make_manager()
        _rows(_source("jobs", manager))

        manager.save_state.assert_called_once_with(ChartHopResumeConfig(from_token="1", start_date=None))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_cursor_and_start_date(self, MockSession) -> None:
        session = MockSession.return_value
        params, _urls = _wire(session, [_response([{"id": "9"}])])

        manager = _make_manager(ChartHopResumeConfig(from_token="8", start_date="2026-01-01"))
        rows = _rows(
            _source(
                "changes",
                manager,
                should_use_incremental_field=True,
                # The saved window must win over the advanced watermark on resume.
                db_incremental_field_last_value=date(2026, 2, 1),
            )
        )

        assert [r["id"] for r in rows] == ["9"]
        assert params[0]["from"] == "8"
        assert params[0]["date"] == "2026-01-01"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_date_filter_sent_on_every_page(self, MockSession) -> None:
        session = MockSession.return_value
        params, _urls = _wire(session, [_response([{"id": "1"}], next_token="1"), _response([{"id": "2"}])])

        _rows(
            _source(
                "changes",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=date(2026, 1, 15),
            )
        )

        assert all(page_params["date"] == "2026-01-15" for page_params in params)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_endpoint_never_sends_date_filter(self, MockSession) -> None:
        session = MockSession.return_value
        params, _urls = _wire(session, [_response([{"id": "1"}])])

        _rows(
            _source(
                "jobs",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=date(2026, 1, 15),
            )
        )

        assert "date" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_persons_includes_ex_employees(self, MockSession) -> None:
        session = MockSession.return_value
        params, _urls = _wire(session, [_response([])])

        rows = _rows(_source("persons", _make_manager()))

        assert rows == []
        assert params[0]["includeAll"] == "true"

    @parameterized.expand([(401,), (403,)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_http_auth_errors_raise_matchable_error(self, status_code: int, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], status_code=status_code)])

        with pytest.raises(HTTPError) as exc:
            _rows(_source("jobs", _make_manager()))
        assert f"{status_code} Client Error" in str(exc.value)


class TestResolveOrgId:
    @parameterized.expand([("plain", "org-1"), ("padded", "  org-1  ")])
    def test_configured_org_id_skips_lookup(self, _name: str, configured: str) -> None:
        session = mock.MagicMock()
        with mock.patch(CHARTHOP_SESSION_PATCH, return_value=session):
            assert resolve_org_id("key", configured) == "org-1"
        session.get.assert_not_called()

    def test_single_org_auto_detected(self) -> None:
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=200, json=lambda: {"data": [{"id": "org-9"}]})
        with mock.patch(CHARTHOP_SESSION_PATCH, return_value=session):
            assert resolve_org_id("key", None) == "org-9"

    @parameterized.expand(
        [
            ("no_orgs", [], "has no access to any organization"),
            ("multiple_orgs", [{"id": "a"}, {"id": "b"}], "can access multiple organizations"),
        ]
    )
    def test_zero_or_multiple_orgs_raise(self, _name: str, orgs: list[dict[str, Any]], expected_message: str) -> None:
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=200, json=lambda: {"data": orgs})
        with mock.patch(CHARTHOP_SESSION_PATCH, return_value=session):
            with pytest.raises(ChartHopAPIError) as exc:
                resolve_org_id("key", "")
        assert expected_message in str(exc.value)

    def test_auth_error_raises_matchable_api_error(self) -> None:
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=401)
        with mock.patch(CHARTHOP_SESSION_PATCH, return_value=session):
            with pytest.raises(ChartHopAPIError) as exc:
                resolve_org_id("key", None)
        assert "401 Client Error" in str(exc.value)


class TestChartHopSource:
    def test_changes_partitioned_by_effective_date(self) -> None:
        response = _source("changes", _make_manager())
        assert response.name == "changes"
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["date"]

    def test_full_refresh_endpoint_is_unpartitioned(self) -> None:
        response = _source("persons", _make_manager())
        assert response.partition_mode is None
        assert response.partition_keys is None

    def test_all_endpoints_buildable(self) -> None:
        for endpoint in ENDPOINTS:
            response = _source(endpoint, _make_manager())
            assert response.primary_keys == ["id"]
