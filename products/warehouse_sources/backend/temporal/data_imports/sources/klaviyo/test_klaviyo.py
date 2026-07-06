from datetime import UTC, date, datetime
from typing import Any

import pytest
from freezegun import freeze_time
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.klaviyo import klaviyo
from products.warehouse_sources.backend.temporal.data_imports.sources.klaviyo.klaviyo import (
    KlaviyoResumeConfig,
    _build_filter,
    _build_initial_params,
    _clamp_future_value_to_now,
    _format_incremental_value,
    get_rows,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.klaviyo.settings import (
    KLAVIYO_ENDPOINTS,
    KlaviyoEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.klaviyo.source import KlaviyoSource


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14.000Z"),
            (
                "datetime_with_microseconds",
                datetime(2026, 1, 15, 10, 30, 45, 123456, tzinfo=UTC),
                "2026-01-15T10:30:45.123Z",
            ),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00.000Z"),
            ("string_passthrough", "some-cursor-value", "some-cursor-value"),
        ]
    )
    def test_format_incremental_value(self, _name: str, value: object, expected: str) -> None:
        assert _format_incremental_value(value) == expected

    def test_no_plus_zero_offset_in_output(self) -> None:
        result = _format_incremental_value(datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC))
        assert "+00:00" not in result


class TestBuildFilter:
    @parameterized.expand(
        [
            (
                "incremental_only",
                KLAVIYO_ENDPOINTS["events"],
                "datetime",
                "2026-03-04T02:58:14.000Z",
                "greater-than(datetime,2026-03-04T02:58:14.000Z)",
            ),
            (
                "base_filter_only",
                KLAVIYO_ENDPOINTS["email_campaigns"],
                None,
                None,
                "equals(messages.channel,'email')",
            ),
            (
                "combined_base_and_incremental",
                KLAVIYO_ENDPOINTS["email_campaigns"],
                "updated_at",
                "2026-03-04T02:58:14.000Z",
                "and(equals(messages.channel,'email'),greater-than(updated_at,2026-03-04T02:58:14.000Z))",
            ),
            ("no_filter", KLAVIYO_ENDPOINTS["metrics"], None, None, None),
        ]
    )
    def test_build_filter(
        self, _name: str, config: KlaviyoEndpointConfig, field: str | None, value: str | None, expected: str | None
    ) -> None:
        assert _build_filter(config, field, value) == expected


class TestBuildInitialParams:
    def test_events_incremental_uses_z_suffix(self) -> None:
        config = KLAVIYO_ENDPOINTS["events"]
        params = _build_initial_params(
            config,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            incremental_field="datetime",
        )
        assert "+00:00" not in params["filter"]
        assert params["filter"] == "greater-than(datetime,2026-03-04T02:58:14.000Z)"

    def test_lookback_window_uses_z_suffix(self) -> None:
        config = KLAVIYO_ENDPOINTS["events"]
        params = _build_initial_params(
            config,
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
            incremental_field="datetime",
        )
        assert "filter" in params
        assert "+00:00" not in params["filter"]
        assert params["filter"].endswith("Z)")

    @freeze_time("2026-06-15T12:00:00Z")
    def test_future_cursor_is_clamped_to_now(self) -> None:
        # A future-dated cursor would otherwise build greater-than(datetime,<future>),
        # which Klaviyo rejects with a 400 and wedges every subsequent sync.
        config = KLAVIYO_ENDPOINTS["events"]
        params = _build_initial_params(
            config,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2027, 2, 5, 21, 46, 42, tzinfo=UTC),
            incremental_field="datetime",
        )
        assert params["filter"] == "greater-than(datetime,2026-06-15T12:00:00.000Z)"

    @freeze_time("2026-06-15T12:00:00Z")
    def test_past_cursor_is_not_modified(self) -> None:
        config = KLAVIYO_ENDPOINTS["events"]
        params = _build_initial_params(
            config,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            incremental_field="datetime",
        )
        assert params["filter"] == "greater-than(datetime,2026-03-04T02:58:14.000Z)"


