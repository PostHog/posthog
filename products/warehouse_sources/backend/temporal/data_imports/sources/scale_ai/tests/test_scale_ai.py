import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    DEFAULT_RETRY_ATTEMPTS,
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.scale_ai.scale_ai import (
    ScaleAIResumeConfig,
    _build_params,
    _format_incremental_value,
    scale_ai_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.scale_ai.settings import SCALE_AI_ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the scale_ai module.
SCALE_AI_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.scale_ai.scale_ai.make_tracked_session"
)


def _docs_response(docs: list[dict[str, Any]], next_token: Any = "__unset__", status_code: int = 200) -> Response:
    body: dict[str, Any] = {"docs": docs}
    if next_token != "__unset__":
        body["next_token"] = next_token
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    return resp


def _array_response(items: list[dict[str, Any]]) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(items).encode()
    return resp


def _error_response(status_code: int) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = b'{"error": "boom"}'
    return resp


def _make_manager(resume_state: ScaleAIResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and snapshot each request's params/auth AT PREPARE TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the
    run shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"params": dict(request.params or {}), "auth": request.auth})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.MagicMock | None = None, **kwargs: Any):
    return scale_ai_source(
        api_key="live_key",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager if manager is not None else _make_manager(),
        **kwargs,
    )


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14+00:00"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14+00:00"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00+00:00"),
            ("string_passthrough", "cursor", "cursor"),
        ]
    )
    def test_format_incremental_value(self, _name: str, value: object, expected: str) -> None:
        assert _format_incremental_value(value) == expected


class TestBuildParams:
    @parameterized.expand(
        [
            # The chosen incremental field maps to a specific server-side param; the wrong param would
            # silently ignore the cutoff and re-scan the full history every run.
            ("tasks_updated_at", "tasks", "updated_at", "updated_after"),
            ("tasks_created_at", "tasks", "created_at", "start_time"),
            ("batches_created_at", "batches", "created_at", "start_time"),
        ]
    )
    def test_incremental_field_maps_to_server_param(
        self, _name: str, endpoint: str, incremental_field: str, expected_param: str
    ) -> None:
        params = _build_params(
            SCALE_AI_ENDPOINTS[endpoint],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
            incremental_field=incremental_field,
        )
        assert params[expected_param] == "2026-03-04T00:00:00+00:00"

    def test_no_incremental_param_when_disabled(self) -> None:
        params = _build_params(
            SCALE_AI_ENDPOINTS["tasks"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
            incremental_field="updated_at",
        )
        assert "updated_after" not in params
        assert "start_time" not in params
        assert params["limit"] == 100

    def test_projects_has_no_limit_param(self) -> None:
        # Projects is a single non-paginated list; sending limit/offset would be meaningless.
        params = _build_params(
            SCALE_AI_ENDPOINTS["projects"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
        )
        assert params == {}


class TestCursorPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_next_token_until_exhausted(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _docs_response([{"task_id": "T1"}], next_token="tok2"),
                _docs_response([{"task_id": "T2"}], next_token="tok3"),
                _docs_response([{"task_id": "T3"}], next_token=None),
            ],
        )

        rows = _rows(_source("tasks"))
        assert [r["task_id"] for r in rows] == ["T1", "T2", "T3"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_sends_next_token_on_subsequent_requests(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _docs_response([{"task_id": "T1"}], next_token="tok2"),
                _docs_response([{"task_id": "T2"}], next_token=None),
            ],
        )

        _rows(_source("tasks"))
        # First page has no cursor; the second request carries the token from page one.
        assert "next_token" not in snapshots[0]["params"]
        assert snapshots[1]["params"]["next_token"] == "tok2"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_checkpoints_next_page_token_then_stops(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _docs_response([{"task_id": "T1"}], next_token="tok2"),
                _docs_response([{"task_id": "T2"}], next_token=None),
            ],
        )

        manager = _make_manager()
        _rows(_source("tasks", manager))
        # Checkpoint the token pointing at the next page after page one; the final (null-token) page
        # saves nothing, so a resume re-fetches the saved page (merge dedupes) rather than skipping it.
        assert [c.args[0] for c in manager.save_state.call_args_list] == [ScaleAIResumeConfig(next_token="tok2")]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_token(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_docs_response([{"task_id": "T2"}], next_token=None)])

        manager = _make_manager(ScaleAIResumeConfig(next_token="tok2"))
        rows = _rows(_source("tasks", manager))
        # T1 (first page) is skipped because we resume mid-stream from tok2.
        assert [r["task_id"] for r in rows] == ["T2"]
        assert snapshots[0]["params"]["next_token"] == "tok2"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_cutoff_sent_on_first_request(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_docs_response([{"task_id": "T1"}], next_token=None)])

        _rows(
            _source(
                "tasks",
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
                incremental_field="updated_at",
            )
        )
        assert snapshots[0]["params"]["updated_after"] == "2026-03-04T00:00:00+00:00"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_requests_carry_basic_auth(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_docs_response([{"task_id": "T1"}], next_token=None)])

        _rows(_source("tasks"))
        auth = snapshots[0]["auth"]
        # Scale AI uses HTTP Basic with the API key as the username and an empty password.
        assert auth.username == "live_key"
        assert auth.password == ""


class TestOffsetPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_walks_offsets_until_short_page(self, MockSession) -> None:
        session = MockSession.return_value
        full_page = [{"name": f"B{i}"} for i in range(100)]
        snapshots = _wire(session, [_docs_response(full_page), _docs_response([{"name": "B100"}])])

        rows = _rows(_source("batches"))
        assert len(rows) == 101
        assert rows[-1]["name"] == "B100"
        assert snapshots[0]["params"]["offset"] == 0
        assert snapshots[1]["params"]["offset"] == 100

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_on_first_short_page(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_docs_response([{"name": "B1"}, {"name": "B2"}])])

        manager = _make_manager()
        rows = _rows(_source("batches", manager))
        assert [r["name"] for r in rows] == ["B1", "B2"]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_checkpoints_next_offset_after_full_page(self, MockSession) -> None:
        session = MockSession.return_value
        full_page = [{"name": f"B{i}"} for i in range(100)]
        _wire(session, [_docs_response(full_page), _docs_response([{"name": "B100"}])])

        manager = _make_manager()
        _rows(_source("batches", manager))
        # Full first page checkpoints the next offset (100); the short second page saves nothing.
        assert [c.args[0] for c in manager.save_state.call_args_list] == [ScaleAIResumeConfig(offset=100)]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_offset(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_docs_response([{"name": "B100"}])])

        manager = _make_manager(ScaleAIResumeConfig(offset=100))
        rows = _rows(_source("batches", manager))
        assert [r["name"] for r in rows] == ["B100"]
        assert snapshots[0]["params"]["offset"] == 100


class TestSingleFetch:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_projects_fetches_once_from_bare_array(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_array_response([{"name": "P1"}, {"name": "P2"}])])

        rows = _rows(_source("projects"))
        assert [r["name"] for r in rows] == ["P1", "P2"]
        assert session.send.call_count == 1


class TestRetryAndErrors:
    @mock.patch("time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_statuses_retried_then_succeed(self, MockSession, _sleep) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _error_response(500),
                _error_response(429),
                _docs_response([{"task_id": "T1"}], next_token=None),
            ],
        )

        rows = _rows(_source("tasks"))
        assert [r["task_id"] for r in rows] == ["T1"]
        assert session.send.call_count == 3

    @mock.patch("time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retries_exhausted_raises(self, MockSession, _sleep) -> None:
        session = MockSession.return_value
        _wire(session, [_error_response(500)] * DEFAULT_RETRY_ATTEMPTS)

        with pytest.raises(RESTClientRetryableError):
            _rows(_source("tasks"))
        assert session.send.call_count == DEFAULT_RETRY_ATTEMPTS

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_auth_error_is_not_retried(self, _name: str, status_code: int, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_error_response(status_code)])

        with pytest.raises(Exception, match=str(status_code)):
            _rows(_source("tasks"))
        assert session.send.call_count == 1


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    @mock.patch(SCALE_AI_SESSION_PATCH)
    def test_status_maps_to_validity(self, _name: str, status_code: int, expected: bool, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        assert validate_credentials("live_key") is expected

    @mock.patch(SCALE_AI_SESSION_PATCH)
    def test_network_error_is_invalid(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("live_key") is False


class TestSourceResponse:
    @parameterized.expand([("tasks", ["task_id"]), ("batches", ["name"]), ("projects", ["name"])])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_primary_keys_and_desc_sort(self, endpoint: str, primary_keys: list[str], MockSession) -> None:
        # sort_mode="desc" defers watermark persistence to job end — required because tasks filter on
        # updated_at but arrive in created_at order.
        response = _source(endpoint)
        assert response.primary_keys == primary_keys
        assert response.sort_mode == "desc"
        assert response.partition_keys == ["created_at"]
