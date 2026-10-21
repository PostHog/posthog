from datetime import UTC, date, datetime, timedelta
from typing import Any, cast

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.common.safe_point import (
    source_items_are_framework_output,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.anthropic.anthropic import (
    ANALYTICS_ACCESS_MISSING,
    INVALID_ADMIN_KEY_MESSAGE,
    STANDARD_KEY_MESSAGE,
    VALIDATION_UNREACHABLE_MESSAGE,
    AnthropicResumeConfig,
    _analytics_windows,
    _claude_code_start_day,
    _flatten_analytics_entity_usage,
    _flatten_analytics_user_activity,
    _flatten_rbac_role_permission,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.anthropic import (
    AnthropicSourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(AnthropicSource(), AnthropicSourceConfig(api_key="sk-ant-admin-test"))


def _entity_page(items: list[dict[str, Any]], *, has_more: bool, last_id: str | None) -> ScriptedResponse:
    return ScriptedResponse(json={"data": items, "has_more": has_more, "first_id": None, "last_id": last_id})


def _report_page(buckets: list[dict[str, Any]], *, has_more: bool, next_page: str | None) -> ScriptedResponse:
    return ScriptedResponse(json={"data": buckets, "has_more": has_more, "next_page": next_page})


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
    def test_follows_next_page_until_has_more_false(self) -> None:
        result = _driver().run(
            "usage_report",
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

        assert result.raised is None
        assert [r["model"] for r in result.rows] == ["a", "b"]
        # Second request must carry the page token from the first response; the first must not.
        assert result.params("page") == [None, "PAGE2"]
        # Checkpoint saved after the first page was yielded, pointing at the next page.
        assert result.saved_states == [AnthropicResumeConfig(cursor="PAGE2")]
        assert result.committed_states == [AnthropicResumeConfig(cursor="PAGE2")]

    def test_stops_when_has_more_false_even_with_next_page_token(self) -> None:
        # `has_more` is the authoritative stop signal — a stray token on the final page must not
        # trigger an extra request.
        result = _driver().run(
            "cost_report",
            [
                _report_page(
                    [{"starting_at": "d1", "ending_at": "d2", "results": [{"model": "a"}]}],
                    has_more=False,
                    next_page="STRAY",
                ),
            ],
        )

        assert result.raised is None
        assert len(result.rows) == 1
        assert len(result.requests) == 1
        assert result.saved_states == []


class TestEntityPagination:
    def test_resumes_from_saved_after_id(self) -> None:
        result = _driver().run(
            "users",
            [_entity_page([{"id": "user_6"}], has_more=False, last_id="user_6")],
            resume_state=AnthropicResumeConfig(cursor="user_5"),
        )

        assert result.raised is None
        assert result.params("after_id") == ["user_5"]

    def test_api_keys_flatten_created_by(self) -> None:
        result = _driver().run(
            "api_keys",
            [
                _entity_page(
                    [{"id": "apikey_1", "created_by": {"id": "user_1", "type": "user"}}],
                    has_more=False,
                    last_id="apikey_1",
                )
            ],
        )

        assert result.raised is None
        assert result.rows[0]["created_by_id"] == "user_1"
        assert result.rows[0]["created_by_type"] == "user"
        assert "created_by" not in result.rows[0]


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
    def test_client_error_raises_without_retry(self) -> None:
        result = _driver().run("users", [ScriptedResponse(status=401, json={"error": "unauthorized"})])

        assert isinstance(result.raised, requests.HTTPError)
        assert len(result.requests) == 1


class TestUsageReportGroupByFallback:
    def test_rejected_query_is_retried_with_a_narrower_group_by(self) -> None:
        # The usage report 400s a query that groups more finely than it will serve. Narrowing must
        # keep the sync alive and still deliver rows, at the finest breakdown the API accepts.
        result = _driver().run(
            "usage_report",
            [
                ScriptedResponse(status=400, json={"error": "bad request"}),
                _report_page(
                    [{"starting_at": "2025-08-01T00:00:00Z", "results": [{"workspace_id": "wrkspc_1"}]}],
                    has_more=False,
                    next_page=None,
                ),
            ],
        )

        assert result.raised is None
        assert [r["workspace_id"] for r in result.rows] == ["wrkspc_1"]
        assert [request.query.get("group_by[]", ()) for request in result.requests] == [
            tuple(group_by) for group_by in USAGE_GROUP_BY_FALLBACKS[:2]
        ]
        # The pipeline gives the framework's safe points only to a `Resource`. Without them a run
        # that waits on a rate limit cannot hand off.
        assert result.response is not None
        assert source_items_are_framework_output(result.response.items())

    @parameterized.expand(
        [
            # Every fallback rejected: there is nothing narrower left to try.
            (
                "all_rejected",
                [ScriptedResponse(status=400, json={}) for _ in USAGE_GROUP_BY_FALLBACKS],
                len(USAGE_GROUP_BY_FALLBACKS),
            ),
            # A 404 is not the API refusing the breakdown, so narrowing must not paper over it.
            ("not_a_bad_request", [ScriptedResponse(status=404, json={})], 1),
        ]
    )
    def test_error_propagates_instead_of_narrowing(
        self, _name: str, responses: list[ScriptedResponse], expected_requests: int
    ) -> None:
        result = _driver().run("usage_report", responses)

        assert isinstance(result.raised, requests.HTTPError)
        assert len(result.requests) == expected_requests

    def test_rejection_after_rows_are_out_is_not_narrowed(self) -> None:
        # Re-running at a coarser grain would re-emit the buckets already yielded under different
        # synthesized ids, so once rows are out the 400 has to fail the sync instead.
        result = _driver().run(
            "usage_report",
            [
                _report_page(
                    [{"starting_at": "2025-08-01T00:00:00Z", "results": [{"workspace_id": "wrkspc_1"}]}],
                    has_more=True,
                    next_page="page_2",
                ),
                ScriptedResponse(status=400, json={"error": "bad request"}),
            ],
        )

        assert isinstance(result.raised, requests.HTTPError)
        assert [row["workspace_id"] for row in result.rows] == ["wrkspc_1"]
        assert len(result.requests) == 2


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", "sk-ant-admin-test", 200, (True, None)),
            ("forbidden_scope", "sk-ant-admin-test", 403, (True, None)),
            ("unauthorized", "sk-ant-admin-test", 401, (False, INVALID_ADMIN_KEY_MESSAGE)),
            ("standard_key", "sk-ant-api03-test", 401, (False, STANDARD_KEY_MESSAGE)),
            ("server_error", "sk-ant-admin-test", 503, (False, VALIDATION_UNREACHABLE_MESSAGE)),
        ]
    )
    def test_status_mapping(self, _name: str, api_key: str, status: int, expected: tuple[bool, str | None]) -> None:
        # 403 is accepted at create time (real key, unprobed scope); 401 means a bad key.
        with scripted_network([ScriptedResponse(status=status)]) as network:
            assert validate_credentials(api_key) == expected
        assert network.requests_log[0].path == "/v1/organizations/users"
        assert network.requests_log[0].param("limit") == "1"


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            (
                "long_retry_after",
                "RESTClientRetryableError: HTTP 429 for https://api.anthropic.com/v1/organizations/usage_report/claude_code"
                " (the server asked for a wait of 3600 seconds)",
            ),
            (
                "retry_budget_spent",
                "RESTClientRetryableError: HTTP 429 for https://api.anthropic.com/v1/organizations/usage_report/messages",
            ),
        ]
    )
    def test_exhausted_rate_limit_stays_retryable_with_sync_frequency_guidance(
        self, _name: str, observed_error: str
    ) -> None:
        source = AnthropicSource()
        assert not error_message_matches(observed_error, source.get_non_retryable_errors().keys())
        messages = [
            message
            for pattern, message in source.get_retry_exhausted_errors().items()
            if error_message_matches(observed_error, [pattern])
        ]
        assert messages and "sync less often" in messages[0]


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


