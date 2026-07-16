import json
from datetime import UTC, datetime
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.anthropic.anthropic import (
    ANTHROPIC_VERSION,
    AnthropicResumeConfig,
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
        assert AnthropicResumeConfig(**{"cursor": "PAGE2", "workspace_id": None}) == AnthropicResumeConfig(
            cursor="PAGE2"
        )
        assert AnthropicResumeConfig(**{"cursor": "u1", "workspace_id": "wrkspc_2"}).workspace_id == "wrkspc_2"
        assert AnthropicResumeConfig(**{"fanout_state": {"completed": []}}).fanout_state == {"completed": []}


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
