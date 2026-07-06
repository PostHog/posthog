from typing import Any

import pytest
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.planhat import planhat
from products.warehouse_sources.backend.temporal.data_imports.sources.planhat.planhat import (
    PAGE_SIZE,
    PlanhatResumeConfig,
    PlanhatRetryableError,
    check_access,
    get_rows,
    planhat_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.planhat.settings import (
    ENDPOINTS,
    PLANHAT_ENDPOINTS,
)

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_page_unwrapped = planhat._fetch_page.__wrapped__  # type: ignore[attr-defined]


class _FakeResumableManager:
    def __init__(self, state: PlanhatResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[PlanhatResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> PlanhatResumeConfig | None:
        return self._state

    def save_state(self, data: PlanhatResumeConfig) -> None:
        self.saved.append(data)


def _full_page(start_id: int) -> list[dict]:
    return [{"_id": str(start_id + i)} for i in range(PAGE_SIZE)]


class TestGetRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager, monkeypatch: Any, pages: dict[int, list[dict]], endpoint: str = "companies"
    ) -> list[dict]:
        def fake_fetch(session: Any, path: str, offset: int, limit: int, logger: Any) -> list[dict]:
            return pages[offset]

        monkeypatch.setattr(planhat, "_fetch_page", fake_fetch)
        monkeypatch.setattr(planhat, "make_tracked_session", lambda **kwargs: MagicMock())

        rows: list[dict] = []
        for batch in get_rows(
            api_token="ph-token",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            rows.extend(batch)
        return rows

    def test_single_short_page_yields_and_stops(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {0: [{"_id": "1"}, {"_id": "2"}]})
        assert rows == [{"_id": "1"}, {"_id": "2"}]
        # The page is short (< PAGE_SIZE), so we stop without persisting resume state.
        assert manager.saved == []

    def test_follows_offset_pagination_until_short_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = {0: _full_page(0), PAGE_SIZE: [{"_id": "999"}]}
        rows = self._collect(manager, monkeypatch, pages)
        assert len(rows) == PAGE_SIZE + 1
        # State is saved after the first full page (offset advances to PAGE_SIZE), then we stop.
        assert [s.offset for s in manager.saved] == [PAGE_SIZE]

    def test_resumes_from_saved_offset(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(PlanhatResumeConfig(offset=PAGE_SIZE))
        # Offset 0 must never be fetched on resume.
        pages = {PAGE_SIZE: [{"_id": "5"}]}
        rows = self._collect(manager, monkeypatch, pages)
        assert rows == [{"_id": "5"}]

    def test_empty_first_page_yields_nothing(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {0: []})
        assert rows == []
        assert manager.saved == []


class TestFetchPage:
    def _session_returning(self, status_code: int, body: Any = None) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.json.return_value = body if body is not None else []
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
        with pytest.raises(PlanhatRetryableError):
            _fetch_page_unwrapped(session, "/companies", 0, PAGE_SIZE, MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(session, "/companies", 0, PAGE_SIZE, MagicMock())

    def test_success_returns_list_body(self) -> None:
        body = [{"_id": "1"}]
        session = self._session_returning(200, body)
        result = _fetch_page_unwrapped(session, "/companies", 0, PAGE_SIZE, MagicMock())
        assert result == body

    def test_non_list_body_is_retryable(self) -> None:
        session = self._session_returning(200, {"error": "nope"})
        with pytest.raises(PlanhatRetryableError):
            _fetch_page_unwrapped(session, "/companies", 0, PAGE_SIZE, MagicMock())

    def test_request_uses_limit_and_offset_params(self) -> None:
        session = self._session_returning(200, [])
        _fetch_page_unwrapped(session, "/endusers", 200, PAGE_SIZE, MagicMock())
        _, kwargs = session.get.call_args
        assert kwargs["params"] == {"limit": PAGE_SIZE, "offset": 200}


class TestCheckAccess:
    def _patch_session(self, monkeypatch: Any, response: Any) -> MagicMock:
        session = MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        monkeypatch.setattr(planhat, "make_tracked_session", lambda **kwargs: session)
        return session

    @pytest.mark.parametrize(
        "status, ok, expected_status, expected_message",
        [
            (200, True, 200, None),
            (401, False, 401, None),
            (403, False, 403, None),
            (500, False, 500, "Planhat returned HTTP 500"),
        ],
    )
    def test_status_mapping(
        self, status: int, ok: bool, expected_status: int, expected_message: str | None, monkeypatch: Any
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = ok
        self._patch_session(monkeypatch, response)
        assert check_access("ph-token") == (expected_status, expected_message)

    def test_probe_uses_limit_one(self, monkeypatch: Any) -> None:
        response = MagicMock()
        response.status_code = 200
        response.ok = True
        session = self._patch_session(monkeypatch, response)
        check_access("ph-token")
        _, kwargs = session.get.call_args
        assert kwargs["params"] == {"limit": 1, "offset": 0}

    def test_connection_error_maps_to_zero(self, monkeypatch: Any) -> None:
        self._patch_session(monkeypatch, requests.ConnectionError("boom"))
        status, message = check_access("ph-token")
        assert status == 0
        assert message is not None and "boom" in message

    @pytest.mark.parametrize(
        "status, expected_valid, expected_message",
        [
            (200, True, None),
            (401, False, "Invalid Planhat API token"),
            (403, False, "Invalid Planhat API token"),
            (500, False, "Planhat returned HTTP 500"),
        ],
    )
    def test_validate_credentials(
        self, status: int, expected_valid: bool, expected_message: str | None, monkeypatch: Any
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = status < 400
        self._patch_session(monkeypatch, response)
        assert validate_credentials("ph-token") == (expected_valid, expected_message)


class TestPlanhatSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = planhat_source(
            api_token="ph-token",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == ["_id"]
        # No stable creation timestamp is guaranteed across every object, so we don't partition.
        assert response.partition_mode is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["_id"] for config in PLANHAT_ENDPOINTS.values())
        assert set(PLANHAT_ENDPOINTS) == set(ENDPOINTS)
