import os
import json
import time
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.elevenlabs.elevenlabs import (
    ElevenLabsResumeConfig,
    _build_params,
    _to_unix_seconds,
    elevenlabs_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.elevenlabs.settings import ELEVENLABS_ENDPOINTS

# The RESTClient uses the session built by make_tracked_session in the elevenlabs module (passed via
# the client config's `session` slot), and validate_credentials builds its probe session there too.
SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.elevenlabs.elevenlabs.make_tracked_session"
)


def _response(body: dict[str, Any], status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    resp.url = "https://api.elevenlabs.io/v1/history"
    return resp


def _make_manager(resume_state: ElevenLabsResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list capturing each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages (the paginator injects the next
    cursor into it), so inspecting it after the run shows only the final state — snapshot a copy when
    each request is prepared instead.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.MagicMock, **incremental: Any):
    return elevenlabs_source("k", endpoint, team_id=1, job_id="j", resumable_source_manager=manager, **incremental)


class TestToUnixSeconds:
    @parameterized.expand(
        [
            ("int_passthrough", 1700000000, 1700000000),
            ("datetime", datetime(2024, 1, 1, tzinfo=UTC), 1704067200),
            ("numeric_string", "1700000000", 1700000000),
        ]
    )
    def test_to_unix_seconds(self, _name: str, value: Any, expected: int) -> None:
        assert _to_unix_seconds(value) == expected

    def test_naive_values_are_interpreted_as_utc_regardless_of_server_tz(self) -> None:
        # A local-time interpretation would shift the incremental watermark by the server's UTC offset,
        # so the same date would sync different windows on different machines. Force a non-UTC zone and
        # assert both a `date` and a naive `datetime` still resolve to the UTC epoch.
        original_tz = os.environ.get("TZ")
        os.environ["TZ"] = "America/New_York"
        time.tzset()
        try:
            assert _to_unix_seconds(date(2024, 1, 1)) == 1704067200
            assert _to_unix_seconds(datetime(2024, 1, 1)) == 1704067200
        finally:
            if original_tz is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = original_tz
            time.tzset()


class TestBuildParams:
    def test_conversations_incremental_uses_call_start_after_unix_with_summary(self) -> None:
        params = _build_params(ELEVENLABS_ENDPOINTS["conversations"], True, 1700000000, "start_time_unix_secs")
        assert params["call_start_after_unix"] == 1700000000
        assert params["summary_mode"] == "include"

    @parameterized.expand([("agents",), ("voices",), ("triage_tickets",), ("tools",)])
    def test_full_refresh_endpoints_never_send_a_time_filter(self, endpoint: str) -> None:
        # Full-refresh endpoints have no server-side updated-since filter; sending one would 4xx.
        params = _build_params(ELEVENLABS_ENDPOINTS[endpoint], True, 1700000000, "created_at_unix")
        assert not any("after_unix" in key for key in params)


class TestPagination:
    @mock.patch(SESSION_PATCH)
    def test_walks_cursor_pages_and_saves_state_after_each_yield(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response({"history": [{"history_item_id": "a"}], "has_more": True, "last_history_item_id": "a"}),
                _response({"history": [{"history_item_id": "b"}], "has_more": False, "last_history_item_id": "b"}),
            ],
        )
        manager = _make_manager()
        rows = _rows(_source("history", manager))

        assert rows == [{"history_item_id": "a"}, {"history_item_id": "b"}]
        # Page 1 sends no cursor; page 2 sends the cursor from page 1 under the endpoint's cursor param.
        assert "start_after_history_item_id" not in params[0]
        assert params[0]["page_size"] == 1000
        assert params[1]["start_after_history_item_id"] == "a"
        # Saved only once (after page 1, since page 2 is terminal) so a crash re-yields the last page.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == ElevenLabsResumeConfig(cursor="a")

    @mock.patch(SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [_response({"conversations": [{"conversation_id": "x"}], "has_more": False, "next_cursor": None})],
        )
        manager = _make_manager(ElevenLabsResumeConfig(cursor="C1"))
        rows = _rows(_source("conversations", manager))

        assert rows == [{"conversation_id": "x"}]
        # The resumed run starts at the saved cursor, sent under the conversations cursor param.
        assert params[0]["cursor"] == "C1"

    @mock.patch(SESSION_PATCH)
    def test_credential_error_fails_loud(self, MockSession) -> None:
        # A 401 is a doomed credential problem; it must raise (feeding get_non_retryable_errors), not retry.
        session = MockSession.return_value
        _wire(session, [_response({}, status=401)])
        with pytest.raises(requests.HTTPError):
            _rows(_source("history", _make_manager()))
        assert session.send.call_count == 1


