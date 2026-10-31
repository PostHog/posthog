from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.bettermode.bettermode import (
    BettermodeGraphQLError,
    BettermodeResumeConfig,
    BettermodeRetryableError,
    _base_url,
    _execute,
    _format_datetime,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bettermode.settings import (
    BETTERMODE_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bettermode.source import BettermodeSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.bettermode import (
    BettermodeSourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(
        BettermodeSource(),
        BettermodeSourceConfig(region="us", client_id="client", client_secret="secret", network_id="net"),
    )


def _response(payload: dict[str, Any], status_code: int = 200) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = payload
    resp.status_code = status_code
    resp.ok = status_code < 400
    return resp


def _token_response() -> ScriptedResponse:
    return ScriptedResponse(json={"data": {"limitedToken": {"accessToken": "jwt-token"}}})


def _page(query_field: str, nodes: list[dict[str, Any]], end_cursor: str | None = None) -> ScriptedResponse:
    return ScriptedResponse(
        json={
            "data": {
                query_field: {
                    "pageInfo": {"endCursor": end_cursor or "cur-end", "hasNextPage": end_cursor is not None},
                    "nodes": nodes,
                }
            }
        },
    )


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
    def test_valid_when_token_minted(self):
        with scripted_network([_token_response()]) as network:
            assert validate_credentials("us", "client", "secret", "net") == (True, None)

        assert network.requests_log[0].headers["authorization"] == "Basic Y2xpZW50OnNlY3JldA=="
        assert network.requests_log[0].json()["variables"] == {"networkId": "net"}

    def test_invalid_returns_api_error_message(self):
        with scripted_network(
            [ScriptedResponse(json={"errors": [{"message": "App not found", "status": 404}], "data": None})]
        ):
            is_valid, error = validate_credentials("us", "client", "secret", "net")
        assert is_valid is False
        assert error is not None and "App not found" in error


class TestGetRows:
    def test_paginates_via_relay_cursors(self):
        result = _driver().run(
            "members",
            [
                _token_response(),
                _page("members", [{"id": "m1"}, {"id": "m2"}], end_cursor="cur-1"),
                _page("members", [{"id": "m3"}]),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["m1", "m2", "m3"]
        # Resume state persists only while more pages remain, and only after the yield.
        assert result.saved_states == [BettermodeResumeConfig(after="cur-1")]
        second_variables = result.requests[2].json()["variables"]
        assert second_variables["after"] == "cur-1"
        assert second_variables["limit"] == BETTERMODE_ENDPOINTS["members"].page_size

    def test_resumes_from_saved_cursor(self):
        result = _driver().run(
            "members",
            [_token_response(), _page("members", [])],
            resume_state=BettermodeResumeConfig(after="cur-resume"),
        )

        assert result.raised is None
        variables = result.requests[1].json()["variables"]
        assert variables["after"] == "cur-resume"

    def test_incremental_posts_filter_is_json_encoded_gte(self):
        result = _driver().run(
            "posts",
            [_token_response(), _page("posts", [])],
            db_incremental_field_last_value=datetime(2024, 1, 2, tzinfo=UTC),
            incremental_field="publishedAt",
        )

        assert result.raised is None
        variables = result.requests[1].json()["variables"]
        # The filter value must be a JSON-encoded ISO string — the format Bettermode expects.
        assert variables["filterBy"] == [
            {"key": "publishedAt", "operator": "gte", "value": '"2024-01-02T00:00:00.000Z"'}
        ]
        assert variables["orderBy"] == "publishedAt"
        assert variables["reverse"] is False


class TestRepliesFanOut:
    def test_resumes_from_bookmarked_post(self):
        result = _driver().run(
            "replies",
            [
                _token_response(),
                _page("posts", [{"id": "p1", "totalRepliesCount": 2}, {"id": "p3", "totalRepliesCount": 1}]),
                _page("replies", [{"id": "r3"}]),
            ],
            resume_state=BettermodeResumeConfig(after="cur-mid", post_id="p3"),
        )

        assert result.raised is None
        assert len(result.requests) == 3
        variables = result.requests[2].json()["variables"]
        assert variables["postId"] == "p3"
        assert variables["after"] == "cur-mid"


class TestBettermodeSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = BETTERMODE_ENDPOINTS[endpoint]
        if config.is_list:
            data_response = ScriptedResponse(json={"data": {config.query_field: []}})
        elif config.fan_out_spaces:
            data_response = _page("spaces", [])
        elif config.fan_out_replies or config.fan_out_post_reactions:
            data_response = _page("posts", [])
        else:
            data_response = _page(config.query_field, [])

        result = _driver().run(endpoint, [_token_response(), data_response])
        assert result.raised is None
        assert result.response is not None
        response = result.response

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


class TestListEndpoints:
    @pytest.mark.parametrize("endpoint", ["collections", "roles"])
    def test_single_request_yields_the_whole_list(self, endpoint):
        query_field = BETTERMODE_ENDPOINTS[endpoint].query_field
        result = _driver().run(
            endpoint,
            [_token_response(), ScriptedResponse(json={"data": {query_field: [{"id": "a"}, {"id": "b"}]}})],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["a", "b"]
        assert len(result.requests) == 2
        # `collections` and `roles` reject limit/after — they return the whole list.
        assert result.requests[1].json()["variables"] == {}
        assert "$limit" not in result.requests[1].json()["query"]
        assert result.saved_states == []


class TestSpaceFanOut:
    def test_space_members_flattened_and_checkpointed_per_space(self):
        result = _driver().run(
            "space_members",
            [
                _token_response(),
                _page("spaces", [{"id": "s1"}, {"id": "s2"}]),
                _page(
                    "spaceMembers",
                    [{"member": {"id": "m1"}, "role": {"id": "r1", "name": "Admin", "type": "admin"}}],
                    end_cursor="cur-1",
                ),
                _page(
                    "spaceMembers", [{"member": {"id": "m2"}, "role": {"id": "r2", "name": "Member", "type": "member"}}]
                ),
                # A membership whose member is no longer readable carries no usable key.
                _page("spaceMembers", [{"member": None, "role": None}, {"member": {"id": "m3"}, "role": {}}]),
            ],
        )

        assert result.raised is None
        assert result.rows == [
            {"spaceId": "s1", "memberId": "m1", "roleId": "r1", "roleName": "Admin", "roleType": "admin"},
            {"spaceId": "s1", "memberId": "m2", "roleId": "r2", "roleName": "Member", "roleType": "member"},
            {"spaceId": "s2", "memberId": "m3", "roleId": None, "roleName": None, "roleType": None},
        ]
        member_requests = result.requests[2:]
        assert [request.json()["variables"]["spaceId"] for request in member_requests] == ["s1", "s1", "s2"]
        assert member_requests[0].json()["variables"]["orderBy"] == "CREATED_AT"
        # Mid-space page checkpoint, then a bookmark advancing to the next space.
        saved = result.saved_states
        assert [(state.after, state.space_id, state.post_id) for state in saved] == [
            ("cur-1", "s1", None),
            (None, "s2", None),
        ]


class TestPostReactionParticipantsFanOut:
    def test_fans_out_over_post_reaction_pairs(self):
        result = _driver().run(
            "post_reaction_participants",
            [
                _token_response(),
                # Parent enumeration: `love` has zero count and p2 has no reactions, so the only
                # pairs to fetch are (p1, like) and (p3, wow).
                _page(
                    "posts",
                    [
                        {"id": "p1", "reactions": [{"reaction": "like", "count": 2}, {"reaction": "love", "count": 0}]},
                        {"id": "p2", "reactions": []},
                        {"id": "p3", "reactions": [{"reaction": "wow", "count": 1}]},
                    ],
                ),
                _page("postReactionParticipants", [{"participant": {"id": "m1"}}], end_cursor="cur-1"),
                # A participant whose member is no longer readable carries no usable key.
                _page("postReactionParticipants", [{"participant": {"id": "m2"}}, {"participant": None}]),
                _page("postReactionParticipants", [{"participant": {"id": "m3"}}]),
            ],
        )

        assert result.raised is None
        assert result.rows == [
            {"postId": "p1", "reaction": "like", "memberId": "m1"},
            {"postId": "p1", "reaction": "like", "memberId": "m2"},
            {"postId": "p3", "reaction": "wow", "memberId": "m3"},
        ]
        participant_requests = result.requests[2:]
        assert [
            (request.json()["variables"]["postId"], request.json()["variables"]["reaction"])
            for request in participant_requests
        ] == [("p1", "like"), ("p1", "like"), ("p3", "wow")]
        # Mid-pair page checkpoint, then a bookmark advancing to the next (post, reaction) pair.
        saved = result.saved_states
        assert [(state.after, state.post_id, state.reaction) for state in saved] == [
            ("cur-1", "p1", "like"),
            (None, "p3", "wow"),
        ]

    def test_resumes_from_bookmarked_pair(self):
        result = _driver().run(
            "post_reaction_participants",
            [
                _token_response(),
                _page(
                    "posts",
                    [
                        {"id": "p1", "reactions": [{"reaction": "like", "count": 2}]},
                        {"id": "p3", "reactions": [{"reaction": "wow", "count": 1}]},
                    ],
                ),
                _page("postReactionParticipants", [{"participant": {"id": "m9"}}]),
            ],
            resume_state=BettermodeResumeConfig(after="cur-mid", post_id="p3", reaction="wow"),
        )

        assert result.raised is None
        assert len(result.requests) == 3
        variables = result.requests[2].json()["variables"]
        assert variables["postId"] == "p3"
        assert variables["reaction"] == "wow"
        assert variables["after"] == "cur-mid"
