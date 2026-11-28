from datetime import UTC, datetime
from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.sources.monday._config import MondaySourceConfig
from products.warehouse_sources.sources.monday.monday import (
    ACTIVITY_LOGS_PAGE_SIZE,
    BOARD_SUBSCRIBERS_PAGE_SIZE,
    BOARD_TEAMS_MAX_PAGES,
    BOARD_TEAMS_PAGE_SIZE,
    ITEMS_PAGE_SIZE,
    MONDAY_VERSION_2026_07,
    MONDAY_VERSION_2026_10,
    MONDAY_VERSION_V2,
    PAGE_SIZE,
    UPDATES_PAGE_SIZE,
    MondayGraphQLError,
    MondayRetryableError,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.sources.monday.source import MondaySource
from products.warehouse_sources.sources.sdk import IncrementalFieldType
from products.warehouse_sources.sources.sdk.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    activate_safe_point,
    always,
    scripted_network,
)

API_VERSION = MONDAY_VERSION_2026_07


def _response(data: dict[str, Any], errors: list[dict[str, Any]] | None = None) -> ScriptedResponse:
    body: dict[str, Any] = {"data": data}
    if errors is not None:
        body["errors"] = errors
    return ScriptedResponse(json=body)


def _driver() -> SourceDriver:
    return SourceDriver(MondaySource(), MondaySourceConfig(api_token="token"))


class TestValidateCredentials:
    def test_invalid_when_me_is_empty(self) -> None:
        with scripted_network([_response({"me": None})]) as network:
            assert validate_credentials("token", API_VERSION) is False
        assert len(network.requests_log) == 1

    def test_invalid_on_graphql_errors(self) -> None:
        with scripted_network([_response({}, errors=[{"message": "Not Authenticated"}])]) as network:
            assert validate_credentials("token", API_VERSION) is False
        assert len(network.requests_log) == 1


