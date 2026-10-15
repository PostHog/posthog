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

    def test_incremental_sync_sends_time_range_predicate(self):
        result = _run(
            "runs",
            [_response(TOKEN_PAYLOAD), _search_page("searchRuns", [])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=1700000000,
            incremental_field="createdAt",
        )

        sent_input = _query_requests(result)[0].json()["variables"]["input"]
        assert sent_input["predicates"] == [
            {
                "field": "createdAt",
                "constraint": {"timeInRange": {"start": 1700000000 - RUNS_INCREMENTAL_LOOKBACK_SECONDS}},
            }
        ]

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

    def test_unknown_endpoint_raises(self):
        result = _run("nope", [])

        assert isinstance(result.raised, ValueError)
        assert "Unknown Spacelift endpoint" in str(result.raised)

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
