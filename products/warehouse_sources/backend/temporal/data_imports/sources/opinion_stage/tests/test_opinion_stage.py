from typing import Any

import pytest
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.opinion_stage import opinion_stage
from products.warehouse_sources.backend.temporal.data_imports.sources.opinion_stage.opinion_stage import (
    PAGE_SIZE,
    OpinionStageResumeConfig,
    OpinionStageRetryableError,
    check_access,
    get_rows,
    opinion_stage_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.opinion_stage.settings import (
    ENDPOINTS,
    OPINION_STAGE_ENDPOINTS,
)

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_page_unwrapped = opinion_stage._fetch_page.__wrapped__  # type: ignore[attr-defined]


class _FakeResumableManager:
    def __init__(self, state: OpinionStageResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[OpinionStageResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> OpinionStageResumeConfig | None:
        return self._state

    def save_state(self, data: OpinionStageResumeConfig) -> None:
        self.saved.append(data)


def _page(items: list[dict], next_link: str | None) -> dict[str, Any]:
    # JSON:API collection envelope: rows under `data`, pagination via `links.next`.
    return {"data": items, "meta": {}, "links": {"self": "s", "next": next_link}}


class TestGetRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager, monkeypatch: Any, pages: dict[int, dict], endpoint: str = "items"
    ) -> list[dict]:
        def fake_fetch(session: Any, path: str, page: int, per_page: int, logger: Any) -> dict:
            return pages[page]

        monkeypatch.setattr(opinion_stage, "_fetch_page", fake_fetch)
        monkeypatch.setattr(opinion_stage, "make_tracked_session", lambda **kwargs: MagicMock())

        rows: list[dict] = []
        for batch in get_rows(
            api_key="os-key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            rows.extend(batch)
        return rows

    def test_single_page_yields_items_and_stops(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {1: _page([{"id": "1"}, {"id": "2"}], next_link=None)})
        assert rows == [{"id": "1"}, {"id": "2"}]
        # No next link, so no resume state is persisted.
        assert manager.saved == []

    def test_follows_pagination_until_next_link_is_null(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = {
            1: _page([{"id": "1"}], next_link="p2"),
            2: _page([{"id": "2"}], next_link="p3"),
            3: _page([{"id": "3"}], next_link=None),
        }
        rows = self._collect(manager, monkeypatch, pages)
        assert rows == [{"id": "1"}, {"id": "2"}, {"id": "3"}]

    def test_saves_next_page_after_yielding_each_batch(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = {
            1: _page([{"id": "1"}], next_link="p2"),
            2: _page([{"id": "2"}], next_link=None),
        }
        self._collect(manager, monkeypatch, pages)
        # State is saved AFTER page 1 is yielded (pointing at page 2), and never for the final page.
        assert [s.next_page for s in manager.saved] == [2]

    def test_resumes_from_saved_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(OpinionStageResumeConfig(next_page=2))
        pages = {
            # Page 1 must never be fetched on resume.
            2: _page([{"id": "2"}], next_link="p3"),
            3: _page([{"id": "3"}], next_link=None),
        }
        rows = self._collect(manager, monkeypatch, pages)
        assert rows == [{"id": "2"}, {"id": "3"}]

    def test_empty_data_does_not_yield(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {1: _page([], next_link=None)})
        assert rows == []

    def test_stops_when_page_is_empty_even_with_next_link(self, monkeypatch: Any) -> None:
        # A defensive guard: an empty page terminates the sync even if the API keeps advertising a
        # next link, so we never loop forever on a stale cursor.
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {1: _page([], next_link="p2")})
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
        with pytest.raises(OpinionStageRetryableError):
            _fetch_page_unwrapped(session, "/api/v2/items", 1, PAGE_SIZE, MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(session, "/api/v2/items", 1, PAGE_SIZE, MagicMock())

    def test_success_returns_json_body(self) -> None:
        body = _page([{"id": "1"}], next_link=None)
        session = self._session_returning(200, body)
        result = _fetch_page_unwrapped(session, "/api/v2/items", 1, PAGE_SIZE, MagicMock())
        assert result == body

    def test_missing_data_list_is_retryable(self) -> None:
        # A payload without a top-level `data` list is malformed for JSON:API; treat it as transient
        # rather than silently yielding nothing.
        session = self._session_returning(200, {"errors": [{"detail": "nope"}]})
        with pytest.raises(OpinionStageRetryableError):
            _fetch_page_unwrapped(session, "/api/v2/items", 1, PAGE_SIZE, MagicMock())

    def test_request_uses_json_api_page_params(self) -> None:
        session = self._session_returning(200, _page([], next_link=None))
        _fetch_page_unwrapped(session, "/api/v2/items", 3, PAGE_SIZE, MagicMock())
        _, kwargs = session.get.call_args
        assert kwargs["params"] == {"page[number]": 3, "page[size]": PAGE_SIZE}


class TestHeaders:
    def test_basic_auth_uses_api_key_as_username_with_blank_password(self) -> None:
        headers = opinion_stage._headers("secret-key")
        # HTTP Basic: base64("secret-key:") — the API key is the username, password is blank.
        assert headers["Authorization"] == "Basic c2VjcmV0LWtleTo="
        assert headers["Accept"] == "application/vnd.api+json"


class TestCheckAccess:
    def _patch_session(self, monkeypatch: Any, response: Any) -> MagicMock:
        session = MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        monkeypatch.setattr(opinion_stage, "make_tracked_session", lambda **kwargs: session)
        return session

    @pytest.mark.parametrize(
        "status, ok, expected_status, expected_message",
        [
            (200, True, 200, None),
            (401, False, 401, None),
            (403, False, 403, None),
            (500, False, 500, "Opinion Stage returned HTTP 500"),
        ],
    )
    def test_status_mapping(
        self, status: int, ok: bool, expected_status: int, expected_message: str | None, monkeypatch: Any
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = ok
        self._patch_session(monkeypatch, response)
        assert check_access("os-key") == (expected_status, expected_message)

    def test_connection_error_maps_to_zero(self, monkeypatch: Any) -> None:
        self._patch_session(monkeypatch, requests.ConnectionError("boom"))
        status, message = check_access("os-key")
        assert status == 0
        assert message is not None and "boom" in message


class TestOpinionStageSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = opinion_stage_source(
            api_key="os-key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # JSON:API items carry no guaranteed stable creation timestamp column, so we don't partition.
        assert response.partition_mode is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["id"] for config in OPINION_STAGE_ENDPOINTS.values())
        assert set(OPINION_STAGE_ENDPOINTS) == set(ENDPOINTS)
