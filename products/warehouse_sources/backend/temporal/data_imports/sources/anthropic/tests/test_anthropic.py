import json
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.anthropic.anthropic import (
    ANALYTICS_ACCESS_MISSING,
    ANTHROPIC_VERSION,
    DEFAULT_CLAUDE_CODE_START,
    MAX_RETRY_ATTEMPTS,
    REPORT_MAX_RETRY_ATTEMPTS,
    AnthropicResumeConfig,
    ClaudeCodeDayPaginator,
    _analytics_windows,
    _claude_code_start_day,
    _flatten_analytics_entity_usage,
    _flatten_analytics_user_activity,
    _flatten_analytics_user_cost,
    _flatten_analytics_user_usage,
    _flatten_claude_code_core,
    _flatten_claude_code_models,
    _flatten_cost_result,
    _flatten_rbac_role_permission,
    _flatten_usage_result,
    _row_id,
    anthropic_source,
    check_analytics_access,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.anthropic.settings import (
    ANALYTICS_DATA_FLOOR,
    ANALYTICS_ENGAGEMENT_LAG_DAYS,
    ANALYTICS_PATH_PREFIX,
    ANALYTICS_REPORT_MAX_HISTORY_DAYS,
    ANTHROPIC_ENDPOINTS,
    COST_REPORT_PAGE_BUCKETS,
    RBAC_GROUPS_PATH,
    RBAC_ROLES_PATH,
    USAGE_GROUP_BY_FALLBACKS,
    USAGE_REPORT_PAGE_BUCKETS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.anthropic.source import AnthropicSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches

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
        assert params[0]["params"]["limit"] == USAGE_REPORT_PAGE_BUCKETS
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

    def test_cost_report_pages_at_the_bucket_max(self) -> None:
        # Every page is one request against a per-organization rate limit, so leaving the cost
        # report on the API's default page walks history in four times as many requests.
        assert ANTHROPIC_ENDPOINTS["cost_report"].limit == COST_REPORT_PAGE_BUCKETS == 31

    def test_usage_group_by_fallbacks_narrow_to_nothing(self) -> None:
        # The list is walked in order when the API rejects a query, so each step must be strictly
        # narrower than the last and the final one must be a query the endpoint cannot refuse.
        steps = list(zip(USAGE_GROUP_BY_FALLBACKS, USAGE_GROUP_BY_FALLBACKS[1:]))
        assert steps and all(set(later) < set(earlier) for earlier, later in steps)
        assert USAGE_GROUP_BY_FALLBACKS[-1] == []

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

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_workspace_that_does_not_serve_the_sub_resource_is_skipped(self, MockSession) -> None:
        # A workspace can 404 on the fan-out child (it does not serve that sub-resource, or was
        # archived between enumeration and the fetch). Skip only that workspace instead of failing
        # the whole schema, and still deliver the workspaces that do serve it.
        session = MockSession.return_value
        _wire(
            session,
            [
                _entity_page([{"id": "wrkspc_1"}, {"id": "wrkspc_2"}], has_more=False, last_id="wrkspc_2"),
                _response({"error": "not_found"}, status=404),
                _entity_page([{"user_id": "u2", "workspace_id": "wrkspc_2"}], has_more=False, last_id="u2"),
            ],
        )

        rows = _rows(_source("workspace_members", _make_manager()))

        assert [(r["workspace_id"], r["user_id"]) for r in rows] == [("wrkspc_2", "u2")]

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

    @mock.patch("tenacity.nap.time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_rate_limit_budget_outlasts_the_default(self, MockSession, _mock_sleep) -> None:
        # The report endpoints 429 without a Retry-After, so the client falls back to exponential
        # backoff; the default budget is spent in seconds, well short of a per-minute limit window.
        session = MockSession.return_value
        _wire(
            session,
            [
                *[_response({}, status=429) for _ in range(MAX_RETRY_ATTEMPTS - 1)],
                _entity_page([{"id": "user_1"}], has_more=False, last_id="user_1"),
            ],
        )

        rows = _rows(_source("users", _make_manager()))

        assert [r["id"] for r in rows] == ["user_1"]
        assert session.send.call_count == MAX_RETRY_ATTEMPTS

    @mock.patch("tenacity.nap.time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_report_endpoint_gets_a_wider_retry_budget(self, MockSession, _mock_sleep) -> None:
        # The report endpoints share one organization rate limit and 429 without a Retry-After, so
        # they need more attempts than the entity lists to outlast the window. A burst that would
        # exhaust the entity budget still resolves for a report endpoint.
        session = MockSession.return_value
        _wire(
            session,
            [
                *[_response({}, status=429) for _ in range(REPORT_MAX_RETRY_ATTEMPTS - 1)],
                _report_page([{"starting_at": "2024-01-01", "results": []}], has_more=False, next_page=None),
            ],
        )

        _rows(_source("cost_report", _make_manager()))

        assert session.send.call_count == REPORT_MAX_RETRY_ATTEMPTS
        assert REPORT_MAX_RETRY_ATTEMPTS > MAX_RETRY_ATTEMPTS


class TestUsageReportGroupByFallback:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_rejected_query_is_retried_with_a_narrower_group_by(self, MockSession) -> None:
        # The usage report 400s a query that groups more finely than it will serve. Narrowing must
        # keep the sync alive and still deliver rows, at the finest breakdown the API accepts.
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response({"error": "bad request"}, status=400),
                _report_page(
                    [{"starting_at": "2025-08-01T00:00:00Z", "results": [{"workspace_id": "wrkspc_1"}]}],
                    has_more=False,
                    next_page=None,
                ),
            ],
        )

        rows = _rows(_source("usage_report", _make_manager()))

        assert [r["workspace_id"] for r in rows] == ["wrkspc_1"]
        assert [p["params"]["group_by[]"] for p in params] == USAGE_GROUP_BY_FALLBACKS[:2]

    @parameterized.expand(
        [
            # Every fallback rejected: there is nothing narrower left to try.
            (
                "all_rejected",
                [_response({}, status=400) for _ in USAGE_GROUP_BY_FALLBACKS],
                len(USAGE_GROUP_BY_FALLBACKS),
            ),
            # A 404 is not the API refusing the breakdown, so narrowing must not paper over it.
            ("not_a_bad_request", [_response({}, status=404)], 1),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_error_propagates_instead_of_narrowing(
        self, _name: str, responses: list[Response], expected_requests: int, MockSession
    ) -> None:
        session = MockSession.return_value
        _wire(session, responses)

        with pytest.raises(requests.HTTPError):
            _rows(_source("usage_report", _make_manager()))
        assert session.send.call_count == expected_requests

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_rejection_after_rows_are_out_is_not_narrowed(self, MockSession) -> None:
        # Re-running at a coarser grain would re-emit the buckets already yielded under different
        # synthesized ids, so once rows are out the 400 has to fail the sync instead.
        session = MockSession.return_value
        _wire(
            session,
            [
                _report_page(
                    [{"starting_at": "2025-08-01T00:00:00Z", "results": [{"workspace_id": "wrkspc_1"}]}],
                    has_more=True,
                    next_page="page_2",
                ),
                _response({"error": "bad request"}, status=400),
            ],
        )

        with pytest.raises(requests.HTTPError):
            _rows(_source("usage_report", _make_manager()))
        assert session.send.call_count == 2


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


class TestRetiredEndpoint:
    def test_a_dropped_endpoint_fails_non_retryably(self) -> None:
        # A schema row discovered before an endpoint was dropped still names it, and its schedule
        # keeps firing. The run must fail with a message the source classifies as non-retryable, so
        # it disables the schema and pauses the schedule instead of retrying a KeyError forever.
        with pytest.raises(ValueError) as exc:
            _source("service_accounts", _make_manager())
        assert error_message_matches(str(exc.value), AnthropicSource().get_non_retryable_errors().keys())


def _analytics_page(rows: list[dict[str, Any]], *, next_page: str | None) -> Response:
    # `/organizations/analytics/users` sends no `has_more`: a null `next_page` is the last page.
    return _response({"data": rows, "next_page": next_page})


def _activity_record(email: str = "dev@example.com") -> dict[str, Any]:
    return {
        "user": {"id": "user_1", "email_address": email, "type": "user"},
        "chat_metrics": {"message_count": 7, "distinct_conversation_count": 2},
        "claude_code_metrics": {
            "core_metrics": {"commit_count": 3, "lines_of_code": {"added_count": 120, "removed_count": 30}},
            "tool_actions": {"edit_tool": {"accepted_count": 10, "rejected_count": 2}},
        },
        "office_metrics": {"excel": {"message_count": 1}},
        "web_search_count": 4,
    }


def _user_report_row(user_id: str = "user_1", starting_at: str = "2026-03-04T00:00:00Z") -> dict[str, Any]:
    return {
        "actor": {
            "user_id": user_id,
            "email": "dev@example.com",
            "name": "Dev",
            "deleted": False,
            "type": "user_actor",
        },
        "starting_at": starting_at,
        "ending_at": "2026-03-05T00:00:00Z",
        "amount": "41280.000000",
        "list_amount": "51600.000000",
        "currency": "USD",
        "requests": 128,
        "uncached_input_tokens": 1284500,
        "cache_read_input_tokens": 3200000,
        "cache_creation": {"ephemeral_1h_input_tokens": 1000, "ephemeral_5m_input_tokens": 500},
        "output_tokens": 891000,
        "total_tokens": 5377000,
        "server_tool_use": {"web_search_requests": 10},
    }


class TestAnalyticsWindows:
    def test_full_refresh_starts_at_the_data_floor(self) -> None:
        config = ANTHROPIC_ENDPOINTS["analytics_user_activity"]
        windows = _analytics_windows(config, None, ANALYTICS_DATA_FLOOR + timedelta(days=4))
        assert windows[0].start == ANALYTICS_DATA_FLOOR
        # The engagement export lags, so the newest requested day stops short of today. Asking for a
        # day it has not covered fails the whole request with a 400.
        assert windows[-1].start == ANALYTICS_DATA_FLOOR + timedelta(days=4 - ANALYTICS_ENGAGEMENT_LAG_DAYS)

    def test_report_floor_stays_inside_the_history_bound(self) -> None:
        # The per-user reports reject a starting_at older than a year, so a full refresh cannot start
        # at the data floor once the floor has aged past that bound.
        config = ANTHROPIC_ENDPOINTS["analytics_user_cost"]
        today = ANALYTICS_DATA_FLOOR + timedelta(days=500)
        windows = _analytics_windows(config, None, today)
        assert windows[0].start == today - timedelta(days=ANALYTICS_REPORT_MAX_HISTORY_DAYS)

    @parameterized.expand(
        [
            ("datetime", datetime(2026, 3, 4, 12, 0, 0, tzinfo=UTC)),
            ("rfc3339_string", "2026-03-04T12:00:00Z"),
            ("date", date(2026, 3, 4)),
        ]
    )
    def test_incremental_watermark_starts_the_fan_out(self, _name: str, watermark: Any) -> None:
        config = ANTHROPIC_ENDPOINTS["analytics_user_cost"]
        windows = _analytics_windows(config, watermark, date(2026, 3, 6))
        assert [w.start for w in windows] == [date(2026, 3, 4), date(2026, 3, 5), date(2026, 3, 6)]
        # The report endpoints take an exclusive end, so each window covers exactly its own day.
        assert windows[0].end == date(2026, 3, 5)

    def test_watermark_past_the_newest_available_day_re_pulls_that_day(self) -> None:
        # A watermark at or after the newest available day must not request a day the endpoint
        # rejects, and must still return work so the run keeps the recent day fresh.
        config = ANTHROPIC_ENDPOINTS["analytics_user_activity"]
        today = date(2026, 3, 10)
        windows = _analytics_windows(config, today, today)
        assert [w.start for w in windows] == [today - timedelta(days=ANALYTICS_ENGAGEMENT_LAG_DAYS)]

    def test_resume_checkpoint_skips_days_already_yielded(self) -> None:
        config = ANTHROPIC_ENDPOINTS["analytics_user_cost"]
        windows = _analytics_windows(config, date(2026, 3, 1), date(2026, 3, 4), resume_from=date(2026, 3, 3))
        assert [w.start for w in windows] == [date(2026, 3, 3), date(2026, 3, 4)]


class TestFlattenAnalyticsRows:
    def test_activity_flattens_product_blocks_and_stamps_the_day(self) -> None:
        row = _flatten_analytics_user_activity(date(2026, 3, 4), _activity_record())
        # The record carries no day, so the requested day is the only source for it.
        assert row["date"] == "2026-03-04T00:00:00Z"
        assert row["user_id"] == "user_1"
        assert row["user_email_address"] == "dev@example.com"
        assert row["chat_message_count"] == 7
        assert row["claude_code_core_metrics_lines_of_code_added_count"] == 120
        assert row["claude_code_tool_actions_edit_tool_accepted_count"] == 10
        assert row["office_excel_message_count"] == 1
        assert row["web_search_count"] == 4
        assert "user" not in row

    def test_activity_id_is_stable_across_metric_changes(self) -> None:
        record = _activity_record()
        busier = {**record, "web_search_count": 99, "chat_metrics": {"message_count": 100}}
        assert (
            _flatten_analytics_user_activity(date(2026, 3, 4), record)["id"]
            == (_flatten_analytics_user_activity(date(2026, 3, 4), busier)["id"])
        )

    def test_activity_id_differs_by_day_and_user(self) -> None:
        base = _flatten_analytics_user_activity(date(2026, 3, 4), _activity_record())
        other_day = _flatten_analytics_user_activity(date(2026, 3, 5), _activity_record())
        other_user = _activity_record()
        other_user["user"] = {"id": "user_2", "email_address": "b@example.com"}
        assert (
            len({base["id"], other_day["id"], _flatten_analytics_user_activity(date(2026, 3, 4), other_user)["id"]})
            == 3
        )

    def test_cost_surfaces_the_actor_and_keeps_amounts_as_strings(self) -> None:
        row = _flatten_analytics_user_cost(_user_report_row())
        assert row["user_id"] == "user_1"
        assert row["user_email"] == "dev@example.com"
        assert row["user_deleted"] is False
        # Fractional cents can exceed exact float range, so the decimal string must survive intact.
        assert row["amount"] == "41280.000000"
        assert row["list_amount"] == "51600.000000"
        assert row["starting_at"] == "2026-03-04T00:00:00Z"

    def test_usage_flattens_nested_token_objects(self) -> None:
        row = _flatten_analytics_user_usage(_user_report_row())
        assert row["cache_creation_ephemeral_1h_input_tokens"] == 1000
        assert row["cache_creation_ephemeral_5m_input_tokens"] == 500
        assert row["web_search_requests"] == 10
        assert row["total_tokens"] == 5377000

    def test_usage_missing_nested_objects_yield_none_not_crash(self) -> None:
        row = _flatten_analytics_user_usage({"actor": {"user_id": "user_1"}, "starting_at": "2026-03-04T00:00:00Z"})
        assert row["cache_creation_ephemeral_1h_input_tokens"] is None
        assert row["web_search_requests"] is None

    def test_cost_and_usage_rows_for_the_same_day_and_user_share_an_id(self) -> None:
        # Both reports key on (day, user), so a bucket restated between runs merges in place.
        assert (
            _flatten_analytics_user_cost(_user_report_row())["id"]
            == (_flatten_analytics_user_usage(_user_report_row())["id"])
        )


class TestAnalyticsFanOut:
    @mock.patch(ANTHROPIC_SESSION_PATCH)
    def test_activity_fans_out_one_dated_request_per_day(self, MockSession) -> None:
        session = MockSession.return_value
        today = datetime.now(UTC).date()
        watermark = _midnight(today - timedelta(days=ANALYTICS_ENGAGEMENT_LAG_DAYS + 2))
        params = _wire(session, [_analytics_page([_activity_record()], next_page=None) for _ in range(3)])
        rows = _rows(_source("analytics_user_activity", _make_manager(), last_value=watermark))
        assert len(rows) == 3
        assert [p["params"]["date"] for p in params] == [
            (watermark.date() + timedelta(days=i)).isoformat() for i in range(3)
        ]
        assert [r["date"] for r in rows] == [
            f"{(watermark.date() + timedelta(days=i)).isoformat()}T00:00:00Z" for i in range(3)
        ]

    @parameterized.expand([("analytics_user_cost",), ("analytics_user_usage",)])
    @mock.patch(ANTHROPIC_SESSION_PATCH)
    def test_report_requests_carry_a_single_day_range_and_daily_buckets(self, endpoint: str, MockSession) -> None:
        session = MockSession.return_value
        today = datetime.now(UTC).date()
        params = _wire(session, [_report_page([_user_report_row()], has_more=False, next_page=None)])
        _rows(_source(endpoint, _make_manager(), last_value=_midnight(today)))
        # A row only carries its own starting_at when a bucket width is set, and the range has to be
        # one day wide so a row's day is unambiguous and rows arrive in ascending day order.
        assert params[0]["params"]["starting_at"] == f"{today.isoformat()}T00:00:00Z"
        assert params[0]["params"]["ending_at"] == f"{(today + timedelta(days=1)).isoformat()}T00:00:00Z"
        assert params[0]["params"]["bucket_width"] == "1d"

    @mock.patch(ANTHROPIC_SESSION_PATCH)
    def test_paginates_within_a_day_on_next_page_alone(self, MockSession) -> None:
        # The activity endpoint omits has_more, so a null next_page is the only stop signal.
        session = MockSession.return_value
        today = datetime.now(UTC).date()
        params = _wire(
            session,
            [
                _analytics_page([_activity_record("a@example.com")], next_page="P2"),
                _analytics_page([_activity_record("b@example.com")], next_page=None),
            ],
        )
        rows = _rows(_source("analytics_user_activity", _make_manager(), last_value=_midnight(today)))
        assert {r["user_email_address"] for r in rows} == {"a@example.com", "b@example.com"}
        assert "page" not in params[0]["params"]
        assert params[1]["params"]["page"] == "P2"
        assert params[1]["params"]["date"] == params[0]["params"]["date"]

    @mock.patch(ANTHROPIC_SESSION_PATCH)
    def test_checkpoints_the_next_day_after_a_day_is_yielded(self, MockSession) -> None:
        session = MockSession.return_value
        today = datetime.now(UTC).date()
        first_day = today - timedelta(days=ANALYTICS_ENGAGEMENT_LAG_DAYS + 1)
        manager = _make_manager()
        _wire(session, [_analytics_page([_activity_record()], next_page=None) for _ in range(2)])
        _rows(_source("analytics_user_activity", manager, last_value=_midnight(first_day)))
        saved = [call.args[0].analytics_window_state for call in manager.save_state.call_args_list]
        # Only the day still to come is checkpointed; the final day saves nothing to resume to.
        assert saved == [{"start": (first_day + timedelta(days=1)).isoformat()}]

    @mock.patch(ANTHROPIC_SESSION_PATCH)
    def test_resumes_from_the_saved_day(self, MockSession) -> None:
        session = MockSession.return_value
        today = datetime.now(UTC).date()
        last_day = today - timedelta(days=ANALYTICS_ENGAGEMENT_LAG_DAYS)
        manager = _make_manager(AnthropicResumeConfig(analytics_window_state={"start": last_day.isoformat()}))
        params = _wire(session, [_analytics_page([_activity_record()], next_page=None)])
        _rows(_source("analytics_user_activity", manager, last_value=_midnight(today - timedelta(days=30))))
        assert [p["params"]["date"] for p in params] == [last_day.isoformat()]

    @mock.patch(ANTHROPIC_SESSION_PATCH)
    def test_legacy_resume_state_restarts_the_fan_out(self, MockSession) -> None:
        # A resume state saved before this endpoint existed carries no analytics checkpoint; the run
        # must restart from the watermark rather than fail reading it.
        session = MockSession.return_value
        today = datetime.now(UTC).date()
        watermark = today - timedelta(days=ANALYTICS_ENGAGEMENT_LAG_DAYS)
        manager = _make_manager(AnthropicResumeConfig(cursor="OLD"))
        params = _wire(session, [_analytics_page([_activity_record()], next_page=None)])
        _rows(_source("analytics_user_activity", manager, last_value=_midnight(watermark)))
        assert [p["params"]["date"] for p in params] == [watermark.isoformat()]


class TestAnalyticsAccessProbe:
    @parameterized.expand(
        [
            ("granted", 200, None),
            ("scope_missing", 403, ANALYTICS_ACCESS_MISSING),
            ("route_absent_off_enterprise", 404, ANALYTICS_ACCESS_MISSING),
            # A bad key is reported once for the whole source by validate_credentials.
            ("bad_key", 401, None),
            # A blip during schema discovery must not hide a table the customer can sync.
            ("throttled", 429, None),
            ("server_error", 500, None),
        ]
    )
    @mock.patch(ANTHROPIC_SESSION_PATCH)
    def test_status_mapping(self, _name: str, status: int, expected: str | None, MockSession) -> None:
        MockSession.return_value.get.return_value = _response({}, status=status)
        assert check_analytics_access("sk-ant-admin-test") == expected

    @mock.patch(ANTHROPIC_SESSION_PATCH)
    def test_network_error_leaves_the_tables_reachable(self, MockSession) -> None:
        MockSession.return_value.get.side_effect = requests.ConnectionError("boom")
        assert check_analytics_access("sk-ant-admin-test") is None


class TestAnalyticsNonRetryableError:
    def test_analytics_forbidden_reports_the_scope_not_admin_access(self) -> None:
        # Both the analytics pattern and the generic api.anthropic.com 403 match this error, and the
        # first matching entry supplies the message the customer reads.
        errors = AnthropicSource().get_non_retryable_errors()
        observed = f"403 Client Error: Forbidden for url: https://api.anthropic.com{ANALYTICS_PATH_PREFIX}users?limit=1"
        matched = [message for pattern, message in errors.items() if error_message_matches(observed, [pattern])]
        assert len(matched) == 2
        assert "read:analytics" in (matched[0] or "")


def _token_page(items: list[dict[str, Any]], *, has_more: bool, next_page: str | None) -> Response:
    # The RBAC group and role lists page with an opaque `page`/`next_page` token, not an after_id.
    return _response({"data": items, "has_more": has_more, "next_page": next_page})


class TestRbacListPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_pages_with_the_page_token_not_an_after_id_cursor(self, MockSession) -> None:
        # These endpoints send no `last_id`, so paging them with the entity cursor would stop after
        # the first page and silently drop every group past it.
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _token_page([{"id": "rbac_group_1"}], has_more=True, next_page="P2"),
                _token_page([{"id": "rbac_group_2"}], has_more=False, next_page=None),
            ],
        )

        rows = _rows(_source("rbac_groups", _make_manager()))

        assert [r["id"] for r in rows] == ["rbac_group_1", "rbac_group_2"]
        assert "page" not in params[0]["params"]
        assert "after_id" not in params[1]["params"]
        assert params[1]["params"]["page"] == "P2"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_the_saved_page_token(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_token_page([{"id": "rbac_role_2"}], has_more=False, next_page=None)])

        _rows(_source("rbac_roles", _make_manager(AnthropicResumeConfig(cursor="P2"))))

        assert params[0]["params"]["page"] == "P2"


class TestRbacFanOut:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_group_members_carry_the_group_id_from_the_parent(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _token_page([{"id": "rbac_group_1"}, {"id": "rbac_group_2"}], has_more=False, next_page=None),
                _token_page(
                    [{"type": "rbac_group_member", "user_id": "u1", "group_id": "rbac_group_1"}],
                    has_more=False,
                    next_page=None,
                ),
                # The API always sends group_id, but stamp it from the parent defensively so the
                # composite primary key is populated even if it goes missing.
                _token_page([{"type": "rbac_group_member", "user_id": "u2"}], has_more=False, next_page=None),
            ],
        )

        rows = _rows(_source("rbac_group_members", _make_manager()))

        assert [(r["group_id"], r["user_id"]) for r in rows] == [("rbac_group_1", "u1"), ("rbac_group_2", "u2")]
        assert all("_rbac_groups_id" not in r for r in rows)
        assert params[0]["url"].endswith("/v1/organizations/rbac_groups")
        assert params[1]["url"].endswith("/v1/organizations/rbac_groups/rbac_group_1/members")
        assert params[2]["url"].endswith("/v1/organizations/rbac_groups/rbac_group_2/members")

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_permissions_take_their_role_id_from_the_parent(self, MockSession) -> None:
        # A permission object carries no role id at all, so without the parent stamp every row would
        # land with a null role_id and collide on the synthesized key.
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _token_page([{"id": "rbac_role_1"}, {"id": "rbac_role_2"}], has_more=False, next_page=None),
                _token_page(
                    [{"type": "rbac_role_permission", "action": "chat", "resource": {"type": "organization"}}],
                    has_more=False,
                    next_page=None,
                ),
                _token_page(
                    [{"type": "rbac_role_permission", "action": "chat", "resource": {"type": "organization"}}],
                    has_more=False,
                    next_page=None,
                ),
            ],
        )

        rows = _rows(_source("rbac_role_permissions", _make_manager()))

        assert [r["role_id"] for r in rows] == ["rbac_role_1", "rbac_role_2"]
        # The same grant under two roles must not share a key, or merge would keep only one row.
        assert rows[0]["id"] != rows[1]["id"]
        assert params[1]["url"].endswith("/v1/organizations/rbac_roles/rbac_role_1/permissions")
        assert params[2]["url"].endswith("/v1/organizations/rbac_roles/rbac_role_2/permissions")

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_a_role_that_belongs_to_another_organization_is_skipped(self, MockSession) -> None:
        # Groups span the enterprise while the role catalog is per-organization, so a role the key
        # cannot read answers 404. Skip that role rather than failing the whole schema.
        session = MockSession.return_value
        _wire(
            session,
            [
                _token_page([{"id": "rbac_role_1"}, {"id": "rbac_role_2"}], has_more=False, next_page=None),
                _response({"error": "not_found"}, status=404),
                _token_page(
                    [{"type": "rbac_role_permission", "action": "chat", "resource": {"type": "organization"}}],
                    has_more=False,
                    next_page=None,
                ),
            ],
        )

        rows = _rows(_source("rbac_role_permissions", _make_manager()))

        assert [r["role_id"] for r in rows] == ["rbac_role_2"]


