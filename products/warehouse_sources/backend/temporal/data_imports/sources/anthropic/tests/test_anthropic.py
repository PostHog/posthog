import json
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.anthropic.anthropic import (
    ANTHROPIC_VERSION,
    DEFAULT_CLAUDE_CODE_START,
    AnthropicResumeConfig,
    ClaudeCodeDayPaginator,
    _claude_code_start_day,
    _flatten_claude_code_core,
    _flatten_claude_code_models,
    _flatten_cost_result,
    _flatten_usage_result,
    _row_id,
    anthropic_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.anthropic.settings import ANTHROPIC_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.anthropic.source import AnthropicSource

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the anthropic module.
ANTHROPIC_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.anthropic.anthropic.make_tracked_session"
)

MEMBERS_PATH = "/v1/organizations/workspaces/{workspace_id}/members"


def _response(body: dict[str, Any], status: int = 200, headers: dict[str, str] | None = None) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    resp.url = "https://api.anthropic.com/v1/organizations/users"
    if headers:
        resp.headers.update(headers)
    return resp


def _entity_page(items: list[dict[str, Any]], *, has_more: bool, last_id: str | None) -> Response:
    return _response({"data": items, "has_more": has_more, "first_id": None, "last_id": last_id})


def _report_page(buckets: list[dict[str, Any]], *, has_more: bool, next_page: str | None) -> Response:
    return _response({"data": buckets, "has_more": has_more, "next_page": next_page})


def _make_manager(resume_state: AnthropicResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's url + params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {})})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _source(endpoint: str, manager: mock.MagicMock, last_value: Any = None):
    return anthropic_source(
        api_key="sk-ant-admin-test",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        db_incremental_field_last_value=last_value,
    )


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


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

    def test_inference_geo_surfaced(self) -> None:
        # The data-residency dimension is parsed into cost results when grouped by description; surface
        # it as its own column rather than dropping it on the floor.
        row = _flatten_cost_result(
            {"starting_at": "2025-08-01T00:00:00Z", "ending_at": "2025-08-02T00:00:00Z"},
            {"workspace_id": "wrkspc_1", "amount": "1.0", "inference_geo": "us"},
        )
        assert row["inference_geo"] == "us"

    def test_id_stable_when_inference_geo_added(self) -> None:
        # inference_geo is deliberately kept out of the surrogate key (description already disambiguates
        # it), so surfacing it must not change the id of a row that existed before the column was added.
        base = {"starting_at": "s", "ending_at": "e", "workspace_id": "w", "description": "d", "amount": "1"}
        without_geo = _flatten_cost_result({"starting_at": "s", "ending_at": "e"}, base)
        with_geo = _flatten_cost_result({"starting_at": "s", "ending_at": "e"}, {**base, "inference_geo": "us"})
        assert without_geo["id"] == with_geo["id"]


class TestReportParams:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_uses_watermark_as_starting_at(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_report_page([], has_more=False, next_page=None)])

        _rows(_source("usage_report", _make_manager(), last_value=datetime(2026, 3, 4, 0, 0, 0, tzinfo=UTC)))

        config = ANTHROPIC_ENDPOINTS["usage_report"]
        assert params[0]["params"]["starting_at"] == "2026-03-04T00:00:00Z"
        assert params[0]["params"]["bucket_width"] == "1d"
        assert params[0]["params"]["limit"] == 7
        # requests encodes the list as one repeated group_by[] query param per dimension.
        assert params[0]["params"]["group_by[]"] == config.group_by

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_falls_back_to_launch_date(self, MockSession) -> None:
        # Without a watermark we must still send the required starting_at; the Anthropic launch date
        # pulls all available history without requesting decades of empty pre-launch buckets.
        session = MockSession.return_value
        params = _wire(session, [_report_page([], has_more=False, next_page=None)])

        _rows(_source("cost_report", _make_manager()))

        assert params[0]["params"]["starting_at"] == "2023-01-01T00:00:00Z"

    def test_usage_report_page_size_stays_below_bucket_max(self) -> None:
        # Grouping by every dimension multiplies the results per bucket, so requesting the 31-bucket
        # max overflows the per-response result cap and the API 400s. Keep the page small while still
        # grouping by the full set; pagination walks the rest.
        config = ANTHROPIC_ENDPOINTS["usage_report"]
        assert len(config.group_by) == 8
        assert config.limit is not None and config.limit <= 7

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_version_header_is_set_on_session(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_entity_page([{"id": "user_1"}], has_more=False, last_id="user_1")])

        _rows(_source("users", _make_manager()))
        assert session.headers.get("anthropic-version") == ANTHROPIC_VERSION


class TestReportPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_next_page_until_has_more_false(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _report_page(
                    [{"starting_at": "d1", "ending_at": "d2", "results": [{"model": "a"}]}],
                    has_more=True,
                    next_page="PAGE2",
                ),
                _report_page(
                    [{"starting_at": "d2", "ending_at": "d3", "results": [{"model": "b"}]}],
                    has_more=False,
                    next_page=None,
                ),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("usage_report", manager))

        assert [r["model"] for r in rows] == ["a", "b"]
        # Second request must carry the page token from the first response; the first must not.
        assert "page" not in params[0]["params"]
        assert params[1]["params"]["page"] == "PAGE2"
        # Checkpoint saved after the first page was yielded, pointing at the next page.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == AnthropicResumeConfig(cursor="PAGE2")

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_explodes_every_result_in_a_bucket(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _report_page(
                    [
                        {
                            "starting_at": "d1",
                            "ending_at": "d2",
                            "results": [{"model": "a"}, {"model": "b"}],
                        },
                        {"starting_at": "d2", "ending_at": "d3", "results": []},
                    ],
                    has_more=False,
                    next_page=None,
                ),
            ],
        )

        rows = _rows(_source("usage_report", _make_manager()))

        # Two rows from the first bucket (bucket window merged into each), none from the empty one.
        assert [(r["model"], r["starting_at"], r["ending_at"]) for r in rows] == [
            ("a", "d1", "d2"),
            ("b", "d1", "d2"),
        ]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _report_page(
                    [{"starting_at": "d2", "ending_at": "d3", "results": [{"model": "b"}]}],
                    has_more=False,
                    next_page=None,
                ),
            ],
        )

        manager = _make_manager(AnthropicResumeConfig(cursor="PAGE2"))
        rows = _rows(_source("usage_report", manager))

        assert [r["model"] for r in rows] == ["b"]
        assert params[0]["params"]["page"] == "PAGE2"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_when_has_more_false_even_with_next_page_token(self, MockSession) -> None:
        # `has_more` is the authoritative stop signal — a stray token on the final page must not
        # trigger an extra request.
        session = MockSession.return_value
        _wire(
            session,
            [
                _report_page(
                    [{"starting_at": "d1", "ending_at": "d2", "results": [{"model": "a"}]}],
                    has_more=False,
                    next_page="STRAY",
                ),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("cost_report", manager))

        assert len(rows) == 1
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()


class TestEntityPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_cursor_pagination_uses_last_id_and_stops_on_has_more_false(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _entity_page([{"id": "user_1"}], has_more=True, last_id="user_1"),
                # Final page still carries a last_id — has_more must stop the walk with no extra call.
                _entity_page([{"id": "user_2"}], has_more=False, last_id="user_2"),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("users", manager))

        assert [r["id"] for r in rows] == ["user_1", "user_2"]
        assert "after_id" not in params[0]["params"]
        assert params[0]["params"]["limit"] == 1000
        assert params[1]["params"]["after_id"] == "user_1"
        assert session.send.call_count == 2
        # Checkpoint saved after the first page, pointing past it; nothing saved on the final page.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == AnthropicResumeConfig(cursor="user_1")

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_after_id(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_entity_page([{"id": "user_6"}], has_more=False, last_id="user_6")])

        _rows(_source("users", _make_manager(AnthropicResumeConfig(cursor="user_5"))))

        assert params[0]["params"]["after_id"] == "user_5"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_api_keys_flatten_created_by(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _entity_page(
                    [{"id": "apikey_1", "created_by": {"id": "user_1", "type": "user"}}],
                    has_more=False,
                    last_id="apikey_1",
                )
            ],
        )

        rows = _rows(_source("api_keys", _make_manager()))

        assert rows[0]["created_by_id"] == "user_1"
        assert rows[0]["created_by_type"] == "user"
        assert "created_by" not in rows[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_workspaces_include_archived(self, MockSession) -> None:
        # Archived workspaces are still referenced by historical usage/cost rows, so the dimension
        # table must stay complete.
        session = MockSession.return_value
        params = _wire(session, [_entity_page([{"id": "wrkspc_1"}], has_more=False, last_id="wrkspc_1")])

        _rows(_source("workspaces", _make_manager()))

        assert params[0]["params"]["include_archived"] == "true"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_data_key_yields_no_rows(self, MockSession) -> None:
        # The legacy implementation tolerated a body without `data` (0 rows); preserve that.
        session = MockSession.return_value
        _wire(session, [_response({"has_more": False, "last_id": None})])

        assert _rows(_source("users", _make_manager())) == []


class TestWorkspaceMembersFanOut:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_emits_one_row_per_workspace_member_with_composite_key(self, MockSession) -> None:
        # First response lists workspaces, then one members page per workspace.
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _entity_page([{"id": "wrkspc_1"}, {"id": "wrkspc_2"}], has_more=False, last_id="wrkspc_2"),
                _entity_page(
                    [{"type": "workspace_member", "user_id": "u1", "workspace_id": "wrkspc_1"}],
                    has_more=False,
                    last_id="u1",
                ),
                _entity_page(
                    # The API always sends workspace_id, but stamp it from the parent defensively
                    # so the composite primary key is populated even if it goes missing.
                    [{"type": "workspace_member", "user_id": "u2"}],
                    has_more=False,
                    last_id="u2",
                ),
            ],
        )

        rows = _rows(_source("workspace_members", _make_manager()))

        assert [(r["workspace_id"], r["user_id"]) for r in rows] == [("wrkspc_1", "u1"), ("wrkspc_2", "u2")]
        # The framework's parent-key column must not leak into the row shape.
        assert all("_workspaces_id" not in r for r in rows)
        assert params[0]["url"].endswith("/v1/organizations/workspaces")
        assert params[0]["params"]["include_archived"] == "true"
        assert params[1]["url"].endswith("/v1/organizations/workspaces/wrkspc_1/members")
        assert params[2]["url"].endswith("/v1/organizations/workspaces/wrkspc_2/members")

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_checkpoints_completed_workspaces(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _entity_page([{"id": "wrkspc_1"}, {"id": "wrkspc_2"}], has_more=False, last_id="wrkspc_2"),
                _entity_page([{"user_id": "u1", "workspace_id": "wrkspc_1"}], has_more=False, last_id="u1"),
                _entity_page([{"user_id": "u2", "workspace_id": "wrkspc_2"}], has_more=False, last_id="u2"),
            ],
        )

        manager = _make_manager()
        _rows(_source("workspace_members", manager))

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved, "fan-out must checkpoint progress"
        assert all(isinstance(state, AnthropicResumeConfig) and state.fanout_state for state in saved)
        final = saved[-1].fanout_state
        assert final["completed"] == [
            MEMBERS_PATH.format(workspace_id="wrkspc_1"),
            MEMBERS_PATH.format(workspace_id="wrkspc_2"),
        ]
        assert final["current"] is None

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_skipping_completed_workspaces(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _entity_page([{"id": "wrkspc_1"}, {"id": "wrkspc_2"}], has_more=False, last_id="wrkspc_2"),
                # Only wrkspc_2's members are fetched — wrkspc_1 completed before the crash.
                _entity_page([{"user_id": "u2", "workspace_id": "wrkspc_2"}], has_more=False, last_id="u2"),
            ],
        )

        resume = AnthropicResumeConfig(
            fanout_state={
                "completed": [MEMBERS_PATH.format(workspace_id="wrkspc_1")],
                "current": None,
                "child_state": None,
            }
        )
        rows = _rows(_source("workspace_members", _make_manager(resume)))

        assert [(r["workspace_id"], r["user_id"]) for r in rows] == [("wrkspc_2", "u2")]
        assert session.send.call_count == 2
        assert params[1]["url"].endswith("/v1/organizations/workspaces/wrkspc_2/members")

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_legacy_resume_state_restarts_fan_out_fresh(self, MockSession) -> None:
        # Pre-framework state carried (cursor, workspace_id). It still parses, but the fan-out
        # restarts from scratch — the overlap merge dedupes on the composite key.
        session = MockSession.return_value
        _wire(
            session,
            [
                _entity_page([{"id": "wrkspc_1"}], has_more=False, last_id="wrkspc_1"),
                _entity_page([{"user_id": "u1", "workspace_id": "wrkspc_1"}], has_more=False, last_id="u1"),
            ],
        )

        resume = AnthropicResumeConfig(cursor="u0", workspace_id="wrkspc_1")
        rows = _rows(_source("workspace_members", _make_manager(resume)))

        assert [(r["workspace_id"], r["user_id"]) for r in rows] == [("wrkspc_1", "u1")]

    def test_saved_state_shapes_still_parse(self) -> None:
        # ResumableSourceManager._load_json does dataclass(**saved) — every historical shape must
        # keep parsing after the migration.
        assert AnthropicResumeConfig(
            **cast("dict[str, Any]", {"cursor": "PAGE2", "workspace_id": None})
        ) == AnthropicResumeConfig(cursor="PAGE2")
        assert (
            AnthropicResumeConfig(**cast("dict[str, Any]", {"cursor": "u1", "workspace_id": "wrkspc_2"})).workspace_id
            == "wrkspc_2"
        )
        assert AnthropicResumeConfig(**cast("dict[str, Any]", {"fanout_state": {"completed": []}})).fanout_state == {
            "completed": []
        }


