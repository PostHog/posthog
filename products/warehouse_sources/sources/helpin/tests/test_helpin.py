import json
from typing import Any

import pytest

from products.warehouse_sources.sources.helpin._config import HelpinSourceConfig
from products.warehouse_sources.sources.helpin.helpin import HelpinResumeConfig, normalize_api_host
from products.warehouse_sources.sources.helpin.source import HelpinSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, route, scripted_network

CLOUD = "https://api.helpin.ai/public/v1"


def _driver() -> SourceDriver:
    return SourceDriver(HelpinSource(), HelpinSourceConfig(api_token="hmp_test", api_host=None))


def _page(key: str, rows: list[dict[str, Any]], next_offset: int | None) -> ScriptedResponse:
    return ScriptedResponse(
        json={
            "data": {key: rows, "total": 999, "has_more": next_offset is not None, "next_offset": next_offset},
            "summary": "ok",
            "links": {},
        }
    )


def _error(status: int, code: str, message: str) -> ScriptedResponse:
    return ScriptedResponse(status=status, json={"error": {"code": code, "message": message}})


class TestHelpinTransport:
    def test_conversations_follow_next_offset_to_the_last_page(self) -> None:
        result = _driver().run(
            "support_conversations",
            [
                _page("items", [{"id": "c1", "created_at": "2026-01-01T00:00:00Z"}], 25),
                _page("items", [{"id": "c2", "created_at": "2026-01-02T00:00:00Z"}], None),
            ],
        )

        assert result.raised is None
        assert result.paths == ["/public/v1/support/conversations"] * 2
        assert result.params("offset") == [None, "25"]
        assert result.params("limit") == ["25", "25"]
        assert result.params("status") == [None, None]
        assert [row["id"] for row in result.rows] == ["c1", "c2"]
        assert result.requests[0].headers["authorization"] == "Bearer hmp_test"

    def test_tasks_read_live_tasks_then_archived_tasks(self) -> None:
        result = _driver().run(
            "tasks",
            [
                _page("tasks", [{"task_id": "t1"}], 50),
                _page("tasks", [{"task_id": "t2"}], None),
                _page("tasks", [{"task_id": "t3", "archived": True}], None),
            ],
            incremental_field="updated_at",
            should_use_incremental_field=False,
        )

        assert result.raised is None
        assert result.params("archived") == ["false", "false", "true"]
        assert result.params("offset") == [None, "50", None]
        assert [row["task_id"] for row in result.rows] == ["t1", "t2", "t3"]

    def test_tasks_resume_in_the_archived_pass(self) -> None:
        result = _driver().run(
            "tasks",
            [_page("tasks", [{"task_id": "t9", "archived": True}], None)],
            resume_state=HelpinResumeConfig(paginator_state={"pass": 1, "cursor": 50}),
        )

        assert result.raised is None
        assert result.params("archived") == ["true"]
        assert result.params("offset") == ["50"]
        assert [row["task_id"] for row in result.rows] == ["t9"]

    def test_state_is_saved_before_the_page_it_covers(self) -> None:
        result = _driver().run(
            "tasks",
            [
                _page("tasks", [{"task_id": "t1"}], 50),
                _page("tasks", [{"task_id": "t2"}], None),
                _page("tasks", [{"task_id": "t3"}], None),
            ],
        )

        assert result.raised is None
        assert [state.paginator_state for state in result.committed_states] == [
            {"pass": 0, "cursor": 50},
            {"pass": 1, "cursor": None},
        ]

    @pytest.mark.parametrize(
        "schema, use_incremental, expected",
        [
            ("tasks", True, {"updated_after": "2026-03-09", "filter": None}),
            (
                "crm_companies",
                True,
                {
                    "updated_after": None,
                    "filter": json.dumps(
                        {
                            "logic": "and",
                            "rules": [{"field": "updated_at", "operator": "on_or_after", "value": "2026-03-09"}],
                        },
                        separators=(",", ":"),
                    ),
                },
            ),
            ("tasks", False, {"updated_after": None, "filter": None}),
            ("crm_companies", False, {"updated_after": None, "filter": None}),
        ],
    )
    def test_incremental_runs_send_the_watermark_day_minus_one(
        self, schema: str, use_incremental: bool, expected: dict[str, str | None]
    ) -> None:
        key = "tasks" if schema == "tasks" else "companies"
        result = _driver().run(
            schema,
            lambda _request: _page(key, [], None),
            incremental_field="updated_at",
            should_use_incremental_field=use_incremental,
            db_incremental_field_last_value="2026-03-10T05:00:00Z",
        )

        assert result.raised is None
        for name, value in expected.items():
            assert set(result.params(name)) == {value}

    def test_messages_fan_out_per_conversation_and_page_each_conversation(self) -> None:
        result = _driver().run(
            "support_conversation_messages",
            route(
                {
                    "/support/conversations": [_page("items", [{"id": "c1"}, {"id": "c_gone"}], None)],
                    "/support/conversations/c1/messages": [
                        _page("items", [{"id": "m1", "conversation_id": "c1"}], 20),
                        _page("items", [{"id": "m2", "conversation_id": "c1"}], None),
                    ],
                    "/support/conversations/c_gone/messages": [
                        _error(404, "not_found", "Conversation not found."),
                    ],
                }
            ),
        )

        assert result.raised is None
        assert result.paths == [
            "/public/v1/support/conversations",
            "/public/v1/support/conversations/c1/messages",
            "/public/v1/support/conversations/c1/messages",
            "/public/v1/support/conversations/c_gone/messages",
        ]
        assert result.params("limit") == ["25", "20", "20", "20"]
        assert result.params("offset") == [None, None, "20", None]
        assert [row["id"] for row in result.rows] == ["m1", "m2"]
        assert all(row["conversation_id"] == "c1" for row in result.rows)