class TestFlattenRbacRolePermission:
    @parameterized.expand(
        [
            (
                "organization",
                {"type": "organization", "organization_id": "org-uuid"},
                {"organization_id": "org-uuid", "connector_id": None, "tool_name": None, "scope": None},
            ),
            (
                "connector_tool",
                {"type": "connector_tool", "connector_id": "mcpsrv_1", "tool_name": "search_tickets"},
                {
                    "organization_id": None,
                    "connector_id": "mcpsrv_1",
                    "tool_name": "search_tickets",
                    "scope": None,
                },
            ),
            (
                "connector_scope",
                {"type": "connector_scope", "connector_id": "mcpsrv_1", "scope": "read_scope_deadbeef"},
                {
                    "organization_id": None,
                    "connector_id": "mcpsrv_1",
                    "tool_name": None,
                    "scope": "read_scope_deadbeef",
                },
            ),
            (
                "all_connectors",
                {"type": "all_connectors"},
                {"organization_id": None, "connector_id": None, "tool_name": None, "scope": None},
            ),
        ]
    )
    def test_each_resource_tag_fills_only_its_own_identifiers(
        self, _name: str, resource: dict[str, Any], expected: dict[str, Any]
    ) -> None:
        row = _flatten_rbac_role_permission({"role_id": "rbac_role_1", "action": "use", "resource": resource})
        assert row["resource_type"] == resource["type"]
        assert {key: row[key] for key in expected} == expected

    def test_two_grants_on_one_role_get_distinct_ids(self) -> None:
        base = {"role_id": "rbac_role_1", "resource": {"type": "all_connectors"}}
        use = _flatten_rbac_role_permission({**base, "action": "use"})
        always = _flatten_rbac_role_permission({**base, "action": "always_allow"})
        assert use["id"] != always["id"]

    def test_missing_resource_object_does_not_crash(self) -> None:
        row = _flatten_rbac_role_permission({"role_id": "rbac_role_1", "action": "chat"})
        assert row["resource_type"] is None
        assert row["id"]


