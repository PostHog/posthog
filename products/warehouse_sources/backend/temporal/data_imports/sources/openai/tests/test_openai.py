import json
from datetime import UTC, datetime
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.openai.openai import (
    OpenAIResumeConfig,
    _flatten_bucket_result,
    _flatten_owner,
    _normalize_audit_log,
    _row_id,
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


class TestBucketParams:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_uses_watermark_as_unix_start_time(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_bucket_page([], has_more=False, next_page=None)])

        watermark = datetime(2026, 3, 4, 0, 0, 0, tzinfo=UTC)
        _rows(_source("usage_completions", _make_manager(), last_value=watermark))

        config = OPENAI_ENDPOINTS["usage_completions"]
        assert params[0]["params"]["start_time"] == int(watermark.timestamp())
        assert params[0]["params"]["bucket_width"] == "1d"
        assert params[0]["params"]["limit"] == 31
        # requests encodes the list as one repeated group_by query param per dimension.
        assert params[0]["params"]["group_by"] == config.group_by

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_falls_back_to_api_launch_era(self, MockSession) -> None:
        # Without a watermark we must still send the required start_time; the API launch era pulls
        # all available history without requesting decades of empty pre-launch buckets.
        session = MockSession.return_value
        params = _wire(session, [_bucket_page([], has_more=False, next_page=None)])

        _rows(_source("costs", _make_manager()))

        assert params[0]["params"]["start_time"] == int(datetime(2020, 1, 1, tzinfo=UTC).timestamp())
        assert params[0]["params"]["limit"] == 180


class TestBucketPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_next_page_until_has_more_false(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _bucket_page(
                    [{"start_time": 1, "end_time": 2, "results": [{"model": "a"}]}], has_more=True, next_page="PAGE2"
                ),
                _bucket_page(
                    [{"start_time": 2, "end_time": 3, "results": [{"model": "b"}]}], has_more=False, next_page=None
                ),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("usage_completions", manager))

        assert [r["model"] for r in rows] == ["a", "b"]
        # Second request must carry the page token from the first response; the first must not.
        assert "page" not in params[0]["params"]
        assert params[1]["params"]["page"] == "PAGE2"
        # Checkpoint saved after the first page was yielded, pointing at the next page.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == OpenAIResumeConfig(cursor="PAGE2")

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_explodes_every_result_in_a_bucket(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _bucket_page(
                    [
                        {"start_time": 1722470400, "end_time": 1722556800, "results": [{"model": "a"}, {"model": "b"}]},
                        {"start_time": 1722556800, "end_time": 1722643200, "results": []},
                    ],
                    has_more=False,
                    next_page=None,
                ),
            ],
        )

        rows = _rows(_source("usage_completions", _make_manager()))

        # Two rows from the first bucket (bucket window merged into each), none from the empty one.
        assert [(r["model"], r["start_time"]) for r in rows] == [
            ("a", datetime(2024, 8, 1, tzinfo=UTC)),
            ("b", datetime(2024, 8, 1, tzinfo=UTC)),
        ]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _bucket_page(
                    [{"start_time": 2, "end_time": 3, "results": [{"model": "b"}]}], has_more=False, next_page=None
                )
            ],
        )

        manager = _make_manager(OpenAIResumeConfig(cursor="PAGE2"))
        rows = _rows(_source("usage_completions", manager))

        assert [r["model"] for r in rows] == ["b"]
        assert params[0]["params"]["page"] == "PAGE2"

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
    def test_falls_back_to_last_item_id_when_last_id_missing(self, MockSession) -> None:
        # `last_id` isn't documented on every list response; the last item's id must keep
        # pagination moving instead of stopping after page one.
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _entity_page([{"id": "user_1"}], has_more=True),
                _entity_page([{"id": "user_2"}], has_more=False),
            ],
        )

        rows = _rows(_source("users", _make_manager()))

        assert [r["id"] for r in rows] == ["user_1", "user_2"]
        assert params[1]["params"]["after"] == "user_1"

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

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_projects_include_archived(self, MockSession) -> None:
        # Archived projects are still referenced by historical usage/cost rows, so the dimension
        # table must stay complete.
        session = MockSession.return_value
        params = _wire(session, [_entity_page([{"id": "proj_1"}], has_more=False, last_id="proj_1")])

        _rows(_source("projects", _make_manager()))

        assert params[0]["params"]["include_archived"] == "true"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_data_key_yields_no_rows(self, MockSession) -> None:
        # The legacy implementation tolerated a body without `data` (0 rows); preserve that.
        session = MockSession.return_value
        _wire(session, [_response({"has_more": False})])

        assert _rows(_source("users", _make_manager())) == []