@pytest.mark.parametrize(
    "api_host, expected",
    [
        (None, CLOUD),
        ("", CLOUD),
        ("helpin.example.com", "https://helpin.example.com/public/v1"),
        ("https://helpin.example.com:8443/", "https://helpin.example.com:8443/public/v1"),
        ("https://helpin.example.com/api/public/v1/", "https://helpin.example.com/api/public/v1"),
        ("http://helpin.example.com", ValueError),
        ("https://user:pass@helpin.example.com", ValueError),
        ("https://helpin.example.com%40evil.example", ValueError),
        ("https://helpin.example.com\\@evil.example", ValueError),
        ("https://helpin.example.com/?x=1", ValueError),
        ("ftp://helpin.example.com", ValueError),
    ],
)
def test_normalize_api_host(api_host: str | None, expected: str | type[Exception]) -> None:
    if isinstance(expected, str):
        assert normalize_api_host(api_host) == expected
    else:
        with pytest.raises(expected):
            normalize_api_host(api_host)


class TestHelpinCredentials:
    @pytest.mark.parametrize(
        "response, expected",
        [
            (ScriptedResponse(json={"data": {"scopes": ["helpin.context.read"]}}), (True, None)),
            # A genuine token that lacks only the context scope can still sync the tables it can read.
            (_error(403, "forbidden", "This token is missing the helpin.context.read scope."), (True, None)),
            (
                _error(
                    401, "unauthorized", "Send an Authorization: Bearer <token> header with a Helpin service token."
                ),
                (False, "Helpin didn't accept this token. Create a new token for the automation account in Helpin."),
            ),
            (
                _error(403, "api_disabled", "The public API is disabled for this workspace."),
                (False, "The Helpin API is turned off for this workspace. Ask a workspace manager to turn it on."),
            ),
        ],
    )
    def test_validate_at_create_probes_me(self, response: ScriptedResponse, expected: tuple[bool, str | None]) -> None:
        config = HelpinSourceConfig(api_token="hmp_test", api_host=None)
        with scripted_network([response]) as network:
            assert HelpinSource().validate_credentials(config, team_id=1) == expected

        assert [request.path for request in network.requests_log] == ["/public/v1/me"]

    def test_validate_a_table_names_the_missing_scope(self) -> None:
        config = HelpinSourceConfig(api_token="hmp_test", api_host=None)
        with scripted_network([_error(403, "forbidden", "Missing scope helpin.support.read.")]) as network:
            ok, message = HelpinSource().validate_credentials(
                config, team_id=1, schema_name="support_conversation_messages"
            )

        assert not ok
        assert message is not None and "`helpin.support.read`" in message
        assert [request.path for request in network.requests_log] == ["/public/v1/support/conversations"]

    def test_endpoint_permissions_report_tables_whose_scope_the_token_lacks(self) -> None:
        config = HelpinSourceConfig(api_token="hmp_test", api_host=None)
        me = ScriptedResponse(json={"data": {"scopes": ["helpin.support.read", "helpin.pm.read"]}})
        with scripted_network([me]):
            permissions = HelpinSource().get_endpoint_permissions(
                config, team_id=1, endpoints=["support_tags", "tasks", "crm_contacts"]
            )

        assert permissions == {
            "support_tags": None,
            "tasks": None,
            "crm_contacts": "Needs the `helpin.crm.read` scope on the automation account.",
        }
