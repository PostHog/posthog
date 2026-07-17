from datetime import UTC, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.openai import openai
from products.warehouse_sources.backend.temporal.data_imports.sources.openai.openai import (
    OpenAIResumeConfig,
    _bucket_params,
    _build_url,
    _flatten_bucket_result,
    _flatten_owner,
    _normalize_audit_log,
    _row_id,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.openai.settings import OPENAI_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.openai.source import OpenAISource


class _FakeResumableManager:
    def __init__(self, state: OpenAIResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[OpenAIResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> OpenAIResumeConfig | None:
        return self._state

    def save_state(self, data: OpenAIResumeConfig) -> None:
        self.saved.append(data)


def _collect(
    manager: _FakeResumableManager, monkeypatch: Any, responses: list[dict], endpoint: str, **kw: Any
) -> list[dict]:
    calls: list[str] = []

    def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
        calls.append(url)
        return responses[len(calls) - 1]

    monkeypatch.setattr(openai, "_fetch_page", fake_fetch)

    rows: list[dict] = []
    for table in get_rows(
        api_key="sk-admin-test",
        endpoint=endpoint,
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
        **kw,
    ):
        rows.extend(table.to_pylist())
    manager._captured_calls = calls  # type: ignore[attr-defined]
    return rows


class TestRowId:
    def test_id_is_stable_across_metric_changes(self) -> None:
        # The surrogate key must depend only on identity dims, never metric values — otherwise a
        # restated bucket would get a new id and merge would insert a duplicate instead of updating.
        a = _row_id(1722470400, "proj_1", "gpt-4o")
        b = _row_id(1722470400, "proj_1", "gpt-4o")
        assert a == b

    def test_id_differs_by_dimension(self) -> None:
        a = _row_id(1722470400, "proj_1", "gpt-4o")
        b = _row_id(1722470400, "proj_2", "gpt-4o")
        assert a != b

    def test_none_and_empty_string_distinguished_positionally(self) -> None:
        # A missing dimension (None) must not collide with an empty-string value at the same
        # position, and positions stay aligned so distinct dimension tuples never collide either.
        assert _row_id(None, "x") != _row_id("", "x")
        assert _row_id(None, "x") != _row_id("x", None)


class TestBuildUrl:
    def test_repeats_multi_params(self) -> None:
        url = _build_url("/v1/organization/usage/completions", {"limit": 31}, {"group_by": ["model", "project_id"]})
        assert url.count("group_by=") == 2
        assert "limit=31" in url

    def test_drops_none_values(self) -> None:
        url = _build_url("/v1/organization/users", {"limit": 100, "after": None})
        assert "after" not in url


class TestBucketParams:
    def test_incremental_uses_watermark_as_unix_start_time(self) -> None:
        config = OPENAI_ENDPOINTS["usage_completions"]
        watermark = datetime(2026, 3, 4, 0, 0, 0, tzinfo=UTC)
        params, multi = _bucket_params(
            config, should_use_incremental_field=True, db_incremental_field_last_value=watermark
        )
        assert params["start_time"] == int(watermark.timestamp())
        assert params["bucket_width"] == "1d"
        assert params["limit"] == 31
        assert multi == {"group_by": config.group_by}

    def test_full_refresh_falls_back_to_api_launch_era(self) -> None:
        # Without a watermark we must still send the required start_time; the API launch era pulls
        # all available history without requesting decades of empty pre-launch buckets.
        config = OPENAI_ENDPOINTS["costs"]
        params, _ = _bucket_params(config, should_use_incremental_field=False, db_incremental_field_last_value=None)
        assert params["start_time"] == int(datetime(2020, 1, 1, tzinfo=UTC).timestamp())
        assert params["limit"] == 180

    def test_costs_groups_only_by_dimensions_the_api_accepts(self) -> None:
        # api_key_id grouping is rejected by the live costs endpoint with a 400 that fails the whole
        # sync, even though the SDK types list it.
        config = OPENAI_ENDPOINTS["costs"]
        _, multi = _bucket_params(config, should_use_incremental_field=False, db_incremental_field_last_value=None)
        assert multi == {"group_by": ["project_id", "line_item"]}


class TestFlattenBucketResult:
    def test_flattens_nested_amount_and_converts_bucket_times(self) -> None:
        config = OPENAI_ENDPOINTS["costs"]
        bucket = {"start_time": 1722470400, "end_time": 1722556800}
        result = {
            "object": "organization.costs.result",
            "amount": {"value": 12.34, "currency": "usd"},
            "line_item": "GPT-4o mini, input",
            "project_id": "proj_1",
            "api_key_id": None,
        }
        row = _flatten_bucket_result(config, bucket, result)
        assert row["amount_value"] == 12.34
        assert row["amount_currency"] == "usd"
        assert row["line_item"] == "GPT-4o mini, input"
        assert row["start_time"] == datetime(2024, 8, 1, tzinfo=UTC)
        assert row["end_time"] == datetime(2024, 8, 2, tzinfo=UTC)
        assert "object" not in row
        assert row["id"]

    def test_metric_fields_copied_through_per_endpoint(self) -> None:
        config = OPENAI_ENDPOINTS["usage_completions"]
        row = _flatten_bucket_result(
            config,
            {"start_time": 1722470400, "end_time": 1722556800},
            {"input_tokens": 100, "output_tokens": 5, "input_cached_tokens": 50, "model": "gpt-4o", "batch": False},
        )
        assert row["input_tokens"] == 100
        assert row["input_cached_tokens"] == 50
        assert row["model"] == "gpt-4o"
        assert row["batch"] is False


class TestFlattenOwner:
    def test_project_api_key_owner_principal_is_nested(self) -> None:
        item = {
            "id": "key_1",
            "owner": {"type": "user", "user": {"id": "user_1", "name": "Ada", "email": "ada@example.com"}},
        }
        flat = _flatten_owner(item)
        assert flat["owner_type"] == "user"
        assert flat["owner_id"] == "user_1"
        assert flat["owner_name"] == "Ada"
        assert "owner" not in flat

    def test_admin_api_key_owner_fields_are_direct(self) -> None:
        item = {"id": "key_1", "owner": {"type": "service_account", "id": "sa_1", "name": "CI bot"}}
        flat = _flatten_owner(item)
        assert flat["owner_type"] == "service_account"
        assert flat["owner_id"] == "sa_1"
        assert flat["owner_name"] == "CI bot"


class TestNormalizeAuditLog:
    def test_event_payload_folds_into_event_data_and_effective_at_is_datetime(self) -> None:
        # Each event type carries its details under a key named after the type; without folding,
        # the table would grow one sparse column per event type.
        item = {
            "id": "audit_log-1",
            "type": "project.created",
            "effective_at": 1722470400,
            "actor": {"type": "session"},
            "project.created": {"id": "proj_1", "name": "My project"},
        }
        row = _normalize_audit_log(item)
        assert row["event_data"] == {"id": "proj_1", "name": "My project"}
        assert "project.created" not in row
        assert row["effective_at"] == datetime(2024, 8, 1, tzinfo=UTC)


class TestBucketPagination:
    def test_follows_next_page_until_has_more_false(self, monkeypatch: Any) -> None:
        responses = [
            {
                "data": [{"start_time": 1, "end_time": 2, "results": [{"model": "a"}]}],
                "has_more": True,
                "next_page": "PAGE2",
            },
            {
                "data": [{"start_time": 2, "end_time": 3, "results": [{"model": "b"}]}],
                "has_more": False,
                "next_page": None,
            },
        ]
        manager = _FakeResumableManager()
        rows = _collect(manager, monkeypatch, responses, "usage_completions")
        assert [r["model"] for r in rows] == ["a", "b"]
        # Second request must carry the page token from the first response.
        assert "page=PAGE2" in manager._captured_calls[1]  # type: ignore[attr-defined]

    def test_resumes_from_saved_page_cursor(self, monkeypatch: Any) -> None:
        responses = [
            {
                "data": [{"start_time": 2, "end_time": 3, "results": [{"model": "b"}]}],
                "has_more": False,
                "next_page": None,
            },
        ]
        manager = _FakeResumableManager(OpenAIResumeConfig(cursor="PAGE2"))
        rows = _collect(manager, monkeypatch, responses, "usage_completions")
        assert [r["model"] for r in rows] == ["b"]
        assert "page=PAGE2" in manager._captured_calls[0]  # type: ignore[attr-defined]

    def test_empty_page_with_next_page_token_stops_pagination(self, monkeypatch: Any) -> None:
        # The costs endpoint is known to return a next_page token alongside an empty page; without
        # the guard, pagination would loop on the empty tail forever.
        responses = [
            {
                "data": [{"start_time": 1, "end_time": 2, "results": [{"line_item": "x"}]}],
                "has_more": True,
                "next_page": "PAGE2",
            },
            {"data": [], "has_more": True, "next_page": "PAGE3"},
        ]
        manager = _FakeResumableManager()
        rows = _collect(manager, monkeypatch, responses, "costs")
        assert [r["line_item"] for r in rows] == ["x"]
        assert len(manager._captured_calls) == 2  # type: ignore[attr-defined]

    def test_drains_every_chunk_when_a_batch_splits(self, monkeypatch: Any) -> None:
        # A batch can split into several ready chunks (byte/offset caps). Force it with tiny limits:
        # if the loop only pops one chunk per batch, the next batch() raises and rows go missing.
        real_batcher = openai.Batcher

        def tiny_batcher(**_: Any) -> openai.Batcher:
            return real_batcher(logger=MagicMock(), chunk_size=4, chunk_size_bytes=10**12, max_table_bytes=1)

        monkeypatch.setattr(openai, "Batcher", tiny_batcher)

        results = [{"model": f"m{i}"} for i in range(8)]
        responses = [
            {
                "data": [{"start_time": 1, "end_time": 2, "results": results}],
                "has_more": False,
                "next_page": None,
            }
        ]
        rows = _collect(_FakeResumableManager(), monkeypatch, responses, "usage_completions")
        assert sorted(r["model"] for r in rows) == [f"m{i}" for i in range(8)]


class TestEntityPagination:
    def test_cursor_pagination_uses_after_and_stops(self, monkeypatch: Any) -> None:
        responses = [
            {"data": [{"id": "user_1"}], "has_more": True, "last_id": "user_1"},
            {"data": [{"id": "user_2"}], "has_more": False, "last_id": "user_2"},
        ]
        manager = _FakeResumableManager()
        rows = _collect(manager, monkeypatch, responses, "users")
        assert [r["id"] for r in rows] == ["user_1", "user_2"]
        assert "after=user_1" in manager._captured_calls[1]  # type: ignore[attr-defined]

    def test_falls_back_to_last_item_id_when_last_id_missing(self, monkeypatch: Any) -> None:
        # `last_id` isn't documented on every list response; the last item's id must keep
        # pagination moving instead of stopping after page one.
        responses = [
            {"data": [{"id": "user_1"}], "has_more": True},
            {"data": [{"id": "user_2"}], "has_more": False},
        ]
        manager = _FakeResumableManager()
        rows = _collect(manager, monkeypatch, responses, "users")
        assert [r["id"] for r in rows] == ["user_1", "user_2"]
        assert "after=user_1" in manager._captured_calls[1]  # type: ignore[attr-defined]

    def test_admin_api_keys_flatten_owner(self, monkeypatch: Any) -> None:
        responses = [
            {
                "data": [{"id": "key_1", "owner": {"type": "user", "id": "user_1", "name": "Ada"}}],
                "has_more": False,
                "last_id": "key_1",
            }
        ]
        rows = _collect(_FakeResumableManager(), monkeypatch, responses, "admin_api_keys")
        assert rows[0]["owner_id"] == "user_1"
        assert "owner" not in rows[0]


class TestAuditLogs:
    def test_incremental_applies_effective_at_filter(self, monkeypatch: Any) -> None:
        responses = [
            {"data": [{"id": "audit_log-1", "type": "project.created", "effective_at": 1722470400}], "has_more": False}
        ]
        manager = _FakeResumableManager()
        watermark = datetime(2026, 3, 4, tzinfo=UTC)
        _collect(
            manager,
            monkeypatch,
            responses,
            "audit_logs",
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
        )
        # Bracket-style nested param (URL-encoded), matching the official SDK's serialization.
        assert f"effective_at%5Bgte%5D={int(watermark.timestamp())}" in manager._captured_calls[0]  # type: ignore[attr-defined]

    def test_full_refresh_sends_no_effective_at_filter(self, monkeypatch: Any) -> None:
        responses = [
            {"data": [{"id": "audit_log-1", "type": "project.created", "effective_at": 1722470400}], "has_more": False}
        ]
        manager = _FakeResumableManager()
        _collect(manager, monkeypatch, responses, "audit_logs")
        assert "effective_at" not in manager._captured_calls[0]  # type: ignore[attr-defined]


class TestProjectFanOut:
    def test_emits_one_row_per_project_resource_with_composite_key(self, monkeypatch: Any) -> None:
        # First response lists projects, then one page per project's users.
        responses = [
            {"data": [{"id": "proj_1"}, {"id": "proj_2"}], "has_more": False, "last_id": "proj_2"},
            {"data": [{"id": "user_1"}], "has_more": False, "last_id": "user_1"},
            {"data": [{"id": "user_1"}], "has_more": False, "last_id": "user_1"},
        ]
        rows = _collect(_FakeResumableManager(), monkeypatch, responses, "project_users")
        assert [(r["project_id"], r["id"]) for r in rows] == [("proj_1", "user_1"), ("proj_2", "user_1")]

    def test_flushes_each_projects_rows_before_checkpointing_next(self, monkeypatch: Any) -> None:
        # A project's buffered rows must be yielded before the resume cursor advances to the next
        # project; otherwise a crash before the final flush would lose them (they'd never be re-read
        # on resume, which starts at the checkpointed next project).
        responses = [
            {"data": [{"id": "proj_1"}, {"id": "proj_2"}], "has_more": False, "last_id": "proj_2"},
            {"data": [{"id": "user_a"}], "has_more": False, "last_id": "user_a"},
            {"data": [{"id": "user_b"}], "has_more": False, "last_id": "user_b"},
        ]
        calls: list[str] = []

        def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
            calls.append(url)
            return responses[len(calls) - 1]

        monkeypatch.setattr(openai, "_fetch_page", fake_fetch)

        events: list[tuple[str, Any]] = []

        class _RecordingManager(_FakeResumableManager):
            def save_state(self, data: OpenAIResumeConfig) -> None:
                super().save_state(data)
                events.append(("save", data.project_id))

        manager = _RecordingManager()
        for table in get_rows(
            api_key="sk-admin-test",
            endpoint="project_users",
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            for row in table.to_pylist():
                events.append(("yield", row["project_id"]))

        assert events.index(("yield", "proj_1")) < events.index(("save", "proj_2"))


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("forbidden_scope", 403, True), ("unauthorized", 401, False)])
    def test_status_mapping(self, _name: str, status: int, expected: bool) -> None:
        # 403 is accepted at create time (real key, unprobed scope); 401 means a bad key.
        response = MagicMock(status_code=status)
        session = MagicMock()
        session.get.return_value = response
        with patch.object(openai, "make_tracked_session", return_value=session):
            assert validate_credentials("sk-admin-test") is expected

    def test_network_error_is_invalid(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with patch.object(openai, "make_tracked_session", return_value=session):
            assert validate_credentials("sk-admin-test") is False


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://api.openai.com/v1/organization/users?limit=100",
            ),
            (
                "forbidden",
                "403 Client Error: Forbidden for url: https://api.openai.com/v1/organization/costs",
            ),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = OpenAISource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("read_timeout", "HTTPSConnectionPool(host='api.openai.com', port=443): Read timed out."),
            (
                "server_error",
                "500 Server Error: Internal Server Error for url: https://api.openai.com/v1/organization/users",
            ),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = OpenAISource().get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)


class TestFetchPage:
    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_retryable_statuses_raise_retryable_error(self, _name: str, status: int) -> None:
        response = MagicMock(status_code=status, ok=False)
        session = MagicMock()
        session.get.return_value = response
        with patch.object(openai._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            with pytest.raises(openai.OpenAIRetryableError):
                openai._fetch_page(session, "https://api.openai.com/v1/organization/users", {}, MagicMock())
        assert session.get.call_count == 5  # exhausts the retry budget

    def test_client_error_raises_for_status_without_retry(self) -> None:
        response = MagicMock(status_code=401, ok=False, text="unauthorized")
        response.raise_for_status.side_effect = requests.HTTPError("401 Client Error", response=response)
        session = MagicMock()
        session.get.return_value = response
        with pytest.raises(requests.HTTPError):
            openai._fetch_page(session, "https://api.openai.com/v1/organization/users", {}, MagicMock())
        assert session.get.call_count == 1