class TestRetries:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_rate_limited_request_is_retried_honoring_retry_after(self, MockSession) -> None:
        # The report endpoints are strictly rate limited and return Retry-After on 429; the request
        # must be reissued (Retry-After: 0 keeps the test instant) and the rows still delivered.
        session = MockSession.return_value
        _wire(
            session,
            [
                _response({}, status=429, headers={"Retry-After": "0"}),
                _entity_page([{"id": "user_1"}], has_more=False, last_id="user_1"),
            ],
        )

        rows = _rows(_source("users", _make_manager()))

        assert [r["id"] for r in rows] == ["user_1"]
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_error_raises_without_retry(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"error": "unauthorized"}, status=401)])

        with pytest.raises(requests.HTTPError):
            _rows(_source("users", _make_manager()))
        assert session.send.call_count == 1


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("forbidden_scope", 403, True), ("unauthorized", 401, False)])
    def test_status_mapping(self, _name: str, status: int, expected: bool) -> None:
        # 403 is accepted at create time (real key, unprobed scope); 401 means a bad key.
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=status)
        with mock.patch(ANTHROPIC_SESSION_PATCH, return_value=session):
            assert validate_credentials("sk-ant-admin-test") is expected

    def test_network_error_is_invalid(self) -> None:
        session = mock.MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with mock.patch(ANTHROPIC_SESSION_PATCH, return_value=session):
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


