from datetime import UTC, date, datetime
from typing import Any

from freezegun import freeze_time
from unittest import mock
from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.better_stack import better_stack
from products.warehouse_sources.backend.temporal.data_imports.sources.better_stack.better_stack import (
    BetterStackResumeConfig,
    BetterStackUntrustedURLError,
    _build_initial_params,
    _fetch_page_once,
    _flatten_item,
    _format_from_date,
    _validate_pagination_url,
    get_rows,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.better_stack.settings import (
    BETTER_STACK_ENDPOINTS,
)


class TestFormatFromDate:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04"),
            ("date_value", date(2026, 3, 4), "2026-03-04"),
            ("string_passthrough", "2026-03-04", "2026-03-04"),
        ]
    )
    def test_formats_as_date_only(self, _name: str, value: object, expected: str) -> None:
        # Better Stack's `from` filter takes YYYY-MM-DD, not a full timestamp.
        assert _format_from_date(value) == expected


class TestBuildInitialParams:
    def test_incremental_endpoint_filters_from_watermark_date(self) -> None:
        params = _build_initial_params(
            BETTER_STACK_ENDPOINTS["incidents"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )
        assert params == {"per_page": 50, "from": "2026-03-04"}

    def test_incremental_first_sync_has_no_filter(self) -> None:
        params = _build_initial_params(
            BETTER_STACK_ENDPOINTS["incidents"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
        )
        assert params == {"per_page": 50}

    @freeze_time("2026-06-15T12:00:00Z")
    def test_future_cursor_is_clamped(self) -> None:
        params = _build_initial_params(
            BETTER_STACK_ENDPOINTS["incidents"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2027, 2, 5, tzinfo=UTC),
        )
        assert params["from"] == "2026-06-15"

    def test_full_refresh_endpoint_never_filters(self) -> None:
        params = _build_initial_params(
            BETTER_STACK_ENDPOINTS["monitors"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )
        assert params == {"per_page": 250}


class TestFlattenItem:
    def test_attributes_hoisted_to_root_and_id_type_kept(self) -> None:
        item = {
            "id": "123",
            "type": "incident",
            "attributes": {"name": "API", "cause": "Status 500", "started_at": "2026-01-01T00:00:00Z"},
        }
        assert _flatten_item(item) == {
            "id": "123",
            "type": "incident",
            "name": "API",
            "cause": "Status 500",
            "started_at": "2026-01-01T00:00:00Z",
        }

    def test_missing_attributes_is_safe(self) -> None:
        assert _flatten_item({"id": "123", "type": "incident"}) == {"id": "123", "type": "incident"}


class TestFetchPage:
    def test_429_honors_retry_after_and_raises_retryable(self) -> None:
        response = MagicMock(status_code=429, headers={"Retry-After": "7"})
        session = MagicMock()
        session.get.return_value = response
        with mock.patch.object(better_stack.time, "sleep") as sleep:
            try:
                # Call the undecorated function so tenacity doesn't retry 5 times in the test.
                _fetch_page_once(session, "https://uptime.betterstack.com/api/v2/monitors", {}, MagicMock())
                raise AssertionError("expected BetterStackRetryableError")
            except better_stack.BetterStackRetryableError:
                pass
        sleep.assert_called_once_with(7)

    def test_429_retry_after_is_capped(self) -> None:
        response = MagicMock(status_code=429, headers={"Retry-After": "3600"})
        session = MagicMock()
        session.get.return_value = response
        with mock.patch.object(better_stack.time, "sleep") as sleep:
            try:
                _fetch_page_once(session, "https://uptime.betterstack.com/api/v2/monitors", {}, MagicMock())
                raise AssertionError("expected BetterStackRetryableError")
            except better_stack.BetterStackRetryableError:
                pass
        sleep.assert_called_once_with(better_stack.MAX_RETRY_AFTER_SECONDS)


class TestValidatePaginationUrl:
    def test_api_origin_url_is_returned_unchanged(self) -> None:
        url = "https://uptime.betterstack.com/api/v3/incidents?page=2&per_page=50"
        assert _validate_pagination_url(url) == url

    @parameterized.expand(
        [
            ("other_host", "https://evil.example.com/api/v3/incidents"),
            ("http_downgrade", "http://uptime.betterstack.com/api/v3/incidents"),
            ("userinfo_confusion", "https://uptime.betterstack.com@evil.example.com/api/v3/incidents"),
            ("wrong_path", "https://uptime.betterstack.com/steal-token"),
        ]
    )
    def test_off_origin_urls_are_refused(self, _name: str, url: str) -> None:
        # A poisoned resume state or hostile response must not retarget the bearer-token request.
        try:
            _validate_pagination_url(url)
            raise AssertionError("expected BetterStackUntrustedURLError")
        except BetterStackUntrustedURLError:
            pass


class _FakeResumableManager:
    def __init__(self, state: BetterStackResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[BetterStackResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> BetterStackResumeConfig | None:
        return self._state

    def save_state(self, data: BetterStackResumeConfig) -> None:
        self.saved.append(data)


class TestGetRows:
    @staticmethod
    def _collect(manager: _FakeResumableManager, monkeypatch: Any, pages: dict[str, Any], **kwargs: Any) -> list[dict]:
        def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
            return pages[url]

        monkeypatch.setattr(better_stack, "_fetch_page", fake_fetch)

        rows: list[dict] = []
        for page in get_rows(
            api_token="bs_test",
            endpoint="incidents",
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
            **kwargs,
        ):
            rows.extend(page)
        return rows

    def test_follows_pagination_next_and_flattens(self, monkeypatch: Any) -> None:
        first = "https://uptime.betterstack.com/api/v3/incidents?per_page=50"
        second = "https://uptime.betterstack.com/api/v3/incidents?page=2&per_page=50"
        pages = {
            first: {
                "data": [{"id": "1", "type": "incident", "attributes": {"cause": "Timeout"}}],
                "pagination": {"next": second},
            },
            second: {
                "data": [{"id": "2", "type": "incident", "attributes": {"cause": "Status 500"}}],
                "pagination": {"next": None},
            },
        }
        rows = self._collect(_FakeResumableManager(), monkeypatch, pages)
        assert rows == [
            {"id": "1", "type": "incident", "cause": "Timeout"},
            {"id": "2", "type": "incident", "cause": "Status 500"},
        ]

    def test_saves_state_after_each_page_except_the_last(self, monkeypatch: Any) -> None:
        first = "https://uptime.betterstack.com/api/v3/incidents?per_page=50"
        second = "https://uptime.betterstack.com/api/v3/incidents?page=2&per_page=50"
        pages = {
            first: {"data": [{"id": "1", "attributes": {}}], "pagination": {"next": second}},
            second: {"data": [{"id": "2", "attributes": {}}], "pagination": {"next": None}},
        }
        manager = _FakeResumableManager()
        self._collect(manager, monkeypatch, pages)
        # State saved once (pointing at the second page) so a crash re-yields that page; nothing
        # is saved after the final page (no next link).
        assert [s.next_url for s in manager.saved] == [second]

    def test_resumes_from_saved_next_url(self, monkeypatch: Any) -> None:
        resume_url = "https://uptime.betterstack.com/api/v3/incidents?page=3&per_page=50"
        pages = {resume_url: {"data": [{"id": "9", "attributes": {"cause": "Z"}}], "pagination": {"next": None}}}
        manager = _FakeResumableManager(BetterStackResumeConfig(next_url=resume_url))
        rows = self._collect(manager, monkeypatch, pages)
        # Starts at the resumed URL, not the freshly-built first page.
        assert rows == [{"id": "9", "cause": "Z"}]

    def test_empty_collection_yields_nothing(self, monkeypatch: Any) -> None:
        first = "https://uptime.betterstack.com/api/v3/incidents?per_page=50"
        pages = {first: {"data": [], "pagination": {"next": None}}}
        rows = self._collect(_FakeResumableManager(), monkeypatch, pages)
        assert rows == []

    def test_off_origin_next_url_is_refused(self, monkeypatch: Any) -> None:
        first = "https://uptime.betterstack.com/api/v3/incidents?per_page=50"
        pages = {
            first: {
                "data": [{"id": "1", "attributes": {}}],
                "pagination": {"next": "https://evil.example.com/api/v3/incidents?page=2"},
            }
        }
        try:
            self._collect(_FakeResumableManager(), monkeypatch, pages)
            raise AssertionError("expected BetterStackUntrustedURLError")
        except BetterStackUntrustedURLError:
            pass

    def test_poisoned_resume_url_is_refused(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(BetterStackResumeConfig(next_url="https://evil.example.com/api/v3/incidents"))
        try:
            self._collect(manager, monkeypatch, pages={})
            raise AssertionError("expected BetterStackUntrustedURLError")
        except BetterStackUntrustedURLError:
            pass


class TestProbeCredentials:
    @parameterized.expand([("ok", 200), ("unauthorized", 401), ("forbidden", 403)])
    def test_returns_status_code(self, _name: str, status_code: int) -> None:
        session = MagicMock()
        session.get.return_value = MagicMock(status_code=status_code)
        with mock.patch.object(better_stack, "make_tracked_session", return_value=session):
            assert better_stack.probe_credentials("bs_test", "incidents") == status_code

    def test_connection_failure_returns_none(self) -> None:
        session = MagicMock()
        session.get.side_effect = Exception("boom")
        with mock.patch.object(better_stack, "make_tracked_session", return_value=session):
            assert better_stack.probe_credentials("bs_test") is None
