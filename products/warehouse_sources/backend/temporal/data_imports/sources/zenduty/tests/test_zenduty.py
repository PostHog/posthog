from typing import Any

import pytest
from unittest import mock
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.zenduty import zenduty
from products.warehouse_sources.backend.temporal.data_imports.sources.zenduty.zenduty import (
    ZendutyResumeConfig,
    ZendutyRetryableError,
    _extract_items_and_next,
    _fetch_page,
    get_rows,
    probe_credentials,
)


class TestExtractItemsAndNext:
    def test_paginated_envelope_returns_results_and_next(self) -> None:
        data = {"count": 2, "next": "https://www.zenduty.com/api/incidents/?page=2", "results": [{"a": 1}, {"a": 2}]}
        rows, next_url = _extract_items_and_next(data)
        assert rows == [{"a": 1}, {"a": 2}]
        assert next_url == "https://www.zenduty.com/api/incidents/?page=2"

    def test_last_page_has_null_next(self) -> None:
        rows, next_url = _extract_items_and_next({"next": None, "results": [{"a": 1}]})
        assert rows == [{"a": 1}]
        assert next_url is None

    def test_bare_list_returns_no_next(self) -> None:
        # Smaller team-nested collections come back as a bare array with no pagination envelope.
        rows, next_url = _extract_items_and_next([{"a": 1}, {"a": 2}])
        assert rows == [{"a": 1}, {"a": 2}]
        assert next_url is None

    @parameterized.expand(
        [
            ("empty_results", {"results": []}, [], None),
            ("null_results", {"results": None}, [], None),
            ("single_object", {"unique_id": "x"}, [{"unique_id": "x"}], None),
            ("unexpected_type", "nope", [], None),
        ]
    )
    def test_edge_shapes(self, _name: str, data: Any, expected_rows: list, expected_next: Any) -> None:
        assert _extract_items_and_next(data) == (expected_rows, expected_next)


class TestFetchPage:
    def _response(self, status_code: int, json_value: Any = None, raises_json: bool = False) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.text = "body"
        if raises_json:
            response.json.side_effect = ValueError("not json")
        else:
            response.json.return_value = json_value
        response.raise_for_status.side_effect = (
            requests.HTTPError(f"{status_code} Client Error") if status_code >= 400 else None
        )
        return response

    def test_success_returns_parsed_json(self) -> None:
        session = MagicMock()
        session.get.return_value = self._response(200, {"results": []})
        assert _fetch_page(session, "https://www.zenduty.com/api/incidents/", {}, MagicMock()) == {"results": []}

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_transient_status_raises_retryable(self, _name: str, status_code: int) -> None:
        session = MagicMock()
        session.get.return_value = self._response(status_code)
        # Retry wrapper re-raises the last error after exhausting attempts.
        with pytest.raises(ZendutyRetryableError):
            _fetch_page(session, "https://www.zenduty.com/api/incidents/", {}, MagicMock())

    def test_non_json_2xx_is_retryable(self) -> None:
        # Zenduty's WAF answered our unauthenticated probe with a non-JSON "Blocked" body (HTTP 209);
        # treat an unparseable 2xx as transient rather than crashing the sync.
        session = MagicMock()
        session.get.return_value = self._response(209, raises_json=True)
        with pytest.raises(ZendutyRetryableError):
            _fetch_page(session, "https://www.zenduty.com/api/incidents/", {}, MagicMock())

    def test_forbidden_raises_http_error(self) -> None:
        session = MagicMock()
        session.get.return_value = self._response(403)
        with pytest.raises(requests.HTTPError):
            _fetch_page(session, "https://www.zenduty.com/api/account/teams/", {}, MagicMock())


