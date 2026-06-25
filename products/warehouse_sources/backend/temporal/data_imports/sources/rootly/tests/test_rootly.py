from datetime import UTC, date, datetime
from typing import Any

from freezegun import freeze_time
from unittest import mock
from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.rootly import rootly
from products.warehouse_sources.backend.temporal.data_imports.sources.rootly.rootly import (
    RootlyResumeConfig,
    _build_initial_params,
    _build_url,
    _clamp_future_value_to_now,
    _flatten_item,
    _format_incremental_value,
    get_rows,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rootly.settings import ROOTLY_ENDPOINTS


class TestBuildUrl:
    def test_no_params_returns_base(self) -> None:
        assert _build_url("https://api.rootly.com/v1/users", {}) == "https://api.rootly.com/v1/users"

    def test_bracket_params_are_percent_encoded(self) -> None:
        # Rootly is Rails/JSON:API and parses percent-encoded brackets; urlencode keeps them safe.
        url = _build_url("https://api.rootly.com/v1/incidents", {"page[size]": 100})
        assert url == "https://api.rootly.com/v1/incidents?page%5Bsize%5D=100"


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14+00:00"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14+00:00"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00+00:00"),
            ("string_passthrough", "cursor-token", "cursor-token"),
        ]
    )
    def test_format_incremental_value(self, _name: str, value: object, expected: str) -> None:
        assert _format_incremental_value(value) == expected


class TestClampFutureValueToNow:
    @freeze_time("2026-06-15T12:00:00Z")
    def test_future_datetime_is_clamped(self) -> None:
        assert _clamp_future_value_to_now(datetime(2027, 2, 5, tzinfo=UTC)) == datetime(2026, 6, 15, 12, 0, tzinfo=UTC)

    @freeze_time("2026-06-15T12:00:00Z")
    def test_past_datetime_is_unchanged(self) -> None:
        value = datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC)
        assert _clamp_future_value_to_now(value) == value

    def test_string_passthrough(self) -> None:
        assert _clamp_future_value_to_now("cursor-token") == "cursor-token"


class TestFlattenItem:
    def test_attributes_hoisted_to_root_and_id_type_kept(self) -> None:
        item = {
            "id": "123",
            "type": "incidents",
            "attributes": {"title": "DB down", "status": "started", "created_at": "2026-01-01T00:00:00Z"},
        }
        assert _flatten_item(item) == {
            "id": "123",
            "type": "incidents",
            "title": "DB down",
            "status": "started",
            "created_at": "2026-01-01T00:00:00Z",
        }

    def test_missing_attributes_is_safe(self) -> None:
        assert _flatten_item({"id": "123", "type": "incidents"}) == {"id": "123", "type": "incidents"}


