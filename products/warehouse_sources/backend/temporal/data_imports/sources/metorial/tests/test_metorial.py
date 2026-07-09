from datetime import UTC, datetime
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.metorial import metorial
from products.warehouse_sources.backend.temporal.data_imports.sources.metorial.metorial import (
    MetorialResumeConfig,
    MetorialRetryableError,
    _build_url,
    get_rows,
    metorial_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.metorial.settings import (
    ENDPOINTS,
    METORIAL_BASE_URL,
    METORIAL_ENDPOINTS,
    PAGE_SIZE,
)

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_page_unwrapped = metorial._fetch_page.__wrapped__  # type: ignore[attr-defined]


class _FakeResumableManager:
    def __init__(self, state: MetorialResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[MetorialResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> MetorialResumeConfig | None:
        return self._state

    def save_state(self, data: MetorialResumeConfig) -> None:
        self.saved.append(data)


def _query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(url).query)


class TestBuildUrl:
    def test_first_page_has_limit_and_asc_order_but_no_cursor(self) -> None:
        url = _build_url("/sessions", after=None, incremental_field=None, db_incremental_field_last_value=None)
        assert url.startswith(f"{METORIAL_BASE_URL}/sessions?")
        query = _query(url)
        assert query["limit"] == [str(PAGE_SIZE)]
        assert query["order"] == ["asc"]
        assert "after" not in query

    def test_after_cursor_is_sent(self) -> None:
        url = _build_url("/sessions", after="ses_123", incremental_field=None, db_incremental_field_last_value=None)
        assert _query(url)["after"] == ["ses_123"]

    def test_incremental_filter_uses_bracket_gt_syntax(self) -> None:
        watermark = datetime(2025, 6, 1, 12, 30, 45, 999999, tzinfo=UTC)
        url = _build_url(
            "/sessions", after=None, incremental_field="updated_at", db_incremental_field_last_value=watermark
        )
        # Sub-second precision must be truncated DOWN so boundary rows are re-fetched, never skipped.
        assert _query(url)["updated_at[gt]"] == ["2025-06-01T12:30:45Z"]

    def test_no_filter_when_watermark_is_none(self) -> None:
        url = _build_url("/sessions", after=None, incremental_field="updated_at", db_incremental_field_last_value=None)
        assert "updated_at" not in _query(url)


class TestFetchPage:
    def _session_returning(self, status_code: int, body: Any = None) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.json.return_value = (
            body if body is not None else {"items": [], "pagination": {"has_more_after": False}}
        )
        response.text = ""
        response.raise_for_status.side_effect = (
            requests.HTTPError(f"{status_code} error", response=response) if status_code >= 400 else None
        )
        session = MagicMock()
        session.get.return_value = response
        return session

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 502)])
    def test_transient_statuses_raise_retryable_error(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(MetorialRetryableError):
            _fetch_page_unwrapped(session, f"{METORIAL_BASE_URL}/sessions", MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(session, f"{METORIAL_BASE_URL}/sessions", MagicMock())

    def test_success_returns_items_and_has_more_after(self) -> None:
        body = {"items": [{"id": "ses_1"}], "pagination": {"has_more_after": True, "has_more_before": False}}
        session = self._session_returning(200, body)
        items, has_more = _fetch_page_unwrapped(session, f"{METORIAL_BASE_URL}/sessions", MagicMock())
        assert items == [{"id": "ses_1"}]
        assert has_more is True

    @parameterized.expand([("bare_list", [{"id": "a"}]), ("missing_items", {"pagination": {}})])
    def test_unexpected_payload_is_retryable(self, _name: str, body: Any) -> None:
        session = self._session_returning(200, body)
        with pytest.raises(MetorialRetryableError):
            _fetch_page_unwrapped(session, f"{METORIAL_BASE_URL}/sessions", MagicMock())


class TestGetRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager,
        monkeypatch: Any,
        pages: dict[Optional[str], tuple[list[dict], bool]],
        endpoint: str = "sessions",
        incremental_field: str | None = None,
        db_incremental_field_last_value: Any = None,
    ) -> tuple[list[dict], list[str]]:
        """Pages are keyed by the `after` cursor the request carries (None = first page)."""
        requested_urls: list[str] = []

        def fake_fetch(session: Any, url: str, logger: Any) -> tuple[list[dict], bool]:
            requested_urls.append(url)
            after = _query(url).get("after", [None])[0]
            return pages[after]

        monkeypatch.setattr(metorial, "_fetch_page", fake_fetch)
        monkeypatch.setattr(metorial, "make_tracked_session", lambda **kwargs: MagicMock())

        rows: list[dict] = []
        for batch in get_rows(
            api_key="metorial_sk_test",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
            incremental_field=incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ):
            rows.extend(batch)
        return rows, requested_urls

    def test_single_page_yields_and_stops_without_saving_state(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows, _ = self._collect(manager, monkeypatch, {None: ([{"id": "ses_1"}, {"id": "ses_2"}], False)})
        assert rows == [{"id": "ses_1"}, {"id": "ses_2"}]
        assert manager.saved == []

    def test_follows_after_cursor_until_has_more_is_false(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = {
            None: ([{"id": "ses_1"}], True),
            "ses_1": ([{"id": "ses_2"}], True),
            "ses_2": ([{"id": "ses_3"}], False),
        }
        rows, _ = self._collect(manager, monkeypatch, pages)
        assert rows == [{"id": "ses_1"}, {"id": "ses_2"}, {"id": "ses_3"}]
        # State is saved after each yielded page that has a successor, pointing at the next cursor.
        assert [s.after for s in manager.saved] == ["ses_1", "ses_2"]

    def test_resumes_from_saved_cursor(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(MetorialResumeConfig(after="ses_5"))
        # The un-cursored first page must never be fetched on resume.
        rows, urls = self._collect(manager, monkeypatch, {"ses_5": ([{"id": "ses_6"}], False)})
        assert rows == [{"id": "ses_6"}]
        assert len(urls) == 1

    def test_stops_when_cursor_does_not_advance(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(MetorialResumeConfig(after="ses_1"))
        # Server keeps claiming more pages but returns the same last id — must terminate, not loop.
        rows, urls = self._collect(manager, monkeypatch, {"ses_1": ([{"id": "ses_1"}], True)})
        assert rows == [{"id": "ses_1"}]
        assert len(urls) == 1

    def test_empty_page_with_has_more_stops(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows, _ = self._collect(manager, monkeypatch, {None: ([], True)})
        assert rows == []

    def test_incremental_watermark_is_sent_on_every_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        watermark = datetime(2025, 6, 1, tzinfo=UTC)
        pages = {None: ([{"id": "ses_1"}], True), "ses_1": ([{"id": "ses_2"}], False)}
        _, urls = self._collect(
            manager,
            monkeypatch,
            pages,
            incremental_field="updated_at",
            db_incremental_field_last_value=watermark,
        )
        assert all(_query(url)["updated_at[gt]"] == ["2025-06-01T00:00:00Z"] for url in urls)


class TestMetorialSource:
    def _source(self, endpoint: str, **kwargs: Any):
        return metorial_source(
            api_key="metorial_sk_test",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
            **kwargs,
        )

    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = self._source(endpoint)
        assert response.name == endpoint
        assert response.primary_keys == ["id"]

    def test_full_refresh_and_created_at_use_asc_sort(self) -> None:
        assert self._source("sessions").sort_mode == "asc"
        assert (
            self._source(
                "sessions",
                should_use_incremental_field=True,
                incremental_field="created_at",
            ).sort_mode
            == "asc"
        )

    def test_updated_at_incremental_uses_desc_sort(self) -> None:
        # `order=asc` sorts by id (creation order), which is NOT monotonic in updated_at — the
        # pipeline must only commit the updated_at watermark at end of run.
        response = self._source("sessions", should_use_incremental_field=True, incremental_field="updated_at")
        assert response.sort_mode == "desc"

    @parameterized.expand([("providers", "updated_at"), ("tool_calls", "updated_at"), ("sessions", "completed_at")])
    def test_unsupported_incremental_field_is_rejected(self, endpoint: str, field: str) -> None:
        with pytest.raises(ValueError, match="is not supported for Metorial"):
            self._source(endpoint, should_use_incremental_field=True, incremental_field=field)

    def test_partition_key_is_stable_created_at(self) -> None:
        response = self._source("sessions")
        assert response.partition_keys == ["created_at"]
        assert response.partition_mode == "datetime"

    def test_incremental_fields_only_where_server_side_filter_exists(self) -> None:
        # `/providers` has no created_at/updated_at list filters; every other stream does.
        assert METORIAL_ENDPOINTS["providers"].incremental_fields == []
        for name in set(ENDPOINTS) - {"providers"}:
            fields = {f["field"] for f in METORIAL_ENDPOINTS[name].incremental_fields}
            assert "created_at" in fields, name


class TestValidateCredentials:
    def _session(self, response: Any) -> MagicMock:
        session = MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        return session

    @parameterized.expand(
        [
            ("ok", 200, True),
            ("unauthorized", 401, False),
            ("forbidden", 403, False),
            ("server_error", 500, False),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected_valid: bool) -> None:
        response = MagicMock()
        response.status_code = status
        with patch.object(metorial, "make_tracked_session", return_value=self._session(response)):
            valid, message = validate_credentials("metorial_sk_test")
        assert valid is expected_valid
        assert (message is None) is expected_valid

    def test_auth_failure_mentions_secret_key(self) -> None:
        response = MagicMock()
        response.status_code = 401
        with patch.object(metorial, "make_tracked_session", return_value=self._session(response)):
            _, message = validate_credentials("metorial_pk_wrong_key_type")
        assert message is not None and "metorial_sk_" in message

    def test_connection_error_returns_retry_message(self) -> None:
        session = self._session(requests.ConnectionError("boom"))
        with patch.object(metorial, "make_tracked_session", return_value=session):
            valid, message = validate_credentials("metorial_sk_test")
        assert valid is False
        assert message is not None and "try again" in message.lower()