def _usage_breakdown_page(rows: list[dict[str, Any]], *, next_page: str | None) -> Response:
    # The connector/plugin/skill breakdowns send no `has_more`: a null `next_page` is the last page.
    return _response({"data": rows, "next_page": next_page})


def _summaries_page(rows: list[dict[str, Any]]) -> Response:
    # The summaries endpoint answers a whole range in one response, under `summaries`, with no cursor.
    return _response({"summaries": rows})


def _summary_row(starting_at: str = "2026-03-04T00:00:00Z") -> dict[str, Any]:
    return {
        "starting_at": starting_at,
        "ending_at": "2026-03-05T00:00:00Z",
        "assigned_seat_count": 120,
        "pending_invite_count": 3,
        "daily_active_user_count": 84,
        "weekly_active_user_count": 101,
        "monthly_active_user_count": 112,
        "daily_adoption_rate": 70,
        "cowork_daily_active_user_count": 12,
        "cowork_weekly_active_user_count": 20,
        "cowork_monthly_active_user_count": 25,
    }


class TestFlattenAnalyticsEntityUsage:
    _SKILL_ROW = {
        "skill_name": "writing-tests",
        "skill_display_name": "Writing tests",
        "distinct_user_count": 9,
        "invocation_count": 31,
        "chat_metrics": {"distinct_conversation_skill_used_count": 4},
        "office_metrics": {"excel": {"distinct_session_skill_used_count": 2}},
    }

    def test_stamps_the_requested_day_and_flattens_the_product_blocks(self) -> None:
        row = _flatten_analytics_entity_usage("skill_name", date(2026, 3, 4), self._SKILL_ROW)
        assert row["date"] == "2026-03-04T00:00:00Z"
        assert row["skill_name"] == "writing-tests"
        assert row["distinct_user_count"] == 9
        assert row["chat_distinct_conversation_skill_used_count"] == 4
        assert row["office_excel_distinct_session_skill_used_count"] == 2
        # The nested blocks must not survive as columns of their own.
        assert "chat_metrics" not in row and "office_metrics" not in row

    def test_id_is_stable_across_metric_changes(self) -> None:
        revised = {**self._SKILL_ROW, "distinct_user_count": 11, "invocation_count": 40}
        assert (
            _flatten_analytics_entity_usage("skill_name", date(2026, 3, 4), self._SKILL_ROW)["id"]
            == _flatten_analytics_entity_usage("skill_name", date(2026, 3, 4), revised)["id"]
        )

    def test_id_differs_by_day_and_by_entity(self) -> None:
        same_day = _flatten_analytics_entity_usage("skill_name", date(2026, 3, 4), self._SKILL_ROW)
        next_day = _flatten_analytics_entity_usage("skill_name", date(2026, 3, 5), self._SKILL_ROW)
        other_skill = _flatten_analytics_entity_usage(
            "skill_name", date(2026, 3, 4), {**self._SKILL_ROW, "skill_name": "writing-skills"}
        )
        assert len({same_day["id"], next_day["id"], other_skill["id"]}) == 3