class TestFanOut:
    @parameterized.expand(
        [
            ("full_refresh", False, None),
            ("incremental", True, 1700000000.5),
        ]
    )
    @mock.patch(SESSION_PATCH)
    def test_tool_executions_walk_every_tool_and_page(
        self, _name: str, use_incremental: bool, last_value: Any, MockSession
    ) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response({"tools": [{"id": "t1"}, {"id": "t2"}], "has_more": False, "next_cursor": None}),
                _response({"executions": [{"id": "e1", "tool_id": "t1"}], "has_more": True, "next_cursor": "c1"}),
                _response({"executions": [{"id": "e2", "tool_id": "t1"}], "has_more": False, "next_cursor": None}),
                _response({"executions": [{"id": "e3", "tool_id": "t2"}], "has_more": False, "next_cursor": None}),
            ],
        )
        rows = _rows(
            _source(
                "tool_executions",
                _make_manager(),
                should_use_incremental_field=use_incremental,
                db_incremental_field_last_value=last_value,
                incremental_field="timestamp" if use_incremental else None,
            )
        )

        assert [row["id"] for row in rows] == ["e1", "e2", "e3"]
        assert params[0]["sort_by"] == "created_at"
        assert "start_time" not in params[0]
        assert params[2]["cursor"] == "c1"
        # The time filter binds every child page, so incremental runs never re-walk full history.
        for child_params in params[1:]:
            if use_incremental:
                assert child_params["start_time"] == 1700000000
            else:
                assert "start_time" not in child_params


class TestSecretRedaction:
    @parameterized.expand(
        [
            (
                "tool_config_headers",
                "tools",
                [
                    {
                        "tools": [
                            {
                                "id": "t1",
                                "tool_config": {
                                    "api_schema": {
                                        "request_headers": {
                                            "Authorization": "Bearer sk_fake",
                                            "X-Ref": {"secret_id": "s1"},
                                        }
                                    }
                                },
                            }
                        ],
                        "has_more": False,
                    }
                ],
                lambda row: row["tool_config"]["api_schema"]["request_headers"],
            ),
            (
                "execution_sent_headers",
                "tool_executions",
                [
                    {"tools": [{"id": "t1"}], "has_more": False},
                    {
                        "executions": [
                            {
                                "id": "e1",
                                "tool_id": "t1",
                                "tool_call_details": {
                                    "headers": {"Authorization": "Bearer sk_fake", "X-Ref": {"secret_id": "s1"}}
                                },
                            }
                        ],
                        "has_more": False,
                    },
                ],
                lambda row: row["tool_call_details"]["headers"],
            ),
        ]
    )
    @mock.patch(SESSION_PATCH)
    def test_literal_header_values_never_reach_the_warehouse(
        self, _name: str, endpoint: str, bodies: list[dict[str, Any]], headers_of: Any, MockSession
    ) -> None:
        _wire(MockSession.return_value, [_response(body) for body in bodies])

        rows = _rows(_source(endpoint, _make_manager()))

        # A secret reference is safe to keep and tells the reader which secret the tool uses.
        assert headers_of(rows[0]) == {"Authorization": "[REDACTED]", "X-Ref": {"secret_id": "s1"}}


