from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.zep import zep
from products.warehouse_sources.backend.temporal.data_imports.sources.zep.settings import ZEP_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.zep.zep import (
    ZEP_BASE_URL,
    ZepResumeConfig,
    _build_url,
    _headers,
    get_rows,
    validate_credentials,
    zep_source,
)


class _FakeResumableManager:
    def __init__(self, state: ZepResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[ZepResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> ZepResumeConfig | None:
        return self._state

    def save_state(self, data: ZepResumeConfig) -> None:
        self.saved.append(data)


def _collect(manager: _FakeResumableManager, monkeypatch: Any, endpoint: str, responses: list[dict]) -> list[dict]:
    """Drive get_rows with a queue of page responses, recording the URLs requested."""
    urls: list[str] = []
    queue = list(responses)

    def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
        urls.append(url)
        return queue.pop(0)

    monkeypatch.setattr(zep, "_fetch_page", fake_fetch)

    rows: list[dict] = []
    for page in get_rows(
        api_key="z_test",
        endpoint=endpoint,
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
    ):
        rows.extend(page)
    manager.urls = urls  # type: ignore[attr-defined]
    return rows


class TestHelpers:
    def test_headers_use_api_key_scheme(self) -> None:
        assert _headers("z_abc") == {"Authorization": "Api-Key z_abc", "Accept": "application/json"}

    def test_build_url_encodes_params(self) -> None:
        url = _build_url("/users-ordered", {"pageSize": 1, "order_by": "created_at"})
        assert url == f"{ZEP_BASE_URL}/users-ordered?pageSize=1&order_by=created_at"

    def test_build_url_no_params(self) -> None:
        assert _build_url("/threads", {}) == f"{ZEP_BASE_URL}/threads"


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("server_error", 500, False)])
    def test_validate_credentials_maps_status(self, _name: str, status_code: int, expected: bool) -> None:
        response = MagicMock(status_code=status_code)
        session = MagicMock()
        session.get.return_value = response
        with patch.object(zep, "make_tracked_session", return_value=session):
            assert validate_credentials("z_test") is expected

    def test_validate_credentials_swallows_network_error(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with patch.object(zep, "make_tracked_session", return_value=session):
            assert validate_credentials("z_test") is False


class TestFetchPage:
    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_retryable_statuses_retry_then_succeed(self, _name: str, status_code: int) -> None:
        bad = MagicMock(status_code=status_code)
        good = MagicMock(status_code=200, ok=True)
        good.json.return_value = {"users": []}
        session = MagicMock()
        session.get.side_effect = [bad, good]

        with patch.object(zep._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = zep._fetch_page(session, f"{ZEP_BASE_URL}/users-ordered", {}, MagicMock())

        assert result == {"users": []}
        assert session.get.call_count == 2

    def test_client_error_raises_immediately(self) -> None:
        response = MagicMock(status_code=401, ok=False, text="unauthorized")
        response.raise_for_status.side_effect = requests.HTTPError("401 Client Error", response=response)
        session = MagicMock()
        session.get.return_value = response

        with pytest.raises(requests.HTTPError):
            zep._fetch_page(session, f"{ZEP_BASE_URL}/users-ordered", {}, MagicMock())
        # A 4xx is a permanent failure: no retry.
        assert session.get.call_count == 1


class TestPageBasedPagination:
    def test_stops_on_short_page_and_injects_nothing(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(ZEP_ENDPOINTS["users"], "page_size", 2)
        manager = _FakeResumableManager()
        rows = _collect(
            manager,
            monkeypatch,
            "users",
            [
                {"users": [{"uuid": "u1"}, {"uuid": "u2"}], "total_count": 3},
                {"users": [{"uuid": "u3"}], "total_count": 3},
            ],
        )
        assert [r["uuid"] for r in rows] == ["u1", "u2", "u3"]
        # First page requested pageNumber=1; state saved pointing at page 2 after yielding page 1.
        assert "pageNumber=1" in manager.urls[0]  # type: ignore[attr-defined]
        assert manager.saved == [ZepResumeConfig(page_number=2)]

    def test_stops_when_total_count_reached(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(ZEP_ENDPOINTS["users"], "page_size", 2)
        manager = _FakeResumableManager()
        rows = _collect(manager, monkeypatch, "users", [{"users": [{"uuid": "u1"}, {"uuid": "u2"}], "total_count": 2}])
        assert [r["uuid"] for r in rows] == ["u1", "u2"]
        # Reached total_count on the first full page, so no further pages and no state saved.
        assert manager.saved == []

    def test_resumes_from_saved_page(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(ZEP_ENDPOINTS["users"], "page_size", 2)
        manager = _FakeResumableManager(ZepResumeConfig(page_number=2))
        rows = _collect(manager, monkeypatch, "users", [{"users": [{"uuid": "u3"}], "total_count": 3}])
        assert [r["uuid"] for r in rows] == ["u3"]
        assert "pageNumber=2" in manager.urls[0]  # type: ignore[attr-defined]

    def test_threads_use_snake_case_page_params(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(ZEP_ENDPOINTS["threads"], "page_size", 2)
        manager = _FakeResumableManager()
        _collect(manager, monkeypatch, "threads", [{"threads": [{"uuid": "t1"}], "total_count": 1}])
        assert "page_number=1" in manager.urls[0]  # type: ignore[attr-defined]
        assert "page_size=2" in manager.urls[0]  # type: ignore[attr-defined]


class TestThreadMessagesFanOut:
    def test_fans_out_over_threads_and_injects_parent_ids(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(ZEP_ENDPOINTS["thread_messages"], "page_size", 2)
        monkeypatch.setattr(zep, "_iter_thread_ids", lambda *a, **k: ["T1", "T2"])
        manager = _FakeResumableManager()
        rows = _collect(
            manager,
            monkeypatch,
            "thread_messages",
            [
                {"messages": [{"uuid": "m1"}], "total_count": 1, "user_id": "U1"},
                {"messages": [{"uuid": "m2"}], "total_count": 1, "user_id": "U2"},
            ],
        )
        assert rows == [
            {"uuid": "m1", "thread_id": "T1", "user_id": "U1"},
            {"uuid": "m2", "thread_id": "T2", "user_id": "U2"},
        ]

    def test_resumes_from_saved_thread(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(ZEP_ENDPOINTS["thread_messages"], "page_size", 2)
        monkeypatch.setattr(zep, "_iter_thread_ids", lambda *a, **k: ["T1", "T2"])
        manager = _FakeResumableManager(ZepResumeConfig(thread_id="T2", cursor=0))
        rows = _collect(
            manager,
            monkeypatch,
            "thread_messages",
            [{"messages": [{"uuid": "m2"}], "total_count": 1, "user_id": "U2"}],
        )
        # T1 is skipped: we resume straight into T2.
        assert [r["uuid"] for r in rows] == ["m2"]
        assert all("/threads/T2/messages" in u for u in manager.urls)  # type: ignore[attr-defined]

    def test_cursor_advances_across_message_pages(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(ZEP_ENDPOINTS["thread_messages"], "page_size", 2)
        monkeypatch.setattr(zep, "_iter_thread_ids", lambda *a, **k: ["T1"])
        manager = _FakeResumableManager()
        rows = _collect(
            manager,
            monkeypatch,
            "thread_messages",
            [
                {"messages": [{"uuid": "m1"}, {"uuid": "m2"}], "total_count": 3, "user_id": "U1"},
                {"messages": [{"uuid": "m3"}], "total_count": 3, "user_id": "U1"},
            ],
        )
        assert [r["uuid"] for r in rows] == ["m1", "m2", "m3"]
        # Second page requested with cursor advanced past the first two messages.
        assert "cursor=2" in manager.urls[1]  # type: ignore[attr-defined]
        assert manager.saved == [ZepResumeConfig(thread_id="T1", cursor=2)]


class TestZepSourceResponse:
    @parameterized.expand(
        [
            ("users", ["uuid"]),
            ("threads", ["uuid"]),
            ("thread_messages", ["uuid"]),
        ]
    )
    def test_source_response_shape(self, endpoint: str, expected_pks: list[str]) -> None:
        response = zep_source("z_test", endpoint, MagicMock(), MagicMock())
        assert response.name == endpoint
        assert response.primary_keys == expected_pks
        assert response.sort_mode == "asc"
        assert response.partition_keys == ["created_at"]
        assert response.partition_mode == "datetime"