class TestAnalyticsBreakdownFanOut:
    @parameterized.expand(
        [
            ("analytics_connector_usage", "connector_name", "atlassian"),
            ("analytics_plugin_usage", "plugin_name", "serena"),
            ("analytics_skill_usage", "skill_name", "writing-tests"),
        ]
    )
    @mock.patch(ANTHROPIC_SESSION_PATCH)
    def test_fans_out_one_dated_request_per_day(self, endpoint: str, name_field: str, name: str, MockSession) -> None:
        session = MockSession.return_value
        today = datetime.now(UTC).date()
        watermark = _midnight(today - timedelta(days=ANALYTICS_ENGAGEMENT_LAG_DAYS + 1))
        params = _wire(session, [_usage_breakdown_page([{name_field: name}], next_page=None) for _ in range(2)])

        rows = _rows(_source(endpoint, _make_manager(), last_value=watermark))

        assert [p["params"]["date"] for p in params] == [
            (watermark.date() + timedelta(days=i)).isoformat() for i in range(2)
        ]
        assert [r["date"] for r in rows] == [
            f"{(watermark.date() + timedelta(days=i)).isoformat()}T00:00:00Z" for i in range(2)
        ]
        assert [r[name_field] for r in rows] == [name, name]
        # A row's day comes from the request, so the request must never carry a range.
        assert "starting_at" not in params[0]["params"]

    @mock.patch(ANTHROPIC_SESSION_PATCH)
    def test_paginates_within_a_day_on_next_page_alone(self, MockSession) -> None:
        session = MockSession.return_value
        today = datetime.now(UTC).date()
        params = _wire(
            session,
            [
                _usage_breakdown_page([{"connector_name": "atlassian"}], next_page="P2"),
                _usage_breakdown_page([{"connector_name": "github"}], next_page=None),
            ],
        )

        rows = _rows(_source("analytics_connector_usage", _make_manager(), last_value=_midnight(today)))

        assert {r["connector_name"] for r in rows} == {"atlassian", "github"}
        assert params[1]["params"]["page"] == "P2"
        assert params[1]["params"]["date"] == params[0]["params"]["date"]