class TestGetRowsPaged:
    @pytest.mark.parametrize(
        "endpoint, page_size",
        [("boards", PAGE_SIZE), ("updates", UPDATES_PAGE_SIZE)],
    )
    def test_paginate_until_short_page(self, endpoint: str, page_size: int) -> None:
        full_page = [{"id": str(i)} for i in range(page_size)]
        result = _driver().run(
            endpoint,
            [_response({endpoint: full_page}), _response({endpoint: [{"id": "last"}]})],
            api_version=API_VERSION,
        )

        assert result.raised is None
        assert len(result.rows) == page_size + 1
        assert result.requests[0].json()["variables"] == {"limit": page_size, "page": 1}
        assert result.requests[1].json()["variables"] == {"limit": page_size, "page": 2}

    def test_updates_drop_rows_a_new_comment_pushed_onto_the_next_page(self) -> None:
        first_page = [{"id": str(i)} for i in range(UPDATES_PAGE_SIZE)]
        shifted_page = [{"id": str(UPDATES_PAGE_SIZE - 1)}, {"id": "older"}]
        result = _driver().run(
            "updates",
            [_response({"updates": first_page}), _response({"updates": shifted_page})],
            api_version=API_VERSION,
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [*(str(i) for i in range(UPDATES_PAGE_SIZE)), "older"]

    def test_graphql_error_raises(self) -> None:
        result = _driver().run(
            "users", [_response({}, errors=[{"message": "Field not found"}])], api_version=API_VERSION
        )

        assert isinstance(result.raised, MondayGraphQLError)

    def test_internal_server_error_is_retried_then_succeeds(self) -> None:
        result = _driver().run(
            "users",
            [
                _response({}, errors=[{"message": "Internal Server Error"}]),
                _response({"users": [{"id": "1"}]}),
            ],
            api_version=API_VERSION,
        )

        assert result.raised is None
        assert result.items == [[{"id": "1"}]]
        assert len(result.requests) == 2

    def test_internal_server_error_raises_retryable_when_exhausted(self) -> None:
        result = _driver().run(
            "users",
            always(_response({}, errors=[{"message": "Internal Server Error"}])),
            api_version=API_VERSION,
        )

        assert isinstance(result.raised, MondayRetryableError)

    def test_404_status_is_retried_then_succeeds(self) -> None:
        result = _driver().run(
            "users",
            [ScriptedResponse(status=404), _response({"users": [{"id": "1"}]})],
            api_version=API_VERSION,
        )

        assert result.raised is None
        assert result.items == [[{"id": "1"}]]
        assert len(result.requests) == 2

    @pytest.mark.parametrize(
        "api_version, expected_header",
        [
            (MONDAY_VERSION_V2, "2024-10"),
            (MONDAY_VERSION_2026_07, "2026-07"),
            (MONDAY_VERSION_2026_10, "2026-10"),
        ],
    )
    def test_requests_carry_token_and_pinned_api_version(self, api_version: str, expected_header: str) -> None:
        result = _driver().run("users", [_response({"users": []})], api_version=api_version)

        assert result.raised is None
        assert result.requests[0].headers["authorization"] == "token"
        assert result.requests[0].headers["api-version"] == expected_header

    def test_unknown_api_version_is_rejected_instead_of_sent_without_header(self) -> None:
        result = _driver().run("users", [], api_version="2024-10")

        assert isinstance(result.raised, ValueError)
        assert "Unsupported monday.com API version" in str(result.raised)
        assert result.requests == []
        assert result.session_options == []


class TestGetRowsItems:
    def test_items_fan_out_over_boards_and_walk_cursors(self) -> None:
        full_items = [{"id": str(i)} for i in range(ITEMS_PAGE_SIZE)]
        result = _driver().run(
            "items",
            [
                _response({"boards": [{"id": "b1"}]}),  # board ids page
                _response({"boards": [{"items_page": {"cursor": "cur1", "items": full_items}}]}),
                _response({"next_items_page": {"cursor": None, "items": [{"id": "tail"}]}}),
            ],
            api_version=API_VERSION,
        )

        assert result.raised is None
        assert len(result.rows) == ITEMS_PAGE_SIZE + 1
        assert all(item["_board_id"] == "b1" for item in result.rows)
        assert result.requests[2].json()["variables"] == {"cursor": "cur1", "limit": ITEMS_PAGE_SIZE}


class TestGetRowsBoardChildren:
    @pytest.mark.parametrize(
        "endpoint, child_key",
        [("board_columns", "columns"), ("board_groups", "groups")],
    )
    def test_children_carry_their_board_across_board_pages(self, endpoint, child_key):
        first_page = [{"id": "b1", child_key: [{"id": "status"}, None]}] + [
            {"id": f"empty{i}", child_key: []} for i in range(PAGE_SIZE - 1)
        ]
        script = [
            _response({"boards": first_page}),
            ScriptedResponse(json={"data": {"boards": [{"id": "b2", child_key: [{"id": "status"}]}]}}),
        ]

        result = _driver().run(endpoint, script)

        assert result.raised is None
        assert result.rows == [{"id": "status", "_board_id": "b1"}, {"id": "status", "_board_id": "b2"}]
        assert [r.json()["variables"] for r in result.requests] == [
            {"limit": PAGE_SIZE, "page": 1},
            {"limit": PAGE_SIZE, "page": 2},
        ]

    @pytest.mark.parametrize(
        "endpoint, api_version, requested_field, absent_field",
        [
            ("board_columns", MONDAY_VERSION_V2, "settings_str", " settings "),
            ("board_columns", MONDAY_VERSION_2026_07, " settings ", "settings_str"),
            ("board_columns", MONDAY_VERSION_2026_10, " settings ", "settings_str"),
            ("users", MONDAY_VERSION_V2, "is_admin", "status"),
            ("users", MONDAY_VERSION_2026_07, "is_admin", "status"),
            ("users", MONDAY_VERSION_2026_10, "status", "is_admin"),
            ("users", MONDAY_VERSION_2026_10, "kind", "enabled"),
            ("teams", MONDAY_VERSION_V2, "is_guest", "created_at"),
            ("teams", MONDAY_VERSION_2026_07, "created_at", "settings"),
            ("teams", MONDAY_VERSION_2026_10, "created_at", "settings"),
        ],
    )
    def test_queries_request_the_fields_the_pinned_version_serves(
        self, endpoint, api_version, requested_field, absent_field
    ):
        with scripted_network([ScriptedResponse(json={"data": {"boards": [], "users": [], "teams": []}})]) as network:
            list(get_rows("token", endpoint, mock.MagicMock(), api_version))

        query = network.requests_log[0].json()["query"]
        assert requested_field in query
        assert absent_field not in query


class TestGetRowsFolders:
    def test_walks_main_and_every_workspace_without_duplicating_folders(self):
        script = [
            ScriptedResponse(json={"data": {"workspaces": [{"id": "w1"}]}}),
            ScriptedResponse(json={"data": {"folders": [{"id": "f1"}]}}),
            ScriptedResponse(json={"data": {"folders": [{"id": "f1"}, {"id": "f2"}]}}),
        ]

        result = _driver().run("folders", script)

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["f1", "f2"]
        assert [r.json()["variables"].get("workspaceIds") for r in result.requests] == [None, [None], ["w1"]]


class TestGetRowsBoardActivityLogs:
    @pytest.mark.parametrize(
        "incremental_inputs, expected_from",
        [
            ({}, None),
            (
                {
                    "incremental_field": "created_at",
                    "incremental_field_type": IncrementalFieldType.DateTime,
                    "db_incremental_field_last_value": datetime(2026, 1, 2, 3, 4, 5, 678000, tzinfo=UTC),
                },
                "2026-01-02T03:04:05Z",
            ),
        ],
    )
    def test_pages_each_board_and_sends_the_watermark_only_when_incremental(self, incremental_inputs, expected_from):
        full_page = [{"id": f"log{i}", "created_at": "17000000000000000"} for i in range(ACTIVITY_LOGS_PAGE_SIZE)]
        script = [
            ScriptedResponse(json={"data": {"boards": [{"id": "b1"}, {"id": "b2"}]}}),
            ScriptedResponse(json={"data": {"boards": [{"activity_logs": full_page}]}}),
            ScriptedResponse(json={"data": {"boards": [{"activity_logs": [{"id": "tail", "created_at": "bad"}]}]}}),
            ScriptedResponse(json={"data": {"boards": [{"activity_logs": []}]}}),
        ]

        result = _driver().run("board_activity_logs", script, **incremental_inputs)

        assert result.raised is None
        assert len(result.rows) == ACTIVITY_LOGS_PAGE_SIZE + 1
        assert result.rows[0]["created_at"] == datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC)
        assert result.rows[-1] == {"id": "tail", "created_at": "bad", "_board_id": "b1"}
        log_variables = [r.json()["variables"] for r in result.requests[1:]]
        assert [(v["boardId"], v["page"]) for v in log_variables] == [(["b1"], 1), (["b1"], 2), (["b2"], 1)]
        assert {v.get("from") for v in log_variables} == {expected_from}


