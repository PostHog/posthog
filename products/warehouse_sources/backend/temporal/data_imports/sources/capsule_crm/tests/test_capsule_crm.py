from datetime import UTC, date, datetime
from typing import Any

import pytest
from freezegun import freeze_time
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.capsule_crm import capsule_crm
from products.warehouse_sources.backend.temporal.data_imports.sources.capsule_crm.capsule_crm import (
    CAPSULE_CRM_BASE_URL,
    CapsuleCRMResumeConfig,
    _build_initial_url,
    _clamp_future_value_to_now,
    _format_since_value,
    capsule_crm_source,
    get_rows,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.capsule_crm.settings import CAPSULE_CRM_ENDPOINTS


class TestFormatSinceValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("string_passthrough", "2026-03-04T02:58:14Z", "2026-03-04T02:58:14Z"),
        ]
    )
    def test_format_since_value(self, _name: str, value: object, expected: str) -> None:
        assert _format_since_value(value) == expected

    def test_no_offset_suffix(self) -> None:
        # Capsule expects a Z suffix, not the +00:00 offset isoformat() produces.
        assert "+00:00" not in _format_since_value(datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC))

    def test_non_utc_datetime_is_converted_to_utc(self) -> None:
        from datetime import timedelta, timezone

        value = datetime(2026, 3, 4, 12, 0, 0, tzinfo=timezone(timedelta(hours=5)))
        assert _format_since_value(value) == "2026-03-04T07:00:00Z"


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

    def test_string_passthrough(self) -> None:
        assert _clamp_future_value_to_now("some-cursor") == "some-cursor"


