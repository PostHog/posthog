from datetime import UTC, date, datetime
from typing import Any

import pytest
from freezegun import freeze_time
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.lemlist import lemlist
from products.warehouse_sources.backend.temporal.data_imports.sources.lemlist.lemlist import (
    PAGE_SIZE,
    LemlistResumeConfig,
    _build_params,
    _build_url,
    _clamp_future_value_to_now,
    _format_incremental_value,
    get_rows,
    lemlist_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lemlist.settings import LEMLIST_ENDPOINTS


class _FakeResumableManager:
    def __init__(self, state: LemlistResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[LemlistResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> LemlistResumeConfig | None:
        return self._state

    def save_state(self, data: LemlistResumeConfig) -> None:
        self.saved.append(data)


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 5, 11, 2, 58, 14, tzinfo=UTC), "2026-05-11T02:58:14Z"),
            ("naive_datetime", datetime(2026, 5, 11, 2, 58, 14), "2026-05-11T02:58:14Z"),
            ("date_value", date(2026, 5, 11), "2026-05-11T00:00:00Z"),
            ("string_passthrough", "1715385600", "1715385600"),
        ]
    )
    def test_format_incremental_value(self, _name: str, value: object, expected: str) -> None:
        assert _format_incremental_value(value) == expected

    def test_no_plus_zero_offset(self) -> None:
        assert "+00:00" not in _format_incremental_value(datetime(2026, 5, 11, tzinfo=UTC))


class TestClampFutureValueToNow:
    @freeze_time("2026-06-15T12:00:00Z")
    def test_future_datetime_clamped(self) -> None:
        assert _clamp_future_value_to_now(datetime(2027, 2, 5, tzinfo=UTC)) == datetime(
            2026, 6, 15, 12, 0, 0, tzinfo=UTC
        )

    @freeze_time("2026-06-15T12:00:00Z")
    def test_past_datetime_unchanged(self) -> None:
        value = datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC)
        assert _clamp_future_value_to_now(value) == value

    @freeze_time("2026-06-15T12:00:00Z")
    def test_future_date_clamped(self) -> None:
        assert _clamp_future_value_to_now(date(2027, 2, 5)) == date(2026, 6, 15)

    def test_string_passthrough(self) -> None:
        assert _clamp_future_value_to_now("cursor") == "cursor"


class TestBuildParams:
    def test_campaigns_requests_version_and_stable_sort(self) -> None:
        params = _build_params(
            LEMLIST_ENDPOINTS["campaigns"], should_use_incremental_field=False, db_incremental_field_last_value=None
        )
        assert params == {"version": "v2", "sortBy": "createdAt", "sortOrder": "asc"}

    def test_campaigns_never_sends_mindate(self) -> None:
        # Campaigns has no server-side date filter, so even an incremental request must not add minDate.
        params = _build_params(
            LEMLIST_ENDPOINTS["campaigns"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 5, 11, tzinfo=UTC),
        )
        assert "minDate" not in params

    def test_activities_incremental_sets_mindate(self) -> None:
        params = _build_params(
            LEMLIST_ENDPOINTS["activities"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 5, 11, 0, 0, 0, tzinfo=UTC),
        )
        assert params["minDate"] == "2026-05-11T00:00:00Z"
        assert params["version"] == "v2"

    @freeze_time("2026-06-15T12:00:00Z")
    def test_activities_first_sync_uses_lookback_window(self) -> None:
        # No stored watermark -> bound the first sync by the configured lookback instead of full history.
        params = _build_params(
            LEMLIST_ENDPOINTS["activities"], should_use_incremental_field=True, db_incremental_field_last_value=None
        )
        assert params["minDate"] == "2025-06-15T12:00:00Z"

    @freeze_time("2026-06-15T12:00:00Z")
    def test_activities_future_watermark_clamped(self) -> None:
        params = _build_params(
            LEMLIST_ENDPOINTS["activities"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2027, 1, 1, tzinfo=UTC),
        )
        assert params["minDate"] == "2026-06-15T12:00:00Z"

    def test_activities_full_refresh_has_no_mindate(self) -> None:
        params = _build_params(
            LEMLIST_ENDPOINTS["activities"], should_use_incremental_field=False, db_incremental_field_last_value=None
        )
        assert "minDate" not in params


class TestValidateCredentials:
    @pytest.mark.parametrize("status_code,expected", [(200, True), (401, False), (404, False)])
    def test_status_mapping(self, status_code: int, expected: bool, monkeypatch: Any) -> None:
        response = MagicMock(status_code=status_code)
        session = MagicMock()
        session.get.return_value = response
        monkeypatch.setattr(lemlist, "make_tracked_session", lambda **_: session)
        assert validate_credentials("key") is expected

    def test_exception_returns_false(self, monkeypatch: Any) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError()
        monkeypatch.setattr(lemlist, "make_tracked_session", lambda **_: session)
        assert validate_credentials("key") is False