def _cc_record(actor_email: str = "dev@example.com") -> dict[str, Any]:
    return {
        "date": "2025-09-01T00:00:00Z",
        "organization_id": "org_1",
        "actor": {"type": "user_actor", "email_address": actor_email},
        "customer_type": "subscription",
        "terminal_type": "vscode",
        "core_metrics": {
            "num_sessions": 1,
            "lines_of_code": {"added": 1, "removed": 0},
            "commits_by_claude_code": 0,
            "pull_requests_by_claude_code": 0,
        },
        "tool_actions": {},
        "model_breakdown": [
            {"model": "claude-opus-4-8", "tokens": {"input": 1}, "estimated_cost": {"amount": "1", "currency": "USD"}}
        ],
    }


def _cc_page(records: list[dict[str, Any]], *, has_more: bool, next_page: str | None) -> Response:
    return _response({"data": records, "has_more": has_more, "next_page": next_page})


def _midnight(day: date) -> datetime:
    return datetime.combine(day, datetime.min.time(), tzinfo=UTC)


class TestFlattenClaudeCode:
    _RECORD = {
        "date": "2025-09-01T00:00:00Z",
        "organization_id": "org_1",
        "actor": {"type": "user_actor", "email_address": "dev@example.com"},
        "customer_type": "subscription",
        "terminal_type": "vscode",
        "core_metrics": {
            "num_sessions": 4,
            "lines_of_code": {"added": 120, "removed": 30},
            "commits_by_claude_code": 3,
            "pull_requests_by_claude_code": 1,
        },
        "tool_actions": {
            "edit_tool": {"accepted": 10, "rejected": 2},
            "write_tool": {"accepted": 5, "rejected": 0},
        },
        "model_breakdown": [
            {
                "model": "claude-opus-4-8",
                "tokens": {"input": 1000, "output": 500, "cache_read": 200, "cache_creation": 100},
                "estimated_cost": {"amount": "12.50", "currency": "USD"},
            },
            {
                "model": "claude-haiku-4-5",
                "tokens": {"input": 50, "output": 20, "cache_read": 0, "cache_creation": 0},
                "estimated_cost": {"amount": "0.10", "currency": "USD"},
            },
        ],
    }

    def test_core_flattens_metrics_and_tool_actions(self) -> None:
        row = _flatten_claude_code_core(self._RECORD)
        assert row["actor_type"] == "user_actor"
        assert row["actor_email_address"] == "dev@example.com"
        assert row["actor_api_key_name"] is None
        assert row["num_sessions"] == 4
        assert row["lines_of_code_added"] == 120
        assert row["lines_of_code_removed"] == 30
        assert row["edit_tool_accepted"] == 10
        assert row["edit_tool_rejected"] == 2
        assert row["write_tool_accepted"] == 5
        # A tool the record omits yields nulls, never a crash.
        assert row["multi_edit_tool_accepted"] is None
        assert row["id"]

    def test_api_actor_surfaces_key_name_not_email(self) -> None:
        record = {**self._RECORD, "actor": {"type": "api_actor", "api_key_name": "ci-key"}}
        row = _flatten_claude_code_core(record)
        assert row["actor_api_key_name"] == "ci-key"
        assert row["actor_email_address"] is None

    def test_models_explode_one_row_per_model_with_distinct_ids(self) -> None:
        rows = _flatten_claude_code_models(self._RECORD)
        assert [r["model"] for r in rows] == ["claude-opus-4-8", "claude-haiku-4-5"]
        assert rows[0]["input_tokens"] == 1000
        assert rows[0]["cache_creation_tokens"] == 100
        assert rows[0]["estimated_cost_amount"] == "12.50"
        # Per-model rows for the same (day, actor) must have distinct ids so merge keeps them apart.
        assert rows[0]["id"] != rows[1]["id"]

    def test_empty_model_breakdown_yields_no_rows(self) -> None:
        assert _flatten_claude_code_models({**self._RECORD, "model_breakdown": []}) == []