class TestAnalyticsSummaries:
    @mock.patch(ANTHROPIC_SESSION_PATCH)
    def test_requests_a_single_day_as_calendar_dates_with_no_pagination_params(self, MockSession) -> None:
        session = MockSession.return_value
        today = datetime.now(UTC).date()
        params = _wire(session, [_summaries_page([_summary_row()])])

        _rows(_source("analytics_summaries", _make_manager(), last_value=_midnight(today)))

        last_day = today - timedelta(days=ANALYTICS_ENGAGEMENT_LAG_DAYS)
        assert params[0]["params"]["starting_date"] == last_day.isoformat()
        # `ending_date` is exclusive, and the endpoint rejects `limit` and `bucket_width`.
        assert params[0]["params"]["ending_date"] == (last_day + timedelta(days=1)).isoformat()
        assert "limit" not in params[0]["params"]
        assert "bucket_width" not in params[0]["params"]
        assert "starting_at" not in params[0]["params"]

    @mock.patch(ANTHROPIC_SESSION_PATCH)
    def test_rows_come_from_the_summaries_key_and_keep_their_own_day(self, MockSession) -> None:
        session = MockSession.return_value
        today = datetime.now(UTC).date()
        _wire(session, [_summaries_page([_summary_row("2026-03-04T00:00:00Z")])])

        rows = _rows(_source("analytics_summaries", _make_manager(), last_value=_midnight(today)))

        # The row's own `starting_at` is the primary key, so nothing may overwrite or synthesize it.
        assert [r["starting_at"] for r in rows] == ["2026-03-04T00:00:00Z"]
        assert rows[0]["daily_active_user_count"] == 84
        assert rows[0]["cowork_weekly_active_user_count"] == 20
        assert "id" not in rows[0]

    @mock.patch(ANTHROPIC_SESSION_PATCH)
    def test_a_day_ends_after_one_request(self, MockSession) -> None:
        # The response carries neither `has_more` nor `next_page`, so a paginator that treated a
        # missing token as "keep going" would re-request the same day forever.
        session = MockSession.return_value
        today = datetime.now(UTC).date()
        _wire(session, [_summaries_page([_summary_row()])])

        _rows(_source("analytics_summaries", _make_manager(), last_value=_midnight(today)))

        assert session.send.call_count == 1


