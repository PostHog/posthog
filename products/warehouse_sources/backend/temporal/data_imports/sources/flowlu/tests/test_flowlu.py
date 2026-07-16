from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.flowlu import flowlu
from products.warehouse_sources.backend.temporal.data_imports.sources.flowlu.flowlu import (
    FlowluResumeConfig,
    FlowluRetryableError,
    check_access,
    flowlu_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.flowlu.settings import ENDPOINTS, FLOWLU_ENDPOINTS

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_page_unwrapped = flowlu._fetch_page.__wrapped__  # type: ignore[attr-defined]


class _FakeResumableManager:
    def __init__(self, state: FlowluResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[FlowluResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> FlowluResumeConfig | None:
        return self._state

    def save_state(self, data: FlowluResumeConfig) -> None:
        self.saved.append(data)


def _envelope(items: list[dict], total: int | None = None) -> dict[str, Any]:
    return {"response": {"items": items, "total": total if total is not None else len(items), "count": len(items)}}


class TestGetRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager, monkeypatch: Any, pages: dict[int, list[dict]], endpoint: str = "accounts"
    ) -> list[dict]:
        def fake_fetch(session: Any, api_key: str, subdomain: str, path: str, page: int, logger: Any) -> list[dict]:
            return pages[page]

        monkeypatch.setattr(flowlu, "_fetch_page", fake_fetch)
        monkeypatch.setattr(flowlu, "make_tracked_session", lambda **kwargs: MagicMock())

        rows: list[dict] = []
        for batch in get_rows(
            api_key="fl-key",
            subdomain="acme",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            rows.extend(batch)
        return rows

    def test_follows_pagination_until_empty_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = {
            1: [{"id": 1}],
            2: [{"id": 2}],
            3: [],
        }
        rows = self._collect(manager, monkeypatch, pages)
        assert rows == [{"id": 1}, {"id": 2}]

    def test_saves_next_page_after_yielding_each_batch(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = {
            1: [{"id": 1}],
            2: [{"id": 2}],
            3: [],
        }
        self._collect(manager, monkeypatch, pages)
        # State is saved AFTER each non-empty page is yielded, pointing at the next page to fetch.
        assert [s.next_page for s in manager.saved] == [2, 3]

    def test_resumes_from_saved_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(FlowluResumeConfig(next_page=2))
        pages = {
            # Page 1 must never be fetched on resume.
            2: [{"id": 2}],
            3: [],
        }
        rows = self._collect(manager, monkeypatch, pages)
        assert rows == [{"id": 2}]

    def test_empty_first_page_yields_nothing(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {1: []})
        assert rows == []
        assert manager.saved == []


class TestFetchPage:
    def _session_returning(self, status_code: int, body: Any = None) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.json.return_value = body if body is not None else {}
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
        with pytest.raises(FlowluRetryableError):
            _fetch_page_unwrapped(session, "fl-key", "acme", "/crm/account/list", 1, MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(session, "fl-key", "acme", "/crm/account/list", 1, MagicMock())

    def test_client_error_message_omits_api_key_and_keeps_status_prefix(self) -> None:
        # `raise_for_status()` would embed the full request URL (with the `api_key` query param) in the
        # error text, which surfaces in sync error logs; the raised message must drop the query string
        # while keeping the "<status> Client Error: <reason> for url" prefix `get_non_retryable_errors`
        # matches on.
        response = MagicMock()
        response.status_code = 401
        response.ok = False
        response.reason = "Unauthorized"
        response.url = "https://acme.flowlu.com/api/v1/module/crm/account/list?api_key=fl-key&page=1"
        response.json.return_value = {}
        response.text = ""
        session = MagicMock()
        session.get.return_value = response

        with pytest.raises(requests.HTTPError) as exc_info:
            _fetch_page_unwrapped(session, "fl-key", "acme", "/crm/account/list", 1, MagicMock())

        message = str(exc_info.value)
        assert "fl-key" not in message
        assert "api_key" not in message
        assert message.startswith("401 Client Error: Unauthorized for url")

    def test_success_returns_items(self) -> None:
        session = self._session_returning(200, _envelope([{"id": 1}]))
        items = _fetch_page_unwrapped(session, "fl-key", "acme", "/crm/account/list", 1, MagicMock())
        assert items == [{"id": 1}]

    @parameterized.expand(
        [
            ("bare_array", [{"id": 1}]),
            ("missing_response_key", {"data": []}),
            ("non_dict_response", {"response": []}),
            ("missing_items", {"response": {"total": 0}}),
        ]
    )
    def test_malformed_payload_is_retryable(self, _name: str, body: Any) -> None:
        session = self._session_returning(200, body)
        with pytest.raises(FlowluRetryableError):
            _fetch_page_unwrapped(session, "fl-key", "acme", "/crm/account/list", 1, MagicMock())

    def test_request_targets_account_host_with_api_key_param(self) -> None:
        session = self._session_returning(200, _envelope([]))
        _fetch_page_unwrapped(session, "fl-key", "acme", "/task/tasks/list", 3, MagicMock())
        args, kwargs = session.get.call_args
        assert args[0] == "https://acme.flowlu.com/api/v1/module/task/tasks/list"
        assert kwargs["params"] == {"api_key": "fl-key", "page": 3}


class TestCheckAccess:
    def _patch_session(self, response: Any) -> Any:
        session = MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        return patch.object(flowlu, "make_tracked_session", lambda **kwargs: session)

    @parameterized.expand(
        [
            (200, True, 200, None),
            (401, False, 401, None),
            (403, False, 403, None),
            (500, False, 500, "Flowlu returned HTTP 500"),
        ]
    )
    def test_status_mapping(self, status: int, ok: bool, expected_status: int, expected_message: str | None) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = ok
        with self._patch_session(response):
            assert check_access("fl-key", "acme") == (expected_status, expected_message)

    def test_connection_error_maps_to_zero(self) -> None:
        # The message must be a fixed string: `requests` exceptions can embed the prepared URL
        # (carrying the `api_key` query param), so the raw exception text must never be surfaced.
        with self._patch_session(requests.ConnectionError("https://acme.flowlu.com/...?api_key=fl-key")):
            status, message = check_access("fl-key", "acme")
        assert status == 0
        assert message == "Could not connect to Flowlu"

    @parameterized.expand(
        [
            (200, True, None),
            (401, False, "Invalid Flowlu API key"),
            (403, False, "Invalid Flowlu API key"),
            (500, False, "Flowlu returned HTTP 500"),
        ]
    )
    def test_validate_credentials(self, status: int, expected_valid: bool, expected_message: str | None) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = status < 400
        with self._patch_session(response):
            assert validate_credentials("fl-key", "acme") == (expected_valid, expected_message)


class TestFlowluSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = flowlu_source(
            api_key="fl-key",
            subdomain="acme",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # No stable creation timestamp could be verified across every object, so we don't partition.
        assert response.partition_mode is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["id"] for config in FLOWLU_ENDPOINTS.values())
        assert set(FLOWLU_ENDPOINTS) == set(ENDPOINTS)
