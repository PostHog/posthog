from typing import Any

import pytest
from unittest import mock
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.teamtailor import teamtailor
from products.warehouse_sources.backend.temporal.data_imports.sources.teamtailor.settings import (
    ENDPOINTS,
    TEAMTAILOR_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.teamtailor.teamtailor import (
    API_VERSION,
    PAGE_SIZE,
    TeamtailorResumeConfig,
    TeamtailorRetryableError,
    check_access,
    get_rows,
    teamtailor_source,
    validate_credentials,
)

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_page_unwrapped = teamtailor._fetch_page.__wrapped__  # type: ignore[attr-defined]


class _FakeResumableManager:
    def __init__(self, state: TeamtailorResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[TeamtailorResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> TeamtailorResumeConfig | None:
        return self._state

    def save_state(self, data: TeamtailorResumeConfig) -> None:
        self.saved.append(data)


def _page(rows: list[dict], next_url: str | None) -> dict:
    return {"data": rows, "links": {"next": next_url} if next_url else {}, "meta": {}}


class TestGetRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager,
        monkeypatch: Any,
        pages: list[dict],
        endpoint: str = "candidates",
    ) -> tuple[list[dict], list[str | None]]:
        calls: list[str | None] = []
        queue = list(pages)

        def fake_fetch(session: Any, url: str, params: Any, logger: Any) -> dict:
            # Record whether the first page (params present) or a followed `next` URL was requested.
            calls.append(None if params is not None else url)
            return queue.pop(0)

        monkeypatch.setattr(teamtailor, "_fetch_page", fake_fetch)
        monkeypatch.setattr(teamtailor, "make_tracked_session", lambda **kwargs: MagicMock())

        rows: list[dict] = []
        for batch in get_rows(
            api_key="tt-key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            rows.extend(batch)
        return rows, calls

    def test_single_page_yields_and_stops(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows, _ = self._collect(manager, monkeypatch, [_page([{"id": "1"}, {"id": "2"}], next_url=None)])
        assert rows == [{"id": "1"}, {"id": "2"}]
        # Only one page, no `next` link, so nothing is persisted.
        assert manager.saved == []

    def test_follows_next_link_until_null(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = [
            _page([{"id": "1"}], next_url="https://api.teamtailor.com/v1/candidates?page%5Bnumber%5D=2"),
            _page([{"id": "2"}], next_url=None),
        ]
        rows, calls = self._collect(manager, monkeypatch, pages)
        assert rows == [{"id": "1"}, {"id": "2"}]
        # First call sends params (first page), the second follows the saved `next` URL verbatim.
        assert calls == [None, "https://api.teamtailor.com/v1/candidates?page%5Bnumber%5D=2"]
        assert [s.next_url for s in manager.saved] == ["https://api.teamtailor.com/v1/candidates?page%5Bnumber%5D=2"]

    def test_resumes_from_saved_cursor(self, monkeypatch: Any) -> None:
        resume_url = "https://api.teamtailor.com/v1/candidates?page%5Bnumber%5D=3"
        manager = _FakeResumableManager(TeamtailorResumeConfig(next_url=resume_url))
        rows, calls = self._collect(manager, monkeypatch, [_page([{"id": "9"}], next_url=None)])
        assert rows == [{"id": "9"}]
        # The first fetch follows the saved cursor, never re-requesting the first page.
        assert calls == [resume_url]

    def test_empty_first_page_yields_nothing(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows, _ = self._collect(manager, monkeypatch, [_page([], next_url=None)])
        assert rows == []
        assert manager.saved == []


class TestFetchPage:
    def _session_returning(self, status_code: int, body: Any = None) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.json.return_value = body if body is not None else {"data": []}
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
        with pytest.raises(TeamtailorRetryableError):
            _fetch_page_unwrapped(session, "https://api.teamtailor.com/v1/candidates", None, MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(session, "https://api.teamtailor.com/v1/candidates", None, MagicMock())

    def test_success_returns_object_body(self) -> None:
        body = {"data": [{"id": "1"}], "links": {}}
        session = self._session_returning(200, body)
        result = _fetch_page_unwrapped(session, "https://api.teamtailor.com/v1/candidates", None, MagicMock())
        assert result == body

    def test_non_object_body_is_retryable(self) -> None:
        session = self._session_returning(200, [{"id": "1"}])
        with pytest.raises(TeamtailorRetryableError):
            _fetch_page_unwrapped(session, "https://api.teamtailor.com/v1/candidates", None, MagicMock())

    def test_first_page_sends_page_size_param(self) -> None:
        session = self._session_returning(200, {"data": []})
        _fetch_page_unwrapped(session, "https://api.teamtailor.com/v1/jobs", {"page[size]": PAGE_SIZE}, MagicMock())
        _, kwargs = session.get.call_args
        assert kwargs["params"] == {"page[size]": PAGE_SIZE}

    def test_next_url_sent_without_params(self) -> None:
        session = self._session_returning(200, {"data": []})
        _fetch_page_unwrapped(session, "https://api.teamtailor.com/v1/jobs?page=2", None, MagicMock())
        _, kwargs = session.get.call_args
        assert kwargs["params"] is None


class TestHeaders:
    def test_headers_carry_token_and_api_version(self) -> None:
        headers = teamtailor._headers("tt-key")
        assert headers["Authorization"] == "Token token=tt-key"
        assert headers["X-Api-Version"] == API_VERSION


class TestCheckAccess:
    def _configure_session(self, mock_make_session: MagicMock, response: Any) -> MagicMock:
        session = MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        mock_make_session.return_value = session
        return session

    @parameterized.expand(
        [
            ("ok", 200, True, 200, None),
            ("unauthorized", 401, False, 401, None),
            ("forbidden", 403, False, 403, None),
            ("server_error", 500, False, 500, "Teamtailor returned HTTP 500"),
        ]
    )
    @mock.patch.object(teamtailor, "make_tracked_session")
    def test_status_mapping(
        self,
        _name: str,
        status: int,
        ok: bool,
        expected_status: int,
        expected_message: str | None,
        mock_make_session: MagicMock,
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = ok
        self._configure_session(mock_make_session, response)
        assert check_access("tt-key") == (expected_status, expected_message)

    @mock.patch.object(teamtailor, "make_tracked_session")
    def test_connection_error_maps_to_zero(self, mock_make_session: MagicMock) -> None:
        self._configure_session(mock_make_session, requests.ConnectionError("boom"))
        status, message = check_access("tt-key")
        assert status == 0
        assert message is not None and "boom" in message

    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid Teamtailor API key"),
            ("forbidden", 403, False, "Invalid Teamtailor API key"),
            ("server_error", 500, False, "Teamtailor returned HTTP 500"),
        ]
    )
    @mock.patch.object(teamtailor, "make_tracked_session")
    def test_validate_credentials(
        self,
        _name: str,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
        mock_make_session: MagicMock,
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = status < 400
        self._configure_session(mock_make_session, response)
        assert validate_credentials("tt-key") == (expected_valid, expected_message)


class TestTeamtailorSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = teamtailor_source(
            api_key="tt-key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.partition_mode is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["id"] for config in TEAMTAILOR_ENDPOINTS.values())
        assert set(TEAMTAILOR_ENDPOINTS) == set(ENDPOINTS)
