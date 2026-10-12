import json
from datetime import UTC, datetime
from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.monday import MondaySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.monday.monday import (
    ACTIVITY_LOGS_PAGE_SIZE,
    ITEMS_PAGE_SIZE,
    MONDAY_VERSION_2026_07,
    MONDAY_VERSION_V2,
    PAGE_SIZE,
    MondayGraphQLError,
    MondayRetryableError,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.monday.source import MondaySource
from products.warehouse_sources.backend.types import IncrementalFieldType

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.monday.monday"
API_VERSION = MONDAY_VERSION_2026_07


def _response(data: dict[str, Any], errors: list[dict[str, Any]] | None = None) -> mock.MagicMock:
    resp = mock.MagicMock()
    body: dict[str, Any] = {"data": data}
    if errors is not None:
        body["errors"] = errors
    resp.json.return_value = body
    resp.status_code = 200
    resp.ok = True
    return resp


class TestValidateCredentials:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_invalid_when_me_is_empty(self, mock_session):
        mock_session.return_value.post.return_value = _response({"me": None})
        assert validate_credentials("token", API_VERSION) is False

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_invalid_on_graphql_errors(self, mock_session):
        mock_session.return_value.post.return_value = _response({}, errors=[{"message": "Not Authenticated"}])
        assert validate_credentials("token", API_VERSION) is False


class TestGetRowsPaged:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_boards_paginate_until_short_page(self, mock_session):
        full_page = [{"id": str(i)} for i in range(PAGE_SIZE)]
        mock_session.return_value.post.side_effect = [
            _response({"boards": full_page}),
            _response({"boards": [{"id": "last"}]}),
        ]

        batches = list(get_rows("token", "boards", mock.MagicMock(), API_VERSION))

        assert len(batches) == 2
        first_vars = mock_session.return_value.post.call_args_list[0].kwargs["json"]["variables"]
        second_vars = mock_session.return_value.post.call_args_list[1].kwargs["json"]["variables"]
        assert first_vars == {"limit": PAGE_SIZE, "page": 1}
        assert second_vars == {"limit": PAGE_SIZE, "page": 2}

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_graphql_error_raises(self, mock_session):
        mock_session.return_value.post.return_value = _response({}, errors=[{"message": "Field not found"}])

        with pytest.raises(MondayGraphQLError):
            list(get_rows("token", "users", mock.MagicMock(), API_VERSION))

    @mock.patch("time.sleep")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_internal_server_error_is_retried_then_succeeds(self, mock_session, _mock_sleep):
        mock_session.return_value.post.side_effect = [
            _response({}, errors=[{"message": "Internal Server Error"}]),
            _response({"users": [{"id": "1"}]}),
        ]

        batches = list(get_rows("token", "users", mock.MagicMock(), API_VERSION))

        assert batches == [[{"id": "1"}]]
        assert mock_session.return_value.post.call_count == 2

    @mock.patch("time.sleep")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_internal_server_error_raises_retryable_when_exhausted(self, mock_session, _mock_sleep):
        mock_session.return_value.post.return_value = _response({}, errors=[{"message": "Internal Server Error"}])

        with pytest.raises(MondayRetryableError):
            list(get_rows("token", "users", mock.MagicMock(), API_VERSION))

    @mock.patch("time.sleep")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_404_status_is_retried_then_succeeds(self, mock_session, _mock_sleep):
        not_found = mock.MagicMock(status_code=404, ok=False)
        mock_session.return_value.post.side_effect = [
            not_found,
            _response({"users": [{"id": "1"}]}),
        ]

        batches = list(get_rows("token", "users", mock.MagicMock(), API_VERSION))

        assert batches == [[{"id": "1"}]]
        assert mock_session.return_value.post.call_count == 2

    @pytest.mark.parametrize(
        "api_version, expected_header",
        [
            (MONDAY_VERSION_V2, "2024-10"),
            (MONDAY_VERSION_2026_07, "2026-07"),
        ],
    )
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_requests_carry_token_and_pinned_api_version(self, mock_session, api_version, expected_header):
        mock_session.return_value.post.return_value = _response({"users": []})

        list(get_rows("token", "users", mock.MagicMock(), api_version))

        headers = mock_session.call_args.kwargs["headers"]
        assert headers["Authorization"] == "token"
        assert headers["API-Version"] == expected_header

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_unknown_api_version_is_rejected_instead_of_sent_without_header(self, mock_session):
        with pytest.raises(ValueError, match="Unsupported monday.com API version"):
            list(get_rows("token", "users", mock.MagicMock(), "2024-10"))

        mock_session.assert_not_called()


class TestGetRowsItems:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_items_fan_out_over_boards_and_walk_cursors(self, mock_session):
        full_items = [{"id": str(i)} for i in range(ITEMS_PAGE_SIZE)]
        mock_session.return_value.post.side_effect = [
            _response({"boards": [{"id": "b1"}]}),  # board ids page
            _response({"boards": [{"items_page": {"cursor": "cur1", "items": full_items}}]}),
            _response({"next_items_page": {"cursor": None, "items": [{"id": "tail"}]}}),
        ]

        batches = list(get_rows("token", "items", mock.MagicMock(), API_VERSION))

        flat = [item for batch in batches for item in batch]
        assert len(flat) == ITEMS_PAGE_SIZE + 1
        assert all(item["_board_id"] == "b1" for item in flat)
        next_vars = mock_session.return_value.post.call_args_list[2].kwargs["json"]["variables"]
        assert next_vars == {"cursor": "cur1", "limit": ITEMS_PAGE_SIZE}


def _graphql(request: RecordedRequest) -> dict[str, Any]:
    assert request.body is not None
    return json.loads(request.body)


def _driver() -> SourceDriver:
    return SourceDriver(MondaySource(), MondaySourceConfig(api_token="token"))


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
            ScriptedResponse(json={"data": {"boards": first_page}}),
            ScriptedResponse(json={"data": {"boards": [{"id": "b2", child_key: [{"id": "status"}]}]}}),
        ]

        result = _driver().run(endpoint, script)

        assert result.raised is None
        assert result.rows == [{"id": "status", "_board_id": "b1"}, {"id": "status", "_board_id": "b2"}]
        assert [_graphql(r)["variables"] for r in result.requests] == [
            {"limit": PAGE_SIZE, "page": 1},
            {"limit": PAGE_SIZE, "page": 2},
        ]

    @pytest.mark.parametrize(
        "api_version, requested_field, absent_field",
        [
            (MONDAY_VERSION_V2, "settings_str", " settings "),
            (MONDAY_VERSION_2026_07, " settings ", "settings_str"),
        ],
    )
    def test_columns_request_the_settings_field_the_pinned_version_serves(
        self, api_version, requested_field, absent_field
    ):
        with scripted_network([ScriptedResponse(json={"data": {"boards": []}})]) as network:
            list(get_rows("token", "board_columns", mock.MagicMock(), api_version))

        query = _graphql(network.requests_log[0])["query"]
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
        assert [_graphql(r)["variables"].get("workspaceIds") for r in result.requests] == [None, [None], ["w1"]]


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
        log_variables = [_graphql(r)["variables"] for r in result.requests[1:]]
        assert [(v["boardId"], v["page"]) for v in log_variables] == [(["b1"], 1), (["b1"], 2), (["b2"], 1)]
        assert {v.get("from") for v in log_variables} == {expected_from}
