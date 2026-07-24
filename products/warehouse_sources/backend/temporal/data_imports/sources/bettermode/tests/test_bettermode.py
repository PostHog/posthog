from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.bettermode.bettermode import (
    BettermodeGraphQLError,
    BettermodeResumeConfig,
    BettermodeRetryableError,
    _base_url,
    _build_query,
    _execute,
    _format_datetime,
    bettermode_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bettermode.settings import (
    BETTERMODE_ENDPOINTS,
    ENDPOINTS,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.bettermode.bettermode"


def _make_manager(resume_state: BettermodeResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(payload: dict[str, Any], status_code: int = 200) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = payload
    resp.status_code = status_code
    resp.ok = status_code < 400
    return resp


def _token_response(token: str = "jwt-token") -> mock.MagicMock:
    return _response({"data": {"limitedToken": {"accessToken": token}}})


def _page(query_field: str, nodes: list[dict[str, Any]], end_cursor: str | None = None) -> mock.MagicMock:
    return _response(
        {
            "data": {
                query_field: {
                    "pageInfo": {"endCursor": end_cursor or "cur-end", "hasNextPage": end_cursor is not None},
                    "nodes": nodes,
                }
            }
        }
    )


def _mock_sessions(mock_make_session: mock.MagicMock, data_responses: list[mock.MagicMock]) -> tuple[Any, Any]:
    """get_rows opens two tracked sessions: one for the token exchange, one for data."""
    token_session = mock.MagicMock()
    token_session.post.return_value = _token_response()
    data_session = mock.MagicMock()
    data_session.post.side_effect = data_responses
    mock_make_session.side_effect = [token_session, data_session]
    return token_session, data_session


class TestFormatDatetime:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC), "2024-01-02T03:04:05.000Z"),
            (datetime(2024, 1, 2, 3, 4, 5), "2024-01-02T03:04:05.000Z"),
            (date(2024, 1, 2), "2024-01-02T00:00:00.000Z"),
            ("2024-01-02T03:04:05.000Z", "2024-01-02T03:04:05.000Z"),
        ],
    )
    def test_format_values(self, value, expected):
        assert _format_datetime(value) == expected


class TestBaseUrl:
    def test_regional_hosts(self):
        assert _base_url("us") == "https://api.bettermode.com"
        assert _base_url("eu") == "https://api.bettermode.de"

    def test_invalid_region_raises(self):
        with pytest.raises(ValueError):
            _base_url("mars")


class TestExecute:
    @pytest.mark.parametrize("status_code", [429, 500, 503])
    def test_throttle_and_server_errors_are_retryable(self, status_code):
        session = mock.MagicMock()
        session.post.return_value = _response({}, status_code=status_code)

        with pytest.raises(BettermodeRetryableError):
            _execute(session, "https://api.bettermode.com", "query {}", {}, mock.MagicMock())

    @pytest.mark.parametrize(
        "error, expected_fragment",
        [
            ({"message": "Forbidden resource", "status": 403}, "Bettermode API error (status 403)"),
            ({"message": "Unauthorized", "extensions": {"status": 401}}, "Bettermode API error (status 401)"),
            ({"message": "App not found", "status": 404}, "App not found"),
        ],
    )
    def test_graphql_errors_raise_with_stable_status_prefix(self, error, expected_fragment):
        session = mock.MagicMock()
        session.post.return_value = _response({"errors": [error], "data": None})

        with pytest.raises(BettermodeGraphQLError) as exc_info:
            _execute(session, "https://api.bettermode.com", "query {}", {}, mock.MagicMock())

        assert expected_fragment in str(exc_info.value)


class TestValidateCredentials:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_valid_when_token_minted(self, mock_make_session):
        session = mock.MagicMock()
        session.post.return_value = _token_response()
        mock_make_session.return_value = session

        assert validate_credentials("us", "client", "secret", "net") == (True, None)
        assert session.auth == ("client", "secret")

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_invalid_returns_api_error_message(self, mock_make_session):
        session = mock.MagicMock()
        session.post.return_value = _response({"errors": [{"message": "App not found", "status": 404}], "data": None})
        mock_make_session.return_value = session

        is_valid, error = validate_credentials("us", "client", "secret", "net")
        assert is_valid is False
        assert error is not None and "App not found" in error

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_invalid_on_network_failure(self, mock_make_session):
        mock_make_session.return_value.post.side_effect = Exception("boom")

        is_valid, error = validate_credentials("us", "client", "secret", "net")
        assert is_valid is False
        assert error == "Could not reach the Bettermode API"


