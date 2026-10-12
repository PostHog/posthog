import json
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.common.safe_point import (
    source_items_are_framework_output,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.anthropic.anthropic import (
    ANALYTICS_ACCESS_MISSING,
    AnthropicResumeConfig,
    _analytics_windows,
    _claude_code_start_day,
    _flatten_analytics_entity_usage,
    _flatten_analytics_user_activity,
    _flatten_rbac_role_permission,
    anthropic_source,
    check_analytics_access,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.anthropic.settings import (
    ANALYTICS_ENGAGEMENT_LAG_DAYS,
    ANALYTICS_PATH_PREFIX,
    ANTHROPIC_ENDPOINTS,
    COST_REPORT_PAGE_BUCKETS,
    RBAC_GROUPS_PATH,
    RBAC_ROLES_PATH,
    USAGE_GROUP_BY_FALLBACKS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.anthropic.source import AnthropicSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the anthropic module.
ANTHROPIC_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.anthropic.anthropic.make_tracked_session"
)


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


class TestReportParams:
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


class TestWorkspaceMembersFanOut:
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
    def test_client_error_raises_without_retry(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"error": "unauthorized"}, status=401)])

        with pytest.raises(requests.HTTPError):
            _rows(_source("users", _make_manager()))
        assert session.send.call_count == 1


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

        source_response = _source("usage_report", _make_manager())
        rows = _rows(source_response)

        assert [r["workspace_id"] for r in rows] == ["wrkspc_1"]
        assert [p["params"]["group_by[]"] for p in params] == USAGE_GROUP_BY_FALLBACKS[:2]
        # The pipeline gives the framework's safe points only to a `Resource`. Without them a run
        # that waits on a rate limit cannot hand off.
        assert source_items_are_framework_output(source_response.items())

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


class TestClaudeCodeStartDay:
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


class TestClaudeCodeDayFanOut:
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


class TestAnalyticsFanOut:
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
    def test_resumes_from_the_saved_day(self, MockSession) -> None:
        session = MockSession.return_value
        today = datetime.now(UTC).date()
        last_day = today - timedelta(days=ANALYTICS_ENGAGEMENT_LAG_DAYS)
        manager = _make_manager(AnthropicResumeConfig(analytics_window_state={"start": last_day.isoformat()}))
        params = _wire(session, [_analytics_page([_activity_record()], next_page=None)])
        _rows(_source("analytics_user_activity", manager, last_value=_midnight(today - timedelta(days=30))))
        assert [p["params"]["date"] for p in params] == [last_day.isoformat()]


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


class TestRbacFanOut:
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


def _usage_breakdown_page(rows: list[dict[str, Any]], *, next_page: str | None) -> Response:
    # The connector/plugin/skill breakdowns send no `has_more`: a null `next_page` is the last page.
    return _response({"data": rows, "next_page": next_page})


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
