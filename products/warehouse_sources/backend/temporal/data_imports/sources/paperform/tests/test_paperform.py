from datetime import UTC, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.paperform import paperform
from products.warehouse_sources.backend.temporal.data_imports.sources.paperform.paperform import (
    PAGE_SIZE,
    PaperformResumeConfig,
    PaperformRetryableError,
    _format_after_date,
    check_access,
    get_rows,
    paperform_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.paperform.settings import (
    ENDPOINTS,
    PAPERFORM_ENDPOINTS,
)

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_page_unwrapped = paperform._fetch_page.__wrapped__  # type: ignore[attr-defined]


class _FakeResumableManager:
    def __init__(self, state: PaperformResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[PaperformResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> PaperformResumeConfig | None:
        return self._state

    def save_state(self, data: PaperformResumeConfig) -> None:
        self.saved.append(data)


def _envelope(results_key: str, items: list[dict], has_more: bool = False) -> dict:
    return {"status": "ok", "results": {results_key: items}, "has_more": has_more, "total": len(items)}


class _FakeFetch:
    """Dispatches on (path, after_id cursor) and records every call's params."""

    def __init__(self, pages: dict[tuple[str, str | None], dict]) -> None:
        self._pages = pages
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, session: Any, path: str, params: dict, logger: Any) -> dict:
        self.calls.append((path, params))
        return self._pages[(path, params.get("after_id"))]


class TestGetRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager,
        monkeypatch: Any,
        fetch: _FakeFetch,
        endpoint: str,
        **kwargs: Any,
    ) -> list[dict]:
        monkeypatch.setattr(paperform, "_fetch_page", fetch)
        monkeypatch.setattr(paperform, "make_tracked_session", lambda **_: MagicMock())

        rows: list[dict] = []
        for batch in get_rows(
            api_key="pf-key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
            **kwargs,
        ):
            rows.extend(batch)
        return rows

    def test_top_level_single_page_yields_and_stops(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        fetch = _FakeFetch({("/forms", None): _envelope("forms", [{"id": "f1"}, {"id": "f2"}])})
        rows = self._collect(manager, monkeypatch, fetch, "forms")
        assert rows == [{"id": "f1"}, {"id": "f2"}]
        # has_more is false, so we stop without persisting resume state.
        assert manager.saved == []

    def test_top_level_follows_after_id_cursor_until_has_more_false(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        fetch = _FakeFetch(
            {
                ("/forms", None): _envelope("forms", [{"id": "f1"}, {"id": "f2"}], has_more=True),
                ("/forms", "f2"): _envelope("forms", [{"id": "f3"}]),
            }
        )
        rows = self._collect(manager, monkeypatch, fetch, "forms")
        assert [r["id"] for r in rows] == ["f1", "f2", "f3"]
        # State is saved after the first page (cursor advances to the last id), then we stop.
        assert [(s.cursor, s.form_id) for s in manager.saved] == [("f2", None)]
        # Every page requests the largest page size in stable ascending creation order.
        assert all(p["limit"] == PAGE_SIZE and p["sort"] == "ASC" for _, p in fetch.calls)

    def test_top_level_resumes_from_saved_cursor(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(PaperformResumeConfig(cursor="f2"))
        # The initial (cursor=None) page must never be fetched on resume.
        fetch = _FakeFetch({("/forms", "f2"): _envelope("forms", [{"id": "f3"}])})
        rows = self._collect(manager, monkeypatch, fetch, "forms")
        assert rows == [{"id": "f3"}]

    def test_fan_out_injects_form_id_and_bookmarks_next_form(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        fetch = _FakeFetch(
            {
                ("/forms", None): _envelope("forms", [{"id": "f1"}, {"id": "f2"}]),
                ("/forms/f1/submissions", None): _envelope("submissions", [{"id": "s1"}, {"id": "s2"}], has_more=True),
                ("/forms/f1/submissions", "s2"): _envelope("submissions", [{"id": "s3"}]),
                ("/forms/f2/submissions", None): _envelope("submissions", [{"id": "s4"}]),
            }
        )
        rows = self._collect(manager, monkeypatch, fetch, "submissions")
        assert rows == [
            {"form_id": "f1", "id": "s1"},
            {"form_id": "f1", "id": "s2"},
            {"form_id": "f1", "id": "s3"},
            {"form_id": "f2", "id": "s4"},
        ]
        # Mid-form page cursor, then the bookmark advancing to the next form (fresh first page).
        assert [(s.cursor, s.form_id) for s in manager.saved] == [("s2", "f1"), (None, "f2")]

    def test_fan_out_resumes_from_bookmarked_form_and_cursor(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(PaperformResumeConfig(cursor="s9", form_id="f2"))
        fetch = _FakeFetch(
            {
                ("/forms", None): _envelope("forms", [{"id": "f1"}, {"id": "f2"}]),
                ("/forms/f2/submissions", "s9"): _envelope("submissions", [{"id": "s10"}]),
            }
        )
        rows = self._collect(manager, monkeypatch, fetch, "submissions")
        # f1 was fully processed before the crash and must not be re-fetched.
        assert rows == [{"form_id": "f2", "id": "s10"}]

    def test_fan_out_restarts_when_bookmarked_form_no_longer_exists(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(PaperformResumeConfig(cursor="s9", form_id="deleted-form"))
        fetch = _FakeFetch(
            {
                ("/forms", None): _envelope("forms", [{"id": "f1"}]),
                ("/forms/f1/submissions", None): _envelope("submissions", [{"id": "s1"}]),
            }
        )
        rows = self._collect(manager, monkeypatch, fetch, "submissions")
        assert rows == [{"form_id": "f1", "id": "s1"}]

    def test_fan_out_non_paginated_endpoint_fetches_each_form_once(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        fetch = _FakeFetch(
            {
                ("/forms", None): _envelope("forms", [{"id": "f1"}, {"id": "f2"}]),
                ("/forms/f1/products", None): _envelope("products", [{"SKU": "P-1"}]),
                ("/forms/f2/products", None): _envelope("products", []),
            }
        )
        rows = self._collect(manager, monkeypatch, fetch, "products")
        assert rows == [{"form_id": "f1", "SKU": "P-1"}]
        # Non-paginated child requests carry no pagination params.
        product_calls = [params for path, params in fetch.calls if path.endswith("/products")]
        assert product_calls == [{}, {}]

    def test_incremental_watermark_only_on_first_page_of_each_form(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        fetch = _FakeFetch(
            {
                ("/forms", None): _envelope("forms", [{"id": "f1"}, {"id": "f2"}]),
                ("/forms/f1/submissions", None): _envelope("submissions", [{"id": "s1"}], has_more=True),
                ("/forms/f1/submissions", "s1"): _envelope("submissions", [{"id": "s2"}]),
                ("/forms/f2/submissions", None): _envelope("submissions", []),
            }
        )
        self._collect(
            manager,
            monkeypatch,
            fetch,
            "submissions",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 2, 3, 4, 5, 999999, tzinfo=UTC),
        )
        params_by_call = {(path, params.get("after_id")): params for path, params in fetch.calls}
        # The forms listing that drives the fan-out is never date-filtered.
        assert "after_date" not in params_by_call[("/forms", None)]
        # Each form's first page carries the watermark (truncated down to whole seconds)...
        assert params_by_call[("/forms/f1/submissions", None)]["after_date"] == "2024-01-02T03:04:05Z"
        assert params_by_call[("/forms/f2/submissions", None)]["after_date"] == "2024-01-02T03:04:05Z"
        # ...and later pages advance purely on after_id (the API ignores after_date alongside it).
        assert "after_date" not in params_by_call[("/forms/f1/submissions", "s1")]

    def test_full_refresh_ignores_stale_watermark(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        fetch = _FakeFetch(
            {
                ("/forms", None): _envelope("forms", [{"id": "f1"}]),
                ("/forms/f1/partial-submissions", None): _envelope("partial-submissions", [{"id": "p1"}]),
            }
        )
        # partial_submissions declares no incremental fields, so a leftover watermark must not filter.
        self._collect(
            manager,
            monkeypatch,
            fetch,
            "partial_submissions",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
        )
        assert all("after_date" not in params for _, params in fetch.calls)


class TestFormatAfterDate:
    @parameterized.expand(
        [
            ("aware_datetime", datetime(2024, 5, 6, 7, 8, 9, 123456, tzinfo=UTC), "2024-05-06T07:08:09Z"),
            ("naive_datetime_assumed_utc", datetime(2024, 5, 6, 7, 8, 9), "2024-05-06T07:08:09Z"),
            ("string_passthrough", "2024-05-06T07:08:09Z", "2024-05-06T07:08:09Z"),
        ]
    )
    def test_formats_watermark(self, _name: str, value: Any, expected: str) -> None:
        assert _format_after_date(value) == expected


class TestFetchPage:
    def _session_returning(self, status_code: int, body: Any = None) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.json.return_value = body if body is not None else _envelope("forms", [])
        response.text = ""
        response.raise_for_status.side_effect = (
            requests.HTTPError(f"{status_code} error", response=response) if status_code >= 400 else None
        )
        session = MagicMock()
        session.get.return_value = response
        return session

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_raise_retryable_error(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(PaperformRetryableError):
            _fetch_page_unwrapped(session, "/forms", {}, MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(session, "/forms", {}, MagicMock())

    def test_non_dict_body_is_retryable(self) -> None:
        session = self._session_returning(200, [{"id": "f1"}])
        with pytest.raises(PaperformRetryableError):
            _fetch_page_unwrapped(session, "/forms", {}, MagicMock())

    def test_missing_results_key_raises_retryable_on_extract(self) -> None:
        config = PAPERFORM_ENDPOINTS["forms"]
        with pytest.raises(PaperformRetryableError):
            paperform._extract_rows({"status": "ok", "results": {}}, config, "/forms")


class TestCheckAccess:
    @staticmethod
    def _session(response: Any) -> MagicMock:
        session = MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        return session

    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid Paperform API key"),
            (
                "forbidden_no_api_plan",
                403,
                False,
                "Your Paperform plan does not include API access. API access requires a Pro, Business, or Agency plan.",
            ),
            ("server_error", 500, False, "Paperform returned HTTP 500"),
        ]
    )
    @patch(f"{paperform.__name__}.make_tracked_session")
    def test_validate_credentials(
        self,
        _name: str,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
        mock_session: MagicMock,
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = status < 400
        mock_session.return_value = self._session(response)
        assert validate_credentials("pf-key") == (expected_valid, expected_message)

    @patch(f"{paperform.__name__}.make_tracked_session")
    def test_connection_error_maps_to_zero(self, mock_session: MagicMock) -> None:
        mock_session.return_value = self._session(requests.ConnectionError("boom"))
        status, message = check_access("pf-key")
        assert status == 0
        assert message is not None and "boom" in message


class TestPaperformSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        config = PAPERFORM_ENDPOINTS[endpoint]
        response = paperform_source(
            api_key="pf-key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None

    def test_form_scoped_endpoints_include_form_id_in_primary_key(self) -> None:
        # This table aggregates rows across every form, so per-form identifiers (submission id,
        # field key, SKU, coupon code) are only unique with the parent form id in the key.
        for config in PAPERFORM_ENDPOINTS.values():
            if config.form_scoped:
                assert config.primary_keys[0] == "form_id"
