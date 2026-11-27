import json
import time
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock

import pyarrow as pa
from parameterized import parameterized

from products.warehouse_sources.sources.sdk.internals import table_from_py_list
from products.warehouse_sources.sources.sdk.testing import RecordedRequest, ScriptedResponse, SourceDriver
from products.warehouse_sources.sources.vapi import vapi
from products.warehouse_sources.sources.vapi._config import VapiSourceConfig
from products.warehouse_sources.sources.vapi.settings import VAPI_VERSION_V1, VAPI_VERSION_V2
from products.warehouse_sources.sources.vapi.source import VapiSource
from products.warehouse_sources.sources.vapi.vapi import VapiResumeConfig, _format_datetime_param, get_rows, vapi_source


class TestAddedEndpoints:
    @parameterized.expand(
        [
            ("empty", []),
            (
                "daily_totals",
                [
                    {
                        "date": "2026-01-01",
                        "callCount": 2,
                        "totalCost": 0.5,
                        "totalDuration": 90,
                        "totalMinutesUsed": 1.5,
                    },
                    {"date": "2026-01-02", "callCount": 0, "totalCost": 0, "totalDuration": 0, "totalMinutesUsed": 0},
                ],
            ),
        ]
    )
    def test_analytics_posts_history_query_and_extracts_daily_rows(
        self, _name: str, rows: list[dict[str, Any]]
    ) -> None:
        result = SourceDriver(VapiSource(), VapiSourceConfig(api_key="test-key")).run(
            "analytics",
            [ScriptedResponse(json=[{"name": "daily_calls", "timeRange": {"step": "day"}, "result": rows}])],
        )

        assert result.raised is None
        assert [row for table in result.items for row in table.to_pylist()] == rows
        assert result.paths == ["/analytics"]
        assert result.requests[0].method == "POST"
        assert result.requests[0].json() == {
            "queries": [
                {
                    "name": "daily_calls",
                    "table": "call",
                    "timeRange": {"start": "1970-01-01T00:00:00.000Z", "step": "day", "timezone": "UTC"},
                    "operations": [
                        {"operation": "count", "column": "id", "alias": "callCount"},
                        {"operation": "sum", "column": "cost", "alias": "totalCost"},
                        {"operation": "sum", "column": "duration", "alias": "totalDuration"},
                        {"operation": "sum", "column": "minutesUsed", "alias": "totalMinutesUsed"},
                    ],
                }
            ]
        }
        assert result.saved_states == []

    def test_analytics_waits_for_vendor_cooldown(self) -> None:
        retry_at: float | None = None
        rows = [{"date": "2026-01-01", "callCount": 2}]

        def respond(request: RecordedRequest) -> ScriptedResponse:
            nonlocal retry_at
            assert request.method == "POST"
            if retry_at is None:
                retry_at = time.monotonic() + 60
            if time.monotonic() < retry_at:
                return ScriptedResponse(status=429, json={}, headers={"Retry-After": "60"})
            return ScriptedResponse(json=[{"name": "daily_calls", "result": rows}])

        result = SourceDriver(VapiSource(), VapiSourceConfig(api_key="test-key")).run("analytics", respond)

        assert result.raised is None
        assert [row for table in result.items for row in table.to_pylist()] == rows
        assert result.paths == ["/analytics", "/analytics"]

    def test_structured_outputs_follow_page_metadata(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "secretaryName": {"type": "string"},
                "headers": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"password": {"type": "string"}, "apiKey": {"type": "string"}},
                    },
                },
            },
        }
        result = SourceDriver(VapiSource(), VapiSourceConfig(api_key="test-key")).run(
            "structured_outputs",
            [
                ScriptedResponse(
                    json={
                        "results": [
                            {
                                "id": "output-1",
                                "name": "Category",
                                "createdAt": "2026-01-01T00:00:00.000Z",
                                "schema": schema,
                                "model": {
                                    "provider": "custom-llm",
                                    "url": "https://example.com/model",
                                    "headers": {"Authorization": "fake-token"},
                                },
                            }
                        ],
                        "metadata": {"hasNextPage": True},
                    }
                ),
                ScriptedResponse(
                    json={
                        "results": [{"id": "output-2", "name": "Rating", "createdAt": "2026-01-02T00:00:00.000Z"}],
                        "metadata": {"hasNextPage": False},
                    }
                ),
            ],
        )

        assert result.raised is None
        assert [row["id"] for table in result.items for row in table.to_pylist()] == ["output-1", "output-2"]
        assert result.paths == ["/structured-output", "/structured-output"]
        assert result.params("page") == ["1", "2"]
        assert result.params("sortBy") == ["createdAt", "createdAt"]
        assert result.params("sortOrder") == ["ASC", "ASC"]
        first_row = result.items[0].to_pylist()[0]
        assert json.loads(first_row["schema"]) == schema
        assert json.loads(first_row["model"]) == {
            "provider": "custom-llm",
            "url": "https://example.com/model",
            "headers": "[REDACTED]",
        }
        assert "fake-token" not in str(first_row)


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


