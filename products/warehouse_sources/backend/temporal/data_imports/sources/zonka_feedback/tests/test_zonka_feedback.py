from typing import Any

import pytest
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.zonka_feedback import zonka_feedback
from products.warehouse_sources.backend.temporal.data_imports.sources.zonka_feedback.settings import (
    ENDPOINTS,
    ZONKA_FEEDBACK_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zonka_feedback.zonka_feedback import (
    ZonkaFeedbackResumeConfig,
    ZonkaFeedbackRetryableError,
    base_url,
    check_access,
    get_rows,
    zonka_feedback_source,
)

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_page_unwrapped = zonka_feedback._fetch_page.__wrapped__  # type: ignore[attr-defined]


class _FakeResumableManager:
    def __init__(self, state: ZonkaFeedbackResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[ZonkaFeedbackResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> ZonkaFeedbackResumeConfig | None:
        return self._state

    def save_state(self, data: ZonkaFeedbackResumeConfig) -> None:
        self.saved.append(data)


def _page(items: list[dict]) -> dict[str, Any]:
    return {"result": items}


class TestGetRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager, monkeypatch: Any, pages: dict[int, dict], endpoint: str = "responses"
    ) -> list[dict]:
        def fake_fetch(session: Any, url: str, page: int, page_size: int, logger: Any) -> dict:
            return pages[page]

        monkeypatch.setattr(zonka_feedback, "_fetch_page", fake_fetch)
        monkeypatch.setattr(zonka_feedback, "make_tracked_session", lambda **kwargs: MagicMock())

        rows: list[dict] = []
        for batch in get_rows(
            auth_token="zonka-token",
            data_center="us1",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            rows.extend(batch)
        return rows

    def test_single_page_then_empty_page_stops(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {1: _page([{"id": 1}, {"id": 2}]), 2: _page([])})
        assert rows == [{"id": 1}, {"id": 2}]
        # State is saved after page 1 (pointing at page 2); the terminating empty page saves nothing.
        assert [s.next_page for s in manager.saved] == [2]

    def test_follows_pagination_until_empty_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = {
            1: _page([{"id": 1}]),
            2: _page([{"id": 2}]),
            3: _page([{"id": 3}]),
            4: _page([]),
        }
        rows = self._collect(manager, monkeypatch, pages)
        assert rows == [{"id": 1}, {"id": 2}, {"id": 3}]

    def test_saves_next_page_after_yielding_each_batch(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = {1: _page([{"id": 1}]), 2: _page([{"id": 2}]), 3: _page([])}
        self._collect(manager, monkeypatch, pages)
        assert [s.next_page for s in manager.saved] == [2, 3]

    def test_resumes_from_saved_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(ZonkaFeedbackResumeConfig(next_page=2))
        pages = {
            # Page 1 must never be fetched on resume.
            2: _page([{"id": 2}]),
            3: _page([]),
        }
        rows = self._collect(manager, monkeypatch, pages)
        assert rows == [{"id": 2}]

    def test_first_page_empty_yields_nothing(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {1: _page([])})
        assert rows == []
        assert manager.saved == []


class TestFetchPage:
    def _session_returning(self, status_code: int, body: dict | None = None) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.json.return_value = body or {}
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
        with pytest.raises(ZonkaFeedbackRetryableError):
            _fetch_page_unwrapped(session, "https://us1.apis.zonkafeedback.com/responses", 1, 100, MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(session, "https://us1.apis.zonkafeedback.com/responses", 1, 100, MagicMock())

    def test_success_returns_json_body(self) -> None:
        body = _page([{"id": 1}])
        session = self._session_returning(200, body)
        result = _fetch_page_unwrapped(session, "https://us1.apis.zonkafeedback.com/responses", 1, 100, MagicMock())
        assert result == body

    def test_request_uses_page_and_page_size_params(self) -> None:
        session = self._session_returning(200, _page([]))
        _fetch_page_unwrapped(session, "https://e.apis.zonkafeedback.com/surveys", 3, 100, MagicMock())
        _, kwargs = session.get.call_args
        assert kwargs["params"] == {"page": 3, "page_size": 100}


class TestBaseUrl:
    @parameterized.expand(
        [
            ("us", "us1", "https://us1.apis.zonkafeedback.com"),
            ("eu", "e", "https://e.apis.zonkafeedback.com"),
            ("in", "in", "https://in.apis.zonkafeedback.com"),
        ]
    )
    def test_base_url_per_data_center(self, _name: str, data_center: str, expected: str) -> None:
        assert base_url(data_center) == expected


class TestCheckAccess:
    def _patch_session(self, monkeypatch: Any, response: Any) -> MagicMock:
        session = MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        monkeypatch.setattr(zonka_feedback, "make_tracked_session", lambda **kwargs: session)
        return session

    @pytest.mark.parametrize(
        "status, ok, expected_status, expected_message",
        [
            (200, True, 200, None),
            (401, False, 401, None),
            (403, False, 403, None),
            (500, False, 500, "Zonka Feedback returned HTTP 500"),
        ],
    )
    def test_status_mapping(
        self, status: int, ok: bool, expected_status: int, expected_message: str | None, monkeypatch: Any
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = ok
        self._patch_session(monkeypatch, response)
        assert check_access("zonka-token", "us1") == (expected_status, expected_message)

    def test_connection_error_maps_to_zero(self, monkeypatch: Any) -> None:
        self._patch_session(monkeypatch, requests.ConnectionError("boom"))
        status, message = check_access("zonka-token", "us1")
        assert status == 0
        assert message is not None and "boom" in message


class TestZonkaFeedbackSourceResponse:
    @parameterized.expand([("responses",), ("surveys",), ("contacts",)])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = zonka_feedback_source(
            auth_token="zonka-token",
            data_center="us1",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # No endpoint exposes a stable creation timestamp we can safely partition on.
        assert response.partition_mode is None
        assert response.partition_keys is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["id"] for config in ZONKA_FEEDBACK_ENDPOINTS.values())
        assert set(ZONKA_FEEDBACK_ENDPOINTS) == set(ENDPOINTS)