class _FakeResumableManager:
    def __init__(self, state: ZendutyResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[ZendutyResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> ZendutyResumeConfig | None:
        return self._state

    def save_state(self, data: ZendutyResumeConfig) -> None:
        self.saved.append(data)


def _collect(manager: _FakeResumableManager, monkeypatch: Any, pages: dict[str, Any], endpoint: str) -> list[dict]:
    def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> Any:
        return pages[url]

    monkeypatch.setattr(zenduty, "_fetch_page", fake_fetch)
    monkeypatch.setattr(zenduty, "make_tracked_session", lambda: MagicMock())

    rows: list[dict] = []
    for page in get_rows(api_key="tok", endpoint=endpoint, logger=MagicMock(), resumable_source_manager=manager):  # type: ignore[arg-type]
        rows.extend(page)
    return rows


class TestGetRowsTopLevel:
    def test_follows_next_across_pages(self, monkeypatch: Any) -> None:
        first = "https://www.zenduty.com/api/incidents/?page_size=100"
        second = "https://www.zenduty.com/api/incidents/?page=2"
        pages = {
            first: {"results": [{"unique_id": "1"}], "next": second},
            second: {"results": [{"unique_id": "2"}], "next": None},
        }
        rows = _collect(_FakeResumableManager(), monkeypatch, pages, "incidents")
        assert rows == [{"unique_id": "1"}, {"unique_id": "2"}]

    def test_saves_state_after_each_page_except_last(self, monkeypatch: Any) -> None:
        first = "https://www.zenduty.com/api/incidents/?page_size=100"
        second = "https://www.zenduty.com/api/incidents/?page=2"
        pages = {
            first: {"results": [{"unique_id": "1"}], "next": second},
            second: {"results": [{"unique_id": "2"}], "next": None},
        }
        manager = _FakeResumableManager()
        _collect(manager, monkeypatch, pages, "incidents")
        assert [(s.next_url, s.team_id) for s in manager.saved] == [(second, None)]

    def test_resumes_from_saved_next_url(self, monkeypatch: Any) -> None:
        resume_url = "https://www.zenduty.com/api/incidents/?page=3"
        pages = {resume_url: {"results": [{"unique_id": "9"}], "next": None}}
        manager = _FakeResumableManager(ZendutyResumeConfig(next_url=resume_url))
        rows = _collect(manager, monkeypatch, pages, "incidents")
        assert rows == [{"unique_id": "9"}]


class TestGetRowsFanOut:
    def _team_pages(self) -> dict[str, Any]:
        teams_url = "https://www.zenduty.com/api/account/teams/?page_size=100"
        return {teams_url: {"results": [{"unique_id": "team-a"}, {"unique_id": "team-b"}], "next": None}}

    def test_walks_each_team_and_injects_parent_id(self, monkeypatch: Any) -> None:
        pages = self._team_pages()
        pages["https://www.zenduty.com/api/account/teams/team-a/services/?page_size=100"] = {
            "results": [{"unique_id": "svc-1"}],
            "next": None,
        }
        pages["https://www.zenduty.com/api/account/teams/team-b/services/?page_size=100"] = {
            "results": [{"unique_id": "svc-2"}],
            "next": None,
        }
        rows = _collect(_FakeResumableManager(), monkeypatch, pages, "services")
        # Each child row carries the parent team's id so the composite key stays unique table-wide.
        assert rows == [
            {"unique_id": "svc-1", "_zenduty_team_id": "team-a"},
            {"unique_id": "svc-2", "_zenduty_team_id": "team-b"},
        ]

    def test_checkpoints_next_team_when_a_team_completes(self, monkeypatch: Any) -> None:
        pages = self._team_pages()
        pages["https://www.zenduty.com/api/account/teams/team-a/services/?page_size=100"] = {
            "results": [{"unique_id": "svc-1"}],
            "next": None,
        }
        pages["https://www.zenduty.com/api/account/teams/team-b/services/?page_size=100"] = {
            "results": [{"unique_id": "svc-2"}],
            "next": None,
        }
        manager = _FakeResumableManager()
        _collect(manager, monkeypatch, pages, "services")
        # After team-a completes, state points at team-b's start so a resume skips team-a entirely.
        assert [(s.next_url, s.team_id) for s in manager.saved] == [(None, "team-b")]

    def test_resume_skips_completed_teams(self, monkeypatch: Any) -> None:
        pages = self._team_pages()
        # Only team-b's collection is provided; if the loop tried team-a it would KeyError.
        pages["https://www.zenduty.com/api/account/teams/team-b/services/?page_size=100"] = {
            "results": [{"unique_id": "svc-2"}],
            "next": None,
        }
        manager = _FakeResumableManager(ZendutyResumeConfig(next_url=None, team_id="team-b"))
        rows = _collect(manager, monkeypatch, pages, "services")
        assert rows == [{"unique_id": "svc-2", "_zenduty_team_id": "team-b"}]

    def test_no_teams_yields_nothing(self, monkeypatch: Any) -> None:
        teams_url = "https://www.zenduty.com/api/account/teams/?page_size=100"
        rows = _collect(_FakeResumableManager(), monkeypatch, {teams_url: {"results": [], "next": None}}, "services")
        assert rows == []


class TestProbeCredentials:
    @parameterized.expand([("ok", 200), ("forbidden_bad_token", 403), ("server_error", 500)])
    def test_returns_status_code(self, _name: str, status_code: int) -> None:
        session = MagicMock()
        session.get.return_value = MagicMock(status_code=status_code)
        with mock.patch.object(zenduty, "make_tracked_session", return_value=session):
            assert probe_credentials("tok") == status_code

    def test_connection_failure_returns_none(self) -> None:
        session = MagicMock()
        session.get.side_effect = Exception("boom")
        with mock.patch.object(zenduty, "make_tracked_session", return_value=session):
            assert probe_credentials("tok") is None