class TestGetRows:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_paginates_via_relay_cursors(self, mock_make_session):
        _, data_session = _mock_sessions(
            mock_make_session,
            [
                _page("members", [{"id": "m1"}, {"id": "m2"}], end_cursor="cur-1"),
                _page("members", [{"id": "m3"}]),
            ],
        )

        manager = _make_manager()
        batches = list(get_rows("us", "client", "secret", "net", "members", mock.MagicMock(), manager))

        assert [row["id"] for batch in batches for row in batch] == ["m1", "m2", "m3"]
        # Resume state persists only while more pages remain, and only after the yield.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0].after == "cur-1"
        second_variables = data_session.post.call_args_list[1].kwargs["json"]["variables"]
        assert second_variables["after"] == "cur-1"
        assert second_variables["limit"] == BETTERMODE_ENDPOINTS["members"].page_size

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_data_requests_carry_bearer_of_minted_token(self, mock_make_session):
        _mock_sessions(mock_make_session, [_page("members", [])])

        list(get_rows("us", "client", "secret", "net", "members", mock.MagicMock(), _make_manager()))

        data_session_headers = mock_make_session.call_args_list[1].kwargs["headers"]
        assert data_session_headers == {"Authorization": "Bearer jwt-token"}

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_resumes_from_saved_cursor(self, mock_make_session):
        _, data_session = _mock_sessions(mock_make_session, [_page("members", [])])

        manager = _make_manager(BettermodeResumeConfig(after="cur-resume"))
        list(get_rows("us", "client", "secret", "net", "members", mock.MagicMock(), manager))

        variables = data_session.post.call_args.kwargs["json"]["variables"]
        assert variables["after"] == "cur-resume"

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_incremental_posts_filter_is_json_encoded_gte(self, mock_make_session):
        _, data_session = _mock_sessions(mock_make_session, [_page("posts", [])])

        list(
            get_rows(
                "us",
                "client",
                "secret",
                "net",
                "posts",
                mock.MagicMock(),
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 1, 2, tzinfo=UTC),
                incremental_field="publishedAt",
            )
        )

        variables = data_session.post.call_args.kwargs["json"]["variables"]
        # The filter value must be a JSON-encoded ISO string — the format Bettermode expects.
        assert variables["filterBy"] == [
            {"key": "publishedAt", "operator": "gte", "value": '"2024-01-02T00:00:00.000Z"'}
        ]
        assert variables["orderBy"] == "publishedAt"
        assert variables["reverse"] is False

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_full_refresh_posts_has_no_filter(self, mock_make_session):
        _, data_session = _mock_sessions(mock_make_session, [_page("posts", [])])

        list(get_rows("us", "client", "secret", "net", "posts", mock.MagicMock(), _make_manager()))

        variables = data_session.post.call_args.kwargs["json"]["variables"]
        assert "filterBy" not in variables
        assert variables["orderBy"] == "createdAt"


class TestRepliesFanOut:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_fans_out_only_over_posts_with_replies(self, mock_make_session):
        _, data_session = _mock_sessions(
            mock_make_session,
            [
                # Parent enumeration: p2 has no replies and must be skipped.
                _page(
                    "posts",
                    [
                        {"id": "p1", "totalRepliesCount": 2},
                        {"id": "p2", "totalRepliesCount": 0},
                        {"id": "p3", "totalRepliesCount": 1},
                    ],
                ),
                _page("replies", [{"id": "r1"}], end_cursor="cur-r1"),
                _page("replies", [{"id": "r2"}]),
                _page("replies", [{"id": "r3"}]),
            ],
        )

        manager = _make_manager()
        batches = list(get_rows("us", "client", "secret", "net", "replies", mock.MagicMock(), manager))

        assert [row["id"] for batch in batches for row in batch] == ["r1", "r2", "r3"]
        reply_calls = data_session.post.call_args_list[1:]
        assert [call.kwargs["json"]["variables"]["postId"] for call in reply_calls] == ["p1", "p1", "p3"]
        # Mid-post page checkpoint, then a bookmark advancing to the next parent.
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert [(state.after, state.post_id) for state in saved] == [("cur-r1", "p1"), (None, "p3")]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_resumes_from_bookmarked_post(self, mock_make_session):
        _, data_session = _mock_sessions(
            mock_make_session,
            [
                _page("posts", [{"id": "p1", "totalRepliesCount": 2}, {"id": "p3", "totalRepliesCount": 1}]),
                _page("replies", [{"id": "r3"}]),
            ],
        )

        manager = _make_manager(BettermodeResumeConfig(after="cur-mid", post_id="p3"))
        list(get_rows("us", "client", "secret", "net", "replies", mock.MagicMock(), manager))

        reply_calls = data_session.post.call_args_list[1:]
        assert len(reply_calls) == 1
        variables = reply_calls[0].kwargs["json"]["variables"]
        assert variables["postId"] == "p3"
        assert variables["after"] == "cur-mid"


class TestBettermodeSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = BETTERMODE_ENDPOINTS[endpoint]
        response = bettermode_source("us", "client", "secret", "net", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        # Connection ordering is undocumented — watermark commits only at run end.
        assert response.sort_mode == "desc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None


class TestQueryDocuments:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_query_declares_every_variable_it_passes(self, endpoint):
        config = BETTERMODE_ENDPOINTS[endpoint]
        query = _build_query(config)

        assert f"{config.query_field}(" in query
        for arg_name, gql_type in {"limit": "Int!", "after": "String", **config.extra_args}.items():
            assert f"${arg_name}: {gql_type}" in query
            assert f"{arg_name}: ${arg_name}" in query
