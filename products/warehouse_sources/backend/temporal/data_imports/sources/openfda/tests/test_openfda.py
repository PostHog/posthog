from datetime import date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.openfda import openfda
from products.warehouse_sources.backend.temporal.data_imports.sources.openfda.openfda import (
    OPENFDA_BASE_URL,
    PAGE_SIZE,
    OpenFDAResumeConfig,
    _build_initial_url,
    _fetch_page,
    _format_date_value,
    _make_auth,
    get_rows,
    openfda_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.openfda.settings import OPENFDA_ENDPOINTS


class _FakeResumableManager:
    def __init__(self, state: OpenFDAResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[OpenFDAResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> OpenFDAResumeConfig | None:
        return self._state

    def save_state(self, data: OpenFDAResumeConfig) -> None:
        self.saved.append(data)


class TestFormatDateValue:
    @parameterized.expand(
        [
            ("datetime", datetime(2020, 1, 2, 3, 4, 5), "20200102"),
            ("date", date(2020, 1, 2), "20200102"),
            ("yyyymmdd_string", "20200102", "20200102"),
            ("dashed_string", "2020-01-02", "20200102"),
        ]
    )
    def test_formats_to_yyyymmdd(self, _name: str, value: Any, expected: str) -> None:
        # The openFDA search date range only accepts YYYYMMDD; a mis-formatted watermark silently
        # matches nothing (404) and wedges the incremental sync.
        assert _format_date_value(value) == expected


class TestBuildInitialUrl:
    def test_incremental_endpoint_bounds_by_date_and_sorts_ascending(self) -> None:
        config = OPENFDA_ENDPOINTS["drug_enforcement"]
        url = _build_initial_url(
            config,
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2020, 1, 1),
            incremental_field=None,
        )
        # The server-side date filter must survive: without it every "incremental" sync re-scans the
        # whole dataset. Ascending sort keeps the pipeline watermark advancing monotonically.
        assert f"{OPENFDA_BASE_URL}/drug/enforcement.json?" in url
        assert "search=report_date%3A%5B20200101+TO+99991231%5D" in url
        assert "sort=report_date%3Aasc" in url
        assert f"limit={PAGE_SIZE}" in url

    def test_first_incremental_sync_has_no_date_filter(self) -> None:
        config = OPENFDA_ENDPOINTS["drug_enforcement"]
        url = _build_initial_url(
            config,
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
            incremental_field=None,
        )
        # No watermark yet -> backfill the whole history, still ordered so the watermark is valid.
        assert "search=" not in url
        assert "sort=report_date%3Aasc" in url

    def test_user_selected_incremental_field_overrides_default(self) -> None:
        config = OPENFDA_ENDPOINTS["drug_enforcement"]
        url = _build_initial_url(
            config,
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2020, 1, 1),
            incremental_field="recall_initiation_date",
        )
        # Honor the user's chosen cursor field instead of hardcoding the endpoint default.
        assert "search=recall_initiation_date%3A" in url
        assert "sort=recall_initiation_date%3Aasc" in url

    def test_full_refresh_endpoint_omits_search_and_sort(self) -> None:
        config = OPENFDA_ENDPOINTS["drug_ndc"]
        url = _build_initial_url(
            config,
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
        )
        # drug/ndc has no date cursor; it must page on the bare search_after cursor with no sort.
        assert "search=" not in url
        assert "sort=" not in url
        assert f"limit={PAGE_SIZE}" in url


class TestMakeAuth:
    def test_key_becomes_basic_auth_username(self) -> None:
        auth = _make_auth("secret")
        assert auth is not None
        assert auth.username == "secret"
        assert auth.password == ""

    def test_blank_key_sends_no_auth(self) -> None:
        # openFDA allows the unauthenticated tier; a missing key must not become `HTTPBasicAuth("", "")`.
        assert _make_auth(None) is None
        assert _make_auth("") is None


def _response(status: int, *, body: Any = None, next_url: str | None = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.ok = 200 <= status < 300
    response.json.return_value = body or {}
    response.links = {"next": {"url": next_url}} if next_url else {}
    if not response.ok:
        response.raise_for_status.side_effect = requests.HTTPError(f"{status} error", response=response)
    return response


class TestFetchPage:
    def test_404_is_terminal_not_an_error(self) -> None:
        # openFDA returns 404 (not an empty results array) when nothing matches — expected at the tail
        # of an incremental run. Treating it as an error would fail every caught-up sync.
        session = MagicMock()
        session.get.return_value = _response(404)
        assert _fetch_page(session, "http://x", None, MagicMock()) is None

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_status_raises_retryable_error(self, _name: str, status: int) -> None:
        session = MagicMock()
        session.get.return_value = _response(status)
        _fetch_page.retry.sleep = lambda _s: None  # type: ignore[attr-defined]
        with pytest.raises(openfda.OpenFDARetryableError):
            _fetch_page(session, "http://x", None, MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403)])
    def test_auth_error_raises_for_status(self, _name: str, status: int) -> None:
        session = MagicMock()
        session.get.return_value = _response(status)
        with pytest.raises(requests.HTTPError):
            _fetch_page(session, "http://x", None, MagicMock())

    def test_success_returns_results_and_next_cursor(self) -> None:
        session = MagicMock()
        session.get.return_value = _response(
            200, body={"results": [{"recall_number": "D-1"}]}, next_url="http://api.fda.gov/next"
        )
        results, next_url = _fetch_page(session, "http://x", None, MagicMock())
        assert results == [{"recall_number": "D-1"}]
        assert next_url == "http://api.fda.gov/next"

    def test_last_page_has_no_next_cursor(self) -> None:
        session = MagicMock()
        session.get.return_value = _response(200, body={"results": [{"recall_number": "D-9"}]})
        _results, next_url = _fetch_page(session, "http://x", None, MagicMock())
        assert next_url is None


