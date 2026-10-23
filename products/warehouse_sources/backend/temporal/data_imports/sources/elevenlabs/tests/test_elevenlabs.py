import os
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.elevenlabs.elevenlabs import (
    ElevenLabsResumeConfig,
    _build_params,
    _to_unix_seconds,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.elevenlabs.settings import ELEVENLABS_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.elevenlabs.source import ElevenLabsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.elevenlabs import (
    ElevenLabsSourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(ElevenLabsSource(), ElevenLabsSourceConfig(api_key="k"))


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
    @parameterized.expand(
        [
            (
                "history",
                "history",
                "history_item_id",
                "start_after_history_item_id",
                "last_history_item_id",
                "page_size",
                "1000",
            ),
            ("batch_calls", "batch_calls", "id", "last_doc", "next_doc", "limit", "100"),
        ]
    )
    def test_walks_cursor_pages_and_saves_state_after_each_yield(
        self,
        endpoint: str,
        items_key: str,
        id_key: str,
        cursor_param: str,
        cursor_response_key: str,
        page_size_param: str,
        page_size: str,
    ) -> None:
        result = _driver().run(
            endpoint,
            [
                ScriptedResponse(json={items_key: [{id_key: "a"}], "has_more": True, cursor_response_key: "a"}),
                ScriptedResponse(json={items_key: [{id_key: "b"}], "has_more": False, cursor_response_key: "b"}),
            ],
        )

        assert result.raised is None
        assert result.rows == [{id_key: "a"}, {id_key: "b"}]
        # Page 1 sends no cursor; page 2 sends the cursor from page 1 under the endpoint's cursor param.
        assert result.params(cursor_param) == [None, "a"]
        assert result.params(page_size_param) == [page_size, page_size]
        # Saved only once (after page 1, since page 2 is terminal) so a crash re-yields the last page.
        assert result.saved_states == [ElevenLabsResumeConfig(cursor="a")]

    def test_resumes_from_saved_cursor(self) -> None:
        result = _driver().run(
            "conversations",
            [
                ScriptedResponse(
                    json={"conversations": [{"conversation_id": "x"}], "has_more": False, "next_cursor": None}
                )
            ],
            resume_state=ElevenLabsResumeConfig(cursor="C1"),
        )

        assert result.raised is None
        assert result.rows == [{"conversation_id": "x"}]
        # The resumed run starts at the saved cursor, sent under the conversations cursor param.
        assert result.params("cursor") == ["C1"]

    def test_credential_error_fails_loud(self) -> None:
        # A 401 is a doomed credential problem; it must raise (feeding get_non_retryable_errors), not retry.
        result = _driver().run("history", [ScriptedResponse(status=401, json={})])
        assert isinstance(result.raised, requests.HTTPError)
        assert len(result.requests) == 1


class TestFanOut:
    @parameterized.expand(
        [
            ("full_refresh", False, None),
            ("incremental", True, 1700000000.5),
        ]
    )
    def test_tool_executions_walk_every_tool_and_page(self, _name: str, use_incremental: bool, last_value: Any) -> None:
        result = _driver().run(
            "tool_executions",
            [
                ScriptedResponse(json={"tools": [{"id": "t1"}, {"id": "t2"}], "has_more": False, "next_cursor": None}),
                ScriptedResponse(
                    json={"executions": [{"id": "e1", "tool_id": "t1"}], "has_more": True, "next_cursor": "c1"}
                ),
                ScriptedResponse(
                    json={"executions": [{"id": "e2", "tool_id": "t1"}], "has_more": False, "next_cursor": None}
                ),
                ScriptedResponse(
                    json={"executions": [{"id": "e3", "tool_id": "t2"}], "has_more": False, "next_cursor": None}
                ),
            ],
            should_use_incremental_field=use_incremental,
            db_incremental_field_last_value=last_value,
            incremental_field="timestamp" if use_incremental else None,
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["e1", "e2", "e3"]
        assert result.requests[0].param("sort_by") == "created_at"
        assert result.requests[0].param("start_time") is None
        assert result.requests[2].param("cursor") == "c1"
        # The time filter binds every child page, so incremental runs never re-walk full history.
        expected_start = ["1700000000"] * 3 if use_incremental else [None] * 3
        assert result.params("start_time")[1:] == expected_start

    def test_agent_deployments_walk_page_numbers_and_carry_the_agent_id(self) -> None:
        result = _driver().run(
            "agent_deployments",
            [
                ScriptedResponse(json={"agents": [{"agent_id": "a1"}], "has_more": False, "next_cursor": None}),
                ScriptedResponse(json={"results": [{"id": "d1"}], "meta": {"page": 1, "page_size": 100}}),
                ScriptedResponse(json={"results": [{"id": "d2"}], "meta": {"page": 2, "page_size": 100}}),
                ScriptedResponse(json={"results": [], "meta": {"page": 3, "page_size": 100}}),
            ],
        )

        assert result.raised is None
        # Deployment rows carry no agent id; without the parent id the primary key is not table-unique.
        assert result.rows == [{"id": "d1", "agent_id": "a1"}, {"id": "d2", "agent_id": "a1"}]
        assert result.params("page")[1:] == ["1", "2", "3"]
        assert result.params("page_size")[1:] == ["100"] * 3

    def test_flow_template_runs_walk_every_template_and_page(self) -> None:
        result = _driver().run(
            "flow_template_runs",
            [
                ScriptedResponse(
                    json={"templates": [{"id": "t1"}, {"id": "t2"}], "has_more": False, "next_cursor": None}
                ),
                ScriptedResponse(
                    json={"runs": [{"id": "r1", "template_id": "t1"}], "has_more": True, "next_cursor": "c1"}
                ),
                ScriptedResponse(
                    json={"runs": [{"id": "r2", "template_id": "t1"}], "has_more": False, "next_cursor": None}
                ),
                ScriptedResponse(
                    json={"runs": [{"id": "r3", "template_id": "t2"}], "has_more": False, "next_cursor": None}
                ),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["r1", "r2", "r3"]
        # The template list rejects a page size above 25.
        assert result.requests[0].param("page_size") == "25"
        assert result.requests[0].param("versions_per_template") == "1"
        assert result.requests[2].param("cursor") == "c1"


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
            *[
                (
                    f"sip_trunk_{trunk_key}_headers",
                    "phone_numbers",
                    [
                        [
                            {
                                "phone_number_id": "p1",
                                "provider": "sip_trunk",
                                trunk_key: {
                                    "address": "sip.example.com",
                                    "headers": {"Authorization": "Bearer sk_fake", "X-Ref": {"secret_id": "s1"}},
                                },
                            }
                        ]
                    ],
                    lambda row, key=trunk_key: row[key]["headers"],
                )
                for trunk_key in ("outbound_trunk", "provider_config")
            ],
        ]
    )
    def test_literal_header_values_never_reach_the_warehouse(
        self, _name: str, endpoint: str, bodies: list[Any], headers_of: Callable[[Any], Any]
    ) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json=body) for body in bodies])

        assert result.raised is None
        # A secret reference is safe to keep and tells the reader which secret the tool uses.
        assert headers_of(result.rows[0]) == {"Authorization": "[REDACTED]", "X-Ref": {"secret_id": "s1"}}


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
            (
                "phone_numbers_bare_array",
                "phone_numbers",
                [{"phone_number_id": "p1", "provider": "twilio"}, {"phone_number_id": "p2", "provider": "exotel"}],
                ["p1", "p2"],
                "phone_number_id",
            ),
            (
                "voice_collections_wrapped",
                "voice_collections",
                {"collections": [{"collection_id": "c1"}, {"collection_id": "c2"}]},
                ["c1", "c2"],
                "collection_id",
            ),
            # The subscription is one object, not a list, and must land as a single snapshot row.
            (
                "subscription_single_object",
                "subscription",
                {"tier": "creator", "character_count": 1200, "character_limit": 100000},
                ["creator"],
                "tier",
            ),
        ]
    )
    def test_whole_collection_becomes_rows(
        self, _name: str, endpoint: str, body: Any, expected_ids: list[str], id_key: str
    ) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json=body)])

        assert result.raised is None
        assert [row[id_key] for row in result.rows] == expected_ids
        assert len(result.requests) == 1
        assert result.params("page_size") == [None]


