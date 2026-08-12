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
    def test_valid_key_returns_ok(self) -> None:
        response = MagicMock()
        response.ok = True
        session = MagicMock()
        session.get.return_value = response
        with patch.object(nebius_ai, "make_tracked_session", return_value=session):
            assert validate_credentials("nbk_test") == (True, None)

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403)])
    def test_auth_failure_is_rejected_with_message(self, _name: str, status_code: int) -> None:
        response = MagicMock()
        response.ok = False
        response.status_code = status_code
        session = MagicMock()
        session.get.return_value = response
        with patch.object(nebius_ai, "make_tracked_session", return_value=session):
            ok, message = validate_credentials("nbk_test")
        assert ok is False
        assert message

    @parameterized.expand([("network_error", None), ("server_error", 503), ("rate_limited", 429)])
    def test_transient_failure_is_not_reported_as_invalid_key(self, _name: str, status_code: int | None) -> None:
        # A blip must never be surfaced as an invalid key — that would send the user to rotate a good one.
        session = MagicMock()
        if status_code is None:
            session.get.side_effect = requests.ConnectionError("boom")
        else:
            response = MagicMock()
            response.ok = False
            response.status_code = status_code
            session.get.return_value = response
        with patch.object(nebius_ai, "make_tracked_session", return_value=session):
            ok, message = validate_credentials("nbk_test")
        assert ok is False
        assert message is not None
        assert "invalid" not in message.lower()

    def test_probe_redacts_key_and_disables_redirects(self) -> None:
        # The key must stay out of captured samples, and a 30x must not replay the bearer token.
        session = MagicMock()
        session.get.return_value = MagicMock(ok=True)
        with patch.object(nebius_ai, "make_tracked_session", return_value=session) as make_session:
            validate_credentials("nbk_secret")
        make_session.assert_called_once_with(redact_values=("nbk_secret",), allow_redirects=False)


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

    def test_missing_primary_key_on_paginated_page_fails_loudly(self, monkeypatch: Any) -> None:
        # A page that claims has_more but whose final row is missing its `id` must raise, not silently
        # drop every later page by treating the malformed page as terminal.
        pages = {
            f"{NEBIUS_AI_BASE_URL}/files?limit=100": {
                "data": [{"created_at": 1}],
                "has_more": True,
            },
        }
        with pytest.raises(KeyError):
            _collect(_FakeResumableManager(), monkeypatch, "files", pages)

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


class TestSessionHardening:
    def test_get_rows_session_redacts_key_and_disables_redirects(self, monkeypatch: Any) -> None:
        # The long-lived paging session must mask the key and refuse redirects so a 30x can't replay
        # the bearer token to another origin.
        monkeypatch.setattr(nebius_ai, "_fetch_page", lambda *_a, **_k: {"data": []})
        make_session = MagicMock(return_value=MagicMock())
        monkeypatch.setattr(nebius_ai, "make_tracked_session", make_session)
        list(
            get_rows(
                api_key="nbk_secret",
                endpoint="models",
                logger=MagicMock(),
                resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
            )
        )
        make_session.assert_called_once_with(redact_values=("nbk_secret",), allow_redirects=False)


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
        response.raise_for_status.side_effect = requests.HTTPError("401", response=response)
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
