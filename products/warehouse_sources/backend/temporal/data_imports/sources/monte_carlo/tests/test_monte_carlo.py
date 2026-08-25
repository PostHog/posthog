from datetime import UTC, datetime
from typing import Any

from freezegun import freeze_time
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.monte_carlo import monte_carlo
from products.warehouse_sources.backend.temporal.data_imports.sources.monte_carlo.monte_carlo import (
    MonteCarloGraphQLError,
    MonteCarloResumeConfig,
    _execute_query,
    get_rows,
    monte_carlo_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.monte_carlo.settings import MONTE_CARLO_ENDPOINTS


class _FakeResumableManager:
    def __init__(self, state: MonteCarloResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[MonteCarloResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> MonteCarloResumeConfig | None:
        return self._state

    def save_state(self, data: MonteCarloResumeConfig) -> None:
        self.saved.append(data)


def _relay_page(data_path: str, nodes: list[dict], end_cursor: str | None) -> dict:
    return {
        data_path: {
            "edges": [{"node": node} for node in nodes],
            "pageInfo": {"endCursor": end_cursor, "hasNextPage": end_cursor is not None},
        }
    }


class _FakeExecutor:
    """Replaces `_execute_query`, serving responses in call order and recording variables."""

    def __init__(self, responses: list[dict]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, session: Any, query: str, variables: dict, logger: Any) -> dict:
        self.calls.append(variables)
        return self._responses.pop(0)


def _collect(
    endpoint: str,
    responses: list[dict],
    manager: _FakeResumableManager | None = None,
    **incremental: Any,
) -> tuple[list[dict], _FakeExecutor, _FakeResumableManager]:
    manager = manager or _FakeResumableManager()
    executor = _FakeExecutor(responses)
    with (
        patch.object(monte_carlo, "_execute_query", executor),
        patch.object(monte_carlo, "make_tracked_session", MagicMock()),
    ):
        rows: list[dict] = []
        for batch in get_rows(
            api_key_id="key-id",
            api_key_secret="key-secret",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
            **incremental,
        ):
            rows.extend(batch)
    return rows, executor, manager


class TestExecuteQuery:
    def _response(self, status_code: int, payload: dict | None = None) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.json.return_value = payload or {}
        return response

    def test_returns_data_object(self) -> None:
        session = MagicMock()
        session.post.return_value = self._response(200, {"data": {"getWarehouses": []}})
        assert _execute_query(session, "query {}", {}, MagicMock()) == {"getWarehouses": []}

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
        response = MagicMock()
        response.status_code = status_code
        response.json.return_value = payload
        session = MagicMock()
        session.post.return_value = response
        with patch.object(monte_carlo, "make_tracked_session", return_value=session):
            assert validate_credentials("key-id", "key-secret") is expected

    def test_network_error_is_invalid(self) -> None:
        session = MagicMock()
        session.post.side_effect = requests.ConnectionError("boom")
        with patch.object(monte_carlo, "make_tracked_session", return_value=session):
            assert validate_credentials("key-id", "key-secret") is False


class TestRelayEndpoints:
    @parameterized.expand([("tables", "getTables"), ("users", "getUsersInAccount")])
    def test_paginates_until_has_next_page_false(self, endpoint: str, data_path: str) -> None:
        responses = [
            _relay_page(data_path, [{"id": "1"}, {"id": "2"}], "cursor-1"),
            _relay_page(data_path, [{"id": "3"}], None),
        ]
        rows, executor, manager = _collect(endpoint, responses)

        assert [row["id"] for row in rows] == ["1", "2", "3"]
        assert executor.calls[0]["after"] is None
        assert executor.calls[1]["after"] == "cursor-1"
        # State saved after the yielded page, only while more pages remain.
        assert [state.cursor for state in manager.saved] == ["cursor-1"]

    def test_resumes_from_saved_cursor(self) -> None:
        responses = [_relay_page("getTables", [{"id": "9"}], None)]
        manager = _FakeResumableManager(MonteCarloResumeConfig(cursor="cursor-42"))
        rows, executor, _ = _collect("tables", responses, manager=manager)

        assert [row["id"] for row in rows] == ["9"]
        assert executor.calls[0]["after"] == "cursor-42"

    def test_empty_first_page_yields_nothing(self) -> None:
        responses = [_relay_page("getTables", [], None)]
        rows, _, manager = _collect("tables", responses)
        assert rows == []
        assert manager.saved == []


class TestOffsetEndpoint:
    def test_paginates_until_short_page(self) -> None:
        page_size = MONTE_CARLO_ENDPOINTS["monitors"].page_size
        full_page = [{"uuid": f"m-{i}"} for i in range(page_size)]
        responses = [{"getMonitors": full_page}, {"getMonitors": [{"uuid": "last"}]}]
        rows, executor, manager = _collect("monitors", responses)

        assert len(rows) == page_size + 1
        assert executor.calls[0]["offset"] == 0
        assert executor.calls[1]["offset"] == page_size
        assert [state.offset for state in manager.saved] == [page_size]

    def test_resumes_from_saved_offset(self) -> None:
        responses = [{"getMonitors": [{"uuid": "m-200"}]}]
        manager = _FakeResumableManager(MonteCarloResumeConfig(offset=200))
        _, executor, _ = _collect("monitors", responses, manager=manager)
        assert executor.calls[0]["offset"] == 200

    def test_empty_first_page_yields_nothing(self) -> None:
        rows, _, _ = _collect("monitors", [{"getMonitors": []}])
        assert rows == []


class TestUnpaginatedEndpoint:
    def test_warehouses_single_query(self) -> None:
        responses = [{"getWarehouses": [{"uuid": "w-1"}, {"uuid": "w-2"}]}]
        rows, executor, manager = _collect("warehouses", responses)
        assert [row["uuid"] for row in rows] == ["w-1", "w-2"]
        assert len(executor.calls) == 1
        assert manager.saved == []


@freeze_time("2026-07-15T12:00:00Z")
class TestAlertsWindowing:
    def test_first_sync_walks_year_of_30_day_windows(self) -> None:
        empty = _relay_page("getAlerts", [], None)
        responses = [empty] * 13  # 365 days / 30-day windows
        rows, executor, _ = _collect(
            "alerts", responses, should_use_incremental_field=True, db_incremental_field_last_value=None
        )

        assert rows == []
        assert len(executor.calls) == 13
        first_window = executor.calls[0]["createdTime"]
        assert first_window["after"] == "2025-07-15T12:00:00Z"
        assert first_window["before"] == "2025-08-14T12:00:00Z"
        last_window = executor.calls[-1]["createdTime"]
        assert last_window["before"] == "2026-07-15T12:00:00Z"

    def test_incremental_sync_windows_forward_from_watermark(self) -> None:
        watermark = datetime(2026, 7, 1, tzinfo=UTC)
        responses = [_relay_page("getAlerts", [{"uuid": "a-1", "createdTime": "2026-07-02T00:00:00Z"}], None)]
        rows, executor, _ = _collect(
            "alerts", responses, should_use_incremental_field=True, db_incremental_field_last_value=watermark
        )

        assert [row["uuid"] for row in rows] == ["a-1"]
        assert executor.calls[0]["createdTime"] == {
            "after": "2026-07-01T00:00:00Z",
            "before": "2026-07-15T12:00:00Z",
        }

    def test_updated_time_incremental_field_filters_updated_time(self) -> None:
        watermark = datetime(2026, 7, 10, tzinfo=UTC)
        responses = [_relay_page("getAlerts", [], None)]
        _, executor, _ = _collect(
            "alerts",
            responses,
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
            incremental_field="updatedTime",
        )
        assert "updatedTime" in executor.calls[0]
        assert "createdTime" not in executor.calls[0]

    def test_future_watermark_falls_back_to_lookback(self) -> None:
        # A future-dated watermark would produce an empty/invalid window; fall back to the
        # default lookback so the sync self-heals.
        watermark = datetime(2027, 1, 1, tzinfo=UTC)
        responses = [_relay_page("getAlerts", [], None)] * 13
        _, executor, _ = _collect(
            "alerts", responses, should_use_incremental_field=True, db_incremental_field_last_value=watermark
        )
        assert executor.calls[0]["createdTime"]["after"] == "2025-07-15T12:00:00Z"

    def test_saves_cursor_state_mid_window_and_bookmark_between_windows(self) -> None:
        watermark = datetime(2026, 6, 1, tzinfo=UTC)  # two windows: Jun 1 - Jul 1, Jul 1 - now
        responses = [
            _relay_page("getAlerts", [{"uuid": "a-1"}], "cursor-1"),
            _relay_page("getAlerts", [{"uuid": "a-2"}], None),
            _relay_page("getAlerts", [{"uuid": "a-3"}], None),
        ]
        rows, executor, manager = _collect(
            "alerts", responses, should_use_incremental_field=True, db_incremental_field_last_value=watermark
        )

        assert [row["uuid"] for row in rows] == ["a-1", "a-2", "a-3"]
        # Mid-window state pins both bounds so the cursor replays against the same filter.
        mid_window = manager.saved[0]
        assert mid_window.cursor == "cursor-1"
        assert mid_window.window_after == "2026-06-01T00:00:00Z"
        assert mid_window.window_before == "2026-07-01T00:00:00Z"
        # Between windows, only the next lower bound is bookmarked.
        between_windows = manager.saved[1]
        assert between_windows.cursor is None
        assert between_windows.window_after == "2026-07-01T00:00:00Z"
        # Second window resumed pagination from scratch.
        assert executor.calls[2]["after"] is None

    def test_resumes_mid_window_with_pinned_bounds_and_cursor(self) -> None:
        manager = _FakeResumableManager(
            MonteCarloResumeConfig(
                cursor="cursor-7",
                window_after="2026-06-01T00:00:00Z",
                window_before="2026-07-01T00:00:00Z",
            )
        )
        responses = [
            _relay_page("getAlerts", [{"uuid": "a-4"}], None),  # rest of the pinned window
            _relay_page("getAlerts", [{"uuid": "a-5"}], None),  # fresh window to now
        ]
        rows, executor, _ = _collect(
            "alerts",
            responses,
            manager=manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )

        assert [row["uuid"] for row in rows] == ["a-4", "a-5"]
        assert executor.calls[0]["after"] == "cursor-7"
        assert executor.calls[0]["createdTime"] == {
            "after": "2026-06-01T00:00:00Z",
            "before": "2026-07-01T00:00:00Z",
        }
        # Continuation starts at the pinned upper bound, not the stale watermark.
        assert executor.calls[1]["after"] is None
        assert executor.calls[1]["createdTime"]["after"] == "2026-07-01T00:00:00Z"

    def test_resumes_between_windows_without_cursor(self) -> None:
        manager = _FakeResumableManager(MonteCarloResumeConfig(window_after="2026-07-01T00:00:00Z"))
        responses = [_relay_page("getAlerts", [], None)]
        _, executor, _ = _collect(
            "alerts",
            responses,
            manager=manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )
        assert executor.calls[0]["after"] is None
        assert executor.calls[0]["createdTime"]["after"] == "2026-07-01T00:00:00Z"

    def test_full_refresh_ignores_watermark_and_uses_lookback(self) -> None:
        responses = [_relay_page("getAlerts", [], None)] * 13
        _, executor, _ = _collect(
            "alerts",
            responses,
            should_use_incremental_field=False,
            db_incremental_field_last_value=datetime(2026, 7, 14, tzinfo=UTC),
        )
        assert executor.calls[0]["createdTime"]["after"] == "2025-07-15T12:00:00Z"


class TestSourceResponse:
    @parameterized.expand(
        [
            ("alerts", ["uuid"], "desc"),
            ("monitors", ["uuid"], "asc"),
            ("tables", ["id"], "asc"),
            ("users", ["id"], "asc"),
            ("warehouses", ["uuid"], "asc"),
        ]
    )
    def test_primary_keys_and_sort_mode(self, endpoint: str, primary_keys: list[str], sort_mode: str) -> None:
        response = monte_carlo_source(
            api_key_id="key-id",
            api_key_secret="key-secret",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
        )
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.sort_mode == sort_mode

    def test_only_alerts_is_partitioned_on_stable_created_time(self) -> None:
        alerts = monte_carlo_source(
            api_key_id="key-id",
            api_key_secret="key-secret",
            endpoint="alerts",
            logger=MagicMock(),
            resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
        )
        assert alerts.partition_mode == "datetime"
        assert alerts.partition_keys == ["createdTime"]

        monitors = monte_carlo_source(
            api_key_id="key-id",
            api_key_secret="key-secret",
            endpoint="monitors",
            logger=MagicMock(),
            resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
        )
        assert monitors.partition_mode is None
        assert monitors.partition_keys is None