def _cc_page(records: list[dict[str, Any]], *, has_more: bool, next_page: str | None) -> ScriptedResponse:
    return ScriptedResponse(json={"data": records, "has_more": has_more, "next_page": next_page})


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
    def test_model_breakdown_endpoint_explodes_per_model(self) -> None:
        today = datetime.now(UTC).date()
        record = _cc_record()
        record["model_breakdown"] = [
            {"model": "m1", "tokens": {"input": 1}, "estimated_cost": {"amount": "1", "currency": "USD"}},
            {"model": "m2", "tokens": {"input": 2}, "estimated_cost": {"amount": "2", "currency": "USD"}},
        ]
        result = _driver().run(
            "claude_code_model_breakdown",
            [_cc_page([record], has_more=False, next_page=None)],
            incremental_field="date",
            db_incremental_field_last_value=_midnight(today),
        )
        assert result.raised is None
        assert sorted(r["model"] for r in result.rows) == ["m1", "m2"]

    def test_paginates_within_a_day(self) -> None:
        today = datetime.now(UTC).date()
        result = _driver().run(
            "claude_code_analytics",
            [
                _cc_page([_cc_record("a@x.com")], has_more=True, next_page="P2"),
                _cc_page([_cc_record("b@x.com")], has_more=False, next_page=None),
            ],
            incremental_field="date",
            db_incremental_field_last_value=_midnight(today),
        )
        assert result.raised is None
        assert {r["actor_email_address"] for r in result.rows} == {"a@x.com", "b@x.com"}
        assert result.params("page") == [None, "P2"]
        assert result.params("starting_at") == [today.isoformat(), today.isoformat()]

    def test_resumes_from_saved_day_and_page_cursor(self) -> None:
        today = datetime.now(UTC).date()
        result = _driver().run(
            "claude_code_analytics",
            [_cc_page([_cc_record()], has_more=False, next_page=None)],
            resume_state=AnthropicResumeConfig(day_fanout_state={"date": today.isoformat(), "cursor": "P2"}),
            incremental_field="date",
            db_incremental_field_last_value=_midnight(today),
        )
        assert result.raised is None
        assert len(result.rows) == 1
        assert result.params("page") == ["P2"]
        assert result.params("starting_at") == [today.isoformat()]

    def test_waits_out_a_rate_limit_that_asks_for_an_hour(self) -> None:
        today = datetime.now(UTC).date()
        result = _driver().run(
            "claude_code_analytics",
            [
                ScriptedResponse(status=429, headers={"Retry-After": "3600"}),
                _cc_page([_cc_record()], has_more=False, next_page=None),
            ],
            incremental_field="date",
            db_incremental_field_last_value=_midnight(today),
        )
        assert result.raised is None
        assert len(result.rows) == 1


