import json
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.openai.openai import (
    OpenAIResumeConfig,
    _flatten_bucket_result,
    _normalize_audit_log,
    openai_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.openai.settings import OPENAI_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.openai.source import OpenAISource

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the openai module.
OPENAI_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.openai.openai.make_tracked_session"
)
# tenacity sleeps between retries — patch it so retryable-status tests don't actually wait.
TENACITY_SLEEP_PATCH = "tenacity.nap.time.sleep"

PROJECT_USERS_PATH = "/v1/organization/projects/{project_id}/users"


def _response(body: dict[str, Any], status: int = 200, headers: dict[str, str] | None = None) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    resp.url = "https://api.openai.com/v1/organization/users"
    if headers:
        resp.headers.update(headers)
    return resp


def _entity_page(items: list[dict[str, Any]], *, has_more: bool, last_id: str | None = None) -> Response:
    body: dict[str, Any] = {"data": items, "has_more": has_more}
    if last_id is not None:
        body["last_id"] = last_id
    return _response(body)


def _bucket_page(buckets: list[dict[str, Any]], *, has_more: bool, next_page: str | None) -> Response:
    return _response({"data": buckets, "has_more": has_more, "next_page": next_page})


def _lookback_exceeded() -> Response:
    return _response(
        {"error": {"type": "invalid_request_error", "code": "reporting_lookback_exceeded", "message": "too far back"}},
        status=400,
    )


def _make_manager(resume_state: OpenAIResumeConfig | None = None) -> mock.MagicMock:
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
    return openai_source(
        api_key="sk-admin-test",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        db_incremental_field_last_value=last_value,
    )


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


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
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_lookback_exceeded_retries_with_a_later_start(self, _name: str, last_value: Any, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _lookback_exceeded(),
                _lookback_exceeded(),
                _bucket_page(
                    [{"start_time": 1, "end_time": 2, "results": [{"model": "a"}]}], has_more=False, next_page=None
                ),
            ],
        )

        manager = _make_manager(OpenAIResumeConfig(cursor="STALE"))
        rows = _rows(_source("usage_audio_speeches", manager, last_value=last_value))

        assert [r["model"] for r in rows] == ["a"]
        starts = [p["params"]["start_time"] for p in params]
        assert starts[0] < starts[1] < starts[2]
        assert starts[2] > int(datetime.now(UTC).timestamp()) - 400 * 24 * 60 * 60
        # The saved page cursor belongs to the rejected start, so a fallback must not send it.
        assert params[0]["params"]["page"] == "STALE"
        assert "page" not in params[1]["params"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_lookback_exceeded_on_every_start_raises_non_retryable_error(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_lookback_exceeded() for _ in range(10)])

        with pytest.raises(requests.HTTPError) as exc_info:
            _rows(_source("usage_vector_stores", _make_manager()))

        assert session.send.call_count == 7
        non_retryable = OpenAISource().get_non_retryable_errors()
        assert any(key in str(exc_info.value) for key in non_retryable)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_lookback_exceeded_on_recent_watermark_does_not_move_start(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_lookback_exceeded(), _bucket_page([], has_more=False, next_page=None)])

        with pytest.raises(requests.HTTPError):
            _rows(_source("usage_vector_stores", _make_manager(), last_value=datetime.now(UTC)))
        assert session.send.call_count == 1


class TestBucketPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_with_next_page_token_stops_pagination(self, MockSession) -> None:
        # The costs endpoint is known to return a next_page token alongside an empty page; without
        # the guard, pagination would loop on the empty tail forever.
        session = MockSession.return_value
        _wire(
            session,
            [
                _bucket_page(
                    [{"start_time": 1, "end_time": 2, "results": [{"line_item": "x"}]}],
                    has_more=True,
                    next_page="PAGE2",
                ),
                _bucket_page([], has_more=True, next_page="PAGE3"),
            ],
        )

        rows = _rows(_source("costs", _make_manager()))

        assert [r["line_item"] for r in rows] == ["x"]
        assert session.send.call_count == 2


class TestEntityPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_cursor_pagination_uses_after_and_stops(self, MockSession) -> None:
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
        assert "after" not in params[0]["params"]
        assert params[0]["params"]["limit"] == 100
        assert params[1]["params"]["after"] == "user_1"
        assert session.send.call_count == 2
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == OpenAIResumeConfig(cursor="user_1")

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_after_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_entity_page([{"id": "user_6"}], has_more=False, last_id="user_6")])

        _rows(_source("users", _make_manager(OpenAIResumeConfig(cursor="user_5"))))

        assert params[0]["params"]["after"] == "user_5"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_admin_api_keys_flatten_owner(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _entity_page(
                    [{"id": "key_1", "owner": {"type": "user", "id": "user_1", "name": "Ada"}}],
                    has_more=False,
                    last_id="key_1",
                )
            ],
        )

        rows = _rows(_source("admin_api_keys", _make_manager()))

        assert rows[0]["owner_id"] == "user_1"
        assert "owner" not in rows[0]


class TestAuditLogs:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_sends_no_effective_at_filter(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response(
                    {
                        "data": [{"id": "audit_log-1", "type": "project.created", "effective_at": 1722470400}],
                        "has_more": False,
                    }
                )
            ],
        )

        _rows(_source("audit_logs", _make_manager()))

        assert "effective_at[gte]" not in params[0]["params"]


class TestProjectFanOut:
    @mock.patch(TENACITY_SLEEP_PATCH, return_value=None)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_one_project_500ing_is_skipped_and_others_land(self, MockSession, _sleep) -> None:
        # proj_1's resource keeps returning 500 past the client's retry budget; without per-project
        # tolerance that would fail the whole schema. The fan-out must skip proj_1 and still yield
        # proj_2's rows.
        session = MockSession.return_value
        _wire(
            session,
            [
                _entity_page([{"id": "proj_1"}, {"id": "proj_2"}], has_more=False, last_id="proj_2"),
                *[_response({}, status=500) for _ in range(5)],
                _entity_page([{"id": "user_2"}], has_more=False, last_id="user_2"),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("project_users", manager))

        assert [(r["project_id"], r["id"]) for r in rows] == [("proj_2", "user_2")]
        # The skipped project stays off the completed checkpoint so a later run re-attempts it.
        final = [call.args[0] for call in manager.save_state.call_args_list][-1].fanout_state
        assert final["completed"] == [PROJECT_USERS_PATH.format(project_id="proj_2")]

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
    @mock.patch(TENACITY_SLEEP_PATCH, return_value=None)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_status_is_retried_then_succeeds(self, _name: str, status: int, MockSession, _sleep) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response({}, status=status),
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
    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("forbidden_scope", 403, True, None),
            ("unauthorized", 401, False, "rejected your Admin API key"),
            ("service_unavailable", 503, False, "couldn't check your Admin API key"),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected: bool, fragment: str | None) -> None:
        # 403 is accepted at create time (real key, unprobed scope); 401 means a bad key. Anything
        # else leaves the key unjudged, so it must not read as a rejection.
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=status)
        with mock.patch(OPENAI_SESSION_PATCH, return_value=session):
            is_valid, message = validate_credentials("sk-admin-test")

        assert is_valid is expected
        if fragment is None:
            assert message is None
        else:
            assert message is not None and fragment in message


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
