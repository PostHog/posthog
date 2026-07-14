import json
from datetime import UTC, date, datetime
from typing import Any

from unittest.mock import MagicMock

import pyarrow as pa
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.utils import table_from_py_list
from products.warehouse_sources.backend.temporal.data_imports.sources.vapi import vapi
from products.warehouse_sources.backend.temporal.data_imports.sources.vapi.vapi import (
    VapiResumeConfig,
    _format_datetime_param,
    get_rows,
    vapi_source,
)


class TestFormatDatetimeParam:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, 123000, tzinfo=UTC), "2026-03-04T02:58:14.123Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00.000Z"),
            ("string_passthrough", "2026-03-04T02:58:14.123Z", "2026-03-04T02:58:14.123Z"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        result = _format_datetime_param(value)
        assert result == expected
        assert "+00:00" not in result


class _FakeResumableManager:
    def __init__(self, state: VapiResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[VapiResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> VapiResumeConfig | None:
        return self._state

    def save_state(self, data: VapiResumeConfig) -> None:
        self.saved.append(data)


class _FakeBatcher:
    """Yields one table per batched page so save-after-yield behavior is observable without 2000+ rows."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._rows: list[dict] = []

    def batch(self, rows: list[dict]) -> None:
        self._rows.extend(rows)

    def should_yield(self, include_incomplete_chunk: bool = False) -> bool:
        return len(self._rows) > 0

    def get_table(self) -> pa.Table:
        table = table_from_py_list(self._rows)
        self._rows = []
        return table


def _patch_fetch(monkeypatch: Any, pages: dict[str, Any]) -> list[str]:
    fetched: list[str] = []

    def fake_fetch(session: Any, url: str, logger: Any) -> Any:
        fetched.append(url)
        return pages[url]

    monkeypatch.setattr(vapi, "_fetch", fake_fetch)
    monkeypatch.setattr(vapi, "_make_session", lambda api_key: MagicMock())
    return fetched


def _collect(monkeypatch: Any, manager: _FakeResumableManager, **kwargs: Any) -> list[dict]:
    monkeypatch.setattr(vapi, "Batcher", _FakeBatcher)
    monkeypatch.setattr(vapi, "DEFAULT_PAGE_LIMIT", 2)
    rows: list[dict] = []
    for table in get_rows(
        api_key="key",
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
        **kwargs,
    ):
        rows.extend(table.to_pylist())
    return rows


class TestCreatedAtCursorEndpoints:
    def test_paginates_with_created_at_lt_until_short_page(self, monkeypatch: Any) -> None:
        pages = {
            "https://api.vapi.ai/call?limit=2": [
                {"id": "3", "createdAt": "2026-01-03T00:00:00.000Z"},
                {"id": "2", "createdAt": "2026-01-02T00:00:00.000Z"},
            ],
            "https://api.vapi.ai/call?limit=2&createdAtLt=2026-01-02T00%3A00%3A00.000Z": [
                {"id": "1", "createdAt": "2026-01-01T00:00:00.000Z"},
            ],
        }
        fetched = _patch_fetch(monkeypatch, pages)
        rows = _collect(monkeypatch, _FakeResumableManager(), endpoint="calls")

        assert [r["id"] for r in rows] == ["3", "2", "1"]
        assert fetched == list(pages)

    def test_saves_cursor_of_last_yielded_row(self, monkeypatch: Any) -> None:
        pages = {
            "https://api.vapi.ai/call?limit=2": [
                {"id": "3", "createdAt": "2026-01-03T00:00:00.000Z"},
                {"id": "2", "createdAt": "2026-01-02T00:00:00.000Z"},
            ],
            "https://api.vapi.ai/call?limit=2&createdAtLt=2026-01-02T00%3A00%3A00.000Z": [],
        }
        _patch_fetch(monkeypatch, pages)
        manager = _FakeResumableManager()
        _collect(monkeypatch, manager, endpoint="calls")

        assert manager.saved[-1] == VapiResumeConfig(created_at_cursor="2026-01-02T00:00:00.000Z")

    def test_resumes_from_saved_cursor(self, monkeypatch: Any) -> None:
        pages = {
            "https://api.vapi.ai/call?limit=2&createdAtLt=2026-01-02T00%3A00%3A00.000Z": [
                {"id": "1", "createdAt": "2026-01-01T00:00:00.000Z"},
            ],
        }
        fetched = _patch_fetch(monkeypatch, pages)
        manager = _FakeResumableManager(VapiResumeConfig(created_at_cursor="2026-01-02T00:00:00.000Z"))
        rows = _collect(monkeypatch, manager, endpoint="calls")

        assert [r["id"] for r in rows] == ["1"]
        assert fetched == list(pages)

    def test_incremental_fetches_backfill_then_newer_rows(self, monkeypatch: Any) -> None:
        pages = {
            # Backfill leg: rows older than the earliest value already synced.
            "https://api.vapi.ai/call?createdAtLt=2026-01-01T00%3A00%3A00.000Z&limit=2": [
                {"id": "0", "createdAt": "2025-12-31T00:00:00.000Z"},
            ],
            # Newer leg: rows past the watermark.
            "https://api.vapi.ai/call?createdAtGt=2026-01-05T00%3A00%3A00.000Z&limit=2": [
                {"id": "6", "createdAt": "2026-01-06T00:00:00.000Z"},
            ],
        }
        fetched = _patch_fetch(monkeypatch, pages)
        manager = _FakeResumableManager()
        rows = _collect(
            monkeypatch,
            manager,
            endpoint="calls",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 5, tzinfo=UTC),
            db_incremental_field_earliest_value=datetime(2026, 1, 1, tzinfo=UTC),
            incremental_field="createdAt",
        )

        assert [r["id"] for r in rows] == ["0", "6"]
        assert fetched == list(pages)
        # Incremental legs are bounded windows; a retry re-fetches them, so no resume state.
        assert manager.saved == []

    def test_incremental_on_updated_at_uses_updated_at_filters(self, monkeypatch: Any) -> None:
        pages = {
            "https://api.vapi.ai/call?updatedAtGt=2026-01-05T00%3A00%3A00.000Z&limit=2": [
                {"id": "6", "createdAt": "2026-01-06T00:00:00.000Z", "updatedAt": "2026-01-06T00:00:00.000Z"},
            ],
        }
        fetched = _patch_fetch(monkeypatch, pages)
        _collect(
            monkeypatch,
            _FakeResumableManager(),
            endpoint="calls",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 5, tzinfo=UTC),
            incremental_field="updatedAt",
        )
        assert fetched == list(pages)


class TestPageEndpoints:
    def test_walks_ascending_pages_until_has_next_page_false(self, monkeypatch: Any) -> None:
        pages = {
            "https://api.vapi.ai/chat?limit=2&page=1&sortOrder=ASC&sortBy=createdAt": {
                "results": [
                    {"id": "1", "createdAt": "2026-01-01T00:00:00.000Z"},
                    {"id": "2", "createdAt": "2026-01-02T00:00:00.000Z"},
                ],
                "metadata": {"hasNextPage": True},
            },
            "https://api.vapi.ai/chat?limit=2&page=2&sortOrder=ASC&sortBy=createdAt": {
                "results": [{"id": "3", "createdAt": "2026-01-03T00:00:00.000Z"}],
                "metadata": {"hasNextPage": False},
            },
        }
        fetched = _patch_fetch(monkeypatch, pages)
        rows = _collect(monkeypatch, _FakeResumableManager(), endpoint="chats")

        assert [r["id"] for r in rows] == ["1", "2", "3"]
        assert fetched == list(pages)

    def test_resume_cursor_narrows_window_and_restarts_at_page_one(self, monkeypatch: Any) -> None:
        pages = {
            "https://api.vapi.ai/chat?createdAtGt=2026-01-02T00%3A00%3A00.000Z&limit=2&page=1&sortOrder=ASC&sortBy=createdAt": {
                "results": [{"id": "3", "createdAt": "2026-01-03T00:00:00.000Z"}],
                "metadata": {"hasNextPage": False},
            },
        }
        fetched = _patch_fetch(monkeypatch, pages)
        manager = _FakeResumableManager(VapiResumeConfig(created_at_cursor="2026-01-02T00:00:00.000Z"))
        rows = _collect(monkeypatch, manager, endpoint="chats")

        assert [r["id"] for r in rows] == ["3"]
        assert fetched == list(pages)

    def test_incremental_watermark_becomes_created_at_gt(self, monkeypatch: Any) -> None:
        pages = {
            "https://api.vapi.ai/session?createdAtGt=2026-01-05T00%3A00%3A00.000Z&limit=2&page=1&sortOrder=ASC&sortBy=createdAt": {
                "results": [{"id": "6", "createdAt": "2026-01-06T00:00:00.000Z"}],
                "metadata": {"hasNextPage": False},
            },
        }
        fetched = _patch_fetch(monkeypatch, pages)
        _collect(
            monkeypatch,
            _FakeResumableManager(),
            endpoint="sessions",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 5, tzinfo=UTC),
            incremental_field="createdAt",
        )
        assert fetched == list(pages)


class TestSensitiveValueScrubbing:
    def test_auth_material_redacted_before_batching(self, monkeypatch: Any) -> None:
        pages = {
            "https://api.vapi.ai/assistant?limit=2": [
                {
                    "id": "a1",
                    "createdAt": "2026-01-01T00:00:00.000Z",
                    "credentials": [{"provider": "openai", "apiKey": "sk-live"}],
                    "credentialIds": ["550e8400"],
                    "server": {"url": "https://example.com/hook", "secret": "hook-secret", "headers": {"x": "y"}},
                    "model": {"provider": "openai", "model": "gpt-4o"},
                },
            ],
        }
        _patch_fetch(monkeypatch, pages)
        rows = _collect(monkeypatch, _FakeResumableManager(), endpoint="assistants")

        row = rows[0]
        # Nested objects come back JSON-encoded after the Arrow round trip.
        server = json.loads(row["server"]) if isinstance(row["server"], str) else row["server"]
        model = json.loads(row["model"]) if isinstance(row["model"], str) else row["model"]
        credential_ids = (
            json.loads(row["credentialIds"]) if isinstance(row["credentialIds"], str) else row["credentialIds"]
        )

        assert row["credentials"] == "[REDACTED]"
        assert server["secret"] == "[REDACTED]"
        assert server["headers"] == "[REDACTED]"
        # No secret survives anywhere in the row, however it was serialized.
        assert "sk-live" not in str(row)
        assert "hook-secret" not in str(row)
        # Non-secret data survives untouched, including credential ID references.
        assert credential_ids == ["550e8400"]
        assert server["url"] == "https://example.com/hook"
        assert model == {"provider": "openai", "model": "gpt-4o"}


class TestUnpaginatedEndpoints:
    def test_files_fetched_in_single_unparameterized_request(self, monkeypatch: Any) -> None:
        pages = {
            "https://api.vapi.ai/file": [{"id": "f1", "createdAt": "2026-01-01T00:00:00.000Z"}],
        }
        fetched = _patch_fetch(monkeypatch, pages)
        manager = _FakeResumableManager()
        rows = _collect(monkeypatch, manager, endpoint="files")

        assert [r["id"] for r in rows] == ["f1"]
        assert fetched == list(pages)
        assert manager.saved == []


class TestVapiSourceResponse:
    @parameterized.expand(
        [
            ("calls_descending", "calls", "desc", ["createdAt"]),
            ("chats_ascending", "chats", "asc", ["createdAt"]),
            ("files_unpartitioned", "files", "asc", None),
        ]
    )
    def test_sort_mode_and_partitioning(
        self, _name: str, endpoint: str, expected_sort_mode: str, expected_partition_keys: list[str] | None
    ) -> None:
        response = vapi_source(
            api_key="key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.sort_mode == expected_sort_mode
        assert response.partition_keys == expected_partition_keys