class TestAuditLogs:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_applies_effective_at_filter(self, MockSession) -> None:
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

        watermark = datetime(2026, 3, 4, tzinfo=UTC)
        _rows(_source("audit_logs", _make_manager(), last_value=watermark))

        # Bracket-style nested param, matching the official SDK's serialization.
        assert params[0]["params"]["effective_at[gte]"] == int(watermark.timestamp())

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
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_emits_one_row_per_project_resource_with_composite_key(self, MockSession) -> None:
        # First response lists projects, then one page per project's users.
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _entity_page([{"id": "proj_1"}, {"id": "proj_2"}], has_more=False, last_id="proj_2"),
                _entity_page([{"id": "user_1"}], has_more=False, last_id="user_1"),
                _entity_page([{"id": "user_1"}], has_more=False, last_id="user_1"),
            ],
        )

        rows = _rows(_source("project_users", _make_manager()))

        assert [(r["project_id"], r["id"]) for r in rows] == [("proj_1", "user_1"), ("proj_2", "user_1")]
        # The framework's parent-key column must not leak into the row shape.
        assert all("_projects_id" not in r for r in rows)
        assert params[0]["url"].endswith("/v1/organization/projects")
        assert params[0]["params"]["include_archived"] == "true"
        assert params[1]["url"].endswith("/v1/organization/projects/proj_1/users")
        assert params[2]["url"].endswith("/v1/organization/projects/proj_2/users")

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_project_api_keys_flatten_owner_and_stamp_project(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _entity_page([{"id": "proj_1"}], has_more=False, last_id="proj_1"),
                _entity_page(
                    [{"id": "key_1", "owner": {"type": "user", "user": {"id": "user_1", "name": "Ada"}}}],
                    has_more=False,
                    last_id="key_1",
                ),
            ],
        )

        rows = _rows(_source("project_api_keys", _make_manager()))

        assert rows[0]["project_id"] == "proj_1"
        assert rows[0]["owner_id"] == "user_1"
        assert "owner" not in rows[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_checkpoints_completed_projects(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _entity_page([{"id": "proj_1"}, {"id": "proj_2"}], has_more=False, last_id="proj_2"),
                _entity_page([{"id": "user_1"}], has_more=False, last_id="user_1"),
                _entity_page([{"id": "user_2"}], has_more=False, last_id="user_2"),
            ],
        )

        manager = _make_manager()
        _rows(_source("project_users", manager))

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved, "fan-out must checkpoint progress"
        assert all(isinstance(state, OpenAIResumeConfig) and state.fanout_state for state in saved)
        final = saved[-1].fanout_state
        assert final["completed"] == [
            PROJECT_USERS_PATH.format(project_id="proj_1"),
            PROJECT_USERS_PATH.format(project_id="proj_2"),
        ]
        assert final["current"] is None

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_skipping_completed_projects(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _entity_page([{"id": "proj_1"}, {"id": "proj_2"}], has_more=False, last_id="proj_2"),
                # Only proj_2's users are fetched — proj_1 completed before the crash.
                _entity_page([{"id": "user_2"}], has_more=False, last_id="user_2"),
            ],
        )

        resume = OpenAIResumeConfig(
            fanout_state={
                "completed": [PROJECT_USERS_PATH.format(project_id="proj_1")],
                "current": None,
                "child_state": None,
            }
        )
        rows = _rows(_source("project_users", _make_manager(resume)))

        assert [(r["project_id"], r["id"]) for r in rows] == [("proj_2", "user_2")]
        assert session.send.call_count == 2
        assert params[1]["url"].endswith("/v1/organization/projects/proj_2/users")

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_legacy_resume_state_restarts_fan_out_fresh(self, MockSession) -> None:
        # Pre-framework state carried (cursor, project_id). It still parses, but the fan-out restarts
        # from scratch — the overlap merge dedupes on the composite key.
        session = MockSession.return_value
        _wire(
            session,
            [
                _entity_page([{"id": "proj_1"}], has_more=False, last_id="proj_1"),
                _entity_page([{"id": "user_1"}], has_more=False, last_id="user_1"),
            ],
        )

        resume = OpenAIResumeConfig(cursor="user_0", project_id="proj_1")
        rows = _rows(_source("project_users", _make_manager(resume)))

        assert [(r["project_id"], r["id"]) for r in rows] == [("proj_1", "user_1")]

    def test_saved_state_shapes_still_parse(self) -> None:
        # ResumableSourceManager._load_json does dataclass(**saved) — every historical shape must
        # keep parsing after the migration.
        assert OpenAIResumeConfig(**{"cursor": "PAGE2", "project_id": None}) == OpenAIResumeConfig(cursor="PAGE2")
        assert OpenAIResumeConfig(**{"cursor": "u1", "project_id": "proj_2"}).project_id == "proj_2"
        assert OpenAIResumeConfig(**{"fanout_state": {"completed": []}}).fanout_state == {"completed": []}


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
    @parameterized.expand([("ok", 200, True), ("forbidden_scope", 403, True), ("unauthorized", 401, False)])
    def test_status_mapping(self, _name: str, status: int, expected: bool) -> None:
        # 403 is accepted at create time (real key, unprobed scope); 401 means a bad key.
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=status)
        with mock.patch(OPENAI_SESSION_PATCH, return_value=session):
            assert validate_credentials("sk-admin-test") is expected

    def test_network_error_is_invalid(self) -> None:
        session = mock.MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with mock.patch(OPENAI_SESSION_PATCH, return_value=session):
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