def _collect(
    manager: _FakeResumableManager,
    monkeypatch: Any,
    pages: dict[str, tuple[list[dict], str | None] | None],
    endpoint: str = "drug_enforcement",
) -> list[dict]:
    def fake_fetch(session: Any, url: str, auth: Any, logger: Any) -> Any:
        return pages[url]

    monkeypatch.setattr(openfda, "_fetch_page", fake_fetch)
    monkeypatch.setattr(openfda, "make_tracked_session", lambda **kwargs: MagicMock())

    rows: list[dict] = []
    for page in get_rows(
        api_key=None,
        endpoint=endpoint,
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
    ):
        rows.extend(page)
    return rows


class TestGetRows:
    def test_follows_link_cursor_across_pages(self, monkeypatch: Any) -> None:
        initial = _build_initial_url(OPENFDA_ENDPOINTS["drug_enforcement"], False, None, None)
        pages = {
            initial: ([{"recall_number": "D-1"}], "http://api.fda.gov/p2"),
            "http://api.fda.gov/p2": ([{"recall_number": "D-2"}], None),
        }
        rows = _collect(_FakeResumableManager(), monkeypatch, pages)
        assert rows == [{"recall_number": "D-1"}, {"recall_number": "D-2"}]

    def test_saves_cursor_after_yielding_each_page(self, monkeypatch: Any) -> None:
        initial = _build_initial_url(OPENFDA_ENDPOINTS["drug_enforcement"], False, None, None)
        pages = {
            initial: ([{"recall_number": "D-1"}], "http://api.fda.gov/p2"),
            "http://api.fda.gov/p2": ([{"recall_number": "D-2"}], None),
        }
        manager = _FakeResumableManager()
        _collect(manager, monkeypatch, pages)
        # State is saved only while more pages remain, and only the next cursor — so a crash re-fetches
        # the just-yielded page (merge dedupes) rather than skipping it. The final page saves nothing.
        assert [s.next_url for s in manager.saved] == ["http://api.fda.gov/p2"]

    def test_resumes_from_saved_cursor(self, monkeypatch: Any) -> None:
        pages = {
            "http://api.fda.gov/p2": ([{"recall_number": "D-2"}], None),
        }
        manager = _FakeResumableManager(OpenFDAResumeConfig(next_url="http://api.fda.gov/p2"))
        rows = _collect(manager, monkeypatch, pages)
        # Resume must start at the saved cursor, not rebuild the initial URL (which would re-pull page 1).
        assert rows == [{"recall_number": "D-2"}]

    def test_404_first_page_yields_nothing(self, monkeypatch: Any) -> None:
        initial = _build_initial_url(OPENFDA_ENDPOINTS["drug_enforcement"], False, None, None)
        rows = _collect(_FakeResumableManager(), monkeypatch, {initial: None})
        assert rows == []


class TestOpenfdaSource:
    @parameterized.expand(
        [
            ("drug_enforcement", ["recall_number"], "report_date"),
            ("drug_ndc", ["product_id"], None),
            ("device_510k", ["k_number"], "decision_date"),
        ]
    )
    def test_source_response_carries_endpoint_config(
        self, endpoint: str, primary_keys: list[str], partition_key: str | None
    ) -> None:
        response = openfda_source(
            api_key=None, endpoint=endpoint, logger=MagicMock(), resumable_source_manager=MagicMock()
        )
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        # Ascending sort must be declared so the pipeline checkpoints the watermark correctly.
        assert response.sort_mode == "asc"
        if partition_key is None:
            assert response.partition_mode is None
        else:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [partition_key]