_INVALID_KEY_BODY = {"detail": {"status": "invalid_api_key", "message": "Invalid API key"}}
_MISSING_PERMISSION_BODY = {
    "detail": {"status": "missing_permissions", "message": "The API key you used is missing the permission user_read."}
}


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("valid", 200, None, None, True),
            ("bad_key", 401, None, _INVALID_KEY_BODY, False),
            # A 400 (the status users actually hit) is a deterministic client error, not transient.
            ("bad_request_at_create", 400, None, None, False),
            ("missing_scope_at_create", 403, None, None, True),
            ("missing_scope_at_schema", 403, "history", None, False),
            ("missing_permission_401_at_create", 401, None, _MISSING_PERMISSION_BODY, True),
            ("missing_permission_401_at_schema", 401, "history", _MISSING_PERMISSION_BODY, False),
            # An unverified key (transient 429/5xx) must not be saved as valid at create time.
            ("rate_limited_at_create", 429, None, None, False),
            ("server_error_at_create", 500, None, None, False),
        ]
    )
    def test_status_mapping(
        self, _name: str, status: int, schema_name: str | None, body: Any, expected_ok: bool
    ) -> None:
        answer = ScriptedResponse(status=status, json=body)
        with scripted_network(always(answer) if status in (429, 500) else [answer]) as network:
            ok, _msg = validate_credentials("k", schema_name)
        assert ok is expected_ok
        assert network.requests_log[0].headers["xi-api-key"] == "k"

    @parameterized.expand(
        [
            ("fan_out_child_probes_parent", "tool_executions", "https://api.elevenlabs.io/v1/convai/tools?page_size=1"),
            ("unpaginated_sends_no_page_size", "workspace_members", "https://api.elevenlabs.io/v1/workspace/members"),
            (
                "custom_page_size_param",
                "batch_calls",
                "https://api.elevenlabs.io/v1/convai/batch-calling/workspace?limit=1",
            ),
        ]
    )
    def test_schema_probe_url(self, _name: str, schema_name: str, expected_url: str) -> None:
        with scripted_network([ScriptedResponse()]) as network:
            assert validate_credentials("k", schema_name) == (True, None)
        assert [request.url for request in network.requests_log] == [expected_url]

    @parameterized.expand([("unauthorized", 401), ("bad_request", 400)])
    def test_rejected_key_message_is_actionable(self, _name: str, status: int) -> None:
        with scripted_network([ScriptedResponse(status=status)]):
            ok, msg = validate_credentials("k")
        assert ok is False
        assert "Create a new key in your ElevenLabs account settings" in (msg or "")

    def test_session_does_not_follow_redirects(self) -> None:
        # requests keeps the custom xi-api-key header across a cross-origin 3xx; following one would
        # replay the key to the redirect target, so the credentialed session must refuse redirects.
        with scripted_network([ScriptedResponse()]) as network:
            validate_credentials("k")
        assert network.session_options[0]["allow_redirects"] is False


