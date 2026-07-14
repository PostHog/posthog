from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.nebius_ai import nebius_ai
from products.warehouse_sources.backend.temporal.data_imports.sources.nebius_ai.nebius_ai import (
    NEBIUS_AI_BASE_URL,
    NebiusAIResumeConfig,
    _build_url,
    get_rows,
    nebius_ai_source,
    validate_credentials,
)


class _FakeResumableManager:
    def __init__(self, state: NebiusAIResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[NebiusAIResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> NebiusAIResumeConfig | None:
        return self._state

    def save_state(self, data: NebiusAIResumeConfig) -> None:
        self.saved.append(data)


def _collect(
    manager: _FakeResumableManager,
    monkeypatch: Any,
    endpoint: str,
    pages: dict[str, Any],
) -> list[dict]:
    def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
        result = pages[url]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(nebius_ai, "_fetch_page", fake_fetch)

    rows: list[dict] = []
    for batch in get_rows(
        api_key="nbk_test",
        endpoint=endpoint,
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
    ):
        rows.extend(batch)
    return rows


class TestBuildUrl:
    def test_no_params_returns_bare_path(self) -> None:
        assert _build_url("/models", {}) == f"{NEBIUS_AI_BASE_URL}/models"

    def test_params_are_urlencoded(self) -> None:
        # `after` cursors are opaque ids that can contain characters needing encoding.
        assert _build_url("/batches", {"limit": 100, "after": "batch abc"}) == (
            f"{NEBIUS_AI_BASE_URL}/batches?limit=100&after=batch+abc"
        )


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    def test_status_maps_to_bool(self, _name: str, status_code: int, expected: bool) -> None:
        response = MagicMock()
        response.status_code = status_code
        session = MagicMock()
        session.get.return_value = response
        with patch.object(nebius_ai, "make_tracked_session", return_value=session):
            assert validate_credentials("nbk_test") is expected

    def test_network_error_is_false(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with patch.object(nebius_ai, "make_tracked_session", return_value=session):
            assert validate_credentials("nbk_test") is False


class TestNonPaginatedEndpoint:
    def test_models_yields_full_list_in_one_batch(self, monkeypatch: Any) -> None:
        # /models returns the whole list in a single response; it must not be paged with after/limit.
        pages = {
            f"{NEBIUS_AI_BASE_URL}/models": {
                "object": "list",
                "data": [
                    {"id": "meta-llama/Llama-3.3-70B", "created": 1700000000, "owned_by": "nebius"},
                    {"id": "deepseek-ai/DeepSeek-V3", "created": 1710000000, "owned_by": "nebius"},
                ],
            },
        }
        manager = _FakeResumableManager()
        rows = _collect(manager, monkeypatch, "models", pages)
        assert [r["id"] for r in rows] == ["meta-llama/Llama-3.3-70B", "deepseek-ai/DeepSeek-V3"]
        # A single-shot endpoint has nothing to resume from, so it must never persist a cursor.
        assert manager.saved == []

    def test_models_empty_list_yields_nothing(self, monkeypatch: Any) -> None:
        pages = {f"{NEBIUS_AI_BASE_URL}/models": {"object": "list", "data": []}}
        rows = _collect(_FakeResumableManager(), monkeypatch, "models", pages)
        assert rows == []


class TestCursorPagination:
    def test_follows_after_cursor_until_has_more_false(self, monkeypatch: Any) -> None:
        pages = {
            f"{NEBIUS_AI_BASE_URL}/batches?limit=100": {
                "data": [{"id": "b1", "created_at": 1}, {"id": "b2", "created_at": 2}],
                "has_more": True,
                "last_id": "b2",
            },
            f"{NEBIUS_AI_BASE_URL}/batches?limit=100&after=b2": {
                "data": [{"id": "b3", "created_at": 3}],
                "has_more": False,
                "last_id": "b3",
            },
        }
        manager = _FakeResumableManager()
        rows = _collect(manager, monkeypatch, "batches", pages)
        assert [r["id"] for r in rows] == ["b1", "b2", "b3"]
        # State is saved only after a page that has a successor, so exactly one cursor persists here.
        assert manager.saved == [NebiusAIResumeConfig(after="b2")]

    def test_falls_back_to_last_item_id_when_last_id_absent(self, monkeypatch: Any) -> None:
        # Some OpenAI-compatible responses only return has_more; the cursor must come from the row id.
        pages = {
            f"{NEBIUS_AI_BASE_URL}/files?limit=100": {
                "data": [{"id": "f1", "created_at": 1}],
                "has_more": True,
            },
            f"{NEBIUS_AI_BASE_URL}/files?limit=100&after=f1": {
                "data": [{"id": "f2", "created_at": 2}],
                "has_more": False,
            },
        }
        rows = _collect(_FakeResumableManager(), monkeypatch, "files", pages)
        assert [r["id"] for r in rows] == ["f1", "f2"]

    def test_stops_when_has_more_true_but_no_cursor_available(self, monkeypatch: Any) -> None:
        # A malformed page (has_more but no last_id and no row id) must terminate, not loop forever.
        pages = {
            f"{NEBIUS_AI_BASE_URL}/files?limit=100": {
                "data": [{"created_at": 1}],
                "has_more": True,
            },
        }
        rows = _collect(_FakeResumableManager(), monkeypatch, "files", pages)
        assert rows == [{"created_at": 1}]

    def test_resumes_from_saved_cursor(self, monkeypatch: Any) -> None:
        pages = {
            f"{NEBIUS_AI_BASE_URL}/fine_tuning/jobs?limit=100&after=j5": {
                "data": [{"id": "j6", "created_at": 6}],
                "has_more": False,
                "last_id": "j6",
            },
        }
        manager = _FakeResumableManager(NebiusAIResumeConfig(after="j5"))
        rows = _collect(manager, monkeypatch, "fine_tuning_jobs", pages)
        # Resuming must start at the saved cursor, not re-fetch the first page.
        assert [r["id"] for r in rows] == ["j6"]


class TestFetchPage:
    @parameterized.expand([("rate_limited", 429), ("bad_gateway", 502), ("server_error", 500)])
    def test_retryable_statuses_raise_retryable_error(self, _name: str, status_code: int) -> None:
        response = MagicMock()
        response.status_code = status_code
        session = MagicMock()
        session.get.return_value = response
        with patch.object(nebius_ai._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            with pytest.raises(nebius_ai.NebiusAIRetryableError):
                nebius_ai._fetch_page(session, f"{NEBIUS_AI_BASE_URL}/models", {}, MagicMock())
        assert session.get.call_count == 5

    def test_client_error_raises_for_status(self) -> None:
        response = MagicMock()
        response.status_code = 401
        response.ok = False
        response.raise_for_status.side_effect = requests.HTTPError("401")
        session = MagicMock()
        session.get.return_value = response
        with pytest.raises(requests.HTTPError):
            nebius_ai._fetch_page(session, f"{NEBIUS_AI_BASE_URL}/models", {}, MagicMock())

    def test_transient_error_retried_then_succeeds(self) -> None:
        good = MagicMock()
        good.status_code = 200
        good.ok = True
        good.json.return_value = {"data": []}
        session = MagicMock()
        session.get.side_effect = [requests.ReadTimeout("timeout"), good]
        with patch.object(nebius_ai._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = nebius_ai._fetch_page(session, f"{NEBIUS_AI_BASE_URL}/models", {}, MagicMock())
        assert result == {"data": []}
        assert session.get.call_count == 2


class TestSourceResponse:
    @parameterized.expand(
        [
            ("models", "created", False),
            ("files", "created_at", True),
            ("batches", "created_at", True),
            ("fine_tuning_jobs", "created_at", True),
        ]
    )
    def test_partition_and_pk_per_endpoint(self, endpoint: str, partition_key: str, _paginated: bool) -> None:
        response = nebius_ai_source(
            api_key="nbk_test",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == [partition_key]
        # These OpenAI-style list endpoints return newest-first.
        assert response.sort_mode == "desc"
