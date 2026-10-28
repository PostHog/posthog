from datetime import UTC, datetime
from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.monday import MondaySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.monday.monday import (
    ACTIVITY_LOGS_PAGE_SIZE,
    ITEMS_PAGE_SIZE,
    MONDAY_VERSION_2026_07,
    MONDAY_VERSION_2026_10,
    MONDAY_VERSION_V2,
    PAGE_SIZE,
    MondayGraphQLError,
    MondayRetryableError,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.monday.source import MondaySource
from products.warehouse_sources.backend.types import IncrementalFieldType

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
    def test_boards_paginate_until_short_page(self) -> None:
        full_page = [{"id": str(i)} for i in range(PAGE_SIZE)]
        result = _driver().run(
            "boards",
            [_response({"boards": full_page}), _response({"boards": [{"id": "last"}]})],
            api_version=API_VERSION,
        )

        assert result.raised is None
        assert len(result.items) == 2
        assert result.requests[0].json()["variables"] == {"limit": PAGE_SIZE, "page": 1}
        assert result.requests[1].json()["variables"] == {"limit": PAGE_SIZE, "page": 2}

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
        ],
    )
    def test_queries_request_the_fields_the_pinned_version_serves(
        self, endpoint, api_version, requested_field, absent_field
    ):
        with scripted_network([ScriptedResponse(json={"data": {"boards": [], "users": []}})]) as network:
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
