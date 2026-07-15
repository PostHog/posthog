from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.sources.vantage import vantage
from products.warehouse_sources.backend.temporal.data_imports.sources.vantage.vantage import (
    VANTAGE_BASE_URL,
    VantageResumeConfig,
    _build_initial_url,
    get_rows,
    validate_credentials,
    vantage_source,
)


class _FakeResumableManager:
    def __init__(self, state: VantageResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[VantageResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> VantageResumeConfig | None:
        return self._state

    def save_state(self, data: VantageResumeConfig) -> None:
        self.saved.append(data)


def _collect(
    manager: _FakeResumableManager, monkeypatch: Any, pages: dict[str, Any], endpoint: str = "cost_reports"
) -> tuple[list[dict], list[str]]:
    fetched: list[str] = []

    def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
        fetched.append(url)
        result = pages[url]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(vantage, "_fetch_page", fake_fetch)

    rows: list[dict] = []
    for table in get_rows(
        api_key="tok",
        endpoint=endpoint,
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
    ):
        rows.extend(table.to_pylist())
    return rows, fetched


class TestPagination:
    def test_follows_links_next_and_terminates(self, monkeypatch: Any) -> None:
        # Regression guard: not advancing the URL loops forever; not terminating on a null `next`
        # over-fetches. Rows must come back across every page, in order.
        p1 = _build_initial_url(vantage.VANTAGE_ENDPOINTS["cost_reports"])
        p2 = f"{VANTAGE_BASE_URL}/cost_reports?page=2&limit=1000"
        pages = {
            p1: {"cost_reports": [{"token": "a"}, {"token": "b"}], "links": {"next": p2}},
            p2: {"cost_reports": [{"token": "c"}], "links": {"next": None}},
        }
        rows, fetched = _collect(_FakeResumableManager(), monkeypatch, pages)
        assert rows == [{"token": "a"}, {"token": "b"}, {"token": "c"}]
        assert fetched == [p1, p2]

    def test_reads_endpoint_specific_data_key(self, monkeypatch: Any) -> None:
        # The row array is nested under the endpoint's own key (e.g. "budgets"), never a hardcoded
        # "data" - reading the wrong key silently yields zero rows.
        p1 = _build_initial_url(vantage.VANTAGE_ENDPOINTS["budgets"])
        pages = {p1: {"budgets": [{"token": "b1"}], "links": {"next": None}}}
        rows, _ = _collect(_FakeResumableManager(), monkeypatch, pages, endpoint="budgets")
        assert rows == [{"token": "b1"}]

    def test_missing_links_object_terminates(self, monkeypatch: Any) -> None:
        # A last page may omit `links` entirely; the paginator must stop, not KeyError.
        p1 = _build_initial_url(vantage.VANTAGE_ENDPOINTS["cost_reports"])
        pages = {p1: {"cost_reports": [{"token": "a"}]}}
        rows, fetched = _collect(_FakeResumableManager(), monkeypatch, pages)
        assert rows == [{"token": "a"}]
        assert fetched == [p1]


class TestResume:
    def test_starts_from_initial_url_without_state(self, monkeypatch: Any) -> None:
        p1 = _build_initial_url(vantage.VANTAGE_ENDPOINTS["cost_reports"])
        pages = {p1: {"cost_reports": [], "links": {"next": None}}}
        _, fetched = _collect(_FakeResumableManager(), monkeypatch, pages)
        assert fetched == [p1]
        assert "limit=1000" in p1

    def test_resumes_from_saved_url(self, monkeypatch: Any) -> None:
        # Ignoring saved state restarts from page 1 and re-fetches everything already synced.
        resume_url = f"{VANTAGE_BASE_URL}/cost_reports?page=5&limit=1000"
        pages = {resume_url: {"cost_reports": [{"token": "z"}], "links": {"next": None}}}
        manager = _FakeResumableManager(VantageResumeConfig(next_url=resume_url))
        rows, fetched = _collect(manager, monkeypatch, pages)
        assert fetched == [resume_url]
        assert rows == [{"token": "z"}]

    def test_saves_state_after_yield_only_while_pages_remain(self, monkeypatch: Any) -> None:
        # With a tiny chunk size every page emits a batch, so we can observe that resume state is
        # persisted with the *next* page's URL (so a crash re-yields the last page, not skips it)
        # and is never saved on the final page (no `next` to resume from).
        monkeypatch.setattr(
            vantage, "Batcher", lambda **kwargs: Batcher(logger=kwargs["logger"], chunk_size=1, chunk_size_bytes=10**9)
        )
        p1 = _build_initial_url(vantage.VANTAGE_ENDPOINTS["cost_reports"])
        p2 = f"{VANTAGE_BASE_URL}/cost_reports?page=2&limit=1000"
        pages = {
            p1: {"cost_reports": [{"token": "a"}, {"token": "b"}], "links": {"next": p2}},
            p2: {"cost_reports": [{"token": "c"}, {"token": "d"}], "links": {"next": None}},
        }
        manager = _FakeResumableManager()
        _collect(manager, monkeypatch, pages)
        saved_urls = [s.next_url for s in manager.saved]
        assert saved_urls  # state was persisted at least once
        assert all(u == p2 for u in saved_urls)  # only ever the pending page, never the final one


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    def test_status_maps_to_validity(self, _name: str, status: int, expected: bool) -> None:
        response = MagicMock()
        response.status_code = status
        session = MagicMock()
        session.get.return_value = response
        with patch.object(vantage, "make_tracked_session", return_value=session):
            assert validate_credentials("tok") is expected

    def test_network_error_is_invalid(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with patch.object(vantage, "make_tracked_session", return_value=session):
            assert validate_credentials("tok") is False

    def test_probes_cheap_ping_endpoint(self) -> None:
        # Validation must not hit a Cost Report endpoint (5 req/5s cap) - `/ping` is the cheap probe.
        response = MagicMock()
        response.status_code = 200
        session = MagicMock()
        session.get.return_value = response
        with patch.object(vantage, "make_tracked_session", return_value=session):
            validate_credentials("tok")
        assert session.get.call_args[0][0] == f"{VANTAGE_BASE_URL}/ping"


class TestFetchPageRetries:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 502)])
    def test_retryable_status_is_retried(self, _name: str, status: int) -> None:
        retryable = MagicMock()
        retryable.status_code = status
        good = MagicMock()
        good.status_code = 200
        good.ok = True
        good.json.return_value = {"cost_reports": [], "links": {"next": None}}
        session = MagicMock()
        session.get.side_effect = [retryable, good]

        with patch.object(vantage._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = vantage._fetch_page(session, f"{VANTAGE_BASE_URL}/cost_reports", {}, MagicMock())

        assert result == {"cost_reports": [], "links": {"next": None}}
        assert session.get.call_count == 2

    @parameterized.expand(
        [
            ("read_timeout", requests.ReadTimeout("Read timed out.")),
            ("connection_error", requests.ConnectionError("Connection reset by peer")),
            ("chunked", requests.exceptions.ChunkedEncodingError("Connection broken")),
        ]
    )
    def test_transient_network_error_is_retried(self, _name: str, err: Exception) -> None:
        good = MagicMock()
        good.status_code = 200
        good.ok = True
        good.json.return_value = {"cost_reports": []}
        session = MagicMock()
        session.get.side_effect = [err, good]

        with patch.object(vantage._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = vantage._fetch_page(session, f"{VANTAGE_BASE_URL}/cost_reports", {}, MagicMock())

        assert result == {"cost_reports": []}
        assert session.get.call_count == 2

    def test_client_error_is_raised_not_retried(self) -> None:
        # A 4xx (other than 429) is a permanent client error - raise immediately so
        # get_non_retryable_errors can classify it, rather than burning retries.
        response = MagicMock()
        response.status_code = 404
        response.ok = False
        response.raise_for_status.side_effect = requests.HTTPError("404 Client Error", response=response)
        session = MagicMock()
        session.get.return_value = response

        with pytest.raises(requests.HTTPError):
            vantage._fetch_page(session, f"{VANTAGE_BASE_URL}/cost_reports", {}, MagicMock())
        assert session.get.call_count == 1

    @parameterized.expand(
        [
            ("off_host", "https://evil.example.com/v2/cost_reports"),
            ("subdomain_lookalike", "https://api.vantage.sh.evil.example.com/v2/cost_reports"),
            ("plain_http", "http://api.vantage.sh/v2/cost_reports"),
            ("wrong_path_prefix", "https://api.vantage.sh/internal/cost_reports"),
        ]
    )
    def test_untrusted_url_is_refused_without_sending_token(self, _name: str, url: str) -> None:
        # `links.next` is server-controlled; the bearer token must never leave Vantage's own host,
        # so an off-host/non-HTTPS URL is refused before any request (and thus any auth header) goes out.
        session = MagicMock()
        with pytest.raises(vantage.VantageUntrustedURLError):
            vantage._fetch_page(session, url, {"Authorization": "Bearer tok"}, MagicMock())
        session.get.assert_not_called()


class TestSourceResponse:
    @parameterized.expand(
        [
            ("cost_reports", "created_at"),
            ("workspaces", "created_at"),
        ]
    )
    def test_datetime_partitioning_on_created_at(self, endpoint: str, partition_key: str) -> None:
        response = vantage_source("tok", endpoint, MagicMock(), MagicMock())
        assert response.primary_keys == ["token"]
        assert response.sort_mode == "asc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == [partition_key]

    @parameterized.expand([("teams",), ("users",), ("report_notifications",)])
    def test_no_partitioning_when_no_stable_created_at(self, endpoint: str) -> None:
        # These objects carry no creation timestamp; partitioning on a missing field would break sync.
        response = vantage_source("tok", endpoint, MagicMock(), MagicMock())
        assert response.partition_mode is None
        assert response.partition_keys is None
        assert response.primary_keys == ["token"]