class TestClampFutureValueToNow:
    @freeze_time("2026-06-15T12:00:00Z")
    def test_future_datetime_is_clamped(self) -> None:
        assert _clamp_future_value_to_now(datetime(2027, 2, 5, 21, 46, 42, tzinfo=UTC)) == datetime(
            2026, 6, 15, 12, 0, 0, tzinfo=UTC
        )

    @freeze_time("2026-06-15T12:00:00Z")
    def test_naive_future_datetime_is_clamped(self) -> None:
        assert _clamp_future_value_to_now(datetime(2027, 2, 5, 21, 46, 42)) == datetime(
            2026, 6, 15, 12, 0, 0, tzinfo=UTC
        )

    @freeze_time("2026-06-15T12:00:00Z")
    def test_past_datetime_is_unchanged(self) -> None:
        value = datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC)
        assert _clamp_future_value_to_now(value) == value

    @freeze_time("2026-06-15T12:00:00Z")
    def test_future_date_is_clamped(self) -> None:
        assert _clamp_future_value_to_now(date(2027, 2, 5)) == date(2026, 6, 15)

    @freeze_time("2026-06-15T12:00:00Z")
    def test_past_date_is_unchanged(self) -> None:
        assert _clamp_future_value_to_now(date(2026, 3, 4)) == date(2026, 3, 4)

    def test_string_passthrough(self) -> None:
        assert _clamp_future_value_to_now("some-cursor-value") == "some-cursor-value"


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            # 401/403 surfaced as a requests HTTPError when `fetch_page` calls `raise_for_status()`.
            # The per-request path/query/timestamp varies, but the status text and base host are stable.
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://a.klaviyo.com/api/events?filter=greater-than(datetime,2026-06-15T13:03:18.000Z)",
            ),
            (
                "forbidden",
                "403 Client Error: Forbidden for url: https://a.klaviyo.com/api/metrics",
            ),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable_errors = KlaviyoSource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @parameterized.expand(
        [
            # Transient/infra errors and server-side failures must stay retryable.
            ("read_timeout", "HTTPSConnectionPool(host='a.klaviyo.com', port=443): Read timed out."),
            (
                "server_error",
                "500 Server Error: Internal Server Error for url: https://a.klaviyo.com/api/events",
            ),
            ("connection_reset", "Connection reset by peer"),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable_errors = KlaviyoSource().get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)


class TestFetchPageRetries:
    @parameterized.expand(
        [
            ("chunked_encoding", requests.exceptions.ChunkedEncodingError("Connection broken: InvalidChunkLength")),
            ("read_timeout", requests.ReadTimeout("Read timed out.")),
            ("connection_error", requests.ConnectionError("Connection reset by peer")),
        ]
    )
    def test_transient_errors_are_retried(self, _name: str, transient_error: Exception) -> None:
        # A transient network failure on the first attempt must retry rather than fail the whole sync.
        good = MagicMock()
        good.status_code = 200
        good.ok = True
        good.json.return_value = {"data": []}

        session = MagicMock()
        session.get.side_effect = [transient_error, good]

        with patch.object(klaviyo._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = klaviyo._fetch_page(session, "https://a.klaviyo.com/api/events", {}, MagicMock())

        assert result == {"data": []}
        assert session.get.call_count == 2

    def test_transient_error_reraised_after_exhausting_attempts(self) -> None:
        # After the 5-attempt cap the last transient error must surface (reraise=True), not be swallowed.
        session = MagicMock()
        session.get.side_effect = requests.exceptions.ChunkedEncodingError("Connection broken: InvalidChunkLength")

        with patch.object(klaviyo._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            with pytest.raises(requests.exceptions.ChunkedEncodingError):
                klaviyo._fetch_page(session, "https://a.klaviyo.com/api/events", {}, MagicMock())

        assert session.get.call_count == 5


def _response_with_status(status_code: int) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    return response


class _FakeResumableManager:
    def __init__(self, state: KlaviyoResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[KlaviyoResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> KlaviyoResumeConfig | None:
        return self._state

    def save_state(self, data: KlaviyoResumeConfig) -> None:
        self.saved.append(data)


class TestListProfilesFanOut:
    @staticmethod
    def _collect(manager: _FakeResumableManager, monkeypatch: Any, pages: dict[str, Any]) -> list[dict]:
        def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
            result = pages[url]
            if isinstance(result, Exception):
                raise result
            return result

        monkeypatch.setattr(klaviyo, "_fetch_page", fake_fetch)

        rows: list[dict] = []
        for table in get_rows(
            api_key="pk_test",
            endpoint="list_profiles",
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            rows.extend(table.to_pylist())
        return rows

    def test_config_is_fan_out_full_refresh(self) -> None:
        config = KLAVIYO_ENDPOINTS["list_profiles"]
        assert config.fan_out_over_lists is True
        assert config.should_sync_default is False
        assert config.primary_keys == ["list_id", "profile_id"]
        assert config.incremental_fields == []

    def test_schema_is_full_refresh_only_and_off_by_default(self) -> None:
        schemas = {s.name: s for s in KlaviyoSource().get_schemas(MagicMock(), team_id=1)}
        list_profiles = schemas["list_profiles"]
        assert list_profiles.supports_incremental is False
        assert list_profiles.supports_append is False
        assert list_profiles.should_sync_default is False

    def test_lists_request_stays_within_klaviyo_page_size_cap(self, monkeypatch: Any) -> None:
        # Klaviyo's Get Lists endpoint caps page[size] at 10; a larger value 400s the whole fan-out.
        fetched_urls: list[str] = []

        def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
            fetched_urls.append(url)
            return {"data": [], "links": {"next": None}}

        monkeypatch.setattr(klaviyo, "_fetch_page", fake_fetch)
        list(klaviyo._iter_list_ids(MagicMock(), {}, MagicMock()))

        assert fetched_urls == ["https://a.klaviyo.com/api/lists?page[size]=10"]

    def test_fans_out_over_every_list_into_membership_rows(self, monkeypatch: Any) -> None:
        pages = {
            "https://a.klaviyo.com/api/lists?page[size]=10": {
                "data": [{"id": "L1"}, {"id": "L2"}],
                "links": {"next": None},
            },
            "https://a.klaviyo.com/api/lists/L1/relationships/profiles?page[size]=100": {
                "data": [{"type": "profile", "id": "P1"}, {"type": "profile", "id": "P2"}],
                "links": {"next": None},
            },
            "https://a.klaviyo.com/api/lists/L2/relationships/profiles?page[size]=100": {
                "data": [{"type": "profile", "id": "P3"}],
                "links": {"next": None},
            },
        }
        rows = self._collect(_FakeResumableManager(), monkeypatch, pages)
        assert rows == [
            {"list_id": "L1", "profile_id": "P1"},
            {"list_id": "L1", "profile_id": "P2"},
            {"list_id": "L2", "profile_id": "P3"},
        ]

    def test_follows_membership_pagination(self, monkeypatch: Any) -> None:
        next_url = "https://a.klaviyo.com/api/lists/L1/relationships/profiles?page[cursor]=abc"
        pages = {
            "https://a.klaviyo.com/api/lists?page[size]=10": {
                "data": [{"id": "L1"}],
                "links": {"next": None},
            },
            "https://a.klaviyo.com/api/lists/L1/relationships/profiles?page[size]=100": {
                "data": [{"type": "profile", "id": "P1"}],
                "links": {"next": next_url},
            },
            next_url: {
                "data": [{"type": "profile", "id": "P2"}],
                "links": {"next": None},
            },
        }
        rows = self._collect(_FakeResumableManager(), monkeypatch, pages)
        assert rows == [
            {"list_id": "L1", "profile_id": "P1"},
            {"list_id": "L1", "profile_id": "P2"},
        ]

    def test_resume_from_deleted_list_restarts_from_first(self, monkeypatch: Any) -> None:
        pages = {
            "https://a.klaviyo.com/api/lists?page[size]=10": {
                "data": [{"id": "L1"}],
                "links": {"next": None},
            },
            "https://a.klaviyo.com/api/lists/L1/relationships/profiles?page[size]=100": {
                "data": [{"type": "profile", "id": "P1"}],
                "links": {"next": None},
            },
        }
        manager = _FakeResumableManager(KlaviyoResumeConfig(next_url=None, list_id="DELETED"))
        rows = self._collect(manager, monkeypatch, pages)
        assert rows == [{"list_id": "L1", "profile_id": "P1"}]

    def test_list_deleted_mid_fan_out_is_skipped(self, monkeypatch: Any) -> None:
        not_found = requests.HTTPError(response=_response_with_status(404))
        pages = {
            "https://a.klaviyo.com/api/lists?page[size]=10": {
                "data": [{"id": "L1"}, {"id": "GONE"}, {"id": "L2"}],
                "links": {"next": None},
            },
            "https://a.klaviyo.com/api/lists/L1/relationships/profiles?page[size]=100": {
                "data": [{"type": "profile", "id": "P1"}],
                "links": {"next": None},
            },
            "https://a.klaviyo.com/api/lists/GONE/relationships/profiles?page[size]=100": not_found,
            "https://a.klaviyo.com/api/lists/L2/relationships/profiles?page[size]=100": {
                "data": [{"type": "profile", "id": "P2"}],
                "links": {"next": None},
            },
        }
        rows = self._collect(_FakeResumableManager(), monkeypatch, pages)
        assert rows == [
            {"list_id": "L1", "profile_id": "P1"},
            {"list_id": "L2", "profile_id": "P2"},
        ]

    def test_non_404_http_error_propagates(self, monkeypatch: Any) -> None:
        server_error = requests.HTTPError(response=_response_with_status(500))
        pages = {
            "https://a.klaviyo.com/api/lists?page[size]=10": {
                "data": [{"id": "L1"}],
                "links": {"next": None},
            },
            "https://a.klaviyo.com/api/lists/L1/relationships/profiles?page[size]=100": server_error,
        }
        with pytest.raises(requests.HTTPError):
            self._collect(_FakeResumableManager(), monkeypatch, pages)