class TestRetiredEndpoint:
    def test_a_dropped_endpoint_fails_non_retryably(self) -> None:
        # A schema row discovered before an endpoint was dropped still names it, and its schedule
        # keeps firing. The run must fail with a message the source classifies as non-retryable, so
        # it disables the schema and pauses the schedule instead of retrying a KeyError forever.
        result = _driver().run("service_accounts", [])
        assert isinstance(result.raised, ValueError)
        assert error_message_matches(str(result.raised), AnthropicSource().get_non_retryable_errors().keys())


def _analytics_page(rows: list[dict[str, Any]], *, next_page: str | None) -> ScriptedResponse:
    # `/organizations/analytics/users` sends no `has_more`: a null `next_page` is the last page.
    return ScriptedResponse(json={"data": rows, "next_page": next_page})


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
    def test_report_requests_carry_a_single_day_range_and_daily_buckets(self, endpoint: str) -> None:
        today = datetime.now(UTC).date()
        result = _driver().run(
            endpoint,
            [_report_page([_user_report_row()], has_more=False, next_page=None)],
            incremental_field="starting_at",
            db_incremental_field_last_value=_midnight(today),
        )
        assert result.raised is None
        # A row only carries its own starting_at when a bucket width is set, and the range has to be
        # one day wide so a row's day is unambiguous and rows arrive in ascending day order.
        assert result.params("starting_at") == [f"{today.isoformat()}T00:00:00Z"]
        assert result.params("ending_at") == [f"{(today + timedelta(days=1)).isoformat()}T00:00:00Z"]
        assert result.params("bucket_width") == ["1d"]

    def test_resumes_from_the_saved_day(self) -> None:
        today = datetime.now(UTC).date()
        last_day = today - timedelta(days=ANALYTICS_ENGAGEMENT_LAG_DAYS)
        result = _driver().run(
            "analytics_user_activity",
            [_analytics_page([_activity_record()], next_page=None)],
            resume_state=AnthropicResumeConfig(analytics_window_state={"start": last_day.isoformat()}),
            incremental_field="date",
            db_incremental_field_last_value=_midnight(today - timedelta(days=30)),
        )
        assert result.raised is None
        assert result.params("date") == [last_day.isoformat()]


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
    def test_status_mapping(self, _name: str, status: int, expected: str | None) -> None:
        with scripted_network([ScriptedResponse(status=status, json={})]) as network:
            assert check_analytics_access("sk-ant-admin-test") == expected
        assert network.requests_log[0].path == f"{ANALYTICS_PATH_PREFIX}users"


