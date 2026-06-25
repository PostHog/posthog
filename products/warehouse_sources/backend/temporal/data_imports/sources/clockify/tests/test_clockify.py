from datetime import UTC, date, datetime
from typing import Any

import pytest
from freezegun import freeze_time
from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.sources.clockify import clockify
from products.warehouse_sources.backend.temporal.data_imports.sources.clockify.clockify import (
    CLOCKIFY_BASE_URL,
    ClockifyResumeConfig,
    _build_url,
    _clamp_future_value_to_now,
    _flatten_time_entry,
    _format_datetime_z,
    _get_item_mapper,
    clockify_source,
    get_rows,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clockify.settings import (
    CLOCKIFY_ENDPOINTS,
    ClockifyEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager


class TestFormatDatetimeZ:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("string_passthrough", "2026-03-04T02:58:14Z", "2026-03-04T02:58:14Z"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        assert _format_datetime_z(value) == expected

    def test_no_plus_zero_offset(self) -> None:
        assert "+00:00" not in _format_datetime_z(datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC))


class TestClampFutureValueToNow:
    @parameterized.expand(
        [
            # Future cursor caps at now; anything at/before now (and non-ISO strings) passes through.
            ("future_datetime", datetime(2027, 2, 5, tzinfo=UTC), datetime(2026, 6, 15, 12, tzinfo=UTC)),
            ("past_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC)),
            ("non_iso_string_passthrough", "cursor", "cursor"),
            ("future_iso_string", "2030-01-01T00:00:00Z", datetime(2026, 6, 15, 12, tzinfo=UTC)),
            ("past_iso_string", "2026-03-04T02:58:14Z", "2026-03-04T02:58:14Z"),
        ]
    )
    @freeze_time("2026-06-15T12:00:00Z")
    def test_clamp(self, _name: str, value: Any, expected: Any) -> None:
        assert _clamp_future_value_to_now(value) == expected


class TestBuildUrl:
    @parameterized.expand(
        [
            ("no_params", f"{CLOCKIFY_BASE_URL}/workspaces", {}, f"{CLOCKIFY_BASE_URL}/workspaces"),
            ("with_params", "http://x/y", {"page": 1, "page-size": 1000}, "http://x/y?page=1&page-size=1000"),
        ]
    )
    def test_build_url(self, _name: str, base: str, params: dict, expected: str) -> None:
        assert _build_url(base, params) == expected


class TestFlattenTimeEntry:
    def test_flattens_time_interval(self) -> None:
        row = _flatten_time_entry(
            {
                "id": "T1",
                "timeInterval": {"start": "2026-03-04T00:00:00Z", "end": "2026-03-04T01:00:00Z", "duration": "PT1H"},
            }
        )
        assert row["time_interval_start"] == "2026-03-04T00:00:00Z"
        assert row["time_interval_end"] == "2026-03-04T01:00:00Z"
        assert row["time_interval_duration"] == "PT1H"

    def test_missing_time_interval_is_noop(self) -> None:
        row = _flatten_time_entry({"id": "T1"})
        assert "time_interval_start" not in row

    @parameterized.expand([("time_entries", True), ("clients", False), ("workspaces", False)])
    def test_get_item_mapper(self, endpoint: str, has_mapper: bool) -> None:
        assert (_get_item_mapper(endpoint) is not None) == has_mapper


class _FakeManager(ResumableSourceManager[ClockifyResumeConfig]):
    """In-memory stand-in: overrides __init__ to skip Redis wiring, records saved state."""

    def __init__(self, state: ClockifyResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[ClockifyResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> ClockifyResumeConfig | None:
        return self._state

    def save_state(self, data: ClockifyResumeConfig) -> None:
        self.saved.append(data)


class _FakeFetcher:
    """Stand-in for `_fetch_page` keyed by exact request URL; records every URL fetched."""

    def __init__(self, pages: dict[str, list[dict]]) -> None:
        self.pages = pages
        self.urls: list[str] = []

    def __call__(self, session: Any, url: str, headers: dict, logger: Any) -> list[dict]:
        self.urls.append(url)
        if url not in self.pages:
            raise AssertionError(f"Unexpected URL fetched: {url}")
        return self.pages[url]


def _collect(
    manager: _FakeManager, monkeypatch: Any, fetcher: _FakeFetcher, endpoint: str, **kwargs: Any
) -> list[dict]:
    monkeypatch.setattr(clockify, "_fetch_page", fetcher)
    rows: list[dict] = []
    for table in get_rows(
        api_key="key", endpoint=endpoint, logger=MagicMock(), resumable_source_manager=manager, **kwargs
    ):
        rows.extend(table.to_pylist())
    return rows


class TestWorkspacesEndpoint:
    def test_top_level_pagination_and_no_fan_out(self, monkeypatch: Any) -> None:
        fetcher = _FakeFetcher(
            {f"{CLOCKIFY_BASE_URL}/workspaces?page=1&page-size=1000": [{"id": "W1", "name": "A"}, {"id": "W2"}]}
        )
        rows = _collect(_FakeManager(), monkeypatch, fetcher, "workspaces")
        assert [r["id"] for r in rows] == ["W1", "W2"]
        # Workspaces is its own endpoint — it must NOT also enumerate workspaces for a fan-out.
        assert fetcher.urls == [f"{CLOCKIFY_BASE_URL}/workspaces?page=1&page-size=1000"]


class TestSingleLevelFanOut:
    def _pages(self) -> dict[str, list[dict]]:
        return {
            f"{CLOCKIFY_BASE_URL}/workspaces": [{"id": "W1"}, {"id": "W2"}],
            f"{CLOCKIFY_BASE_URL}/workspaces/W1/clients?page=1&page-size=1000": [{"id": "C1", "name": "Acme"}],
            f"{CLOCKIFY_BASE_URL}/workspaces/W2/clients?page=1&page-size=1000": [{"id": "C2"}],
        }

    def test_fans_out_over_workspaces_and_injects_workspace_id(self, monkeypatch: Any) -> None:
        rows = _collect(_FakeManager(), monkeypatch, _FakeFetcher(self._pages()), "clients")
        assert [(r["id"], r["workspace_id"]) for r in rows] == [("C1", "W1"), ("C2", "W2")]

    def test_resume_skips_to_saved_workspace(self, monkeypatch: Any) -> None:
        manager = _FakeManager(ClockifyResumeConfig(workspace_id="W2", parent_id=None, page=1))
        rows = _collect(manager, monkeypatch, _FakeFetcher(self._pages()), "clients")
        # W1 is skipped; only W2's clients are pulled.
        assert [r["id"] for r in rows] == ["C2"]

    def test_resume_from_missing_workspace_restarts_from_beginning(self, monkeypatch: Any) -> None:
        manager = _FakeManager(ClockifyResumeConfig(workspace_id="GONE", parent_id=None, page=1))
        rows = _collect(manager, monkeypatch, _FakeFetcher(self._pages()), "clients")
        assert [r["id"] for r in rows] == ["C1", "C2"]


class TestTwoLevelFanOutTasks:
    def test_fans_out_workspace_then_project_and_injects_both_ids(self, monkeypatch: Any) -> None:
        pages = {
            f"{CLOCKIFY_BASE_URL}/workspaces": [{"id": "W1"}],
            f"{CLOCKIFY_BASE_URL}/workspaces/W1/projects?page=1&page-size=1000": [{"id": "P1"}, {"id": "P2"}],
            f"{CLOCKIFY_BASE_URL}/workspaces/W1/projects/P1/tasks?page=1&page-size=1000": [{"id": "TK1"}],
            f"{CLOCKIFY_BASE_URL}/workspaces/W1/projects/P2/tasks?page=1&page-size=1000": [{"id": "TK2"}],
        }
        rows = _collect(_FakeManager(), monkeypatch, _FakeFetcher(pages), "tasks")
        assert rows == [
            {"id": "TK1", "workspace_id": "W1", "project_id": "P1"},
            {"id": "TK2", "workspace_id": "W1", "project_id": "P2"},
        ]


class TestTwoLevelFanOutTimeEntries:
    def _pages(self) -> dict[str, list[dict]]:
        return {
            f"{CLOCKIFY_BASE_URL}/workspaces": [{"id": "W1"}],
            f"{CLOCKIFY_BASE_URL}/workspaces/W1/users?page=1&page-size=1000": [{"id": "U1"}],
        }

    def test_flattens_interval_and_injects_workspace_and_user(self, monkeypatch: Any) -> None:
        pages = self._pages()
        pages[f"{CLOCKIFY_BASE_URL}/workspaces/W1/user/U1/time-entries?page=1&page-size=1000"] = [
            {"id": "TE1", "timeInterval": {"start": "2026-03-04T00:00:00Z", "end": None, "duration": None}}
        ]
        rows = _collect(_FakeManager(), monkeypatch, _FakeFetcher(pages), "time_entries")
        assert rows[0]["workspace_id"] == "W1"
        assert rows[0]["user_id"] == "U1"
        assert rows[0]["time_interval_start"] == "2026-03-04T00:00:00Z"

    def test_incremental_passes_start_filter(self, monkeypatch: Any) -> None:
        pages = self._pages()
        # The exact URL carries the urlencoded `start`; match it by recording fetched URLs instead.
        fetcher = _FakeFetcher(pages)

        def fetch(session: Any, url: str, headers: dict, logger: Any) -> list[dict]:
            fetcher.urls.append(url)
            if "time-entries" in url:
                return []
            return pages[url]

        monkeypatch.setattr(clockify, "_fetch_page", fetch)
        list(
            get_rows(
                api_key="key",
                endpoint="time_entries",
                logger=MagicMock(),
                resumable_source_manager=_FakeManager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
                incremental_field="time_interval_start",
            )
        )
        time_entry_urls = [u for u in fetcher.urls if "time-entries" in u]
        assert time_entry_urls and "start=2026-03-04T02%3A58%3A14Z" in time_entry_urls[0]


class TestPaginateScope:
    def test_short_page_terminates_pagination(self, monkeypatch: Any) -> None:
        config = ClockifyEndpointConfig(name="t", path="/p", primary_keys=["id"], page_size=2)
        # First page returns a full page (2) -> fetch page 2; second returns 1 (< page_size) -> stop.
        pages = {
            "http://x/p?page=1&page-size=2": [{"id": "a"}, {"id": "b"}],
            "http://x/p?page=2&page-size=2": [{"id": "c"}],
        }
        fetcher = _FakeFetcher(pages)
        monkeypatch.setattr(clockify, "_fetch_page", fetcher)
        batcher = Batcher(logger=MagicMock(), chunk_size=1)
        manager = _FakeManager()
        rows: list[dict] = []
        for table in clockify._paginate_scope(
            MagicMock(),
            {},
            "http://x/p",
            config,
            batcher,
            manager,
            MagicMock(),
            None,
            "W1",
            None,
            1,
            {"workspace_id": "W1"},
            {},
        ):
            rows.extend(table.to_pylist())
        if batcher.should_yield(include_incomplete_chunk=True):
            rows.extend(batcher.get_table().to_pylist())
        assert [r["id"] for r in rows] == ["a", "b", "c"]
        assert fetcher.urls == ["http://x/p?page=1&page-size=2", "http://x/p?page=2&page-size=2"]

    def test_saves_state_after_each_yielded_batch(self, monkeypatch: Any) -> None:
        config = ClockifyEndpointConfig(name="t", path="/p", primary_keys=["id"], page_size=10)
        pages = {"http://x/p?page=1&page-size=10": [{"id": "a"}, {"id": "b"}]}
        monkeypatch.setattr(clockify, "_fetch_page", _FakeFetcher(pages))
        batcher = Batcher(logger=MagicMock(), chunk_size=1)  # every row is a full chunk -> yields + saves
        manager = _FakeManager()
        list(
            clockify._paginate_scope(
                MagicMock(), {}, "http://x/p", config, batcher, manager, MagicMock(), None, "W1", "P1", 1, {}, {}
            )
        )
        # State is saved after each yield, pointing at the page being read so a crash re-reads it.
        assert manager.saved == [
            ClockifyResumeConfig(workspace_id="W1", parent_id="P1", page=1),
            ClockifyResumeConfig(workspace_id="W1", parent_id="P1", page=1),
        ]


class TestClockifySourceResponse:
    @parameterized.expand([(name,) for name in CLOCKIFY_ENDPOINTS])
    def test_primary_keys_and_sort_mode_match_config(self, endpoint: str) -> None:
        response = clockify_source(
            api_key="key", endpoint=endpoint, logger=MagicMock(), resumable_source_manager=_FakeManager()
        )
        config = CLOCKIFY_ENDPOINTS[endpoint]
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == config.sort_mode

    def test_time_entries_is_desc_and_partitioned(self) -> None:
        response = clockify_source(
            api_key="key", endpoint="time_entries", logger=MagicMock(), resumable_source_manager=_FakeManager()
        )
        assert response.sort_mode == "desc"
        assert response.partition_keys == ["time_interval_start"]
        assert response.partition_mode == "datetime"

    def test_full_refresh_endpoint_has_no_partition(self) -> None:
        response = clockify_source(
            api_key="key", endpoint="clients", logger=MagicMock(), resumable_source_manager=_FakeManager()
        )
        assert response.partition_keys is None
        assert response.partition_mode is None


class TestValidateCredentials:
    @pytest.mark.parametrize("status,expected", [(200, True), (401, False), (403, False)])
    def test_status_maps_to_validity(self, status: int, expected: bool, monkeypatch: Any) -> None:
        response = MagicMock()
        response.status_code = status
        session = MagicMock()
        session.get.return_value = response
        monkeypatch.setattr(clockify, "make_tracked_session", lambda *a, **k: session)
        assert clockify.validate_credentials("key") is expected

    def test_network_error_is_invalid(self, monkeypatch: Any) -> None:
        session = MagicMock()
        session.get.side_effect = Exception("boom")
        monkeypatch.setattr(clockify, "make_tracked_session", lambda *a, **k: session)
        assert clockify.validate_credentials("key") is False