def _collect(
    monkeypatch: Any, manager: _FakeResumableManager, api_version: str = VAPI_VERSION_V1, **kwargs: Any
) -> list[dict]:
    monkeypatch.setattr(vapi, "Batcher", _FakeBatcher)
    monkeypatch.setattr(vapi, "DEFAULT_PAGE_LIMIT", 2)
    rows: list[dict] = []
    for table in get_rows(
        api_key="key",
        api_version=api_version,
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
        **kwargs,
    ):
        rows.extend(table.to_pylist())
    return rows


class TestCreatedAtCursorEndpoints:
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


class TestPageEndpoints:
    @pytest.mark.parametrize(
        "endpoint,path",
        [
            ("chats", "/chat"),
            ("scorecards", "/observability/scorecard"),
            ("evals", "/eval"),
            ("eval_runs", "/eval/run"),
        ],
    )
    def test_walks_ascending_pages_until_has_next_page_false(self, monkeypatch: Any, endpoint: str, path: str) -> None:
        pages = {
            f"https://api.vapi.ai{path}?limit=2&page=1&sortOrder=ASC&sortBy=createdAt": {
                "results": [
                    {"id": "1", "createdAt": "2026-01-01T00:00:00.000Z"},
                    {"id": "2", "createdAt": "2026-01-02T00:00:00.000Z"},
                ],
                "metadata": {"hasNextPage": True},
            },
            f"https://api.vapi.ai{path}?limit=2&page=2&sortOrder=ASC&sortBy=createdAt": {
                "results": [{"id": "3", "createdAt": "2026-01-03T00:00:00.000Z"}],
                "metadata": {"hasNextPage": False},
            },
        }
        fetched = _patch_fetch(monkeypatch, pages)
        rows = _collect(monkeypatch, _FakeResumableManager(), endpoint=endpoint)

        assert [r["id"] for r in rows] == ["1", "2", "3"]
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

    def test_bare_array_response_stops_on_short_page(self, monkeypatch: Any) -> None:
        # /eval/simulation/run may answer with a bare array instead of the {results, metadata} envelope.
        pages = {
            "https://api.vapi.ai/eval/simulation/run?limit=2&page=1&sortOrder=ASC&sortBy=createdAt": [
                {"id": "r1", "createdAt": "2026-01-01T00:00:00.000Z"},
                {"id": "r2", "createdAt": "2026-01-02T00:00:00.000Z"},
            ],
            "https://api.vapi.ai/eval/simulation/run?limit=2&page=2&sortOrder=ASC&sortBy=createdAt": [
                {"id": "r3", "createdAt": "2026-01-03T00:00:00.000Z"},
            ],
        }
        fetched = _patch_fetch(monkeypatch, pages)
        rows = _collect(monkeypatch, _FakeResumableManager(), endpoint="simulation_runs")

        assert [r["id"] for r in rows] == ["r1", "r2", "r3"]
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
            ("calls_descending", "calls", VAPI_VERSION_V1, "desc", ["createdAt"]),
            ("chats_ascending", "chats", VAPI_VERSION_V1, "asc", ["createdAt"]),
            ("files_unpartitioned", "files", VAPI_VERSION_V1, "asc", None),
            # phone_numbers flips from a descending cursor (v1) to ascending pages (v2), so the
            # pipeline's watermark direction must follow the pinned version.
            ("phone_numbers_v1_descending", "phone_numbers", VAPI_VERSION_V1, "desc", ["createdAt"]),
            ("phone_numbers_v2_ascending", "phone_numbers", VAPI_VERSION_V2, "asc", ["createdAt"]),
        ]
    )
    def test_sort_mode_and_partitioning(
        self,
        _name: str,
        endpoint: str,
        api_version: str,
        expected_sort_mode: str,
        expected_partition_keys: list[str] | None,
    ) -> None:
        response = vapi_source(
            api_key="key",
            endpoint=endpoint,
            api_version=api_version,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.sort_mode == expected_sort_mode
        assert response.partition_keys == expected_partition_keys