class TestAnalyticsNonRetryableError:
    def test_analytics_forbidden_reports_the_scope_not_admin_access(self) -> None:
        # Both the analytics pattern and the generic api.anthropic.com 403 match this error, and the
        # first matching entry supplies the message the customer reads.
        errors = AnthropicSource().get_non_retryable_errors()
        observed = f"403 Client Error: Forbidden for url: https://api.anthropic.com{ANALYTICS_PATH_PREFIX}users?limit=1"
        matched = [message for pattern, message in errors.items() if error_message_matches(observed, [pattern])]
        assert len(matched) == 2
        assert "read:analytics" in (matched[0] or "")


def _token_page(items: list[dict[str, Any]], *, has_more: bool, next_page: str | None) -> ScriptedResponse:
    # The RBAC group and role lists page with an opaque `page`/`next_page` token, not an after_id.
    return ScriptedResponse(json={"data": items, "has_more": has_more, "next_page": next_page})


class TestRbacFanOut:
    def test_a_role_that_belongs_to_another_organization_is_skipped(self) -> None:
        # Groups span the enterprise while the role catalog is per-organization, so a role the key
        # cannot read answers 404. Skip that role rather than failing the whole schema.
        result = _driver().run(
            "rbac_role_permissions",
            [
                _token_page([{"id": "rbac_role_1"}, {"id": "rbac_role_2"}], has_more=False, next_page=None),
                ScriptedResponse(status=404, json={"error": "not_found"}),
                _token_page(
                    [{"type": "rbac_role_permission", "action": "chat", "resource": {"type": "organization"}}],
                    has_more=False,
                    next_page=None,
                ),
            ],
        )

        assert result.raised is None
        assert [r["role_id"] for r in result.rows] == ["rbac_role_2"]


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


def _usage_breakdown_page(rows: list[dict[str, Any]], *, next_page: str | None) -> ScriptedResponse:
    # The connector/plugin/skill breakdowns send no `has_more`: a null `next_page` is the last page.
    return ScriptedResponse(json={"data": rows, "next_page": next_page})


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
    def test_fans_out_one_dated_request_per_day(self, endpoint: str, name_field: str, name: str) -> None:
        today = datetime.now(UTC).date()
        watermark = _midnight(today - timedelta(days=ANALYTICS_ENGAGEMENT_LAG_DAYS + 1))
        result = _driver().run(
            endpoint,
            [_usage_breakdown_page([{name_field: name}], next_page=None) for _ in range(2)],
            incremental_field="date",
            db_incremental_field_last_value=watermark,
        )
        assert result.raised is None
        assert result.params("date") == [(watermark.date() + timedelta(days=i)).isoformat() for i in range(2)]
        assert [r["date"] for r in result.rows] == [
            f"{(watermark.date() + timedelta(days=i)).isoformat()}T00:00:00Z" for i in range(2)
        ]
        assert [r[name_field] for r in result.rows] == [name, name]
        # A row's day comes from the request, so the request must never carry a range.
        assert result.requests[0].param("starting_at") is None


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
