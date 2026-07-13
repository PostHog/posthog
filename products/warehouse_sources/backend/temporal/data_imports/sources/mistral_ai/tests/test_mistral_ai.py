from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.mistral_ai import mistral_ai
from products.warehouse_sources.backend.temporal.data_imports.sources.mistral_ai.mistral_ai import (
    MistralAIResumeConfig,
    MistralAIUnexpectedResponseError,
    _build_base_params,
    _extract_rows,
    _format_created_after,
    get_rows,
    mistral_ai_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mistral_ai.settings import MISTRAL_AI_ENDPOINTS


class _FakeResumableManager:
    def __init__(self, state: MistralAIResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[MistralAIResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> MistralAIResumeConfig | None:
        return self._state

    def save_state(self, data: MistralAIResumeConfig) -> None:
        self.saved.append(data)


class TestFormatCreatedAfter:
    @parameterized.expand(
        [
            # created/created_at come back as Unix seconds, so the watermark is usually an int.
            ("unix_int", 1_772_000_000, "2026-02-25T06:13:20Z"),
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("string_passthrough", "2026-03-04T00:00:00Z", "2026-03-04T00:00:00Z"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        assert _format_created_after(value) == expected

    def test_no_offset_suffix(self) -> None:
        # A "+00:00" offset instead of "Z" is a common way to produce a value the API rejects.
        assert "+00:00" not in _format_created_after(datetime(2026, 3, 4, tzinfo=UTC))

    def test_bool_raises(self) -> None:
        # bool is an int subclass; without an explicit guard it would be read as a Unix timestamp.
        with pytest.raises(ValueError):
            _format_created_after(True)


class TestBuildBaseParams:
    def test_batch_jobs_incremental_adds_order_by_and_created_after(self) -> None:
        # order_by=created forces ascending order (API default is -created); dropping it corrupts the
        # ascending watermark. Dropping created_after silently reverts incremental to a full refresh.
        params = _build_base_params(
            MISTRAL_AI_ENDPOINTS["batch_jobs"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=1_772_000_000,
        )
        assert params == {"order_by": "created", "created_after": "2026-02-25T06:13:20Z"}

    def test_fine_tuning_incremental_adds_created_after_only(self) -> None:
        params = _build_base_params(
            MISTRAL_AI_ENDPOINTS["fine_tuning_jobs"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=1_772_000_000,
        )
        assert params == {"created_after": "2026-02-25T06:13:20Z"}

    def test_first_sync_has_no_created_after(self) -> None:
        # No watermark yet: sending created_after=None would 400 or filter everything out.
        params = _build_base_params(
            MISTRAL_AI_ENDPOINTS["batch_jobs"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
        )
        assert params == {"order_by": "created"}

    @parameterized.expand([("files",), ("agents",), ("libraries",), ("models",)])
    def test_full_refresh_endpoints_send_no_filter(self, endpoint: str) -> None:
        params = _build_base_params(
            MISTRAL_AI_ENDPOINTS[endpoint],
            should_use_incremental_field=True,
            db_incremental_field_last_value=1_772_000_000,
        )
        assert params == {}


class TestExtractRows:
    @parameterized.expand(
        [
            ("wrapped_data", "files", {"data": [{"id": "a"}], "total": 1}, [{"id": "a"}]),
            ("bare_list", "agents", [{"id": "a"}, {"id": "b"}], [{"id": "a"}, {"id": "b"}]),
            # A wrapped endpoint that actually returns a bare array must still sync its rows rather
            # than silently drop them (Mistral's list shapes aren't uniform across endpoints).
            ("bare_list_for_wrapped_endpoint", "models", [{"id": "m"}], [{"id": "m"}]),
            ("empty_wrapped", "files", {"data": []}, []),
            ("empty_bare", "agents", [], []),
        ]
    )
    def test_extract(self, _name: str, endpoint: str, body: Any, expected: list[dict]) -> None:
        assert _extract_rows(MISTRAL_AI_ENDPOINTS[endpoint], body) == expected

    @parameterized.expand(
        [
            # A 2xx with an unreadable shape must raise, not return [] — get_rows treats [] as the
            # end of pagination, so a silent [] finishes a green sync with rows missing.
            ("wrapped_missing_key", "files", {"object": "list"}),
            ("dict_for_bare_endpoint", "agents", {"data": [{"id": "a"}]}),
            ("data_key_not_a_list", "files", {"data": {"nested": "object"}}),
        ]
    )
    def test_extract_raises_on_unexpected_shape(self, _name: str, endpoint: str, body: Any) -> None:
        with pytest.raises(MistralAIUnexpectedResponseError):
            _extract_rows(MISTRAL_AI_ENDPOINTS[endpoint], body)


class TestGetRows:
    @staticmethod
    def _run(
        endpoint: str, manager: _FakeResumableManager, pages_by_index: dict[int, Any], **incremental: Any
    ) -> tuple[list[dict], list[dict[str, Any]]]:
        seen_params: list[dict[str, Any]] = []

        def fake_fetch(session: Any, url: str, params: dict[str, Any], logger: Any) -> Any:
            seen_params.append(params)
            return pages_by_index[params.get("page", 0)]

        rows: list[dict] = []
        with (
            patch.object(mistral_ai, "_fetch_page", fake_fetch),
            patch.object(mistral_ai, "make_tracked_session", lambda **_: MagicMock()),
        ):
            for batch in get_rows(
                api_key="sk-x",
                endpoint=endpoint,
                logger=MagicMock(),
                resumable_source_manager=manager,  # type: ignore[arg-type]
                **incremental,
            ):
                rows.extend(batch)
        return rows, seen_params

    def test_paginates_until_empty_page(self) -> None:
        # Stopping one page early (e.g. len<page_size heuristic against a clamped page size) drops rows;
        # not advancing `page` loops forever. Empty-page termination guards both.
        pages = {
            0: {"data": [{"id": "f0"}]},
            1: {"data": [{"id": "f1"}]},
            2: {"data": []},
        }
        rows, seen = self._run("files", _FakeResumableManager(), pages)
        assert rows == [{"id": "f0"}, {"id": "f1"}]
        assert [p["page"] for p in seen] == [0, 1, 2]

    def test_unpaginated_endpoint_fetches_once(self) -> None:
        # /v1/models has no pagination; sending page/page_size or looping would be wrong.
        pages = {0: {"data": [{"id": "m1"}, {"id": "m2"}]}}
        rows, seen = self._run("models", _FakeResumableManager(), pages)
        assert rows == [{"id": "m1"}, {"id": "m2"}]
        assert len(seen) == 1
        assert "page" not in seen[0]

    def test_saves_next_page_after_each_yield(self) -> None:
        # State must be saved AFTER yielding so a crash re-yields the last page rather than skipping it.
        pages = {0: {"data": [{"id": "f0"}]}, 1: {"data": [{"id": "f1"}]}, 2: {"data": []}}
        manager = _FakeResumableManager()
        self._run("files", manager, pages)
        assert [c.page for c in manager.saved] == [1, 2]

    def test_resumes_from_saved_page(self) -> None:
        # Resuming re-runs earlier pages would duplicate (or, with replace, waste) work; page 0 must be skipped.
        pages = {1: {"data": [{"id": "f1"}]}, 2: {"data": []}}
        manager = _FakeResumableManager(MistralAIResumeConfig(page=1))
        rows, seen = self._run("files", manager, pages)
        assert rows == [{"id": "f1"}]
        assert [p["page"] for p in seen] == [1, 2]

    def test_bare_array_endpoint_paginates(self) -> None:
        pages = {0: [{"id": "a0"}], 1: []}
        rows, _ = self._run("agents", _FakeResumableManager(), pages)
        assert rows == [{"id": "a0"}]


class TestFetchPageRetries:
    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_retryable_statuses_are_retried(self, _name: str, status: int) -> None:
        bad = MagicMock(status_code=status)
        good = MagicMock(status_code=200, ok=True)
        good.json.return_value = {"data": []}
        session = MagicMock()
        session.get.side_effect = [bad, good]

        with patch.object(mistral_ai._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = mistral_ai._fetch_page(session, "https://api.mistral.ai/v1/files", {}, MagicMock())

        assert result == {"data": []}
        assert session.get.call_count == 2

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403)])
    def test_client_errors_are_not_retried(self, _name: str, status: int) -> None:
        # A credential error must surface immediately (so get_non_retryable_errors fails the sync),
        # never spin through the retry budget.
        resp = MagicMock(status_code=status, ok=False, text="nope")
        resp.raise_for_status.side_effect = requests.HTTPError(f"{status} Client Error", response=resp)
        session = MagicMock()
        session.get.return_value = resp

        with pytest.raises(requests.HTTPError):
            mistral_ai._fetch_page(session, "https://api.mistral.ai/v1/files", {}, MagicMock())
        assert session.get.call_count == 1

    def test_transient_error_reraised_after_cap(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("reset")
        with patch.object(mistral_ai._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            with pytest.raises(requests.ConnectionError):
                mistral_ai._fetch_page(session, "https://api.mistral.ai/v1/files", {}, MagicMock())
        assert session.get.call_count == 5


class TestSourceResponse:
    @parameterized.expand(
        [
            # batch jobs force ascending order (order_by=created), so the watermark can advance per
            # page; fine-tuning has no sort param, so it must persist the watermark only at run end.
            ("models", "created", ["id"], "asc"),
            ("files", "created_at", ["id"], "asc"),
            ("batch_jobs", "created_at", ["id"], "asc"),
            ("fine_tuning_jobs", "created_at", ["id"], "desc"),
        ]
    )
    def test_partitioning_and_keys(
        self, endpoint: str, partition_key: str, primary_keys: list[str], sort_mode: str
    ) -> None:
        response = mistral_ai_source(
            api_key="sk-x",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.partition_mode == "datetime"
        assert response.partition_keys == [partition_key]
        assert response.sort_mode == sort_mode
