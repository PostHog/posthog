from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from freezegun import freeze_time
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.everhour.everhour import (
    EARLIEST_FROM_DATE,
    EVERHOUR_BASE_URL,
    EverhourResumeConfig,
    _build_initial_urls,
    _format_date,
    _parent_project_id,
    _time_records_window,
    _with_query,
    everhour_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.everhour.settings import (
    ENDPOINTS,
    EVERHOUR_ENDPOINTS,
)

EVERHOUR_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.everhour.everhour"


def _make_manager(resume_state: Optional[EverhourResumeConfig] = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _items(start: int, count: int) -> list[dict[str, Any]]:
    return [{"id": i} for i in range(start, start + count)]


class TestWithQuery:
    def test_appends_with_question_mark_when_no_existing_query(self) -> None:
        assert _with_query("/clients", {"limit": 100}) == f"{EVERHOUR_BASE_URL}/clients?limit=100"

    def test_appends_with_ampersand_when_query_present(self) -> None:
        url = _with_query("/time-records?limit=50", {"offset": 50})
        assert url == f"{EVERHOUR_BASE_URL}/time-records?limit=50&offset=50"

    def test_drops_none_values(self) -> None:
        assert _with_query("/clients", {"limit": None}) == f"{EVERHOUR_BASE_URL}/clients"

    def test_accepts_full_url(self) -> None:
        url = _with_query(f"{EVERHOUR_BASE_URL}/projects/5/tasks?limit=100", {"offset": 100})
        assert url == f"{EVERHOUR_BASE_URL}/projects/5/tasks?limit=100&offset=100"


class TestFormatDate:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (date(2026, 3, 4), "2026-03-04"),
            (datetime(2026, 3, 4, 23, 30, tzinfo=UTC), "2026-03-04"),
            (datetime(2026, 3, 4, 12, 0), "2026-03-04"),
            ("2026-03-04", "2026-03-04"),
        ],
    )
    def test_format_date(self, value: Any, expected: str) -> None:
        assert _format_date(value) == expected


class TestTimeRecordsWindow:
    @freeze_time("2026-06-15T12:00:00Z")
    def test_first_sync_spans_all_history(self) -> None:
        window = _time_records_window(should_use_incremental_field=True, db_incremental_field_last_value=None)
        assert window == {"from": EARLIEST_FROM_DATE, "to": "2026-06-15"}

    @freeze_time("2026-06-15T12:00:00Z")
    def test_full_refresh_spans_all_history(self) -> None:
        window = _time_records_window(should_use_incremental_field=False, db_incremental_field_last_value=None)
        assert window == {"from": EARLIEST_FROM_DATE, "to": "2026-06-15"}

    @freeze_time("2026-06-15T12:00:00Z")
    def test_incremental_floors_from_to_watermark_day(self) -> None:
        window = _time_records_window(
            should_use_incremental_field=True, db_incremental_field_last_value=date(2026, 5, 1)
        )
        assert window == {"from": "2026-05-01", "to": "2026-06-15"}


class TestParentProjectId:
    def test_extracts_project_id(self) -> None:
        assert _parent_project_id(f"{EVERHOUR_BASE_URL}/projects/123/tasks?limit=100&offset=0") == "123"

    def test_extracts_prefixed_project_id(self) -> None:
        assert _parent_project_id(f"{EVERHOUR_BASE_URL}/projects/as:99/tasks?limit=100") == "as:99"

    def test_returns_none_for_non_task_url(self) -> None:
        assert _parent_project_id(f"{EVERHOUR_BASE_URL}/clients?limit=100") is None


