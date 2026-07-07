from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.workable import workable
from products.warehouse_sources.backend.temporal.data_imports.sources.workable.settings import (
    PAGE_SIZE,
    WORKABLE_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.workable.workable import (
    WorkableResumeConfig,
    WorkableRetryableError,
    _build_initial_url,
    _format_datetime,
    _sort_mode_for,
    _validate_subdomain,
    get_rows,
    validate_credentials,
    workable_source,
)


class TestValidateSubdomain:
    @parameterized.expand(
        [
            ("simple", "groove-tech", "groove-tech"),
            ("alnum", "company123", "company123"),
            ("single_char", "a", "a"),
            ("trims_whitespace", "  acme  ", "acme"),
        ]
    )
    def test_valid_subdomains(self, _name: str, value: str, expected: str) -> None:
        assert _validate_subdomain(value) == expected

    @parameterized.expand(
        [
            ("empty", ""),
            ("dot_injection", "evil.com/"),
            ("slash", "acme/foo"),
            ("at_sign", "user@host"),
            ("leading_hyphen_ok_but_dot_not", "a.b"),
            ("trailing_hyphen", "acme-"),
            ("leading_hyphen", "-acme"),
            ("space_inside", "ac me"),
        ]
    )
    def test_invalid_subdomains_raise(self, _name: str, value: str) -> None:
        with pytest.raises(ValueError):
            _validate_subdomain(value)


class TestFormatDatetime:
    @parameterized.expand(
        [
            ("aware", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_assumed_utc", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_only", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("string_passthrough", "already-a-cursor", "already-a-cursor"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        assert _format_datetime(value) == expected


class TestBuildInitialUrl:
    def test_full_refresh_only_has_limit(self) -> None:
        url = _build_initial_url(
            "acme",
            "members",
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
        )
        assert url == f"https://acme.workable.com/spi/v3/members?limit={PAGE_SIZE}"

    def test_incremental_adds_updated_after_by_default(self) -> None:
        url = _build_initial_url(
            "acme",
            "candidates",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
            incremental_field=None,
        )
        assert "updated_after=2026-01-02T03%3A04%3A05Z" in url

    def test_incremental_honors_chosen_created_at_field(self) -> None:
        url = _build_initial_url(
            "acme",
            "candidates",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
            incremental_field="created_at",
        )
        assert "created_after=" in url
        assert "updated_after=" not in url

    def test_full_refresh_endpoint_ignores_incremental_filter(self) -> None:
        # `members` is full refresh — a stray incremental value must not produce a time filter.
        url = _build_initial_url(
            "acme",
            "members",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 2, tzinfo=UTC),
            incremental_field="updated_at",
        )
        assert "_after" not in url


class TestSortMode:
    @parameterized.expand(
        [
            ("created_at_is_asc", "candidates", True, "created_at", "asc"),
            ("updated_at_is_desc", "candidates", True, "updated_at", "desc"),
            ("default_field_is_desc", "candidates", True, None, "desc"),
            ("non_incremental_run_is_asc", "candidates", False, "updated_at", "asc"),
            ("full_refresh_endpoint_is_asc", "members", True, "updated_at", "asc"),
        ]
    )
    def test_sort_mode(
        self, _name: str, endpoint: str, use_incremental: bool, field: str | None, expected: str
    ) -> None:
        assert _sort_mode_for(endpoint, use_incremental, field) == expected


class _FakeResumableManager:
    """In-memory stand-in for ResumableSourceManager."""

    def __init__(self, state: WorkableResumeConfig | None = None) -> None:
        self.state = state
        self.saved: list[WorkableResumeConfig] = []

    def can_resume(self) -> bool:
        return self.state is not None

    def load_state(self) -> WorkableResumeConfig | None:
        return self.state

    def save_state(self, data: WorkableResumeConfig) -> None:
        self.saved.append(data)


def _collect(manager: _FakeResumableManager, monkeypatch: Any, pages: dict[str, Any], **kwargs: Any) -> list[dict]:
    def fake_fetch(_session: Any, url: str, _logger: Any) -> dict:
        return pages[url]

    monkeypatch.setattr(workable, "_fetch_page", fake_fetch)
    rows: list[dict] = []
    for batch in get_rows(
        subdomain="acme",
        api_token="tok",
        endpoint=kwargs.get("endpoint", "candidates"),
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
        should_use_incremental_field=kwargs.get("should_use_incremental_field", False),
        db_incremental_field_last_value=kwargs.get("db_incremental_field_last_value"),
        incremental_field=kwargs.get("incremental_field"),
    ):
        rows.extend(batch)
    return rows


class TestGetRows:
    def test_yields_items_and_follows_paging_next(self, monkeypatch: Any) -> None:
        first = f"https://acme.workable.com/spi/v3/candidates?limit={PAGE_SIZE}"
        second = "https://www.workable.com/spi/v3/accounts/acme/candidates?limit=100&since_id=2"
        pages = {
            first: {"candidates": [{"id": "1"}], "paging": {"next": second}},
            second: {"candidates": [{"id": "2"}], "paging": {}},
        }
        rows = _collect(_FakeResumableManager(), monkeypatch, pages)
        assert [r["id"] for r in rows] == ["1", "2"]

    def test_saves_state_after_yielding_each_page_with_more_pages(self, monkeypatch: Any) -> None:
        first = f"https://acme.workable.com/spi/v3/candidates?limit={PAGE_SIZE}"
        second = "https://www.workable.com/spi/v3/accounts/acme/candidates?limit=100&since_id=2"
        pages = {
            first: {"candidates": [{"id": "1"}], "paging": {"next": second}},
            second: {"candidates": [{"id": "2"}], "paging": {}},
        }
        manager = _FakeResumableManager()
        _collect(manager, monkeypatch, pages)
        # State saved once (after page 1, which had a next); not after the final page.
        assert [s.next_url for s in manager.saved] == [second]

    def test_resumes_from_saved_next_url(self, monkeypatch: Any) -> None:
        resume_url = "https://www.workable.com/spi/v3/accounts/acme/candidates?limit=100&since_id=99"
        pages = {resume_url: {"candidates": [{"id": "99"}], "paging": {}}}
        manager = _FakeResumableManager(state=WorkableResumeConfig(next_url=resume_url))
        rows = _collect(manager, monkeypatch, pages)
        # The initial URL is never fetched — we pick up from the saved cursor.
        assert [r["id"] for r in rows] == ["99"]

    def test_empty_page_terminates(self, monkeypatch: Any) -> None:
        first = f"https://acme.workable.com/spi/v3/stages?limit={PAGE_SIZE}"
        pages: dict[str, Any] = {first: {"stages": [], "paging": {}}}
        rows = _collect(_FakeResumableManager(), monkeypatch, pages, endpoint="stages")
        assert rows == []


class TestFetchPage:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 502)])
    def test_retryable_statuses_raise_retryable_error(self, _name: str, status: int) -> None:
        session = MagicMock()
        session.get.return_value = MagicMock(status_code=status)
        # Disable tenacity's real sleeps so the retries don't slow the test down.
        workable._fetch_page.retry.sleep = lambda *_args, **_kwargs: None  # type: ignore[attr-defined]
        with pytest.raises(WorkableRetryableError):
            workable._fetch_page(session, "https://acme.workable.com/spi/v3/jobs", MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_non_retryable_statuses_raise_http_error(self, _name: str, status: int) -> None:
        response = MagicMock(status_code=status, ok=False, text="nope")
        response.raise_for_status.side_effect = requests.HTTPError(f"{status} Client Error", response=response)
        session = MagicMock()
        session.get.return_value = response
        with pytest.raises(requests.HTTPError):
            workable._fetch_page(session, "https://acme.workable.com/spi/v3/jobs", MagicMock())


class TestWorkableSource:
    @parameterized.expand(list(WORKABLE_ENDPOINTS.keys()))
    def test_source_response_primary_keys_and_partitioning(self, endpoint: str) -> None:
        config = WORKABLE_ENDPOINTS[endpoint]
        response = workable_source(
            subdomain="acme",
            api_token="tok",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    def test_partition_keys_are_stable_creation_fields(self) -> None:
        # Never partition on a mutable field like updated_at.
        for config in WORKABLE_ENDPOINTS.values():
            assert config.partition_key in (None, "created_at")


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, (200, True)),
            ("unauthorized", 401, False, (401, False)),
            ("forbidden", 403, False, (403, False)),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, ok: bool, expected: tuple[int, bool]) -> None:
        session = MagicMock()
        session.get.return_value = MagicMock(status_code=status, ok=ok)
        with mock.patch.object(workable, "make_tracked_session", lambda **_kwargs: session):
            assert validate_credentials("acme", "tok") == expected

    def test_transport_error_returns_zero(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with mock.patch.object(workable, "make_tracked_session", lambda **_kwargs: session):
            assert validate_credentials("acme", "tok") == (0, False)

    def test_invalid_subdomain_raises(self) -> None:
        with pytest.raises(ValueError):
            validate_credentials("evil.com/", "tok")
