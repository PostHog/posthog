from datetime import UTC, date, datetime
from typing import Any

import pytest
from freezegun import freeze_time
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.capsule_crm import capsule_crm
from products.warehouse_sources.backend.temporal.data_imports.sources.capsule_crm.capsule_crm import (
    CAPSULE_CRM_BASE_URL,
    CapsuleCRMResumeConfig,
    CapsuleCRMUntrustedURLError,
    _build_initial_url,
    _clamp_future_value_to_now,
    _format_since_value,
    _validate_pagination_url,
    capsule_crm_source,
    get_rows,
    validate_credentials,
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

    def test_hostile_upstream_next_url_is_rejected(self, monkeypatch: Any) -> None:
        # An upstream Link header pointing at another host must abort before the bearer token is sent
        # there, and the poisoned URL must not be persisted as resume state.
        start = _build_initial_url(CAPSULE_CRM_ENDPOINTS["parties"], False, None)
        pages = {start: ({"parties": [{"id": 1}]}, "https://evil.example.com/api/v2/parties")}
        manager = _FakeResumableManager()
        with pytest.raises(CapsuleCRMUntrustedURLError):
            _collect(manager, monkeypatch, pages)
        assert manager.saved == []

    def test_hostile_resumed_next_url_is_rejected(self, monkeypatch: Any) -> None:
        # A poisoned resume state from Redis must never be requested with the bearer token.
        manager = _FakeResumableManager(CapsuleCRMResumeConfig(next_url="https://evil.example.com/api/v2/parties"))
        with pytest.raises(CapsuleCRMUntrustedURLError):
            _collect(manager, monkeypatch, {})


class TestValidatePaginationUrl:
    @parameterized.expand(
        [
            ("first_page", f"{CAPSULE_CRM_BASE_URL}/parties?perPage=100"),
            ("next_page", f"{CAPSULE_CRM_BASE_URL}/parties?perPage=100&page=2"),
            ("other_endpoint", f"{CAPSULE_CRM_BASE_URL}/opportunities?page=3"),
        ]
    )
    def test_trusted_urls_pass_through(self, _name: str, url: str) -> None:
        assert _validate_pagination_url(url) == url

    @parameterized.expand(
        [
            ("foreign_host", "https://evil.example.com/api/v2/parties"),
            ("subdomain_lookalike", "https://api.capsulecrm.com.evil.example.com/api/v2/parties"),
            ("http_scheme", "http://api.capsulecrm.com/api/v2/parties"),
            ("wrong_path_prefix", "https://api.capsulecrm.com/internal/parties"),
            ("missing_path", "https://api.capsulecrm.com"),
            ("metadata_endpoint", "http://169.254.169.254/latest/meta-data/"),
        ]
    )
    def test_untrusted_urls_raise(self, _name: str, url: str) -> None:
        with pytest.raises(CapsuleCRMUntrustedURLError):
            _validate_pagination_url(url)


class TestTokenRedaction:
    def test_validate_credentials_redacts_token_and_disables_redirects(self) -> None:
        session = MagicMock()
        response = MagicMock()
        response.status_code = 200
        session.get.return_value = response
        with patch.object(capsule_crm, "make_tracked_session", return_value=session) as make_session:
            validate_credentials("secret-token")
        assert make_session.call_args.kwargs["redact_values"] == ("secret-token",)
        assert make_session.call_args.kwargs["allow_redirects"] is False

    def test_get_rows_redacts_token_and_disables_redirects(self, monkeypatch: Any) -> None:
        session = MagicMock()
        make_session = MagicMock(return_value=session)
        monkeypatch.setattr(capsule_crm, "make_tracked_session", make_session)
        monkeypatch.setattr(capsule_crm, "_fetch_page", lambda *a, **k: ({"parties": []}, None))
        list(
            get_rows(
                access_token="secret-token",
                endpoint="parties",
                logger=MagicMock(),
                resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
            )
        )
        assert make_session.call_args.kwargs["redact_values"] == ("secret-token",)
        assert make_session.call_args.kwargs["allow_redirects"] is False


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


def _response_with(status_code: int) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response._content = b"{}"
    response.url = "https://api.capsulecrm.com/api/v2/users"
    return response


# The undecorated function behind tenacity's retry wrapper — call it to exercise status handling
# without the retry/backoff loop actually sleeping.
_fetch_page_unwrapped = capsule_crm._fetch_page.__wrapped__  # type: ignore[attr-defined]


class TestRetryableErrorClassification:
    @parameterized.expand([(429,), (500,), (503,)])
    def test_retryable_statuses_raise_retryable_error(self, status: int) -> None:
        session = MagicMock()
        session.get.return_value = _response_with(status)
        with pytest.raises(capsule_crm.CapsuleCRMRetryableError):
            _fetch_page_unwrapped(session, "https://api.capsulecrm.com/api/v2/users", {}, MagicMock())

    @parameterized.expand([(401,), (403,), (404,)])
    def test_client_errors_raise_for_status(self, status: int) -> None:
        session = MagicMock()
        session.get.return_value = _response_with(status)
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(session, "https://api.capsulecrm.com/api/v2/users", {}, MagicMock())