class TestGetRowsTeams:
    def test_flattens_owners_and_users_to_id_lists(self):
        script = [
            ScriptedResponse(
                json={
                    "data": {
                        "teams": [
                            {
                                "id": "t1",
                                "name": "Design",
                                "owners": [{"id": "u1"}],
                                "users": [{"id": "u1"}, None, {"id": "u2"}],
                            },
                            None,
                            {"id": "t2", "name": "Empty", "owners": [], "users": None},
                        ]
                    }
                }
            )
        ]

        result = _driver().run("teams", script)

        assert result.raised is None
        assert result.rows == [
            {"id": "t1", "name": "Design", "owner_ids": ["u1"], "user_ids": ["u1", "u2"]},
            {"id": "t2", "name": "Empty", "owner_ids": [], "user_ids": []},
        ]


class TestGetRowsTags:
    def test_unions_public_and_board_tags_without_duplicates(self):
        first_board_page = [{"id": "b1", "tags": [{"id": "1", "name": "public"}, {"id": "2", "name": "private"}]}] + [
            {"id": f"empty{i}", "tags": None} for i in range(PAGE_SIZE - 1)
        ]
        script = [
            ScriptedResponse(json={"data": {"tags": [{"id": "1", "name": "public"}, None]}}),
            ScriptedResponse(json={"data": {"boards": first_board_page}}),
            ScriptedResponse(
                json={
                    "data": {
                        "boards": [
                            {"id": "b2", "tags": [{"id": "2", "name": "private"}, {"id": "3", "name": "shared"}]}
                        ]
                    }
                }
            ),
        ]

        result = _driver().run("tags", script)

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["1", "2", "3"]
        assert [r.json()["variables"] for r in result.requests] == [
            {},
            {"limit": PAGE_SIZE, "page": 1},
            {"limit": PAGE_SIZE, "page": 2},
        ]


