from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.spacelift.settings import (
    RUNS_INCREMENTAL_LOOKBACK_SECONDS,
    SPACELIFT_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.spacelift.spacelift import (
    SpaceliftAuthError,
    SpaceliftClient,
    SpaceliftPermissionError,
    SpaceliftResumeConfig,
    build_incremental_predicates,
    build_query,
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


def _query_calls(session: mock.MagicMock) -> list[mock.call]:
    # Skip the initial apiKeyUser token exchange, leaving the data queries.
    return session.post.call_args_list[1:]


class TestSpacelift:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("my-company", "my-company"),
            ("  My-Company  ", "my-company"),
            ("acme2", "acme2"),
        ],
    )
    def test_normalize_account_name_accepts_dns_labels(self, raw, expected):
        assert normalize_account_name(raw) == expected

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

    @pytest.mark.parametrize("endpoint", [name for name, c in SPACELIFT_ENDPOINTS.items() if c.is_connection])
    def test_build_query_for_connections(self, endpoint):
        config = SPACELIFT_ENDPOINTS[endpoint]
        query = build_query(config)
        assert f"{config.graphql_field}(input: $input)" in query
        assert "pageInfo" in query
        assert "endCursor" in query

    def test_build_query_wraps_runs_in_run_with_stack(self):
        query = build_query(SPACELIFT_ENDPOINTS["runs"])
        assert "isModule run {" in query
        assert "stack { id name }" in query

    def test_build_query_for_plain_list(self):
        query = build_query(SPACELIFT_ENDPOINTS["spaces"])
        assert "SearchInput" not in query
        assert "spaces {" in query

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

    def test_incremental_predicates_apply_lookback(self):
        predicates = build_incremental_predicates("createdAt", 1700000000)
        assert predicates == [
            {
                "field": "createdAt",
                "constraint": {"timeInRange": {"start": 1700000000 - RUNS_INCREMENTAL_LOOKBACK_SECONDS}},
            }
        ]

    def test_incremental_predicates_clamp_at_zero(self):
        predicates = build_incremental_predicates("createdAt", 10)
        assert predicates is not None
        assert predicates[0]["constraint"]["timeInRange"]["start"] == 0

    def test_incremental_predicates_none_for_unparseable_value(self):
        assert build_incremental_predicates("createdAt", "garbage") is None

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_session_keeps_credentials_out_of_sample_capture(self, mock_make_session):
        # The exchange body carries the raw secret and the response a minted JWT — names
        # the sample scrubber can't recognise, so the session must opt out of capture.
        SpaceliftClient("my-company", "key-id", "key-secret")

        kwargs = mock_make_session.call_args.kwargs
        assert kwargs["capture"] is False
        assert "key-secret" in kwargs["redact_values"]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_token_exchange_null_user_raises_auth_error(self, mock_make_session):
        # Spacelift signals a bad key with apiKeyUser=null and no GraphQL error.
        _mock_session(mock_make_session, [_response({"data": {"apiKeyUser": None}})])

        client = SpaceliftClient("my-company", "key-id", "key-secret")
        with pytest.raises(SpaceliftAuthError):
            client._ensure_token()

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_execute_sends_bearer_token(self, mock_make_session):
        session = _mock_session(
            mock_make_session,
            [_response(TOKEN_PAYLOAD), _search_page("searchStacks", [{"id": "stack-1"}])],
        )

        client = SpaceliftClient("my-company", "key-id", "key-secret")
        data = client.execute("query { x }")

        assert data["searchStacks"]["edges"][0]["node"] == {"id": "stack-1"}
        assert _query_calls(session)[0].kwargs["headers"] == {"Authorization": "Bearer jwt-1"}

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_execute_refreshes_token_once_on_unauthorized(self, mock_make_session):
        # A JWT expiring mid-sync surfaces as an `unauthorized` GraphQL error; one
        # re-exchange must recover, a second unauthorized is a real permission gap.
        session = _mock_session(
            mock_make_session,
            [
                _response(TOKEN_PAYLOAD),
                _response({"errors": [{"message": "unauthorized"}], "data": None}),
                _response({"data": {"apiKeyUser": {"jwt": "jwt-2", "validUntil": 99999999999}}}),
                _search_page("searchStacks", [{"id": "stack-1"}]),
            ],
        )

        client = SpaceliftClient("my-company", "key-id", "key-secret")
        data = client.execute("query { x }")

        assert data["searchStacks"]["edges"][0]["node"] == {"id": "stack-1"}
        assert session.post.call_args_list[3].kwargs["headers"] == {"Authorization": "Bearer jwt-2"}

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
        batches = list(response.items())

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
        list(response.items())

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
        batches = list(response.items())

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
        list(response.items())

        sent_input = _query_calls(session)[0].kwargs["json"]["variables"]["input"]
        assert sent_input["predicates"] == [
            {
                "field": "createdAt",
                "constraint": {"timeInRange": {"start": 1700000000 - RUNS_INCREMENTAL_LOOKBACK_SECONDS}},
            }
        ]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_full_refresh_sends_no_predicates(self, mock_make_session):
        session = _mock_session(mock_make_session, [_response(TOKEN_PAYLOAD), _search_page("searchRuns", [])])
        manager = _make_manager()

        response = spacelift_source("my-company", "key-id", "key-secret", "runs", mock.MagicMock(), manager)
        list(response.items())

        assert "predicates" not in _query_calls(session)[0].kwargs["json"]["variables"]["input"]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_plain_list_endpoint_yields_rows_without_pagination(self, mock_make_session):
        _mock_session(
            mock_make_session,
            [_response(TOKEN_PAYLOAD), _response({"data": {"spaces": [{"id": "root"}, {"id": "legacy"}]}})],
        )
        manager = _make_manager()

        response = spacelift_source("my-company", "key-id", "key-secret", "spaces", mock.MagicMock(), manager)
        batches = list(response.items())

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
            list(response.items())

    def test_unknown_endpoint_raises(self):
        with pytest.raises(ValueError, match="Unknown Spacelift endpoint"):
            spacelift_source("my-company", "key-id", "key-secret", "nope", mock.MagicMock(), _make_manager())

    @pytest.mark.parametrize(
        "endpoint, expected_sort_mode, expected_primary_keys",
        [
            ("stacks", "asc", ["id"]),
            ("runs", "desc", ["id"]),
            ("managed_entities", "asc", ["stackId", "id"]),
        ],
    )
    def test_source_response_metadata(self, endpoint, expected_sort_mode, expected_primary_keys):
        response = spacelift_source("my-company", "key-id", "key-secret", endpoint, mock.MagicMock(), _make_manager())
        assert response.name == endpoint
        assert response.sort_mode == expected_sort_mode
        assert response.primary_keys == expected_primary_keys

    def test_runs_partitions_on_created_at(self):
        response = spacelift_source("my-company", "key-id", "key-secret", "runs", mock.MagicMock(), _make_manager())
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["createdAt"]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_validate_credentials_success(self, mock_make_session):
        _mock_session(mock_make_session, [_response(TOKEN_PAYLOAD)])

        assert validate_credentials("my-company", "key-id", "key-secret") == (True, None)

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_validate_credentials_bad_key(self, mock_make_session):
        _mock_session(mock_make_session, [_response({"data": {"apiKeyUser": None}})])

        is_valid, message = validate_credentials("my-company", "key-id", "key-secret")
        assert is_valid is False
        assert message is not None and "Invalid Spacelift API key" in message

    def test_validate_credentials_invalid_account_name_never_hits_network(self):
        is_valid, message = validate_credentials("evil.com/x", "key-id", "key-secret")
        assert is_valid is False
        assert message is not None and "Invalid Spacelift account name" in message