class TestClaudeCodeStartDay:
    def test_full_refresh_uses_launch_floor(self) -> None:
        assert _claude_code_start_day(None) == DEFAULT_CLAUDE_CODE_START

    @parameterized.expand(
        [
            ("datetime", datetime(2026, 3, 4, 12, 0, 0, tzinfo=UTC)),
            ("rfc3339_string", "2026-03-04T12:00:00Z"),
            ("bare_date_string", "2026-03-04"),
            ("date", date(2026, 3, 4)),
        ]
    )
    def test_incremental_watermark_resolves_to_calendar_day(self, _name: str, watermark: Any) -> None:
        assert _claude_code_start_day(watermark) == date(2026, 3, 4)


class TestClaudeCodeDayPaginator:
    def test_advances_day_when_exhausted_and_stops_past_today(self) -> None:
        paginator = ClaudeCodeDayPaginator(date(2025, 1, 1), date(2025, 1, 3))
        req = Request()
        paginator.init_request(req)
        assert req.params["starting_at"] == "2025-01-01"

        paginator.update_state(_cc_page([_cc_record()], has_more=False, next_page=None), data=[{"x": 1}])
        assert paginator.has_next_page is True
        req2 = Request()
        paginator.update_request(req2)
        assert req2.params["starting_at"] == "2025-01-02"
        assert "page" not in req2.params

        paginator.update_state(_cc_page([], has_more=False, next_page=None), data=[])  # day 2 -> day 3
        assert paginator.has_next_page is True
        paginator.update_state(_cc_page([], has_more=False, next_page=None), data=[])  # day 3 -> past today
        assert paginator.has_next_page is False

    def test_stays_on_day_across_pages(self) -> None:
        paginator = ClaudeCodeDayPaginator(date(2025, 1, 1), date(2025, 1, 1))
        paginator.update_state(_cc_page([_cc_record()], has_more=True, next_page="P2"), data=[{"x": 1}])
        assert paginator.has_next_page is True
        req = Request()
        paginator.update_request(req)
        assert req.params["starting_at"] == "2025-01-01"
        assert req.params["page"] == "P2"

    def test_resume_state_roundtrip(self) -> None:
        paginator = ClaudeCodeDayPaginator(date(2025, 1, 1), date(2025, 1, 5))
        paginator.set_resume_state({"date": "2025-01-04", "cursor": "PX"})
        req = Request()
        paginator.init_request(req)
        assert req.params["starting_at"] == "2025-01-04"
        assert req.params["page"] == "PX"
        assert paginator.get_resume_state() == {"date": "2025-01-04", "cursor": "PX"}

    def test_clamps_future_start_day_to_today(self) -> None:
        # A watermark at/after today must re-pull today, never request a future day.
        paginator = ClaudeCodeDayPaginator(date(2025, 6, 1), date(2025, 1, 1))
        req = Request()
        paginator.init_request(req)
        assert req.params["starting_at"] == "2025-01-01"


