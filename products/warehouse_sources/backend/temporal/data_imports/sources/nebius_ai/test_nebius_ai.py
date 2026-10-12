from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.nebius_ai import nebius_ai
from products.warehouse_sources.backend.temporal.data_imports.sources.nebius_ai.nebius_ai import (
    NEBIUS_AI_BASE_URL,
    NebiusAIResumeConfig,
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

    def safe_point(self) -> None:
        pass


def _collect(
    manager: _FakeResumableManager,
    monkeypatch: Any,
    endpoint: str,
    pages: dict[str, Any],
    staged_at_yield: list[NebiusAIResumeConfig | None] | None = None,
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
        if staged_at_yield is not None:
            staged_at_yield.append(manager.saved[-1] if manager.saved else None)
    return rows


JOBS_URL = f"{NEBIUS_AI_BASE_URL}/fine_tuning/jobs"
EVENTS_PAGES = {
    f"{JOBS_URL}?limit=100": {"data": [{"id": "job-a"}, {"id": "job-b"}], "has_more": True, "last_id": "job-b"},
    f"{JOBS_URL}?limit=100&after=job-b": {"data": [{"id": "job-c"}], "has_more": False},
    f"{JOBS_URL}/job-a/events?limit=100": {"data": [{"id": "ev1", "created_at": 3}], "has_more": True},
    f"{JOBS_URL}/job-a/events?limit=100&after=ev1": {"data": [{"id": "ev2", "created_at": 2}], "has_more": False},
    f"{JOBS_URL}/job-b/events?limit=100": {"data": [], "has_more": False},
    f"{JOBS_URL}/job-c/events?limit=100": {"data": [{"id": "ev1", "created_at": 1}], "has_more": False},
}


class TestPerFineTuningJobEndpoints:
    def test_walks_every_job_page_and_child_page_staging_the_next_position_before_each_yield(
        self, monkeypatch: Any
    ) -> None:
        staged: list[NebiusAIResumeConfig | None] = []
        rows = _collect(_FakeResumableManager(), monkeypatch, "fine_tuning_job_events", EVENTS_PAGES, staged)

        assert [(r["fine_tuning_job_id"], r["id"]) for r in rows] == [
            ("job-a", "ev1"),
            ("job-a", "ev2"),
            ("job-c", "ev1"),
        ]
        assert staged == [
            NebiusAIResumeConfig(job_id="job-a", after="ev1"),
            NebiusAIResumeConfig(job_id="job-b"),
            NebiusAIResumeConfig(jobs_after="job-b"),
        ]

    @parameterized.expand(
        [
            (
                "mid_job_child_page",
                NebiusAIResumeConfig(job_id="job-a", after="ev1"),
                [("job-a", "ev2"), ("job-c", "ev1")],
            ),
            (
                "job_deleted_since_cursor_was_saved",
                NebiusAIResumeConfig(job_id="job-gone", after="ev9"),
                [("job-a", "ev1"), ("job-a", "ev2"), ("job-c", "ev1")],
            ),
            ("later_job_page", NebiusAIResumeConfig(jobs_after="job-b"), [("job-c", "ev1")]),
        ]
    )
    def test_resumes_from_saved_position(
        self, _name: str, state: NebiusAIResumeConfig, expected: list[tuple[str, str]]
    ) -> None:
        with pytest.MonkeyPatch.context() as monkeypatch:
            rows = _collect(_FakeResumableManager(state), monkeypatch, "fine_tuning_job_events", EVENTS_PAGES)
        assert [(r["fine_tuning_job_id"], r["id"]) for r in rows] == expected


OPERATIONS_URL = f"{NEBIUS_AI_BASE_URL}/operations"


class TestOperationsTimeCursor:
    def test_pages_by_created_at_cursor_and_drops_repeated_boundary_rows(self) -> None:
        pages = {
            f"{OPERATIONS_URL}?limit=2": {"data": [{"id": "op3", "created_at": 300}, {"id": "op2", "created_at": 200}]},
            f"{OPERATIONS_URL}?limit=2&cursor_time=1970-01-01T00%3A03%3A20%2B00%3A00": {
                "data": [{"id": "op2", "created_at": 200}, {"id": "op1", "created_at": 100}]
            },
            f"{OPERATIONS_URL}?limit=2&cursor_time=1970-01-01T00%3A01%3A40%2B00%3A00": {
                "data": [{"id": "op1", "created_at": 100}]
            },
        }
        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr(nebius_ai, "PAGE_SIZE", 2)
            rows = _collect(_FakeResumableManager(), monkeypatch, "operations", pages)
        assert [r["id"] for r in rows] == ["op3", "op2", "op1"]

    @parameterized.expand(
        [
            ("same_timestamp_page", [{"id": "op2", "created_at": 200}, {"id": "op1", "created_at": 200}]),
            ("cursor_moves_forward", [{"id": "op4", "created_at": 400}, {"id": "op5", "created_at": 500}]),
        ]
    )
    def test_full_page_whose_cursor_does_not_move_back_fails_the_sync(
        self, _name: str, second_page: list[dict[str, Any]]
    ) -> None:
        pages = {
            f"{OPERATIONS_URL}?limit=2": {"data": [{"id": "op3", "created_at": 300}, {"id": "op2", "created_at": 200}]},
            f"{OPERATIONS_URL}?limit=2&cursor_time=1970-01-01T00%3A03%3A20%2B00%3A00": {"data": second_page},
        }
        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr(nebius_ai, "PAGE_SIZE", 2)
            with pytest.raises(nebius_ai.NebiusAIPaginationError):
                _collect(_FakeResumableManager(), monkeypatch, "operations", pages)


class TestValidateCredentials:
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


class TestCursorPagination:
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
            ("models", "created", ["id"]),
            ("files", "created_at", ["id"]),
            ("batches", "created_at", ["id"]),
            ("fine_tuning_jobs", "created_at", ["id"]),
            ("fine_tuning_job_events", "created_at", ["fine_tuning_job_id", "id"]),
            ("fine_tuning_job_checkpoints", "created_at", ["fine_tuning_job_id", "id"]),
            ("datasets", "created_at", ["id"]),
            ("operations", "created_at", ["id"]),
        ]
    )
    def test_partition_and_pk_per_endpoint(self, endpoint: str, partition_key: str, primary_keys: list[str]) -> None:
        response = nebius_ai_source(
            api_key="nbk_test",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.partition_mode == "datetime"
        assert response.partition_keys == [partition_key]
        # These OpenAI-style list endpoints return newest-first.
        assert response.sort_mode == "desc"