class TestValidateCredentials:
    @pytest.mark.parametrize("status_code, expected", [(200, True), (401, False), (403, False), (500, False)])
    @mock.patch(f"{EVERHOUR_MODULE}.make_tracked_session")
    def test_status_mapping(self, mock_session: mock.MagicMock, status_code: int, expected: bool) -> None:
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response
        assert validate_credentials("key") is expected

    @mock.patch(f"{EVERHOUR_MODULE}.make_tracked_session")
    def test_uses_users_me_probe(self, mock_session: mock.MagicMock) -> None:
        response = mock.MagicMock(status_code=200)
        mock_session.return_value.get.return_value = response
        validate_credentials("key")
        assert mock_session.return_value.get.call_args.args[0] == f"{EVERHOUR_BASE_URL}/users/me"

    @mock.patch(f"{EVERHOUR_MODULE}.make_tracked_session")
    def test_swallows_exceptions(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("key") is False


class TestBuildInitialUrls:
    def test_top_level_endpoint_yields_single_url(self) -> None:
        urls = _build_initial_urls(EVERHOUR_ENDPOINTS["clients"], None, {}, mock.MagicMock(), mock.MagicMock())
        assert urls == [f"{EVERHOUR_BASE_URL}/clients?limit=100"]

    @freeze_time("2026-06-15T12:00:00Z")
    def test_time_records_bakes_in_date_window(self) -> None:
        window = _time_records_window(should_use_incremental_field=True, db_incremental_field_last_value=None)
        urls = _build_initial_urls(EVERHOUR_ENDPOINTS["time_records"], window, {}, mock.MagicMock(), mock.MagicMock())
        assert len(urls) == 1
        assert "limit=50" in urls[0]
        assert f"from={EARLIEST_FROM_DATE}" in urls[0]
        assert "to=2026-06-15" in urls[0]

    @mock.patch(f"{EVERHOUR_MODULE}._iter_all_items")
    def test_project_fan_out_one_url_per_project(self, mock_iter_items: mock.MagicMock) -> None:
        mock_iter_items.return_value = iter([{"id": "p1"}, {"id": "p2"}])
        urls = _build_initial_urls(EVERHOUR_ENDPOINTS["tasks"], None, {}, mock.MagicMock(), mock.MagicMock())
        assert urls == [
            f"{EVERHOUR_BASE_URL}/projects/p1/tasks?limit=100",
            f"{EVERHOUR_BASE_URL}/projects/p2/tasks?limit=100",
        ]


class TestGetRows:
    @mock.patch(f"{EVERHOUR_MODULE}.make_tracked_session")
    @mock.patch(f"{EVERHOUR_MODULE}._build_initial_urls")
    @mock.patch(f"{EVERHOUR_MODULE}._fetch_page")
    def test_single_page_short_stop(
        self, mock_fetch: mock.MagicMock, mock_build_urls: mock.MagicMock, _mock_session: mock.MagicMock
    ) -> None:
        mock_build_urls.return_value = [f"{EVERHOUR_BASE_URL}/clients?limit=100"]
        mock_fetch.return_value = _items(0, 3)  # < page_size, single page

        manager = _make_manager()
        batches = list(get_rows("key", "clients", mock.MagicMock(), manager))

        assert [item["id"] for batch in batches for item in batch] == [0, 1, 2]
        assert mock_fetch.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(f"{EVERHOUR_MODULE}.make_tracked_session")
    @mock.patch(f"{EVERHOUR_MODULE}._build_initial_urls")
    @mock.patch(f"{EVERHOUR_MODULE}._fetch_page")
    def test_offset_pagination_advances(
        self, mock_fetch: mock.MagicMock, mock_build_urls: mock.MagicMock, _mock_session: mock.MagicMock
    ) -> None:
        mock_build_urls.return_value = [f"{EVERHOUR_BASE_URL}/clients?limit=100"]
        # Full first page (100 rows) -> there may be more; short second page -> stop.
        mock_fetch.side_effect = [_items(0, 100), _items(100, 5)]

        manager = _make_manager()
        batches = list(get_rows("key", "clients", mock.MagicMock(), manager))

        ids = [item["id"] for batch in batches for item in batch]
        assert ids == list(range(105))
        # Second fetch must request offset=100.
        assert "offset=100" in mock_fetch.call_args_list[1].args[0]
        # State saved once after the first (non-terminal) page, pointing at offset 100.
        saved = manager.save_state.call_args.args[0]
        assert saved.current_offset == 100

    @mock.patch(f"{EVERHOUR_MODULE}.make_tracked_session")
    @mock.patch(f"{EVERHOUR_MODULE}._build_initial_urls")
    @mock.patch(f"{EVERHOUR_MODULE}._fetch_page")
    def test_ignored_offset_does_not_loop_forever(
        self, mock_fetch: mock.MagicMock, mock_build_urls: mock.MagicMock, _mock_session: mock.MagicMock
    ) -> None:
        # The API ignores `offset` and returns the same full page every time. The seen-id guard must
        # treat a page with no new ids as terminal rather than looping.
        mock_build_urls.return_value = [f"{EVERHOUR_BASE_URL}/clients?limit=100"]
        mock_fetch.side_effect = [_items(0, 100), _items(0, 100)]

        manager = _make_manager()
        batches = list(get_rows("key", "clients", mock.MagicMock(), manager))

        ids = [item["id"] for batch in batches for item in batch]
        assert ids == list(range(100))  # only the first page's rows, no duplicates
        assert mock_fetch.call_count == 2

    @mock.patch(f"{EVERHOUR_MODULE}.make_tracked_session")
    @mock.patch(f"{EVERHOUR_MODULE}._build_initial_urls")
    @mock.patch(f"{EVERHOUR_MODULE}._fetch_page")
    def test_fan_out_drains_parents_and_injects_project_id(
        self, mock_fetch: mock.MagicMock, mock_build_urls: mock.MagicMock, _mock_session: mock.MagicMock
    ) -> None:
        mock_build_urls.return_value = [
            f"{EVERHOUR_BASE_URL}/projects/p1/tasks?limit=100",
            f"{EVERHOUR_BASE_URL}/projects/p2/tasks?limit=100",
        ]
        mock_fetch.side_effect = [[{"id": "a"}], [{"id": "b"}]]

        manager = _make_manager()
        batches = list(get_rows("key", "tasks", mock.MagicMock(), manager))

        rows = [item for batch in batches for item in batch]
        assert rows == [
            {"id": "a", "project_id": "p1"},
            {"id": "b", "project_id": "p2"},
        ]
        # After draining the first parent, state advances to the second parent URL.
        saved = manager.save_state.call_args.args[0]
        assert saved.current_url == f"{EVERHOUR_BASE_URL}/projects/p2/tasks?limit=100"
        assert saved.remaining_urls == []

    @mock.patch(f"{EVERHOUR_MODULE}.make_tracked_session")
    @mock.patch(f"{EVERHOUR_MODULE}._fetch_page")
    def test_resumes_from_saved_state(self, mock_fetch: mock.MagicMock, _mock_session: mock.MagicMock) -> None:
        mock_fetch.return_value = _items(0, 1)
        resume_url = f"{EVERHOUR_BASE_URL}/clients?limit=100"
        manager = _make_manager(EverhourResumeConfig(remaining_urls=[], current_url=resume_url, current_offset=200))

        list(get_rows("key", "clients", mock.MagicMock(), manager))

        # The first fetch must continue from the saved offset, not start over.
        assert "offset=200" in mock_fetch.call_args_list[0].args[0]

    @mock.patch(f"{EVERHOUR_MODULE}.make_tracked_session")
    @mock.patch(f"{EVERHOUR_MODULE}._build_initial_urls")
    @mock.patch(f"{EVERHOUR_MODULE}._fetch_page")
    def test_empty_endpoint_yields_nothing_and_saves_nothing(
        self, mock_fetch: mock.MagicMock, mock_build_urls: mock.MagicMock, _mock_session: mock.MagicMock
    ) -> None:
        mock_build_urls.return_value = [f"{EVERHOUR_BASE_URL}/clients?limit=100"]
        mock_fetch.return_value = []

        manager = _make_manager()
        batches = list(get_rows("key", "clients", mock.MagicMock(), manager))

        assert batches == []
        manager.save_state.assert_not_called()

    @mock.patch(f"{EVERHOUR_MODULE}.make_tracked_session")
    @mock.patch(f"{EVERHOUR_MODULE}._build_initial_urls")
    def test_no_urls_yields_nothing(self, mock_build_urls: mock.MagicMock, _mock_session: mock.MagicMock) -> None:
        mock_build_urls.return_value = []
        manager = _make_manager()
        assert list(get_rows("key", "clients", mock.MagicMock(), manager)) == []
        manager.save_state.assert_not_called()


class TestEverhourSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        config = EVERHOUR_ENDPOINTS[endpoint]
        response = everhour_source("key", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    def test_time_records_partitions_on_stable_date_field(self) -> None:
        config = EVERHOUR_ENDPOINTS["time_records"]
        assert config.partition_key == "date"

    def test_fan_out_child_key_includes_parent(self) -> None:
        # A task can belong to multiple projects, so the project id must be part of the key to stay
        # unique table-wide.
        assert EVERHOUR_ENDPOINTS["tasks"].primary_keys == ["project_id", "id"]