class TestBuildInitialUrl:
    def test_full_refresh_url_has_no_since(self) -> None:
        url = _build_initial_url(
            CAPSULE_CRM_ENDPOINTS["users"], should_use_incremental_field=False, db_incremental_field_last_value=None
        )
        assert url == f"{CAPSULE_CRM_BASE_URL}/users?perPage=100"

    def test_incremental_endpoint_embeds_related_data(self) -> None:
        url = _build_initial_url(
            CAPSULE_CRM_ENDPOINTS["parties"], should_use_incremental_field=False, db_incremental_field_last_value=None
        )
        # embed values are folded in to reduce round-trips; urlencode escapes the comma.
        assert "perPage=100" in url
        assert "embed=tags%2Cfields%2Corganisation" in url
        assert "since" not in url

    def test_first_incremental_sync_omits_since(self) -> None:
        # No watermark yet -> pull full history, no `since` filter.
        url = _build_initial_url(
            CAPSULE_CRM_ENDPOINTS["opportunities"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
        )
        assert "since" not in url

    def test_incremental_sync_with_watermark_adds_since(self) -> None:
        url = _build_initial_url(
            CAPSULE_CRM_ENDPOINTS["opportunities"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )
        assert "since=2026-03-04T02%3A58%3A14Z" in url

    def test_since_ignored_for_full_refresh_only_endpoint(self) -> None:
        # tasks has no server-side `since` filter, so a watermark must not produce a `since` param.
        url = _build_initial_url(
            CAPSULE_CRM_ENDPOINTS["tasks"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )
        assert "since" not in url


class _FakeResumableManager:
    def __init__(self, state: CapsuleCRMResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[CapsuleCRMResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> CapsuleCRMResumeConfig | None:
        return self._state

    def save_state(self, data: CapsuleCRMResumeConfig) -> None:
        self.saved.append(data)


def _collect(
    manager: _FakeResumableManager, monkeypatch: Any, pages: dict[str, Any], endpoint: str = "parties", **kwargs: Any
) -> list[dict]:
    fetched: list[str] = []

    def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> tuple[dict, str | None]:
        fetched.append(url)
        result = pages[url]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(capsule_crm, "_fetch_page", fake_fetch)
    rows: list[dict] = []
    for batch in get_rows(
        access_token="tok",
        endpoint=endpoint,
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
        **kwargs,
    ):
        rows.extend(batch)
    manager.fetched = fetched  # type: ignore[attr-defined]
    return rows


class TestGetRows:
    def test_follows_link_header_pagination(self, monkeypatch: Any) -> None:
        page2 = f"{CAPSULE_CRM_BASE_URL}/parties?perPage=100&page=2"
        start = _build_initial_url(CAPSULE_CRM_ENDPOINTS["parties"], False, None)
        pages = {
            start: ({"parties": [{"id": 1}, {"id": 2}]}, page2),
            page2: ({"parties": [{"id": 3}]}, None),
        }
        rows = _collect(_FakeResumableManager(), monkeypatch, pages)
        assert rows == [{"id": 1}, {"id": 2}, {"id": 3}]

    def test_saves_resume_state_after_each_page_with_more(self, monkeypatch: Any) -> None:
        page2 = f"{CAPSULE_CRM_BASE_URL}/parties?perPage=100&page=2"
        start = _build_initial_url(CAPSULE_CRM_ENDPOINTS["parties"], False, None)
        pages = {
            start: ({"parties": [{"id": 1}]}, page2),
            page2: ({"parties": [{"id": 2}]}, None),
        }
        manager = _FakeResumableManager()
        _collect(manager, monkeypatch, pages)
        # State saved once (after page 1, which still had a next page); not after the final page.
        assert [s.next_url for s in manager.saved] == [page2]

    def test_resumes_from_saved_next_url(self, monkeypatch: Any) -> None:
        page2 = f"{CAPSULE_CRM_BASE_URL}/parties?perPage=100&page=2"
        start = _build_initial_url(CAPSULE_CRM_ENDPOINTS["parties"], False, None)
        pages = {
            # The starting URL must NOT be fetched when resuming.
            start: (Exception("should not fetch first page on resume"), None),
            page2: ({"parties": [{"id": 2}]}, None),
        }
        manager = _FakeResumableManager(CapsuleCRMResumeConfig(next_url=page2))
        rows = _collect(manager, monkeypatch, pages)
        assert rows == [{"id": 2}]
        assert manager.fetched == [page2]  # type: ignore[attr-defined]

    def test_extracts_rows_from_endpoint_specific_wrapper_key(self, monkeypatch: Any) -> None:
        # lost_reasons nests its array under "lostReasons", not the endpoint name.
        start = _build_initial_url(CAPSULE_CRM_ENDPOINTS["lost_reasons"], False, None)
        pages = {start: ({"lostReasons": [{"id": 7, "name": "No budget"}]}, None)}
        rows = _collect(_FakeResumableManager(), monkeypatch, pages, endpoint="lost_reasons")
        assert rows == [{"id": 7, "name": "No budget"}]


class TestSourceResponse:
    @parameterized.expand(
        [
            ("parties", "createdAt"),
            ("opportunities", "createdAt"),
            ("kases", "createdAt"),
            ("tasks", "createdAt"),
        ]
    )
    def test_incremental_and_taskish_endpoints_partition_on_created_at(self, endpoint: str, partition_key: str) -> None:
        response = capsule_crm_source(
            access_token="tok", endpoint=endpoint, logger=MagicMock(), resumable_source_manager=MagicMock()
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == [partition_key]
        assert response.sort_mode == "asc"

    @parameterized.expand([("users",), ("milestones",), ("pipelines",), ("categories",), ("lost_reasons",)])
    def test_metadata_endpoints_are_unpartitioned(self, endpoint: str) -> None:
        response = capsule_crm_source(
            access_token="tok", endpoint=endpoint, logger=MagicMock(), resumable_source_manager=MagicMock()
        )
        assert response.primary_keys == ["id"]
        assert response.partition_mode is None
        assert response.partition_keys is None


class TestRetryableErrorClassification:
    @parameterized.expand([(429,), (500,), (503,)])
    def test_retryable_statuses_raise_retryable_error(self, status: int) -> None:
        session = MagicMock()
        response = MagicMock()
        response.status_code = status
        session.get.return_value = response
        with pytest.raises(capsule_crm.CapsuleCRMRetryableError):
            # Bypass tenacity's retry wrapper to assert the raised type directly.
            capsule_crm._fetch_page.__wrapped__(session, "https://api.capsulecrm.com/api/v2/users", {}, MagicMock())

    @parameterized.expand([(401,), (403,), (404,)])
    def test_client_errors_raise_for_status(self, status: int) -> None:
        session = MagicMock()
        response = MagicMock()
        response.status_code = status
        response.ok = False
        response.raise_for_status.side_effect = requests.HTTPError(f"{status} Client Error")
        session.get.return_value = response
        with pytest.raises(requests.HTTPError):
            capsule_crm._fetch_page.__wrapped__(session, "https://api.capsulecrm.com/api/v2/users", {}, MagicMock())