class TestUnpaginatedEndpoints:
    @parameterized.expand(
        [
            ("models_bare_array", "models", [{"model_id": "m1"}, {"model_id": "m2"}], ["m1", "m2"], "model_id"),
            (
                "groups_keyed_by_id",
                "workspace_groups",
                {"g1": {"id": "g1", "name": "a"}, "g2": {"id": "g2", "name": "b"}},
                ["g1", "g2"],
                "id",
            ),
            # jsonpath unwraps a single match, so a one-group body must still come back as one row.
            ("single_group", "workspace_groups", {"g1": {"id": "g1", "name": "a"}}, ["g1"], "id"),
            ("no_groups", "workspace_groups", {}, [], "id"),
        ]
    )
    @mock.patch(SESSION_PATCH)
    def test_whole_collection_becomes_rows(
        self, _name: str, endpoint: str, body: Any, expected_ids: list[str], id_key: str, MockSession
    ) -> None:
        session = MockSession.return_value
        response = Response()
        response.status_code = 200
        response._content = json.dumps(body).encode()
        response.url = "https://api.elevenlabs.io/v1/workspace/groups"
        params = _wire(session, [response])

        rows = _rows(_source(endpoint, _make_manager()))

        assert [row[id_key] for row in rows] == expected_ids
        assert session.send.call_count == 1
        assert "page_size" not in params[0]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("valid", 200, None, True),
            ("bad_key", 401, None, False),
            # A 400 (the status users actually hit) is a deterministic client error, not transient.
            ("bad_request_at_create", 400, None, False),
            ("missing_scope_at_create", 403, None, True),
            ("missing_scope_at_schema", 403, "history", False),
            # An unverified key (transient 429/5xx) must not be saved as valid at create time.
            ("rate_limited_at_create", 429, None, False),
            ("server_error_at_create", 500, None, False),
        ]
    )
    @mock.patch(SESSION_PATCH)
    def test_status_mapping(self, _name: str, status: int, schema_name: str | None, expected_ok: bool, mts) -> None:
        mts.return_value.get.return_value = mock.MagicMock(status_code=status)
        ok, _msg = validate_credentials("k", schema_name)
        assert ok is expected_ok

    @parameterized.expand(
        [
            ("fan_out_child_probes_parent", "tool_executions", "https://api.elevenlabs.io/v1/convai/tools?page_size=1"),
            ("unpaginated_sends_no_page_size", "workspace_members", "https://api.elevenlabs.io/v1/workspace/members"),
        ]
    )
    @mock.patch(SESSION_PATCH)
    def test_schema_probe_url(self, _name: str, schema_name: str, expected_url: str, mts) -> None:
        mts.return_value.get.return_value = mock.MagicMock(status_code=200)
        assert validate_credentials("k", schema_name) == (True, None)
        assert mts.return_value.get.call_args.args[0] == expected_url

    @mock.patch(SESSION_PATCH)
    def test_network_error_is_not_valid(self, mts) -> None:
        mts.return_value.get.side_effect = requests.ConnectionError("boom")
        ok, msg = validate_credentials("k")
        assert ok is False
        assert msg is not None

    @mock.patch(SESSION_PATCH)
    def test_session_does_not_follow_redirects(self, mts) -> None:
        # requests keeps the custom xi-api-key header across a cross-origin 3xx; following one would
        # replay the key to the redirect target, so the credentialed session must refuse redirects.
        mts.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("k")
        assert mts.call_args.kwargs["allow_redirects"] is False


class TestSyncSecurity:
    @mock.patch(SESSION_PATCH)
    def test_sync_session_does_not_follow_redirects(self, MockSession) -> None:
        # Same key-leak boundary as validation: the sync session must not forward xi-api-key on a 3xx.
        session = MockSession.return_value
        _wire(session, [_response({"history": [], "has_more": False, "last_history_item_id": None})])
        _rows(_source("history", _make_manager()))
        assert any(call.kwargs.get("allow_redirects") is False for call in MockSession.call_args_list)


class TestSourceResponse:
    @parameterized.expand(
        [
            ("history", ["history_item_id"], "asc", "date_unix"),
            ("conversations", ["conversation_id"], "desc", "start_time_unix_secs"),
            ("agents", ["agent_id"], "asc", "created_at_unix_secs"),
            ("voices", ["voice_id"], "asc", "created_at_unix"),
            ("triage_tickets", ["agentqa_ticket_id"], "desc", "created_at_unix_secs"),
            ("models", ["model_id"], "asc", None),
            ("workspace_members", ["user_id"], "asc", None),
            ("workspace_groups", ["id"], "asc", None),
            ("tools", ["id"], "asc", None),
            # Executions from different tools interleave in time, so the watermark must wait for job end.
            ("tool_executions", ["tool_id", "id"], "desc", None),
        ]
    )
    @mock.patch(SESSION_PATCH)
    def test_response_shape_per_endpoint(
        self, endpoint: str, primary_keys: list[str], sort_mode: str, partition_key: str | None, _mts
    ) -> None:
        # sort_mode="asc" on a newest-first endpoint corrupts the watermark; the pk must be table-unique.
        response = _source(endpoint, _make_manager())
        assert response.primary_keys == primary_keys
        assert response.sort_mode == sort_mode
        if partition_key is None:
            # A float or missing timestamp would bucket every row into one bogus 1970 partition.
            assert response.partition_mode is None
        else:
            assert response.partition_keys == [partition_key]
            assert response.partition_mode == "datetime"