class TestBuildInitialParams:
    def test_incremental_endpoint_sorts_and_filters_on_cursor_field(self) -> None:
        params = _build_initial_params(
            ROOTLY_ENDPOINTS["incidents"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            incremental_field="updated_at",
        )
        # Sort and filter must reference the same field so rows arrive in watermark order.
        assert params["sort"] == "updated_at"
        assert params["filter[updated_at][gt]"] == "2026-03-04T02:58:14+00:00"

    def test_incremental_first_sync_sorts_without_filter(self) -> None:
        params = _build_initial_params(
            ROOTLY_ENDPOINTS["incidents"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
            incremental_field="updated_at",
        )
        assert params["sort"] == "updated_at"
        assert not any(key.startswith("filter[") for key in params)

    @freeze_time("2026-06-15T12:00:00Z")
    def test_future_cursor_is_clamped(self) -> None:
        params = _build_initial_params(
            ROOTLY_ENDPOINTS["incidents"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2027, 2, 5, tzinfo=UTC),
            incremental_field="updated_at",
        )
        assert params["filter[updated_at][gt]"] == "2026-06-15T12:00:00+00:00"

    def test_full_refresh_endpoint_has_no_sort_or_filter(self) -> None:
        params = _build_initial_params(
            ROOTLY_ENDPOINTS["users"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
            incremental_field="updated_at",
        )
        assert "sort" not in params
        assert not any(key.startswith("filter[") for key in params)
        assert params["page[size]"] == 100


class _FakeResumableManager:
    def __init__(self, state: RootlyResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[RootlyResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> RootlyResumeConfig | None:
        return self._state

    def save_state(self, data: RootlyResumeConfig) -> None:
        self.saved.append(data)


class TestGetRows:
    @staticmethod
    def _collect(manager: _FakeResumableManager, monkeypatch: Any, pages: dict[str, Any], **kwargs: Any) -> list[dict]:
        def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
            return pages[url]

        monkeypatch.setattr(rootly, "_fetch_page", fake_fetch)

        rows: list[dict] = []
        for page in get_rows(
            api_key="rootly_test",
            endpoint="incidents",
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
            **kwargs,
        ):
            rows.extend(page)
        return rows

    def test_follows_links_next_and_flattens(self, monkeypatch: Any) -> None:
        first = "https://api.rootly.com/v1/incidents?page%5Bsize%5D=100"
        second = "https://api.rootly.com/v1/incidents?page%5Bnumber%5D=2"
        pages = {
            first: {
                "data": [{"id": "1", "type": "incidents", "attributes": {"title": "A"}}],
                "links": {"next": second},
            },
            second: {
                "data": [{"id": "2", "type": "incidents", "attributes": {"title": "B"}}],
                "links": {"next": None},
            },
        }
        rows = self._collect(_FakeResumableManager(), monkeypatch, pages)
        assert rows == [
            {"id": "1", "type": "incidents", "title": "A"},
            {"id": "2", "type": "incidents", "title": "B"},
        ]

    def test_saves_state_after_each_page_except_the_last(self, monkeypatch: Any) -> None:
        first = "https://api.rootly.com/v1/incidents?page%5Bsize%5D=100"
        second = "https://api.rootly.com/v1/incidents?page%5Bnumber%5D=2"
        pages = {
            first: {"data": [{"id": "1", "attributes": {}}], "links": {"next": second}},
            second: {"data": [{"id": "2", "attributes": {}}], "links": {"next": None}},
        }
        manager = _FakeResumableManager()
        self._collect(manager, monkeypatch, pages)
        # State saved once (pointing at the second page) so a crash re-yields that page; nothing
        # is saved after the final page (no next link).
        assert [s.next_url for s in manager.saved] == [second]

    def test_resumes_from_saved_next_url(self, monkeypatch: Any) -> None:
        resume_url = "https://api.rootly.com/v1/incidents?page%5Bnumber%5D=3"
        pages = {resume_url: {"data": [{"id": "9", "attributes": {"title": "Z"}}], "links": {"next": None}}}
        manager = _FakeResumableManager(RootlyResumeConfig(next_url=resume_url))
        rows = self._collect(manager, monkeypatch, pages)
        # Starts at the resumed URL, not the freshly-built first page.
        assert rows == [{"id": "9", "title": "Z"}]

    def test_empty_collection_yields_nothing(self, monkeypatch: Any) -> None:
        first = "https://api.rootly.com/v1/incidents?page%5Bsize%5D=100"
        pages = {first: {"data": [], "links": {"next": None}}}
        rows = self._collect(_FakeResumableManager(), monkeypatch, pages)
        assert rows == []


class TestProbeCredentials:
    @parameterized.expand([("ok", 200), ("unauthorized", 401), ("forbidden", 403)])
    def test_returns_status_code(self, _name: str, status_code: int) -> None:
        session = MagicMock()
        session.get.return_value = MagicMock(status_code=status_code)
        with mock.patch.object(rootly, "make_tracked_session", return_value=session):
            assert rootly.probe_credentials("rootly_test", "incidents") == status_code

    def test_connection_failure_returns_none(self) -> None:
        session = MagicMock()
        session.get.side_effect = Exception("boom")
        with mock.patch.object(rootly, "make_tracked_session", return_value=session):
            assert rootly.probe_credentials("rootly_test") is None
