from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.scale_ai import scale_ai
from products.warehouse_sources.backend.temporal.data_imports.sources.scale_ai.scale_ai import (
    ScaleAIResumeConfig,
    _build_params,
    _extract_docs,
    _format_incremental_value,
    get_rows,
    scale_ai_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.scale_ai.settings import SCALE_AI_ENDPOINTS


class _FakeResumableManager:
    def __init__(self, state: ScaleAIResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[ScaleAIResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> ScaleAIResumeConfig | None:
        return self._state

    def save_state(self, data: ScaleAIResumeConfig) -> None:
        self.saved.append(data)


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14+00:00"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14+00:00"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00+00:00"),
            ("string_passthrough", "cursor", "cursor"),
        ]
    )
    def test_format_incremental_value(self, _name: str, value: object, expected: str) -> None:
        assert _format_incremental_value(value) == expected


class TestBuildParams:
    @parameterized.expand(
        [
            # The chosen incremental field maps to a specific server-side param; the wrong param would
            # silently ignore the cutoff and re-scan the full history every run.
            ("tasks_updated_at", "tasks", "updated_at", "updated_after"),
            ("tasks_created_at", "tasks", "created_at", "start_time"),
            ("batches_created_at", "batches", "created_at", "start_time"),
        ]
    )
    def test_incremental_field_maps_to_server_param(
        self, _name: str, endpoint: str, incremental_field: str, expected_param: str
    ) -> None:
        params = _build_params(
            SCALE_AI_ENDPOINTS[endpoint],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
            incremental_field=incremental_field,
        )
        assert params[expected_param] == "2026-03-04T00:00:00+00:00"

    def test_no_incremental_param_when_disabled(self) -> None:
        params = _build_params(
            SCALE_AI_ENDPOINTS["tasks"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
            incremental_field="updated_at",
        )
        assert "updated_after" not in params
        assert "start_time" not in params
        assert params["limit"] == 100

    def test_projects_has_no_limit_param(self) -> None:
        # Projects is a single non-paginated list; sending limit/offset would be meaningless.
        params = _build_params(
            SCALE_AI_ENDPOINTS["projects"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
        )
        assert params == {}


class TestExtractDocs:
    @parameterized.expand(
        [
            ("docs_envelope", {"docs": [{"a": 1}], "has_more": False}, [{"a": 1}]),
            ("bare_list", [{"a": 1}, {"a": 2}], [{"a": 1}, {"a": 2}]),
            ("empty_docs", {"docs": [], "total": 0}, []),
            ("unknown_shape", {"unexpected": 1}, []),
        ]
    )
    def test_extract_docs(self, _name: str, data: Any, expected: list[dict]) -> None:
        assert _extract_docs(data) == expected


def _collect(
    manager: _FakeResumableManager, monkeypatch: Any, endpoint: str, pages: dict[Any, Any], **kw: Any
) -> list[dict]:
    """Drive get_rows with a per-request fake fetch keyed by (next_token/offset).

    Forces a chunk size of 1 so every row triggers a yield + state save, exercising the resume
    checkpoint path that the production 2000-row chunk would hide in a small test.
    """
    calls: list[dict] = []

    def fake_fetch(session: Any, url: str, params: dict, logger: Any) -> dict:
        calls.append(dict(params))
        key = params.get("next_token", params.get("offset", "__first__"))
        return pages[key]

    monkeypatch.setattr(scale_ai, "_fetch_page", fake_fetch)
    monkeypatch.setattr(
        scale_ai,
        "Batcher",
        lambda **kwargs: Batcher(logger=kwargs["logger"], chunk_size=1, chunk_size_bytes=kwargs["chunk_size_bytes"]),
    )

    rows: list[dict] = []
    for table in get_rows(
        api_key="live_key",
        endpoint=endpoint,
        logger=MagicMock(),
        resumable_source_manager=cast(ResumableSourceManager[ScaleAIResumeConfig], manager),
        **kw,
    ):
        rows.extend(table.to_pylist())
    manager.last_fetch_params = calls  # type: ignore[attr-defined]
    return rows


class TestCursorPagination:
    def test_follows_next_token_until_exhausted(self, monkeypatch: Any) -> None:
        pages = {
            "__first__": {"docs": [{"task_id": "T1"}], "next_token": "tok2"},
            "tok2": {"docs": [{"task_id": "T2"}], "next_token": "tok3"},
            "tok3": {"docs": [{"task_id": "T3"}], "next_token": None},
        }
        manager = _FakeResumableManager()
        rows = _collect(manager, monkeypatch, "tasks", pages)
        assert [r["task_id"] for r in rows] == ["T1", "T2", "T3"]

    def test_checkpoints_current_page_token_after_each_batch(self, monkeypatch: Any) -> None:
        # Resume must re-fetch the page we were on (merge dedupes), not skip to the next one.
        pages = {
            "__first__": {"docs": [{"task_id": "T1"}], "next_token": "tok2"},
            "tok2": {"docs": [{"task_id": "T2"}], "next_token": None},
        }
        manager = _FakeResumableManager()
        _collect(manager, monkeypatch, "tasks", pages)
        # First page's row checkpoints token=None (re-fetch first page); second page checkpoints tok2.
        assert [s.next_token for s in manager.saved] == [None, "tok2"]

    def test_resumes_from_saved_token(self, monkeypatch: Any) -> None:
        pages = {
            "tok2": {"docs": [{"task_id": "T2"}], "next_token": None},
        }
        manager = _FakeResumableManager(ScaleAIResumeConfig(next_token="tok2"))
        rows = _collect(manager, monkeypatch, "tasks", pages)
        # T1 (first page) is skipped because we resume mid-stream from tok2.
        assert [r["task_id"] for r in rows] == ["T2"]

    def test_incremental_cutoff_sent_on_first_request(self, monkeypatch: Any) -> None:
        pages = {"__first__": {"docs": [{"task_id": "T1"}], "next_token": None}}
        manager = _FakeResumableManager()
        _collect(
            manager,
            monkeypatch,
            "tasks",
            pages,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
            incremental_field="updated_at",
        )
        assert manager.last_fetch_params[0]["updated_after"] == "2026-03-04T00:00:00+00:00"  # type: ignore[attr-defined]


class TestOffsetPagination:
    def test_walks_offsets_until_short_page(self, monkeypatch: Any) -> None:
        # batches page_size is 100; a page shorter than that ends pagination.
        full_page = [{"name": f"B{i}"} for i in range(100)]
        pages = {
            "__first__": {"docs": full_page},
            0: {"docs": full_page},
            100: {"docs": [{"name": "B100"}]},
        }
        manager = _FakeResumableManager()
        rows = _collect(manager, monkeypatch, "batches", pages)
        assert len(rows) == 101
        assert rows[-1]["name"] == "B100"

    def test_stops_on_first_short_page(self, monkeypatch: Any) -> None:
        pages = {"__first__": {"docs": [{"name": "B1"}, {"name": "B2"}]}, 0: {"docs": [{"name": "B1"}, {"name": "B2"}]}}
        manager = _FakeResumableManager()
        rows = _collect(manager, monkeypatch, "batches", pages)
        assert [r["name"] for r in rows] == ["B1", "B2"]

    def test_resumes_from_saved_offset(self, monkeypatch: Any) -> None:
        pages = {100: {"docs": [{"name": "B100"}]}}
        manager = _FakeResumableManager(ScaleAIResumeConfig(offset=100))
        rows = _collect(manager, monkeypatch, "batches", pages)
        assert [r["name"] for r in rows] == ["B100"]


class TestSingleFetch:
    def test_projects_fetches_once(self, monkeypatch: Any) -> None:
        pages = {"__first__": {"docs": [{"name": "P1"}, {"name": "P2"}]}}
        manager = _FakeResumableManager()
        rows = _collect(manager, monkeypatch, "projects", pages)
        assert [r["name"] for r in rows] == ["P1", "P2"]
        assert len(manager.last_fetch_params) == 1  # type: ignore[attr-defined]


class TestFetchPageRetries:
    @parameterized.expand(
        [
            ("retryable_500", 500, True),
            ("retryable_429", 429, True),
            ("fatal_401", 401, False),
            ("fatal_403", 403, False),
        ]
    )
    def test_status_handling(self, _name: str, status_code: int, retryable: bool) -> None:
        session = MagicMock()
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.json.return_value = {"docs": []}
        response.raise_for_status.side_effect = requests.HTTPError(f"{status_code} error", response=response)
        session.get.return_value = response

        with patch.object(scale_ai._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            if retryable:
                # Both retryable statuses raise ScaleAIRetryableError and exhaust the 5 attempts.
                with pytest.raises(scale_ai.ScaleAIRetryableError):
                    scale_ai._fetch_page(session, "https://api.scale.com/v1/tasks", {}, MagicMock())
                assert session.get.call_count == 5
            else:
                with pytest.raises(requests.HTTPError):
                    scale_ai._fetch_page(session, "https://api.scale.com/v1/tasks", {}, MagicMock())
                assert session.get.call_count == 1

    def test_transient_error_retried_then_succeeds(self) -> None:
        good = MagicMock()
        good.status_code = 200
        good.ok = True
        good.json.return_value = {"docs": []}
        session = MagicMock()
        session.get.side_effect = [requests.ReadTimeout("timed out"), good]

        with patch.object(scale_ai._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = scale_ai._fetch_page(session, "https://api.scale.com/v1/tasks", {}, MagicMock())

        assert result == {"docs": []}
        assert session.get.call_count == 2


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    def test_status_maps_to_validity(self, _name: str, status_code: int, expected: bool) -> None:
        response = MagicMock(status_code=status_code)
        session = MagicMock()
        session.get.return_value = response
        with patch.object(scale_ai, "make_tracked_session", return_value=session):
            assert scale_ai.validate_credentials("live_key") is expected

    def test_network_error_is_invalid(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with patch.object(scale_ai, "make_tracked_session", return_value=session):
            assert scale_ai.validate_credentials("live_key") is False


class TestSourceResponse:
    @parameterized.expand([("tasks", ["task_id"]), ("batches", ["name"]), ("projects", ["name"])])
    def test_primary_keys_and_desc_sort(self, endpoint: str, primary_keys: list[str]) -> None:
        # sort_mode="desc" defers watermark persistence to job end — required because tasks filter on
        # updated_at but arrive in created_at order.
        response = scale_ai_source(
            api_key="live_key", endpoint=endpoint, logger=MagicMock(), resumable_source_manager=MagicMock()
        )
        assert response.primary_keys == primary_keys
        assert response.sort_mode == "desc"
        assert response.partition_keys == ["created_at"]