class TestSyncSecurity:
    def test_sync_session_does_not_follow_redirects(self) -> None:
        # Same key-leak boundary as validation: the sync session must not forward xi-api-key on a 3xx.
        result = _driver().run(
            "history", [ScriptedResponse(json={"history": [], "has_more": False, "last_history_item_id": None})]
        )
        assert result.raised is None
        assert any(options.get("allow_redirects") is False for options in result.session_options)


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
            ("phone_numbers", ["phone_number_id"], "asc", None),
            ("batch_calls", ["id"], "asc", "created_at_unix"),
            ("agent_deployments", ["agent_id", "id"], "desc", "deployed_at_unix_secs"),
            ("flow_templates", ["id"], "asc", None),
            # Runs from different templates interleave, and run ids are only documented per template.
            ("flow_template_runs", ["template_id", "id"], "desc", None),
            ("voice_collections", ["collection_id"], "asc", None),
            # A single snapshot row has no unique column to merge on; full refresh replaces it.
            ("subscription", None, "asc", None),
        ]
    )
    def test_response_shape_per_endpoint(
        self, endpoint: str, primary_keys: list[str] | None, sort_mode: str, partition_key: str | None
    ) -> None:
        # sort_mode="asc" on a newest-first endpoint corrupts the watermark; the pk must be table-unique.
        result = _driver().run(endpoint, [ScriptedResponse(json={})])
        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.primary_keys == primary_keys
        assert response.sort_mode == sort_mode
        if partition_key is None:
            # A float or missing timestamp would bucket every row into one bogus 1970 partition.
            assert response.partition_mode is None
        else:
            assert response.partition_keys == [partition_key]
            assert response.partition_mode == "datetime"
