from datetime import UTC, datetime
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized
from tenacity import RetryCallState

from products.warehouse_sources.backend.temporal.data_imports.sources.anthropic import anthropic
from products.warehouse_sources.backend.temporal.data_imports.sources.anthropic.anthropic import (
    _MAX_RETRY_AFTER_SECONDS,
    AnthropicResumeConfig,
    AnthropicRetryableError,
    _build_url,
    _flatten_cost_result,
    _flatten_usage_result,
    _parse_retry_after,
    _report_params,
    _row_id,
    _wait_anthropic,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.anthropic.source import AnthropicSource


class _FakeResumableManager:
    def __init__(self, state: AnthropicResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[AnthropicResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> AnthropicResumeConfig | None:
        return self._state

    def save_state(self, data: AnthropicResumeConfig) -> None:
        self.saved.append(data)


def _collect(
    manager: _FakeResumableManager, monkeypatch: Any, responses: list[dict], endpoint: str, **kw: Any
) -> list[dict]:
    calls: list[str] = []

    def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
        calls.append(url)
        return responses[len(calls) - 1]

    monkeypatch.setattr(anthropic, "_fetch_page", fake_fetch)

    rows: list[dict] = []
    for table in get_rows(
        api_key="sk-ant-admin-test",
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
        a = _row_id("2025-08-01T00:00:00Z", "wrkspc_1", "claude-opus-4-6")
        b = _row_id("2025-08-01T00:00:00Z", "wrkspc_1", "claude-opus-4-6")
        assert a == b

    def test_id_differs_by_dimension(self) -> None:
        a = _row_id("2025-08-01T00:00:00Z", "wrkspc_1", "claude-opus-4-6")
        b = _row_id("2025-08-01T00:00:00Z", "wrkspc_2", "claude-opus-4-6")
        assert a != b

    def test_none_and_empty_string_distinguished_positionally(self) -> None:
        # A missing dimension (None) must not collide with an empty-string value at the same position,
        # and positions stay aligned so distinct dimension tuples never collide either.
        assert _row_id(None, "x") != _row_id("", "x")
        assert _row_id(None, "x") != _row_id("x", None)


class TestBuildUrl:
    def test_repeats_multi_params(self) -> None:
        url = _build_url(
            "/v1/organizations/usage_report/messages", {"limit": 31}, {"group_by[]": ["model", "workspace_id"]}
        )
        assert url.count("group_by") == 2
        assert "limit=31" in url

    def test_drops_none_values(self) -> None:
        url = _build_url("/v1/organizations/users", {"limit": 1000, "after_id": None})
        assert "after_id" not in url


class TestReportParams:
    def test_incremental_uses_watermark_as_starting_at(self) -> None:
        config = anthropic.ANTHROPIC_ENDPOINTS["usage_report"]
        params, multi = _report_params(
            config,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 0, 0, 0, tzinfo=UTC),
        )
        assert params["starting_at"] == "2026-03-04T00:00:00Z"
        assert params["bucket_width"] == "1d"
        assert params["limit"] == 7
        assert multi == {"group_by[]": config.group_by}

    def test_usage_report_page_size_stays_below_bucket_max(self) -> None:
        # Grouping by every dimension multiplies the results per bucket, so requesting the 31-bucket
        # max overflows the per-response result cap and the API 400s. Keep the page small while still
        # grouping by the full set; pagination walks the rest.
        config = anthropic.ANTHROPIC_ENDPOINTS["usage_report"]
        params, _ = _report_params(config, should_use_incremental_field=False, db_incremental_field_last_value=None)
        assert len(config.group_by) == 8
        assert params["limit"] <= 7

    def test_full_refresh_falls_back_to_launch_date(self) -> None:
        # Without a watermark we must still send the required starting_at; the Anthropic launch date
        # pulls all available history without requesting decades of empty pre-launch buckets.
        config = anthropic.ANTHROPIC_ENDPOINTS["cost_report"]
        params, _ = _report_params(config, should_use_incremental_field=False, db_incremental_field_last_value=None)
        assert params["starting_at"] == "2023-01-01T00:00:00Z"


class TestFlattenUsage:
    def test_flattens_nested_objects_and_adds_id(self) -> None:
        bucket = {"starting_at": "2025-08-01T00:00:00Z", "ending_at": "2025-08-02T00:00:00Z"}
        result = {
            "workspace_id": "wrkspc_1",
            "model": "claude-opus-4-6",
            "uncached_input_tokens": 1500,
            "output_tokens": 500,
            "cache_creation": {"ephemeral_1h_input_tokens": 1000, "ephemeral_5m_input_tokens": 500},
            "server_tool_use": {"web_search_requests": 10},
        }
        row = _flatten_usage_result(bucket, result)
        assert row["starting_at"] == "2025-08-01T00:00:00Z"
        assert row["cache_creation_ephemeral_1h_input_tokens"] == 1000
        assert row["cache_creation_ephemeral_5m_input_tokens"] == 500
        assert row["web_search_requests"] == 10
        assert row["id"]

    def test_missing_nested_objects_yield_none_not_crash(self) -> None:
        row = _flatten_usage_result({"starting_at": "s", "ending_at": "e"}, {"model": "m"})
        assert row["cache_creation_ephemeral_1h_input_tokens"] is None
        assert row["web_search_requests"] is None


class TestFlattenCost:
    def test_amount_kept_as_string_and_id_added(self) -> None:
        # amount is a decimal string in cents; coercing it would lose precision.
        row = _flatten_cost_result(
            {"starting_at": "2025-08-01T00:00:00Z", "ending_at": "2025-08-02T00:00:00Z"},
            {"workspace_id": "wrkspc_1", "amount": "123.78912", "currency": "USD", "cost_type": "tokens"},
        )
        assert row["amount"] == "123.78912"
        assert row["currency"] == "USD"
        assert row["id"]


class TestReportPagination:
    def test_follows_next_page_until_has_more_false(self, monkeypatch: Any) -> None:
        responses = [
            {
                "data": [{"starting_at": "d1", "ending_at": "d2", "results": [{"model": "a"}]}],
                "has_more": True,
                "next_page": "PAGE2",
            },
            {
                "data": [{"starting_at": "d2", "ending_at": "d3", "results": [{"model": "b"}]}],
                "has_more": False,
                "next_page": None,
            },
        ]
        manager = _FakeResumableManager()
        rows = _collect(manager, monkeypatch, responses, "usage_report")
        assert [r["model"] for r in rows] == ["a", "b"]
        # Second request must carry the page token from the first response.
        assert "page=PAGE2" in manager._captured_calls[1]  # type: ignore[attr-defined]

    def test_resumes_from_saved_page_cursor(self, monkeypatch: Any) -> None:
        responses = [
            {
                "data": [{"starting_at": "d2", "ending_at": "d3", "results": [{"model": "b"}]}],
                "has_more": False,
                "next_page": None,
            },
        ]
        manager = _FakeResumableManager(AnthropicResumeConfig(cursor="PAGE2"))
        rows = _collect(manager, monkeypatch, responses, "usage_report")
        assert [r["model"] for r in rows] == ["b"]
        assert "page=PAGE2" in manager._captured_calls[0]  # type: ignore[attr-defined]

    def test_drains_every_chunk_when_a_batch_splits(self, monkeypatch: Any) -> None:
        # A batch can split into several ready chunks (byte/offset caps). Force it with tiny limits:
        # if the loop only pops one chunk per batch, the next batch() raises and rows go missing.
        real_batcher = anthropic.Batcher

        def tiny_batcher(**_: Any) -> anthropic.Batcher:
            return real_batcher(logger=MagicMock(), chunk_size=4, chunk_size_bytes=10**12, max_table_bytes=1)

        monkeypatch.setattr(anthropic, "Batcher", tiny_batcher)

        results = [{"model": f"m{i}"} for i in range(8)]
        responses = [
            {
                "data": [{"starting_at": "d1", "ending_at": "d2", "results": results}],
                "has_more": False,
                "next_page": None,
            }
        ]
        rows = _collect(_FakeResumableManager(), monkeypatch, responses, "usage_report")
        assert sorted(r["model"] for r in rows) == [f"m{i}" for i in range(8)]


class TestEntityPagination:
    def test_cursor_pagination_uses_last_id_and_stops(self, monkeypatch: Any) -> None:
        responses = [
            {"data": [{"id": "user_1"}], "has_more": True, "last_id": "user_1"},
            {"data": [{"id": "user_2"}], "has_more": False, "last_id": "user_2"},
        ]
        manager = _FakeResumableManager()
        rows = _collect(manager, monkeypatch, responses, "users")
        assert [r["id"] for r in rows] == ["user_1", "user_2"]
        assert "after_id=user_1" in manager._captured_calls[1]  # type: ignore[attr-defined]

    def test_api_keys_flatten_created_by(self, monkeypatch: Any) -> None:
        responses = [
            {
                "data": [{"id": "apikey_1", "created_by": {"id": "user_1", "type": "user"}}],
                "has_more": False,
                "last_id": "apikey_1",
            }
        ]
        rows = _collect(_FakeResumableManager(), monkeypatch, responses, "api_keys")
        assert rows[0]["created_by_id"] == "user_1"
        assert rows[0]["created_by_type"] == "user"
        assert "created_by" not in rows[0]


class TestWorkspaceMembersFanOut:
    def test_emits_one_row_per_workspace_member_with_composite_key(self, monkeypatch: Any) -> None:
        # First response lists workspaces, then one members page per workspace.
        responses = [
            {"data": [{"id": "wrkspc_1"}, {"id": "wrkspc_2"}], "has_more": False, "last_id": "wrkspc_2"},
            {
                "data": [{"type": "workspace_member", "user_id": "u1", "workspace_id": "wrkspc_1"}],
                "has_more": False,
                "last_id": "u1",
            },
            {
                "data": [{"type": "workspace_member", "user_id": "u2", "workspace_id": "wrkspc_2"}],
                "has_more": False,
                "last_id": "u2",
            },
        ]
        rows = _collect(_FakeResumableManager(), monkeypatch, responses, "workspace_members")
        assert [(r["workspace_id"], r["user_id"]) for r in rows] == [("wrkspc_1", "u1"), ("wrkspc_2", "u2")]


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("forbidden_scope", 403, True), ("unauthorized", 401, False)])
    def test_status_mapping(self, _name: str, status: int, expected: bool) -> None:
        # 403 is accepted at create time (real key, unprobed scope); 401 means a bad key.
        response = MagicMock(status_code=status)
        session = MagicMock()
        session.get.return_value = response
        with patch.object(anthropic, "make_tracked_session", return_value=session):
            assert validate_credentials("sk-ant-admin-test") is expected

    def test_network_error_is_invalid(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with patch.object(anthropic, "make_tracked_session", return_value=session):
            assert validate_credentials("sk-ant-admin-test") is False


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://api.anthropic.com/v1/organizations/users?limit=1",
            ),
            (
                "forbidden",
                "403 Client Error: Forbidden for url: https://api.anthropic.com/v1/organizations/cost_report",
            ),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = AnthropicSource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("read_timeout", "HTTPSConnectionPool(host='api.anthropic.com', port=443): Read timed out."),
            (
                "server_error",
                "500 Server Error: Internal Server Error for url: https://api.anthropic.com/v1/organizations/users",
            ),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = AnthropicSource().get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)

    def test_retries_exhausted_rate_limit_is_expected_retryable_not_non_retryable(self) -> None:
        # A report endpoint that exhausts `_fetch_page`'s in-process 429 backoff re-raises this.
        # It must match get_expected_retryable_errors (logged as a warning, no error-tracking issue)
        # and must not match get_non_retryable_errors (which would stop the job). Building the message
        # from the real raise site guards against the prefix drifting away from the matcher.
        response = MagicMock(status_code=429, ok=False, headers={})
        session = MagicMock()
        session.get.return_value = response
        with patch.object(anthropic._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            with pytest.raises(AnthropicRetryableError) as exc_info:
                anthropic._fetch_page(
                    session, "https://api.anthropic.com/v1/organizations/cost_report", {}, MagicMock()
                )
        message = str(exc_info.value)
        source = AnthropicSource()
        assert any(key in message for key in source.get_expected_retryable_errors())
        assert not any(key in message for key in source.get_non_retryable_errors())


class TestFetchPage:
    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_retryable_statuses_raise_retryable_error(self, _name: str, status: int) -> None:
        response = MagicMock(status_code=status, ok=False)
        session = MagicMock()
        session.get.return_value = response
        with patch.object(anthropic._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            with pytest.raises(anthropic.AnthropicRetryableError):
                anthropic._fetch_page(session, "https://api.anthropic.com/v1/organizations/users", {}, MagicMock())
        assert session.get.call_count == 5  # exhausts the retry budget

    def test_client_error_raises_for_status_without_retry(self) -> None:
        response = MagicMock(status_code=401, ok=False, text="unauthorized")
        response.raise_for_status.side_effect = requests.HTTPError("401 Client Error", response=response)
        session = MagicMock()
        session.get.return_value = response
        with pytest.raises(requests.HTTPError):
            anthropic._fetch_page(session, "https://api.anthropic.com/v1/organizations/users", {}, MagicMock())
        assert session.get.call_count == 1


class _FakeRetryState:
    def __init__(self, exc: Exception | None, attempt_number: int = 1) -> None:
        self.outcome = MagicMock()
        self.outcome.exception.return_value = exc
        self.attempt_number = attempt_number


class TestRetryAfter:
    @parameterized.expand(
        [
            ("delta_seconds", "45", 45.0),
            ("zero", "0", 0.0),
            ("missing", None, None),
            ("non_numeric", "in a while", None),
            ("negative", "-5", None),
        ]
    )
    def test_parse_retry_after(self, _name: str, header: str | None, expected: float | None) -> None:
        assert _parse_retry_after(header) == expected

    def test_fetch_page_attaches_retry_after_from_header(self) -> None:
        # The rate-limited report endpoints tell us exactly when the window resets; that value must
        # survive onto the exception so the wait strategy can honor it instead of guessing.
        response = MagicMock(status_code=429, ok=False, headers={"retry-after": "45"})
        session = MagicMock()
        session.get.return_value = response
        with patch.object(anthropic._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            with pytest.raises(AnthropicRetryableError) as exc_info:
                anthropic._fetch_page(
                    session, "https://api.anthropic.com/v1/organizations/cost_report", {}, MagicMock()
                )
        assert exc_info.value.retry_after == 45.0

    def test_wait_honors_retry_after_capped(self) -> None:
        state = _FakeRetryState(AnthropicRetryableError("rate limited", retry_after=45.0))
        assert _wait_anthropic(cast(RetryCallState, state)) == 45.0
        # A server asking for longer than the cap is clamped so it can't wedge the worker.
        capped = _FakeRetryState(AnthropicRetryableError("rate limited", retry_after=6000.0))
        assert _wait_anthropic(cast(RetryCallState, capped)) == _MAX_RETRY_AFTER_SECONDS

    def test_wait_falls_back_when_no_retry_after(self) -> None:
        # No header (e.g. a 5xx) → blind exponential backoff, never a crash on the missing value.
        state = _FakeRetryState(AnthropicRetryableError("server error"), attempt_number=1)
        wait = _wait_anthropic(cast(RetryCallState, state))
        assert isinstance(wait, float)
        assert wait >= 0