class TestGetRows:
    @staticmethod
    def _collect(
        endpoint: str, manager: _FakeResumableManager, monkeypatch: Any, pages: dict[str, Any], **kwargs: Any
    ) -> list[dict]:
        def fake_fetch(session: Any, url: str, api_key: str, logger: Any) -> Any:
            result = pages[url]
            if isinstance(result, Exception):
                raise result
            return result

        monkeypatch.setattr(lemlist, "_fetch", fake_fetch)

        rows: list[dict] = []
        for batch in get_rows(
            api_key="key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
            **kwargs,
        ):
            rows.extend(batch)
        return rows

    def _campaigns_url(self, offset: int) -> str:
        return _build_url(
            "/campaigns",
            {"version": "v2", "sortBy": "createdAt", "sortOrder": "asc", "limit": PAGE_SIZE, "offset": offset},
        )

    def test_single_object_endpoint_wraps_into_one_row(self, monkeypatch: Any) -> None:
        pages = {_build_url("/team", {}): {"_id": "tea_1", "name": "Acme"}}
        rows = self._collect("team", _FakeResumableManager(), monkeypatch, pages)
        assert rows == [{"_id": "tea_1", "name": "Acme"}]

    def test_non_paginated_array_endpoint_yields_once(self, monkeypatch: Any) -> None:
        pages = {_build_url("/team/senders", {}): [{"userId": "usr_1"}, {"userId": "usr_2"}]}
        rows = self._collect("team_senders", _FakeResumableManager(), monkeypatch, pages)
        assert rows == [{"userId": "usr_1"}, {"userId": "usr_2"}]

    def test_short_first_page_terminates(self, monkeypatch: Any) -> None:
        pages = {self._campaigns_url(0): [{"_id": "cam_1"}, {"_id": "cam_2"}]}
        manager = _FakeResumableManager()
        rows = self._collect("campaigns", manager, monkeypatch, pages)
        assert rows == [{"_id": "cam_1"}, {"_id": "cam_2"}]
        # A short page is the last page, so no resume state is persisted.
        assert manager.saved == []

    def test_paginates_until_short_page(self, monkeypatch: Any) -> None:
        full_page = [{"_id": f"cam_{i}"} for i in range(PAGE_SIZE)]
        pages = {
            self._campaigns_url(0): full_page,
            self._campaigns_url(PAGE_SIZE): [{"_id": "cam_last"}],
        }
        manager = _FakeResumableManager()
        rows = self._collect("campaigns", manager, monkeypatch, pages)
        assert len(rows) == PAGE_SIZE + 1
        assert rows[-1] == {"_id": "cam_last"}
        # State is saved once, after the first full page, pointing at the next offset.
        assert manager.saved == [LemlistResumeConfig(offset=PAGE_SIZE)]

    def test_resume_starts_from_saved_offset(self, monkeypatch: Any) -> None:
        pages = {self._campaigns_url(PAGE_SIZE): [{"_id": "cam_resumed"}]}
        manager = _FakeResumableManager(LemlistResumeConfig(offset=PAGE_SIZE))
        rows = self._collect("campaigns", manager, monkeypatch, pages)
        assert rows == [{"_id": "cam_resumed"}]

    def test_empty_first_page_yields_nothing(self, monkeypatch: Any) -> None:
        pages: dict[str, list[dict[str, Any]]] = {self._campaigns_url(0): []}
        rows = self._collect("campaigns", _FakeResumableManager(), monkeypatch, pages)
        assert rows == []


class TestLemlistSourceResponse:
    def test_activities_response_is_incremental_desc_and_partitioned(self) -> None:
        response = lemlist_source(
            api_key="key", endpoint="activities", logger=MagicMock(), resumable_source_manager=MagicMock()
        )
        assert response.name == "activities"
        assert response.primary_keys == ["_id"]
        assert response.sort_mode == "desc"
        assert response.partition_keys == ["createdAt"]
        assert response.partition_mode == "datetime"

    def test_campaigns_response_is_full_refresh_asc(self) -> None:
        response = lemlist_source(
            api_key="key", endpoint="campaigns", logger=MagicMock(), resumable_source_manager=MagicMock()
        )
        assert response.sort_mode == "asc"
        assert response.partition_keys == ["createdAt"]

    def test_team_senders_response_has_no_partitioning(self) -> None:
        response = lemlist_source(
            api_key="key", endpoint="team_senders", logger=MagicMock(), resumable_source_manager=MagicMock()
        )
        assert response.primary_keys == ["userId"]
        assert response.partition_keys is None
        assert response.partition_mode is None


class TestRetryClassification:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_raise_retryable_error(self, _name: str, status_code: int) -> None:
        # Call the undecorated function so we assert the classification, not tenacity's retry loop.
        session = MagicMock()
        session.get.return_value = MagicMock(status_code=status_code, ok=False)
        with pytest.raises(lemlist.LemlistRetryableError):
            lemlist._fetch.__wrapped__(session, "https://api.lemlist.com/api/campaigns", "key", MagicMock())  # type: ignore[attr-defined]

    def test_client_error_raises_for_status(self) -> None:
        # A 4xx (other than 429) is a permanent error surfaced via raise_for_status.
        response = MagicMock(status_code=401, ok=False)
        response.raise_for_status.side_effect = requests.HTTPError("401 Client Error", response=response)
        session = MagicMock()
        session.get.return_value = response
        with pytest.raises(requests.HTTPError):
            lemlist._fetch.__wrapped__(session, "https://api.lemlist.com/api/campaigns", "key", MagicMock())  # type: ignore[attr-defined]
