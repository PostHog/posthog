from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.mixmax import mixmax
from products.warehouse_sources.backend.temporal.data_imports.sources.mixmax.mixmax import (
    MixmaxResumeConfig,
    _build_url,
    _extract_page,
    get_rows,
    mixmax_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mixmax.settings import MIXMAX_ENDPOINTS


class _FakeResumableManager:
    def __init__(self, state: MixmaxResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[MixmaxResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> MixmaxResumeConfig | None:
        return self._state

    def save_state(self, data: MixmaxResumeConfig) -> None:
        self.saved.append(data)


class TestExtractPage:
    @parameterized.expand(
        [
            # Wrapped collection with more pages: rows plus the next cursor.
            ("wrapped_has_next", {"results": [{"_id": "1"}], "next": "cur2", "hasNext": True}, [{"_id": "1"}], "cur2"),
            # Wrapped collection on its last page: hasNext False means stop, even if `next` echoes a value.
            ("wrapped_last_page", {"results": [{"_id": "1"}], "next": "cur2", "hasNext": False}, [{"_id": "1"}], None),
            # `hasNext` missing is treated as no more pages.
            ("wrapped_no_flag", {"results": [{"_id": "1"}]}, [{"_id": "1"}], None),
            ("wrapped_empty", {"results": [], "hasNext": False}, [], None),
            # `/…/me` single-object endpoints return the object directly — one record, no pagination.
            ("single_object", {"_id": "u1", "email": "a@b.com"}, [{"_id": "u1", "email": "a@b.com"}], None),
            # A bare array (defensive) is treated as a full, unpaginated page.
            ("bare_list", [{"_id": "1"}, {"_id": "2"}], [{"_id": "1"}, {"_id": "2"}], None),
        ]
    )
    def test_extract_page(self, _name: str, data: Any, expected_rows: list[dict], expected_cursor: str | None) -> None:
        assert _extract_page(data) == (expected_rows, expected_cursor)


class TestBuildUrl:
    def test_collection_url_has_page_limit(self) -> None:
        url = _build_url("/sequences", single_object=False)
        assert url == "https://api.mixmax.com/v1/sequences?limit=100"

    def test_collection_url_carries_next_cursor(self) -> None:
        url = _build_url("/sequences", single_object=False, next_cursor="abc123")
        assert url == "https://api.mixmax.com/v1/sequences?limit=100&next=abc123"

    def test_single_object_url_has_no_pagination_params(self) -> None:
        # `/users/me` must not receive limit/next — it isn't a paginated collection.
        url = _build_url("/users/me", single_object=True)
        assert url == "https://api.mixmax.com/v1/users/me"


class TestGetRows:
    @staticmethod
    def _collect(manager: _FakeResumableManager, monkeypatch: Any, pages: dict[str, Any], endpoint: str) -> list[dict]:
        def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> Any:
            return pages[url]

        monkeypatch.setattr(mixmax, "_fetch_page", fake_fetch)

        rows: list[dict] = []
        for batch in get_rows(
            api_key="tok",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            rows.extend(batch)
        return rows

    def test_walks_cursor_pages_and_saves_state_after_each_yield(self, monkeypatch: Any) -> None:
        next_url = "https://api.mixmax.com/v1/sequences?limit=100&next=cur2"
        pages = {
            "https://api.mixmax.com/v1/sequences?limit=100": {
                "results": [{"_id": "1"}],
                "next": "cur2",
                "hasNext": True,
            },
            next_url: {"results": [{"_id": "2"}], "hasNext": False},
        }
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, pages, "sequences")

        assert rows == [{"_id": "1"}, {"_id": "2"}]
        # State is saved only when another page follows, pointing at the next page URL — so a crash
        # re-yields the last page rather than skipping it.
        assert manager.saved == [MixmaxResumeConfig(next_url=next_url)]

    def test_resumes_from_saved_cursor(self, monkeypatch: Any) -> None:
        resume_url = "https://api.mixmax.com/v1/sequences?limit=100&next=cur2"
        pages = {resume_url: {"results": [{"_id": "2"}], "hasNext": False}}
        manager = _FakeResumableManager(MixmaxResumeConfig(next_url=resume_url))
        rows = self._collect(manager, monkeypatch, pages, "sequences")

        # The first page is skipped entirely — only the saved cursor's page is fetched.
        assert rows == [{"_id": "2"}]
        assert manager.saved == []

    def test_single_object_endpoint_yields_once_without_saving_state(self, monkeypatch: Any) -> None:
        pages = {"https://api.mixmax.com/v1/users/me": {"_id": "u1", "email": "a@b.com"}}
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, pages, "users")

        assert rows == [{"_id": "u1", "email": "a@b.com"}]
        assert manager.saved == []


class TestFetchPageRetries:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_status_is_retried_then_succeeds(self, _name: str, status: int) -> None:
        bad = MagicMock()
        bad.status_code = status
        good = MagicMock()
        good.status_code = 200
        good.ok = True
        good.json.return_value = {"results": [], "hasNext": False}

        session = MagicMock()
        session.get.side_effect = [bad, good]

        with patch.object(mixmax._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = mixmax._fetch_page(session, "https://api.mixmax.com/v1/sequences", {}, MagicMock())

        assert result == {"results": [], "hasNext": False}
        assert session.get.call_count == 2

    @parameterized.expand(
        [
            ("read_timeout", requests.ReadTimeout("Read timed out.")),
            ("connection_error", requests.ConnectionError("Connection reset by peer")),
        ]
    )
    def test_transient_network_errors_are_retried(self, _name: str, transient: Exception) -> None:
        good = MagicMock()
        good.status_code = 200
        good.ok = True
        good.json.return_value = {"results": [], "hasNext": False}

        session = MagicMock()
        session.get.side_effect = [transient, good]

        with patch.object(mixmax._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = mixmax._fetch_page(session, "https://api.mixmax.com/v1/sequences", {}, MagicMock())

        assert result == {"results": [], "hasNext": False}
        assert session.get.call_count == 2

    def test_client_error_raises_immediately(self) -> None:
        # A 401 is not retryable — it must surface as an HTTPError so the sync fails fast.
        error_response = requests.Response()
        error_response.status_code = 401
        bad = MagicMock()
        bad.status_code = 401
        bad.ok = False
        bad.raise_for_status.side_effect = requests.HTTPError("401 Client Error", response=error_response)

        session = MagicMock()
        session.get.return_value = bad

        with pytest.raises(requests.HTTPError):
            mixmax._fetch_page(session, "https://api.mixmax.com/v1/sequences", {}, MagicMock())
        assert session.get.call_count == 1


class TestMixmaxSource:
    @parameterized.expand(
        [
            ("sequences", ["_id"]),
            ("messages", ["_id"]),
            ("live_feed", ["uid"]),
            ("appointment_links", ["_id"]),
        ]
    )
    def test_source_response_carries_endpoint_primary_keys(self, endpoint: str, expected_pks: list[str]) -> None:
        response = mixmax_source(
            api_key="tok",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
        )
        assert response.name == endpoint
        assert response.primary_keys == expected_pks
        # Collections arrive newest-first; declared honestly so full-refresh ordering isn't misread.
        assert response.sort_mode == "desc"

    def test_every_endpoint_declares_a_unique_primary_key(self) -> None:
        # A non-unique/empty primary key seeds duplicate rows and makes every merge multi-match (OOM risk).
        for config in MIXMAX_ENDPOINTS.values():
            assert config.primary_keys, f"{config.name} has no primary key"