class TestClaudeCodeDayFanOut:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_fans_out_one_windowed_request_per_day(self, MockSession) -> None:
        session = MockSession.return_value
        today = datetime.now(UTC).date()
        watermark = _midnight(today - timedelta(days=2))
        params = _wire(session, [_cc_page([_cc_record()], has_more=False, next_page=None) for _ in range(3)])
        rows = _rows(_source("claude_code_analytics", _make_manager(), last_value=watermark))
        assert len(rows) == 3  # one per-day core row
        days = [(watermark.date() + timedelta(days=i)).isoformat() for i in range(3)]
        assert [p["params"]["starting_at"] for p in params] == days

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_model_breakdown_endpoint_explodes_per_model(self, MockSession) -> None:
        session = MockSession.return_value
        today = datetime.now(UTC).date()
        record = _cc_record()
        record["model_breakdown"] = [
            {"model": "m1", "tokens": {"input": 1}, "estimated_cost": {"amount": "1", "currency": "USD"}},
            {"model": "m2", "tokens": {"input": 2}, "estimated_cost": {"amount": "2", "currency": "USD"}},
        ]
        _wire(session, [_cc_page([record], has_more=False, next_page=None)])
        rows = _rows(_source("claude_code_model_breakdown", _make_manager(), last_value=_midnight(today)))
        assert sorted(r["model"] for r in rows) == ["m1", "m2"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_within_a_day(self, MockSession) -> None:
        session = MockSession.return_value
        today = datetime.now(UTC).date()
        params = _wire(
            session,
            [
                _cc_page([_cc_record("a@x.com")], has_more=True, next_page="P2"),
                _cc_page([_cc_record("b@x.com")], has_more=False, next_page=None),
            ],
        )
        rows = _rows(_source("claude_code_analytics", _make_manager(), last_value=_midnight(today)))
        assert {r["actor_email_address"] for r in rows} == {"a@x.com", "b@x.com"}
        assert "page" not in params[0]["params"]
        assert params[1]["params"]["page"] == "P2"
        assert params[1]["params"]["starting_at"] == today.isoformat()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_day_and_page_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        today = datetime.now(UTC).date()
        manager = _make_manager(AnthropicResumeConfig(day_fanout_state={"date": today.isoformat(), "cursor": "P2"}))
        params = _wire(session, [_cc_page([_cc_record()], has_more=False, next_page=None)])
        rows = _rows(_source("claude_code_analytics", manager, last_value=_midnight(today)))
        assert len(rows) == 1
        assert params[0]["params"]["page"] == "P2"
        assert params[0]["params"]["starting_at"] == today.isoformat()


class TestServiceAccountsFanOut:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_emits_one_row_per_service_account_with_composite_key(self, MockSession) -> None:
        session = MockSession.return_value
        # Service account objects here don't carry workspace_id, so the fan-out must inject it or the
        # composite key's workspace_id lands null.
        _wire(
            session,
            [
                _entity_page([{"id": "wrkspc_1"}, {"id": "wrkspc_2"}], has_more=False, last_id="wrkspc_2"),
                _entity_page([{"id": "svac_1", "type": "service_account"}], has_more=False, last_id="svac_1"),
                _entity_page([{"id": "svac_2", "type": "service_account"}], has_more=False, last_id="svac_2"),
            ],
        )
        rows = _rows(_source("service_accounts", _make_manager()))
        assert [(r["workspace_id"], r["id"]) for r in rows] == [("wrkspc_1", "svac_1"), ("wrkspc_2", "svac_2")]
