from datetime import UTC, datetime
from typing import Any, cast

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.openai import OpenAISourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.openai.openai import (
    OpenAIResumeConfig,
    _flatten_bucket_result,
    _normalize_audit_log,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.openai.settings import OPENAI_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.openai.source import OpenAISource

PROJECT_USERS_PATH = "/v1/organization/projects/{project_id}/users"


def _driver() -> SourceDriver:
    return SourceDriver(OpenAISource(), OpenAISourceConfig(api_key="sk-admin-test"))


def _entity_page(items: list[dict[str, Any]], *, has_more: bool, last_id: str | None = None) -> ScriptedResponse:
    body: dict[str, Any] = {"data": items, "has_more": has_more}
    if last_id is not None:
        body["last_id"] = last_id
    return ScriptedResponse(json=body)


def _bucket_page(buckets: list[dict[str, Any]], *, has_more: bool, next_page: str | None) -> ScriptedResponse:
    return ScriptedResponse(json={"data": buckets, "has_more": has_more, "next_page": next_page})


def _lookback_exceeded() -> ScriptedResponse:
    return ScriptedResponse(
        status=400,
        json={
            "error": {
                "type": "invalid_request_error",
                "code": "reporting_lookback_exceeded",
                "message": "too far back",
            }
        },
    )


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


class TestBucketParams:
    @parameterized.expand(
        [
            ("initial_sync", None),
            ("stale_watermark", datetime(2021, 6, 1, tzinfo=UTC)),
        ]
    )
    def test_lookback_exceeded_retries_with_a_later_start(self, _name: str, last_value: Any) -> None:
        result = _driver().run(
            "usage_audio_speeches",
            [
                _lookback_exceeded(),
                _lookback_exceeded(),
                _bucket_page(
                    [{"start_time": 1, "end_time": 2, "results": [{"model": "a"}]}], has_more=False, next_page=None
                ),
            ],
            resume_state=OpenAIResumeConfig(cursor="STALE"),
            incremental_field="start_time",
            db_incremental_field_last_value=last_value,
        )

        assert result.raised is None
        assert [row["model"] for row in result.rows] == ["a"]
        starts = [int(value) for value in result.params("start_time") if value is not None]
        assert starts[0] < starts[1] < starts[2]
        assert starts[2] > int(datetime.now(UTC).timestamp()) - 400 * 24 * 60 * 60
        # The saved page cursor belongs to the rejected start, so a fallback must not send it.
        assert result.params("page") == ["STALE", None, None]

    def test_lookback_exceeded_on_every_start_raises_non_retryable_error(self) -> None:
        result = _driver().run("usage_vector_stores", always(_lookback_exceeded()))

        assert isinstance(result.raised, requests.HTTPError)
        assert len(result.requests) == 7
        non_retryable = OpenAISource().get_non_retryable_errors()
        assert any(key in str(result.raised) for key in non_retryable)

    def test_lookback_exceeded_on_recent_watermark_does_not_move_start(self) -> None:
        result = _driver().run(
            "usage_vector_stores",
            [_lookback_exceeded(), _bucket_page([], has_more=False, next_page=None)],
            incremental_field="start_time",
            db_incremental_field_last_value=datetime.now(UTC),
        )

        assert isinstance(result.raised, requests.HTTPError)
        assert len(result.requests) == 1


class TestBucketPagination:
    def test_empty_page_with_next_page_token_stops_pagination(self) -> None:
        # The costs endpoint is known to return a next_page token alongside an empty page; without
        # the guard, pagination would loop on the empty tail forever.
        result = _driver().run(
            "costs",
            [
                _bucket_page(
                    [{"start_time": 1, "end_time": 2, "results": [{"line_item": "x"}]}],
                    has_more=True,
                    next_page="PAGE2",
                ),
                _bucket_page([], has_more=True, next_page="PAGE3"),
            ],
        )

        assert result.raised is None
        assert [row["line_item"] for row in result.rows] == ["x"]
        assert result.params("page") == [None, "PAGE2"]


class TestEntityPagination:
    @parameterized.expand(
        [
            ("last_id", "users", {"last_id": "user_1"}, {"last_id": "user_2"}, "user_1"),
            # Groups and roles return an opaque `next` cursor that need not equal the last row's id.
            ("next_cursor", "roles", {"next": "cursor_abc"}, {"next": None}, "cursor_abc"),
        ]
    )
    def test_cursor_pagination_uses_after_and_stops(
        self,
        _name: str,
        endpoint: str,
        first_cursor: dict[str, Any],
        last_cursor: dict[str, Any],
        expected_after: str,
    ) -> None:
        result = _driver().run(
            endpoint,
            [
                ScriptedResponse(json={"data": [{"id": "row_1"}], "has_more": True, **first_cursor}),
                # Final page may still carry a cursor — has_more must stop the walk with no extra call.
                ScriptedResponse(json={"data": [{"id": "row_2"}], "has_more": False, **last_cursor}),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["row_1", "row_2"]
        assert result.params("after") == [None, expected_after]
        assert result.params("limit") == ["100", "100"]
        assert result.saved_states == [OpenAIResumeConfig(cursor=expected_after)]

    def test_resumes_from_saved_after_cursor(self) -> None:
        result = _driver().run(
            "users",
            [_entity_page([{"id": "user_6"}], has_more=False, last_id="user_6")],
            resume_state=OpenAIResumeConfig(cursor="user_5"),
        )

        assert result.raised is None
        assert result.params("after") == ["user_5"]

    def test_admin_api_keys_flatten_owner(self) -> None:
        result = _driver().run(
            "admin_api_keys",
            [
                _entity_page(
                    [{"id": "key_1", "owner": {"type": "user", "id": "user_1", "name": "Ada"}}],
                    has_more=False,
                    last_id="key_1",
                )
            ],
        )

        assert result.raised is None
        assert result.rows[0]["owner_id"] == "user_1"
        assert "owner" not in result.rows[0]


class TestAuditLogs:
    def test_full_refresh_sends_no_effective_at_filter(self) -> None:
        result = _driver().run(
            "audit_logs",
            [
                ScriptedResponse(
                    json={
                        "data": [{"id": "audit_log-1", "type": "project.created", "effective_at": 1722470400}],
                        "has_more": False,
                    }
                )
            ],
        )

        assert result.raised is None
        assert result.params("effective_at[gte]") == [None]


class TestProjectFanOut:
    def test_one_project_500ing_is_skipped_and_others_land(self) -> None:
        # proj_1's resource keeps returning 500 past the client's retry budget; without per-project
        # tolerance that would fail the whole schema. The fan-out must skip proj_1 and still yield
        # proj_2's rows.
        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/v1/organization/projects":
                return _entity_page([{"id": "proj_1"}, {"id": "proj_2"}], has_more=False, last_id="proj_2")
            if request.path == PROJECT_USERS_PATH.format(project_id="proj_1"):
                return ScriptedResponse(status=500, json={})
            if request.path == PROJECT_USERS_PATH.format(project_id="proj_2"):
                return _entity_page([{"id": "user_2"}], has_more=False, last_id="user_2")
            raise AssertionError(f"Unexpected request: {request.path}")

        result = _driver().run("project_users", respond)

        assert result.raised is None
        assert [(row["project_id"], row["id"]) for row in result.rows] == [("proj_2", "user_2")]
        assert set(result.paths) == {
            "/v1/organization/projects",
            PROJECT_USERS_PATH.format(project_id="proj_1"),
            PROJECT_USERS_PATH.format(project_id="proj_2"),
        }
        # The skipped project stays off the completed checkpoint so a later run re-attempts it.
        final = result.saved_states[-1].fanout_state
        assert final["completed"] == [PROJECT_USERS_PATH.format(project_id="proj_2")]

    @parameterized.expand(
        [
            ("project_users", "/v1/organization/projects", PROJECT_USERS_PATH, "project_id"),
            ("group_users", "/v1/organization/groups", "/v1/organization/groups/{parent_id}/users", "group_id"),
            ("user_roles", "/v1/organization/users", "/v1/organization/users/{parent_id}/roles", "user_id"),
        ]
    )
    def test_child_rows_carry_their_parent_id(
        self, endpoint: str, parent_path: str, child_path: str, parent_key: str
    ) -> None:
        # Child ids repeat across parents (one user sits in many groups), so a row without its
        # parent id would collide on the composite primary key.
        child_paths = {child_path.format(parent_id=p, project_id=p): p for p in ("parent_1", "parent_2")}

        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == parent_path:
                return _entity_page([{"id": "parent_1"}, {"id": "parent_2"}], has_more=False)
            if request.path in child_paths:
                return _entity_page([{"id": "shared_child"}], has_more=False)
            raise AssertionError(f"Unexpected request: {request.path}")

        result = _driver().run(endpoint, respond)

        assert result.raised is None
        assert sorted((row[parent_key], row["id"]) for row in result.rows) == [
            ("parent_1", "shared_child"),
            ("parent_2", "shared_child"),
        ]
        assert not any(key.startswith("_") for row in result.rows for key in row)

    def test_saved_state_shapes_still_parse(self) -> None:
        # ResumableSourceManager._load_json does dataclass(**saved) — every historical shape must
        # keep parsing after the migration.
        assert OpenAIResumeConfig(
            **cast("dict[str, Any]", {"cursor": "PAGE2", "project_id": None})
        ) == OpenAIResumeConfig(cursor="PAGE2")
        assert (
            OpenAIResumeConfig(**cast("dict[str, Any]", {"cursor": "u1", "project_id": "proj_2"})).project_id
            == "proj_2"
        )
        assert OpenAIResumeConfig(**cast("dict[str, Any]", {"fanout_state": {"completed": []}})).fanout_state == {
            "completed": []
        }


class TestRetries:
    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_retryable_status_is_retried_then_succeeds(self, _name: str, status: int) -> None:
        result = _driver().run(
            "users",
            [
                ScriptedResponse(status=status, json={}),
                _entity_page([{"id": "user_1"}], has_more=False, last_id="user_1"),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["user_1"]
        assert len(result.requests) == 2

    def test_client_error_raises_without_retry(self) -> None:
        result = _driver().run("users", [ScriptedResponse(status=401, json={"error": "unauthorized"})])

        assert isinstance(result.raised, requests.HTTPError)
        assert len(result.requests) == 1


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("forbidden_scope", 403, True, None),
            ("service_unavailable", 503, False, "couldn't check your Admin API key"),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected: bool, fragment: str | None) -> None:
        # 403 is accepted at create time (real key, unprobed scope); 401 means a bad key. Anything
        # else leaves the key unjudged, so it must not read as a rejection.
        with scripted_network(always(ScriptedResponse(status=status))) as network:
            is_valid, message = validate_credentials("sk-admin-test")

        assert network.requests_log
        assert {request.path for request in network.requests_log} == {"/v1/organization/projects"}
        assert {request.param("limit") for request in network.requests_log} == {"1"}
        assert is_valid is expected
        if fragment is None:
            assert message is None
        else:
            assert message is not None and fragment in message


class TestRetryableErrors:
    @parameterized.expand(
        [
            ("server_error", "HTTP 500 for https://api.openai.com/v1/organization/projects/proj_1/api_keys"),
            ("rate_limited", "HTTP 429 for https://api.openai.com/v1/organization/costs"),
            ("connection_error", "Connection error (ConnectionError) for https://api.openai.com/v1/organization/users"),
            ("timeout", "Request timed out (ReadTimeout) for https://api.openai.com/v1/organization/usage/completions"),
            (
                "malformed_json",
                "Malformed JSON response from https://api.openai.com/v1/organization/costs: Expecting value: line 1 column 1 (char 0)",
            ),
        ]
    )
    def test_exhausted_transient_failures_are_recognized(self, _name: str, observed_error: str) -> None:
        retryable = OpenAISource().get_retryable_errors()
        assert any(pattern in observed_error for pattern in retryable)

    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.openai.com/v1/organization/users"),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.openai.com/v1/organization/costs"),
        ]
    )
    def test_credential_errors_are_not_misclassified(self, _name: str, other_error: str) -> None:
        retryable = OpenAISource().get_retryable_errors()
        assert not any(pattern in other_error for pattern in retryable)


class TestToolCallUsageGroupBy:
    # Each tool-usage endpoint advertises a distinct group_by set; requesting a dimension the endpoint
    # does not support (e.g. `model` on file_search) makes the live API 400, so guard the composition.
    @parameterized.expand(
        [
            ("usage_web_search_calls", ["project_id", "user_id", "api_key_id", "model", "context_level"]),
            ("usage_file_search_calls", ["project_id", "user_id", "api_key_id", "vector_store_id"]),
        ]
    )
    def test_group_by_matches_supported_dimensions(self, endpoint: str, expected: list[str]) -> None:
        assert OPENAI_ENDPOINTS[endpoint].group_by == expected
