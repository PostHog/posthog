from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.hellobaton import hellobaton
from products.warehouse_sources.backend.temporal.data_imports.sources.hellobaton.hellobaton import (
    PER_PAGE,
    HellobatonResumeConfig,
    _build_url,
    _fetch_page,
    get_rows,
    normalize_company,
)


class TestNormalizeCompany:
    @parameterized.expand(
        [
            ("bare", "acme", "acme"),
            ("full_host", "acme.hellobaton.com", "acme"),
            ("https_url", "https://acme.hellobaton.com", "acme"),
            ("trailing_slash", "acme.hellobaton.com/", "acme"),
            ("with_hyphen", "acme-corp", "acme-corp"),
            ("whitespace", "  acme  ", "acme"),
        ]
    )
    def test_valid_companies(self, _name: str, value: str, expected: str) -> None:
        assert normalize_company(value) == expected

    @parameterized.expand(
        [
            ("path_injection", "acme/../evil"),
            ("host_injection", "acme.evil.com"),
            ("userinfo_injection", "acme@evil.com"),
            ("empty", ""),
            ("space_inside", "ac me"),
            ("trailing_hyphen", "acme-"),
        ]
    )
    def test_invalid_companies_raise(self, _name: str, value: str) -> None:
        with pytest.raises(ValueError):
            normalize_company(value)


class TestBuildUrl:
    def test_no_params(self) -> None:
        assert (
            _build_url("https://acme.hellobaton.com/api", "/projects/", {})
            == "https://acme.hellobaton.com/api/projects/"
        )

    def test_encodes_params(self) -> None:
        url = _build_url("https://acme.hellobaton.com/api", "/projects/", {"api_key": "k", "page": 2})
        assert url == "https://acme.hellobaton.com/api/projects/?api_key=k&page=2"


