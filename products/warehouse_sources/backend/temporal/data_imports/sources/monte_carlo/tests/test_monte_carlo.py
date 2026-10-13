from datetime import UTC, datetime

import pytest
import time_machine
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.montecarlo import (
    MonteCarloSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.monte_carlo.monte_carlo import (
    MonteCarloGraphQLError,
    MonteCarloResumeConfig,
    _execute_query,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.monte_carlo.settings import MONTE_CARLO_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.monte_carlo.source import MonteCarloSource


def _relay_page(data_path: str, nodes: list[dict], end_cursor: str | None) -> dict:
    return {
        data_path: {
            "edges": [{"node": node} for node in nodes],
            "pageInfo": {"endCursor": end_cursor, "hasNextPage": end_cursor is not None},
        }
    }


def _driver() -> SourceDriver:
    return SourceDriver(MonteCarloSource(), MonteCarloSourceConfig(api_key_id="key-id", api_key_secret="key-secret"))


def _response(data: dict) -> ScriptedResponse:
    return ScriptedResponse(json={"data": data})


class TestExecuteQuery:
    def _response(self, status_code: int, payload: dict | None = None) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.json.return_value = payload or {}
        return response

    def test_raises_on_graphql_errors(self) -> None:
        session = MagicMock()
        session.post.return_value = self._response(200, {"errors": [{"message": "not allowed"}]})
        try:
            _execute_query(session, "query {}", {}, MagicMock())
            raise AssertionError("expected MonteCarloGraphQLError")
        except MonteCarloGraphQLError as e:
            assert "not allowed" in str(e)

    @parameterized.expand([(429,), (500,), (503,)])
    def test_retries_retryable_statuses_then_succeeds(self, status_code: int) -> None:
        session = MagicMock()
        session.post.side_effect = [
            self._response(status_code),
            self._response(200, {"data": {"getWarehouses": []}}),
        ]
        with patch.object(_execute_query.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            assert _execute_query(session, "query {}", {}, MagicMock()) == {"getWarehouses": []}
        assert session.post.call_count == 2

    def test_raises_http_error_on_unauthorized(self) -> None:
        session = MagicMock()
        response = self._response(401)
        response.raise_for_status.side_effect = requests.HTTPError("401 Client Error", response=response)
        session.post.return_value = response
        try:
            _execute_query(session, "query {}", {}, MagicMock())
            raise AssertionError("expected HTTPError")
        except requests.HTTPError:
            pass


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("valid", 200, {"data": {"getUser": {"email": "a@b.com"}}}, True),
            ("unauthorized", 401, {"message": "Unauthorized"}, False),
            ("graphql_error", 200, {"errors": [{"message": "boom"}]}, False),
        ]
    )
    def test_status_mapping(self, _label: str, status_code: int, payload: dict, expected: bool) -> None:
        with scripted_network([ScriptedResponse(status=status_code, json=payload)]) as network:
            assert validate_credentials("key-id", "key-secret") is expected
        assert len(network.requests_log) == 1
        assert network.requests_log[0].json()["variables"] == {}
        assert network.requests_log[0].headers["x-mcd-id"] == "key-id"
        assert network.requests_log[0].headers["x-mcd-token"] == "key-secret"

    def test_network_error_is_invalid(self) -> None:
        with scripted_network(always(ConnectionError("boom"))) as network:
            assert validate_credentials("key-id", "key-secret") is False
        assert {request.path for request in network.requests_log} == {"/graphql"}


class TestRelayEndpoints:
    @parameterized.expand([("domains", "getDomainsV2"), ("tables", "getTables"), ("users", "getUsersInAccount")])
    def test_paginates_until_has_next_page_false(self, endpoint: str, data_path: str) -> None:
        responses = [
            _relay_page(data_path, [{"id": "1"}, {"id": "2"}], "cursor-1"),
            _relay_page(data_path, [{"id": "3"}], None),
        ]
        result = _driver().run(endpoint, [_response(data) for data in responses])

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["1", "2", "3"]
        assert result.requests[0].json()["variables"]["after"] is None
        assert result.requests[1].json()["variables"]["after"] == "cursor-1"
        # State saved after the yielded page, only while more pages remain.
        assert [state.cursor for state in result.saved_states] == ["cursor-1"]

    def test_resumes_from_saved_cursor(self) -> None:
        responses = [_relay_page("getTables", [{"id": "9"}], None)]
        result = _driver().run(
            "tables", [_response(data) for data in responses], resume_state=MonteCarloResumeConfig(cursor="cursor-42")
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["9"]
        assert result.requests[0].json()["variables"]["after"] == "cursor-42"


class TestEventsEndpoint:
    @parameterized.expand(
        [
            ("incremental", True, datetime(2026, 6, 1, tzinfo=UTC), "2026-06-01T00:00:00Z"),
            ("incremental_first_sync", True, None, None),
            ("full_refresh_ignores_watermark", False, datetime(2026, 6, 1, tzinfo=UTC), None),
        ]
    )
    def test_start_time_filter(
        self, _label: str, use_incremental: bool, watermark: datetime | None, expected_start: str | None
    ) -> None:
        responses = [
            _relay_page("getEvents", [{"uuid": "e-1"}], "cursor-1"),
            _relay_page("getEvents", [{"uuid": "e-2"}], None),
        ]
        result = _driver().run(
            "events",
            [_response(data) for data in responses],
            should_use_incremental_field=use_incremental,
            db_incremental_field_last_value=watermark,
        )

        assert result.raised is None
        assert [row["uuid"] for row in result.rows] == ["e-1", "e-2"]
        calls = [request.json()["variables"] for request in result.requests]
        for call in calls:
            assert call.get("startTime") == expected_start
            assert call["descOrder"] is False
        assert calls[1]["after"] == "cursor-1"
        assert [(state.cursor, state.window_after) for state in result.saved_states] == [("cursor-1", expected_start)]

    def test_resume_replays_cursor_against_saved_start_time(self) -> None:
        responses = [_relay_page("getEvents", [{"uuid": "e-9"}], None)]
        result = _driver().run(
            "events",
            [_response(data) for data in responses],
            resume_state=MonteCarloResumeConfig(cursor="cursor-3", window_after="2026-05-01T00:00:00Z"),
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 6, 1, tzinfo=UTC),
        )

        assert result.raised is None
        variables = result.requests[0].json()["variables"]
        assert variables["after"] == "cursor-3"
        assert variables["startTime"] == "2026-05-01T00:00:00Z"


class TestOffsetEndpoint:
    def test_paginates_until_short_page(self) -> None:
        page_size = MONTE_CARLO_ENDPOINTS["monitors"].page_size
        full_page = [{"uuid": f"m-{i}"} for i in range(page_size)]
        responses = [{"getMonitors": full_page}, {"getMonitors": [{"uuid": "last"}]}]
        result = _driver().run("monitors", [_response(data) for data in responses])

        assert result.raised is None
        assert len(result.rows) == page_size + 1
        assert result.requests[0].json()["variables"]["offset"] == 0
        assert result.requests[1].json()["variables"]["offset"] == page_size
        assert [state.offset for state in result.saved_states] == [page_size]

    def test_resumes_from_saved_offset(self) -> None:
        responses = [{"getMonitors": [{"uuid": "m-200"}]}]
        result = _driver().run(
            "monitors", [_response(data) for data in responses], resume_state=MonteCarloResumeConfig(offset=200)
        )
        assert result.raised is None
        assert result.requests[0].json()["variables"]["offset"] == 200

    def test_empty_first_page_yields_nothing(self) -> None:
        result = _driver().run("monitors", [_response({"getMonitors": []})])
        assert result.raised is None
        assert result.rows == []


class TestUnpaginatedEndpoint:
    def test_warehouses_single_query(self) -> None:
        responses = [{"getWarehouses": [{"uuid": "w-1"}, {"uuid": "w-2"}]}]
        result = _driver().run("warehouses", [_response(data) for data in responses])
        assert result.raised is None
        assert [row["uuid"] for row in result.rows] == ["w-1", "w-2"]
        assert len(result.requests) == 1
        assert result.saved_states == []


class TestAlertsWindowing:
    @pytest.fixture(autouse=True)
    def _frozen_clock(self):
        with time_machine.travel("2026-07-15T12:00:00Z", tick=False):
            yield

    def test_first_sync_walks_year_of_30_day_windows(self) -> None:
        empty = _relay_page("getAlerts", [], None)
        responses = [empty] * 13  # 365 days / 30-day windows
        result = _driver().run(
            "alerts",
            [_response(data) for data in responses],
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
        )

        assert result.raised is None
        assert result.rows == []
        assert len(result.requests) == 13
        first_window = result.requests[0].json()["variables"]["createdTime"]
        assert first_window["after"] == "2025-07-15T12:00:00Z"
        assert first_window["before"] == "2025-08-14T12:00:00Z"
        last_window = result.requests[-1].json()["variables"]["createdTime"]
        assert last_window["before"] == "2026-07-15T12:00:00Z"

    def test_saves_cursor_state_mid_window_and_bookmark_between_windows(self) -> None:
        watermark = datetime(2026, 6, 1, tzinfo=UTC)  # two windows: Jun 1 - Jul 1, Jul 1 - now
        responses = [
            _relay_page("getAlerts", [{"uuid": "a-1"}], "cursor-1"),
            _relay_page("getAlerts", [{"uuid": "a-2"}], None),
            _relay_page("getAlerts", [{"uuid": "a-3"}], None),
        ]
        result = _driver().run(
            "alerts",
            [_response(data) for data in responses],
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
        )

        assert result.raised is None
        assert [row["uuid"] for row in result.rows] == ["a-1", "a-2", "a-3"]
        # Mid-window state pins both bounds so the cursor replays against the same filter.
        mid_window = result.saved_states[0]
        assert mid_window.cursor == "cursor-1"
        assert mid_window.window_after == "2026-06-01T00:00:00Z"
        assert mid_window.window_before == "2026-07-01T00:00:00Z"
        # Between windows, only the next lower bound is bookmarked.
        between_windows = result.saved_states[1]
        assert between_windows.cursor is None
        assert between_windows.window_after == "2026-07-01T00:00:00Z"
        # Second window resumed pagination from scratch.
        assert result.requests[2].json()["variables"]["after"] is None

    def test_resumes_mid_window_with_pinned_bounds_and_cursor(self) -> None:
        resume_state = MonteCarloResumeConfig(
            cursor="cursor-7",
            window_after="2026-06-01T00:00:00Z",
            window_before="2026-07-01T00:00:00Z",
        )
        responses = [
            _relay_page("getAlerts", [{"uuid": "a-4"}], None),  # rest of the pinned window
            _relay_page("getAlerts", [{"uuid": "a-5"}], None),  # fresh window to now
        ]
        result = _driver().run(
            "alerts",
            [_response(data) for data in responses],
            resume_state=resume_state,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )

        assert result.raised is None
        assert [row["uuid"] for row in result.rows] == ["a-4", "a-5"]
        assert result.requests[0].json()["variables"]["after"] == "cursor-7"
        assert result.requests[0].json()["variables"]["createdTime"] == {
            "after": "2026-06-01T00:00:00Z",
            "before": "2026-07-01T00:00:00Z",
        }
        # Continuation starts at the pinned upper bound, not the stale watermark.
        assert result.requests[1].json()["variables"]["after"] is None
        assert result.requests[1].json()["variables"]["createdTime"]["after"] == "2026-07-01T00:00:00Z"


class TestSourceResponse:
    @parameterized.expand(
        [
            ("alerts", ["uuid"], "desc"),
            ("domains", ["id"], "asc"),
            ("events", ["uuid"], "desc"),
            ("monitors", ["uuid"], "asc"),
            ("tables", ["id"], "asc"),
            ("users", ["id"], "asc"),
            ("warehouses", ["uuid"], "asc"),
        ]
    )
    def test_primary_keys_and_sort_mode(self, endpoint: str, primary_keys: list[str], sort_mode: str) -> None:
        if endpoint == "alerts":
            with time_machine.travel("2026-07-15T12:00:00Z", tick=False):
                result = _driver().run(endpoint, always(_response(_relay_page("getAlerts", [], None))))
        elif endpoint in ("monitors", "warehouses"):
            data_path = "getMonitors" if endpoint == "monitors" else "getWarehouses"
            result = _driver().run(endpoint, [_response({data_path: []})])
        else:
            data_path = "getTables" if endpoint == "tables" else "getUsersInAccount"
            result = _driver().run(endpoint, [_response(_relay_page(data_path, [], None))])

        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.sort_mode == sort_mode
