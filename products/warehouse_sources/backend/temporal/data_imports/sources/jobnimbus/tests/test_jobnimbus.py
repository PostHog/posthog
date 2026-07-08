from typing import Any

import pytest
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.jobnimbus import jobnimbus
from products.warehouse_sources.backend.temporal.data_imports.sources.jobnimbus.jobnimbus import (
    PAGE_SIZE,
    JobNimbusResumeConfig,
    JobNimbusRetryableError,
    check_access,
    get_rows,
    jobnimbus_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.jobnimbus.settings import (
    ENDPOINTS,
    JOBNIMBUS_ENDPOINTS,
)

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_page_unwrapped = jobnimbus._fetch_page.__wrapped__  # type: ignore[attr-defined]


class _FakeResumableManager:
    def __init__(self, state: JobNimbusResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[JobNimbusResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> JobNimbusResumeConfig | None:
        return self._state

    def save_state(self, data: JobNimbusResumeConfig) -> None:
        self.saved.append(data)


def _full_page(start_id: int) -> list[dict]:
    return [{"jnid": str(start_id + i)} for i in range(PAGE_SIZE)]


class TestGetRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager,
        monkeypatch: Any,
        pages: dict[int, tuple[list[dict], int]],
        endpoint: str = "contacts",
    ) -> list[dict]:
        def fake_fetch(session: Any, path: str, offset: int, limit: int, logger: Any) -> tuple[list[dict], int]:
            return pages[offset]

        monkeypatch.setattr(jobnimbus, "_fetch_page", fake_fetch)
        monkeypatch.setattr(jobnimbus, "make_tracked_session", lambda **kwargs: MagicMock())

        rows: list[dict] = []
        for batch in get_rows(
            api_key="jn-key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            rows.extend(batch)
        return rows

    def test_single_short_page_yields_and_stops(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {0: ([{"jnid": "1"}, {"jnid": "2"}], 2)})
        assert rows == [{"jnid": "1"}, {"jnid": "2"}]
        # The page is short (< PAGE_SIZE), so we stop without persisting resume state.
        assert manager.saved == []

    def test_follows_offset_pagination_until_short_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = {0: (_full_page(0), PAGE_SIZE + 1), PAGE_SIZE: ([{"jnid": "999"}], PAGE_SIZE + 1)}
        rows = self._collect(manager, monkeypatch, pages)
        assert len(rows) == PAGE_SIZE + 1
        # State is saved after the first full page (offset advances to PAGE_SIZE), then we stop.
        assert [s.offset for s in manager.saved] == [PAGE_SIZE]

    def test_stops_when_offset_reaches_reported_count(self, monkeypatch: Any) -> None:
        # A full page whose length exactly equals the reported total must terminate without a
        # second request, even though the page isn't short.
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {0: (_full_page(0), PAGE_SIZE)})
        assert len(rows) == PAGE_SIZE
        assert manager.saved == []

    def test_resumes_from_saved_offset(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(JobNimbusResumeConfig(offset=PAGE_SIZE))
        # Offset 0 must never be fetched on resume.
        pages = {PAGE_SIZE: ([{"jnid": "5"}], PAGE_SIZE + 1)}
        rows = self._collect(manager, monkeypatch, pages)
        assert rows == [{"jnid": "5"}]

    def test_empty_first_page_yields_nothing(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {0: ([], 0)})
        assert rows == []
        assert manager.saved == []


class TestFetchPage:
    def _session_returning(self, status_code: int, body: Any = None) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.json.return_value = body if body is not None else {"count": 0, "results": []}
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
        with pytest.raises(JobNimbusRetryableError):
            _fetch_page_unwrapped(session, "/contacts", 0, PAGE_SIZE, MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(session, "/contacts", 0, PAGE_SIZE, MagicMock())

    def test_success_returns_results_and_count(self) -> None:
        body = {"count": 3, "results": [{"jnid": "1"}]}
        session = self._session_returning(200, body)
        results, count = _fetch_page_unwrapped(session, "/contacts", 0, PAGE_SIZE, MagicMock())
        assert results == [{"jnid": "1"}]
        assert count == 3

    def test_missing_count_falls_back_to_offset_plus_len(self) -> None:
        body = {"results": [{"jnid": "1"}, {"jnid": "2"}]}
        session = self._session_returning(200, body)
        results, count = _fetch_page_unwrapped(session, "/contacts", 50, PAGE_SIZE, MagicMock())
        assert results == body["results"]
        assert count == 52

    @parameterized.expand([("bare_list", [{"jnid": "1"}]), ("results_not_a_list", {"results": "nope"})])
    def test_unexpected_payload_is_retryable(self, _name: str, body: Any) -> None:
        session = self._session_returning(200, body)
        with pytest.raises(JobNimbusRetryableError):
            _fetch_page_unwrapped(session, "/contacts", 0, PAGE_SIZE, MagicMock())

    def test_request_uses_size_and_from_params(self) -> None:
        session = self._session_returning(200, {"count": 0, "results": []})
        _fetch_page_unwrapped(session, "/jobs", 200, PAGE_SIZE, MagicMock())
        _, kwargs = session.get.call_args
        assert kwargs["params"] == {"size": PAGE_SIZE, "from": 200}


class TestCheckAccess:
    def _patch_session(self, monkeypatch: Any, response: Any) -> MagicMock:
        session = MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        monkeypatch.setattr(jobnimbus, "make_tracked_session", lambda **kwargs: session)
        return session

    @pytest.mark.parametrize(
        "status, ok, expected_status, expected_message",
        [
            (200, True, 200, None),
            (401, False, 401, None),
            (403, False, 403, None),
            (500, False, 500, "JobNimbus returned HTTP 500"),
        ],
    )
    def test_status_mapping(
        self, status: int, ok: bool, expected_status: int, expected_message: str | None, monkeypatch: Any
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = ok
        self._patch_session(monkeypatch, response)
        assert check_access("jn-key") == (expected_status, expected_message)

    def test_connection_error_maps_to_zero(self, monkeypatch: Any) -> None:
        self._patch_session(monkeypatch, requests.ConnectionError("boom"))
        status, message = check_access("jn-key")
        assert status == 0
        assert message is not None and "boom" in message

    @pytest.mark.parametrize(
        "status, expected_valid, expected_message",
        [
            (200, True, None),
            (401, False, "Invalid JobNimbus API key"),
            (403, False, "Invalid JobNimbus API key"),
            (500, False, "JobNimbus returned HTTP 500"),
        ],
    )
    def test_validate_credentials(
        self, status: int, expected_valid: bool, expected_message: str | None, monkeypatch: Any
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = status < 400
        self._patch_session(monkeypatch, response)
        assert validate_credentials("jn-key") == (expected_valid, expected_message)


class TestJobNimbusSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = jobnimbus_source(
            api_key="jn-key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == ["jnid"]
        # No stable creation timestamp is guaranteed across every object, so we don't partition.
        assert response.partition_mode is None

    def test_every_endpoint_uses_jnid_primary_key(self) -> None:
        assert all(config.primary_keys == ["jnid"] for config in JOBNIMBUS_ENDPOINTS.values())
        assert set(JOBNIMBUS_ENDPOINTS) == set(ENDPOINTS)