class TestRbacNonRetryableErrors:
    @parameterized.expand(
        [
            ("groups_forbidden", 403, "Forbidden", RBAC_GROUPS_PATH, "read:rbac_groups"),
            # A Claude Console organization does not serve these routes at all.
            ("groups_absent", 404, "Not Found", f"{RBAC_GROUPS_PATH}/rbac_group_1/members", "read:rbac_groups"),
            ("roles_forbidden", 403, "Forbidden", RBAC_ROLES_PATH, "read:members"),
            ("roles_absent", 404, "Not Found", f"{RBAC_ROLES_PATH}/rbac_role_1/permissions", "read:members"),
        ]
    )
    def test_denial_names_the_scope_not_admin_access(
        self, _name: str, status: int, reason: str, path: str, expected_scope: str
    ) -> None:
        # The generic api.anthropic.com 403 also matches a group or role denial, and the first
        # matching entry supplies the message the customer reads. If it wins, the customer is told to
        # swap their key for a Console Admin API key when the real problem is a missing scope.
        errors = AnthropicSource().get_non_retryable_errors()
        observed = f"{status} Client Error: {reason} for url: https://api.anthropic.com{path}"
        matched = [message for pattern, message in errors.items() if error_message_matches(observed, [pattern])]
        assert matched, "a group or role denial must be non-retryable"
        assert expected_scope in (matched[0] or "")
