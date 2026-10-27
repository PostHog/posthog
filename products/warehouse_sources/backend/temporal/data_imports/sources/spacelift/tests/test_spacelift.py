from datetime import UTC, date, datetime
from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.spacelift import (
    SpaceliftSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.spacelift.settings import (
    AUDIT_TRAIL_INCREMENTAL_LOOKBACK_SECONDS,
    RUNS_INCREMENTAL_LOOKBACK_SECONDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.spacelift.source import SpaceliftSource
from products.warehouse_sources.backend.temporal.data_imports.sources.spacelift.spacelift import (
    ACCOUNT_NOT_FOUND_MESSAGE,
    INVALID_API_KEY_MESSAGE,
    SpaceliftAccountNotFoundError,
    SpaceliftAuthError,
    SpaceliftClient,
    SpaceliftPermissionError,
    SpaceliftResumeConfig,
    build_incremental_predicates,
    normalize_account_name,
    to_unix_seconds,
    validate_credentials,
)

TOKEN_PAYLOAD = {"data": {"apiKeyUser": {"jwt": "jwt-1", "validUntil": 99999999999}}}


def _response(payload: dict[str, Any], status_code: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status_code, json=payload)


def _search_page(
    graphql_field: str, nodes: list[dict[str, Any]], end_cursor: str = "", has_next: bool = False
) -> ScriptedResponse:
    return _response(
        {
            "data": {
                graphql_field: {
                    "edges": [{"cursor": end_cursor, "node": node} for node in nodes],
                    "pageInfo": {"endCursor": end_cursor, "hasNextPage": has_next},
                }
            }
        }
    )


def _run(
    endpoint: str,
    script: list[ScriptedResponse],
    resume_state: SpaceliftResumeConfig | None = None,
    **inputs: Any,
) -> DriveResult:
    config = SpaceliftSourceConfig(account_name="my-company", api_key_id="key-id", api_key_secret="key-secret")
    return SourceDriver(SpaceliftSource(), config).run(endpoint, script, resume_state=resume_state, **inputs)


def _module_page(module_ids: list[str], end_cursor: str = "", has_next: bool = False) -> ScriptedResponse:
    return _search_page("searchModules", [{"id": module_id} for module_id in module_ids], end_cursor, has_next)


def _versions_page(version_ids: list[str] | None, end_cursor: str = "", has_next: bool = False) -> ScriptedResponse:
    if version_ids is None:
        # The module was deleted between listing it and querying its versions.
        return _response({"data": {"module": None}})
    return _response(
        {
            "data": {
                "module": {
                    "searchModuleVersions": {
                        "edges": [{"cursor": v, "node": {"id": v}} for v in version_ids],
                        "pageInfo": {"endCursor": end_cursor, "hasNextPage": has_next},
                    }
                }
            }
        }
    )


def _changes(addresses: list[str], end_cursor: str = "", has_next: bool = False) -> dict[str, Any]:
    return {
        "edges": [
            {"node": {"type": "ADD", "phase": "PLAN", "entity": {"id": f"ent-{a}", "address": a}}} for a in addresses
        ],
        "pageInfo": {"endCursor": end_cursor, "hasNextPage": has_next},
    }


def _run_node(run_id: str, changes: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "isModule": False,
        "stack": {"id": "stack-1"},
        "run": {"id": run_id, "createdAt": 1700000100, "changesV2": changes},
    }


def _change_row(run_id: str, address: str) -> dict[str, Any]:
    return {
        "runId": run_id,
        "stackId": "stack-1",
        "isModule": False,
        "runCreatedAt": 1700000100,
        "phase": "PLAN",
        "changeType": "ADD",
        "address": address,
        "entityId": f"ent-{address}",
        "entityName": None,
        "entityType": None,
        "parent": None,
    }


def _query_requests(result: DriveResult) -> list[RecordedRequest]:
    # Skip the initial apiKeyUser token exchange, leaving the data queries.
    return result.requests[1:]


class TestSpacelift:
    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "   ",
            "evil.com",
            "evil.com/graphql?",
            "acme@attacker",
            "-leading-dash",
            "under_score",
            "spa ce",
        ],
    )
    def test_normalize_account_name_rejects_host_injection(self, raw):
        with pytest.raises(ValueError):
            normalize_account_name(raw)

    @pytest.mark.parametrize(
        "value, expected",
        [
            (1700000000, 1700000000),
            (1700000000.9, 1700000000),
            ("1700000000", 1700000000),
            (datetime(2024, 1, 1, tzinfo=UTC), 1704067200),
            ("2024-01-01T00:00:00+00:00", 1704067200),
            (date(1970, 1, 1), 0),
            (None, None),
            ("not-a-date", None),
            (True, None),
        ],
    )
    def test_to_unix_seconds(self, value, expected):
        assert to_unix_seconds(value) == expected

    def test_incremental_predicates_none_for_unparseable_value(self):
        assert build_incremental_predicates("createdAt", "garbage") is None

    def test_token_exchange_null_user_raises_auth_error(self):
        # Spacelift signals a bad key with apiKeyUser=null and no GraphQL error.
        with scripted_network([_response({"data": {"apiKeyUser": None}})]):
            client = SpaceliftClient("my-company", "key-id", "key-secret")
            with pytest.raises(SpaceliftAuthError):
                client._ensure_token()

    def test_execute_raises_permission_error_when_still_unauthorized(self):
        script = [
            _response(TOKEN_PAYLOAD),
            _response({"errors": [{"message": "unauthorized"}], "data": None}),
            _response(TOKEN_PAYLOAD),
            _response({"errors": [{"message": "unauthorized"}], "data": None}),
        ]
        with scripted_network(script):
            client = SpaceliftClient("my-company", "key-id", "key-secret")
            with pytest.raises(SpaceliftPermissionError):
                client.execute("query { x }")

    def test_retryable_statuses_are_retried(self):
        script = [
            _response({}, status_code=429),
            _response({}, status_code=503),
            _response(TOKEN_PAYLOAD),
        ]
        with scripted_network(script):
            client = SpaceliftClient("my-company", "key-id", "key-secret")
            assert client._ensure_token() == "jwt-1"

    def test_pagination_follows_cursor_and_saves_state_after_yield(self):
        result = _run(
            "stacks",
            [
                _response(TOKEN_PAYLOAD),
                _search_page("searchStacks", [{"id": "stack-1"}], end_cursor="cur-1", has_next=True),
                _search_page("searchStacks", [{"id": "stack-2"}], end_cursor="cur-2", has_next=False),
            ],
        )

        assert result.items == [[{"id": "stack-1"}], [{"id": "stack-2"}]]
        # The cursor checkpoints only between pages, pointing at the next page to fetch.
        assert result.saved_states == [SpaceliftResumeConfig(cursor="cur-1")]
        assert _query_requests(result)[1].json()["variables"]["input"]["after"] == "cur-1"

    def test_resume_starts_from_saved_cursor(self):
        result = _run(
            "stacks",
            [_response(TOKEN_PAYLOAD), _search_page("searchStacks", [{"id": "stack-9"}])],
            resume_state=SpaceliftResumeConfig(cursor="saved-cursor"),
        )

        assert _query_requests(result)[0].json()["variables"]["input"]["after"] == "saved-cursor"

    def test_runs_rows_flatten_run_with_stack(self):
        node = {
            "isModule": False,
            "run": {"id": "run-1", "state": "FINISHED", "createdAt": 1700000100},
            "stack": {"id": "stack-1", "name": "core-infra"},
        }
        result = _run("runs", [_response(TOKEN_PAYLOAD), _search_page("searchRuns", [node])])

        assert result.items == [
            [
                {
                    "id": "run-1",
                    "state": "FINISHED",
                    "createdAt": 1700000100,
                    "isModule": False,
                    "stackId": "stack-1",
                    "stackName": "core-infra",
                }
            ]
        ]

    @pytest.mark.parametrize(
        "endpoint, graphql_field, incremental_field, lookback, order_by",
        [
            ("runs", "searchRuns", "createdAt", RUNS_INCREMENTAL_LOOKBACK_SECONDS, None),
            (
                "audit_trail_entries",
                "searchAuditTrailEntries",
                "createdAt",
                AUDIT_TRAIL_INCREMENTAL_LOOKBACK_SECONDS,
                {"field": "createdAt", "direction": "DESC"},
            ),
            # The row column is runCreatedAt, but searchRuns only filters on createdAt.
            ("run_changes", "searchRuns", "runCreatedAt", RUNS_INCREMENTAL_LOOKBACK_SECONDS, None),
        ],
    )
    def test_incremental_sync_sends_time_range_predicate(
        self, endpoint, graphql_field, incremental_field, lookback, order_by
    ):
        result = _run(
            endpoint,
            [_response(TOKEN_PAYLOAD), _search_page(graphql_field, [])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=1700000000,
            incremental_field=incremental_field,
        )

        assert result.raised is None
        sent_input = _query_requests(result)[0].json()["variables"]["input"]
        assert sent_input["predicates"] == [
            {"field": "createdAt", "constraint": {"timeInRange": {"start": 1700000000 - lookback}}}
        ]
        assert sent_input.get("orderBy") == order_by

    def test_run_changes_flatten_nested_changes_and_fetch_overflow_per_run(self):
        result = _run(
            "run_changes",
            [
                _response(TOKEN_PAYLOAD),
                _search_page(
                    "searchRuns",
                    [
                        _run_node("run-1", _changes(["aws_s3_bucket.a"], end_cursor="ch-1", has_next=True)),
                        _run_node("run-2", None),
                    ],
                    end_cursor="runs-1",
                    has_next=True,
                ),
                _response({"data": {"run": {"changesV2": _changes(["aws_s3_bucket.b"])}}}),
                # A page of runs with no changes yields nothing but the walk continues.
                _search_page("searchRuns", [_run_node("run-3", _changes([]))], end_cursor="runs-2", has_next=True),
                _search_page("searchRuns", [_run_node("run-4", _changes(["aws_iam_role.c"]))]),
            ],
        )

        assert result.raised is None
        assert result.items == [
            [_change_row("run-1", "aws_s3_bucket.a"), _change_row("run-1", "aws_s3_bucket.b")],
            [_change_row("run-4", "aws_iam_role.c")],
        ]
        requests = _query_requests(result)
        overflow = requests[1].json()["variables"]
        assert overflow["id"] == "run-1"
        assert overflow["changesInput"]["after"] == "ch-1"
        assert [r.json()["variables"].get("input", {}).get("after") for r in requests] == [
            None,
            None,
            "runs-1",
            "runs-2",
        ]
        assert result.saved_states == [
            SpaceliftResumeConfig(cursor="runs-1"),
            SpaceliftResumeConfig(cursor="runs-2"),
        ]

    def test_child_endpoint_walks_every_parent_and_child_page(self):
        result = _run(
            "module_versions",
            [
                _response(TOKEN_PAYLOAD),
                _module_page(["mod-a", "mod-b"], end_cursor="mods-1", has_next=True),
                _versions_page(["v1"], end_cursor="v-1", has_next=True),
                _versions_page(["v2"]),
                _versions_page(None),
                _module_page(["mod-c"]),
                _versions_page(["v3"]),
            ],
        )

        assert result.raised is None
        assert result.items == [
            [{"id": "v1", "moduleId": "mod-a"}],
            [{"id": "v2", "moduleId": "mod-a"}],
            [{"id": "v3", "moduleId": "mod-c"}],
        ]
        requests = _query_requests(result)
        assert [r.json()["variables"].get("id") for r in requests] == [
            None,
            "mod-a",
            "mod-a",
            "mod-b",
            None,
            "mod-c",
        ]
        assert requests[2].json()["variables"]["input"]["after"] == "v-1"
        assert requests[4].json()["variables"]["input"]["after"] == "mods-1"
        assert result.saved_states == [
            SpaceliftResumeConfig(cursor="", child_parent_id="mod-a", child_cursor="v-1"),
            SpaceliftResumeConfig(cursor="", completed_parent_ids=["mod-a"]),
            SpaceliftResumeConfig(cursor="", completed_parent_ids=["mod-a", "mod-b"]),
            SpaceliftResumeConfig(cursor="mods-1", completed_parent_ids=["mod-c"]),
        ]

    @pytest.mark.parametrize(
        "resume_state, expected_requests",
        [
            (
                SpaceliftResumeConfig(cursor="mods-1", completed_parent_ids=["mod-a"]),
                [("mod-b", None)],
            ),
            # Parents are skipped by id, so a completed parent that no longer exists changes nothing.
            (
                SpaceliftResumeConfig(cursor="mods-1", completed_parent_ids=["mod-a", "mod-deleted"]),
                [("mod-b", None)],
            ),
            # The parent that was partly synced continues from its saved child cursor.
            (
                SpaceliftResumeConfig(cursor="mods-1", child_parent_id="mod-a", child_cursor="v-1"),
                [("mod-a", "v-1"), ("mod-b", None)],
            ),
        ],
    )
    def test_child_endpoint_resumes_without_repeating_finished_work(self, resume_state, expected_requests):
        result = _run(
            "module_versions",
            [
                _response(TOKEN_PAYLOAD),
                _module_page(["mod-a", "mod-b"]),
                *[_versions_page([f"v-{parent}"]) for parent, _ in expected_requests],
            ],
            resume_state=resume_state,
        )

        assert result.raised is None
        requests = _query_requests(result)
        assert requests[0].json()["variables"]["input"]["after"] == "mods-1"
        assert [
            (r.json()["variables"]["id"], r.json()["variables"]["input"].get("after")) for r in requests[1:]
        ] == expected_requests
        assert [row["moduleId"] for row in result.rows] == [parent for parent, _ in expected_requests]

    def test_plain_list_endpoint_yields_rows_without_pagination(self):
        result = _run(
            "spaces",
            [_response(TOKEN_PAYLOAD), _response({"data": {"spaces": [{"id": "root"}, {"id": "legacy"}]}})],
        )

        assert result.items == [[{"id": "root"}, {"id": "legacy"}]]
        assert result.saved_states == []

    def test_next_page_without_cursor_raises(self):
        # hasNextPage=True with an empty endCursor would loop on the same page forever.
        result = _run(
            "stacks",
            [_response(TOKEN_PAYLOAD), _search_page("searchStacks", [{"id": "stack-1"}], has_next=True)],
        )

        assert result.raised is not None
        assert "endCursor is empty" in str(result.raised)

    def test_validate_credentials_success(self):
        with scripted_network([_response(TOKEN_PAYLOAD)]):
            assert validate_credentials("my-company", "key-id", "key-secret") == (True, None)

    def test_validate_credentials_unknown_account_points_at_the_account_name(self):
        # Spacelift reports an unknown subdomain as a token exchange error, which otherwise reads as
        # a rejected API key and sends the user to rotate a key that was never the problem.
        with scripted_network([_response({"errors": [{"message": "Account not found"}], "data": None})]):
            assert validate_credentials("my-company", "key-id", "key-secret") == (False, ACCOUNT_NOT_FOUND_MESSAGE)

    def test_validate_credentials_keeps_the_upstream_text_out_of_the_message(self):
        with scripted_network([_response({"errors": [{"message": "signature mismatch for key 01ABC"}], "data": None})]):
            assert validate_credentials("my-company", "key-id", "key-secret") == (False, INVALID_API_KEY_MESSAGE)

    def test_token_exchange_raises_account_not_found_for_an_unknown_account(self):
        with scripted_network([_response({"errors": [{"message": "Account not found"}], "data": None})]):
            client = SpaceliftClient("my-company", "key-id", "key-secret")
            with pytest.raises(SpaceliftAccountNotFoundError):
                client.execute("query { x }")

    def test_validate_credentials_invalid_account_name_never_hits_network(self):
        with scripted_network([]) as network:
            is_valid, message = validate_credentials("evil.com/x", "key-id", "key-secret")
        assert is_valid is False
        assert message is not None and "Invalid Spacelift account name" in message
        assert network.requests_log == []