class TestGetRowsBoardSubscribers:
    def test_one_row_per_member_with_owner_flag(self):
        script = [
            ScriptedResponse(
                json={
                    "data": {
                        "boards": [
                            {
                                "id": "b1",
                                # u3 owns the board without being listed as a subscriber.
                                "owners": [{"id": "u1"}, {"id": "u3"}],
                                "subscribers": [{"id": "u1"}, {"id": "u2"}, None],
                                "team_owners": [],
                                "team_subscribers": [{"id": "t1"}],
                            },
                            {
                                "id": "b2",
                                "owners": [],
                                "subscribers": [],
                                "team_owners": None,
                                "team_subscribers": None,
                            },
                        ]
                    }
                }
            )
        ]

        result = _driver().run("board_subscribers", script)

        assert result.raised is None
        assert result.rows == [
            {"_board_id": "b1", "subscriber_type": "user", "id": "u1", "is_owner": True},
            {"_board_id": "b1", "subscriber_type": "user", "id": "u2", "is_owner": False},
            {"_board_id": "b1", "subscriber_type": "user", "id": "u3", "is_owner": True},
            {"_board_id": "b1", "subscriber_type": "team", "id": "t1", "is_owner": False},
        ]
        assert result.requests[0].json()["variables"] == {
            "limit": BOARD_SUBSCRIBERS_PAGE_SIZE,
            "page": 1,
            "teamLimit": BOARD_TEAMS_PAGE_SIZE,
        }

    def test_pages_a_full_team_list_for_its_board(self):
        full_team_page = [{"id": f"t{i}"} for i in range(BOARD_TEAMS_PAGE_SIZE)]
        script = [
            ScriptedResponse(
                json={
                    "data": {
                        "boards": [
                            {
                                "id": "b1",
                                "owners": [],
                                "subscribers": [],
                                "team_owners": [{"id": "t0"}],
                                "team_subscribers": full_team_page,
                            }
                        ]
                    }
                }
            ),
            ScriptedResponse(json={"data": {"boards": [{"team_subscribers": [{"id": "overflow"}]}]}}),
        ]

        result = _driver().run("board_subscribers", script)

        assert result.raised is None
        team_rows = {(row["id"], row["is_owner"]) for row in result.rows}
        assert len(result.rows) == BOARD_TEAMS_PAGE_SIZE + 1
        assert ("overflow", False) in team_rows
        assert ("t0", True) in team_rows
        overflow_request = result.requests[1].json()
        assert "team_subscribers (limit: $limit, page: $page)" in overflow_request["query"]
        assert overflow_request["variables"] == {"boardId": ["b1"], "limit": BOARD_TEAMS_PAGE_SIZE, "page": 2}

    def test_stops_paging_a_team_list_at_the_page_cap(self):
        full_team_page = [{"id": "t"} for _ in range(BOARD_TEAMS_PAGE_SIZE)]

        def respond(request: RecordedRequest) -> ScriptedResponse:
            if "team_subscribers (limit: $limit, page: $page)" in request.json()["query"]:
                return ScriptedResponse(json={"data": {"boards": [{"team_subscribers": full_team_page}]}})
            board = {"id": "b1", "owners": [], "subscribers": [], "team_owners": [], "team_subscribers": full_team_page}
            return ScriptedResponse(json={"data": {"boards": [board]}})

        result = _driver().run("board_subscribers", respond)

        assert result.raised is None
        assert len(result.requests) == BOARD_TEAMS_MAX_PAGES
        assert result.requests[-1].json()["variables"]["page"] == BOARD_TEAMS_MAX_PAGES


class TestSafePoints:
    @pytest.mark.parametrize(
        "endpoint, script, expected_safe_points",
        [
            (
                "tags",
                [
                    ScriptedResponse(json={"data": {"tags": []}}),
                    ScriptedResponse(
                        json={"data": {"boards": [{"id": f"b{i}", "tags": []} for i in range(PAGE_SIZE)]}}
                    ),
                    ScriptedResponse(json={"data": {"boards": [{"id": "last", "tags": None}]}}),
                ],
                2,
            ),
            (
                "board_subscribers",
                [
                    ScriptedResponse(
                        json={
                            "data": {
                                "boards": [
                                    {
                                        "id": f"b{i}",
                                        "owners": [],
                                        "subscribers": [],
                                        "team_owners": [],
                                        "team_subscribers": [],
                                    }
                                    for i in range(BOARD_SUBSCRIBERS_PAGE_SIZE)
                                ]
                            }
                        }
                    ),
                    ScriptedResponse(json={"data": {"boards": []}}),
                ],
                1,
            ),
        ],
    )
    def test_board_pages_with_no_rows_reach_a_safe_point(self, endpoint, script, expected_safe_points):
        safe_points: list[None] = []

        with (
            scripted_network(script),
            activate_safe_point(lambda: safe_points.append(None), covers_framework_checkpoints=False),
        ):
            rows = list(get_rows("token", endpoint, mock.MagicMock(), API_VERSION))

        assert rows == []
        assert len(safe_points) == expected_safe_points
