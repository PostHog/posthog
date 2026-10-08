from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.spacelift.settings import (
    RUNS_INCREMENTAL_LOOKBACK_SECONDS,
)
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
    spacelift_source,
    to_unix_seconds,
    validate_credentials,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.spacelift.spacelift"

TOKEN_PAYLOAD = {"data": {"apiKeyUser": {"jwt": "jwt-1", "validUntil": 99999999999}}}


def _response(payload: dict[str, Any], status_code: int = 200) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.status_code = status_code
    resp.ok = status_code < 400
    resp.json.return_value = payload
    return resp


def _search_page(
    graphql_field: str, nodes: list[dict[str, Any]], end_cursor: str = "", has_next: bool = False
) -> mock.MagicMock:
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


def _make_manager(resume_state: SpaceliftResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _mock_session(mock_make_session: mock.MagicMock, responses: list[mock.MagicMock]) -> mock.MagicMock:
    session = mock.MagicMock()
    session.post.side_effect = responses
    mock_make_session.return_value = session
    return session


def _query_calls(session: mock.MagicMock) -> list[Any]:
    # Skip the initial apiKeyUser token exchange, leaving the data queries.
    return session.post.call_args_list[1:]


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

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_token_exchange_null_user_raises_auth_error(self, mock_make_session):
        # Spacelift signals a bad key with apiKeyUser=null and no GraphQL error.
        _mock_session(mock_make_session, [_response({"data": {"apiKeyUser": None}})])

        client = SpaceliftClient("my-company", "key-id", "key-secret")
        with pytest.raises(SpaceliftAuthError):
            client._ensure_token()

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_execute_raises_permission_error_when_still_unauthorized(self, mock_make_session):
        _mock_session(
            mock_make_session,
            [
                _response(TOKEN_PAYLOAD),
                _response({"errors": [{"message": "unauthorized"}], "data": None}),
                _response(TOKEN_PAYLOAD),
                _response({"errors": [{"message": "unauthorized"}], "data": None}),
            ],
        )

        client = SpaceliftClient("my-company", "key-id", "key-secret")
        with pytest.raises(SpaceliftPermissionError):
            client.execute("query { x }")

    @mock.patch("tenacity.nap.time")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_retryable_statuses_are_retried(self, mock_make_session, mock_nap):
        _mock_session(
            mock_make_session,
            [
                _response({}, status_code=429),
                _response({}, status_code=503),
                _response(TOKEN_PAYLOAD),
            ],
        )

        client = SpaceliftClient("my-company", "key-id", "key-secret")
        assert client._ensure_token() == "jwt-1"

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_pagination_follows_cursor_and_saves_state_after_yield(self, mock_make_session):
        session = _mock_session(
            mock_make_session,
            [
                _response(TOKEN_PAYLOAD),
                _search_page("searchStacks", [{"id": "stack-1"}], end_cursor="cur-1", has_next=True),
                _search_page("searchStacks", [{"id": "stack-2"}], end_cursor="cur-2", has_next=False),
            ],
        )
        manager = _make_manager()

        response = spacelift_source("my-company", "key-id", "key-secret", "stacks", mock.MagicMock(), manager)
        batches = list(cast(Iterable[Any], response.items()))

        assert batches == [[{"id": "stack-1"}], [{"id": "stack-2"}]]
        # The cursor checkpoints only between pages, pointing at the next page to fetch.
        manager.save_state.assert_called_once_with(SpaceliftResumeConfig(cursor="cur-1"))
        assert _query_calls(session)[1].kwargs["json"]["variables"]["input"]["after"] == "cur-1"

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_resume_starts_from_saved_cursor(self, mock_make_session):
        session = _mock_session(
            mock_make_session,
            [_response(TOKEN_PAYLOAD), _search_page("searchStacks", [{"id": "stack-9"}])],
        )
        manager = _make_manager(SpaceliftResumeConfig(cursor="saved-cursor"))

        response = spacelift_source("my-company", "key-id", "key-secret", "stacks", mock.MagicMock(), manager)
        list(cast(Iterable[Any], response.items()))

        assert _query_calls(session)[0].kwargs["json"]["variables"]["input"]["after"] == "saved-cursor"

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_runs_rows_flatten_run_with_stack(self, mock_make_session):
        node = {
            "isModule": False,
            "run": {"id": "run-1", "state": "FINISHED", "createdAt": 1700000100},
            "stack": {"id": "stack-1", "name": "core-infra"},
        }
        _mock_session(mock_make_session, [_response(TOKEN_PAYLOAD), _search_page("searchRuns", [node])])
        manager = _make_manager()

        response = spacelift_source("my-company", "key-id", "key-secret", "runs", mock.MagicMock(), manager)
        batches = list(cast(Iterable[Any], response.items()))

        assert batches == [
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

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_incremental_sync_sends_time_range_predicate(self, mock_make_session):
        session = _mock_session(mock_make_session, [_response(TOKEN_PAYLOAD), _search_page("searchRuns", [])])
        manager = _make_manager()

        response = spacelift_source(
            "my-company",
            "key-id",
            "key-secret",
            "runs",
            mock.MagicMock(),
            manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value=1700000000,
            incremental_field="createdAt",
        )
        list(cast(Iterable[Any], response.items()))

        sent_input = _query_calls(session)[0].kwargs["json"]["variables"]["input"]
        assert sent_input["predicates"] == [
            {
                "field": "createdAt",
                "constraint": {"timeInRange": {"start": 1700000000 - RUNS_INCREMENTAL_LOOKBACK_SECONDS}},
            }
        ]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_plain_list_endpoint_yields_rows_without_pagination(self, mock_make_session):
        _mock_session(
            mock_make_session,
            [_response(TOKEN_PAYLOAD), _response({"data": {"spaces": [{"id": "root"}, {"id": "legacy"}]}})],
        )
        manager = _make_manager()

        response = spacelift_source("my-company", "key-id", "key-secret", "spaces", mock.MagicMock(), manager)
        batches = list(cast(Iterable[Any], response.items()))

        assert batches == [[{"id": "root"}, {"id": "legacy"}]]
        manager.save_state.assert_not_called()

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_next_page_without_cursor_raises(self, mock_make_session):
        # hasNextPage=True with an empty endCursor would loop on the same page forever.
        _mock_session(
            mock_make_session,
            [_response(TOKEN_PAYLOAD), _search_page("searchStacks", [{"id": "stack-1"}], has_next=True)],
        )
        manager = _make_manager()

        response = spacelift_source("my-company", "key-id", "key-secret", "stacks", mock.MagicMock(), manager)
        with pytest.raises(Exception, match="endCursor is empty"):
            list(cast(Iterable[Any], response.items()))

    def test_unknown_endpoint_raises(self):
        with pytest.raises(ValueError, match="Unknown Spacelift endpoint"):
            spacelift_source("my-company", "key-id", "key-secret", "nope", mock.MagicMock(), _make_manager())

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_validate_credentials_success(self, mock_make_session):
        _mock_session(mock_make_session, [_response(TOKEN_PAYLOAD)])

        assert validate_credentials("my-company", "key-id", "key-secret") == (True, None)

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_validate_credentials_unknown_account_points_at_the_account_name(self, mock_make_session):
        # Spacelift reports an unknown subdomain as a token exchange error, which otherwise reads as
        # a rejected API key and sends the user to rotate a key that was never the problem.
        _mock_session(mock_make_session, [_response({"errors": [{"message": "Account not found"}], "data": None})])

        assert validate_credentials("my-company", "key-id", "key-secret") == (False, ACCOUNT_NOT_FOUND_MESSAGE)

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_validate_credentials_keeps_the_upstream_text_out_of_the_message(self, mock_make_session):
        _mock_session(
            mock_make_session,
            [_response({"errors": [{"message": "signature mismatch for key 01ABC"}], "data": None})],
        )

        assert validate_credentials("my-company", "key-id", "key-secret") == (False, INVALID_API_KEY_MESSAGE)

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_token_exchange_raises_account_not_found_for_an_unknown_account(self, mock_make_session):
        _mock_session(mock_make_session, [_response({"errors": [{"message": "Account not found"}], "data": None})])

        client = SpaceliftClient("my-company", "key-id", "key-secret")
        with pytest.raises(SpaceliftAccountNotFoundError):
            client.execute("query { x }")

    def test_validate_credentials_invalid_account_name_never_hits_network(self):
        is_valid, message = validate_credentials("evil.com/x", "key-id", "key-secret")
        assert is_valid is False
        assert message is not None and "Invalid Spacelift account name" in message