class _FakeResumableManager:
    def __init__(self, state: HellobatonResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[HellobatonResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> HellobatonResumeConfig | None:
        return self._state

    def save_state(self, data: HellobatonResumeConfig) -> None:
        self.saved.append(data)


class _FakeBatcher:
    """Yields one batch per item so save-after-yield behavior is observable without 2000+ rows."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._rows: list[dict] = []

    def batch(self, row: dict) -> None:
        self._rows.append(row)

    def should_yield(self, include_incomplete_chunk: bool = False) -> bool:
        return len(self._rows) > 0

    def get_table(self) -> list[dict]:
        rows = self._rows
        self._rows = []
        return rows


def _patch_fetch(monkeypatch: Any, pages: dict[str, Any]) -> list[str]:
    fetched: list[str] = []

    def fake_fetch(session: Any, url: str, logger: Any) -> dict:
        fetched.append(url)
        return pages[url]

    monkeypatch.setattr(hellobaton, "_fetch_page", fake_fetch)
    return fetched


def _collect(monkeypatch: Any, manager: _FakeResumableManager, **kwargs: Any) -> list[dict]:
    monkeypatch.setattr(hellobaton, "Batcher", _FakeBatcher)
    rows: list[dict] = []
    for batch in get_rows(
        company="acme",
        api_key="key",
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
        **kwargs,
    ):
        rows.extend(batch)
    return rows


class TestGetRows:
    def test_paginates_until_next_is_absent(self, monkeypatch: Any) -> None:
        pages = {
            f"https://acme.hellobaton.com/api/projects/?api_key=key&page_size={PER_PAGE}&page=1": {
                "results": [{"id": 1}, {"id": 2}],
                "next": "https://acme.hellobaton.com/api/projects/?page=2",
            },
            f"https://acme.hellobaton.com/api/projects/?api_key=key&page_size={PER_PAGE}&page=2": {
                "results": [{"id": 3}],
                "next": None,
            },
        }
        fetched = _patch_fetch(monkeypatch, pages)
        rows = _collect(monkeypatch, _FakeResumableManager(), endpoint="projects")

        assert [r["id"] for r in rows] == [1, 2, 3]
        assert fetched == list(pages)

    def test_sends_api_key_and_page_size_on_every_page(self, monkeypatch: Any) -> None:
        pages = {
            f"https://acme.hellobaton.com/api/projects/?api_key=key&page_size={PER_PAGE}&page=1": {
                "results": [{"id": 1}],
                "next": "https://acme.hellobaton.com/api/projects/?page=2",
            },
            f"https://acme.hellobaton.com/api/projects/?api_key=key&page_size={PER_PAGE}&page=2": {
                "results": [{"id": 2}],
                "next": None,
            },
        }
        fetched = _patch_fetch(monkeypatch, pages)
        _collect(monkeypatch, _FakeResumableManager(), endpoint="projects")

        # Baton re-requires the api_key query param on paginated requests, not just the first page.
        assert all("api_key=key" in url for url in fetched)

    def test_saves_resume_state_after_each_yielded_page(self, monkeypatch: Any) -> None:
        pages = {
            f"https://acme.hellobaton.com/api/projects/?api_key=key&page_size={PER_PAGE}&page=1": {
                "results": [{"id": 1}],
                "next": "https://acme.hellobaton.com/api/projects/?page=2",
            },
            f"https://acme.hellobaton.com/api/projects/?api_key=key&page_size={PER_PAGE}&page=2": {
                "results": [{"id": 2}],
                "next": None,
            },
        }
        _patch_fetch(monkeypatch, pages)
        manager = _FakeResumableManager()
        _collect(monkeypatch, manager, endpoint="projects")

        # State is saved only while more pages remain (page 1 -> next_page 2), never on the last page.
        assert manager.saved == [HellobatonResumeConfig(next_page=2)]

    def test_resumes_from_saved_page(self, monkeypatch: Any) -> None:
        pages = {
            f"https://acme.hellobaton.com/api/tasks/?api_key=key&page_size={PER_PAGE}&page=2": {
                "results": [{"id": 2}],
                "next": None,
            },
        }
        fetched = _patch_fetch(monkeypatch, pages)
        rows = _collect(monkeypatch, _FakeResumableManager(HellobatonResumeConfig(next_page=2)), endpoint="tasks")

        assert [r["id"] for r in rows] == [2]
        assert fetched == [f"https://acme.hellobaton.com/api/tasks/?api_key=key&page_size={PER_PAGE}&page=2"]

    def test_stops_on_empty_results(self, monkeypatch: Any) -> None:
        pages: dict[str, Any] = {
            f"https://acme.hellobaton.com/api/companies/?api_key=key&page_size={PER_PAGE}&page=1": {
                "results": [],
                "next": None,
            },
        }
        _patch_fetch(monkeypatch, pages)
        rows = _collect(monkeypatch, _FakeResumableManager(), endpoint="companies")

        assert rows == []


class TestFetchPage:
    @parameterized.expand([("rate_limited", 429), ("bad_gateway", 502), ("server_error", 500)])
    def test_retryable_status_is_retried(self, _name: str, status_code: int) -> None:
        # 429 and 5xx are transient (rate limit / server blip); the page must retry, then succeed.
        bad = MagicMock()
        bad.status_code = status_code
        good = MagicMock()
        good.status_code = 200
        good.ok = True
        good.json.return_value = {"results": [], "next": None}

        session = MagicMock()
        session.get.side_effect = [bad, good]

        with patch.object(_fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = _fetch_page(session, "https://acme.hellobaton.com/api/projects/", MagicMock())

        assert result == {"results": [], "next": None}
        assert session.get.call_count == 2

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_without_retry(self, _name: str, status_code: int) -> None:
        # A 4xx (bad key, missing scope, deleted resource) can never be fixed by retrying.
        response = requests.Response()
        response.status_code = status_code

        session = MagicMock()
        session.get.return_value = response

        with pytest.raises(requests.HTTPError):
            _fetch_page(session, "https://acme.hellobaton.com/api/projects/", MagicMock())

    def test_raised_error_scrubs_api_key_but_keeps_status_text(self) -> None:
        # The api_key rides in the query string, so a failing request must not leak it into the
        # raised HTTPError, while still exposing the status text get_non_retryable_errors matches on.
        response = requests.Response()
        response.status_code = 401
        response.reason = "Unauthorized"
        response.url = "https://acme.hellobaton.com/api/projects/?api_key=supersecret&page=1"

        session = MagicMock()
        session.get.return_value = response

        with pytest.raises(requests.HTTPError) as exc_info:
            _fetch_page(session, response.url, MagicMock())

        message = str(exc_info.value)
        assert "supersecret" not in message
        assert "api_key" not in message
        assert "401 Client Error: Unauthorized" in message

        assert session.get.call_count == 1
