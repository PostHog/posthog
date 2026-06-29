from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.monday.monday import (
    ITEMS_PAGE_SIZE,
    PAGE_SIZE,
    MondayGraphQLError,
    get_rows,
    monday_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.monday.settings import ENDPOINTS, MONDAY_ENDPOINTS

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.monday.monday"


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
    def test_valid_when_me_returns_id(self, mock_session):
        mock_session.return_value.post.return_value = _response({"me": {"id": "user-1"}})
        assert validate_credentials("token") is True

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_invalid_when_me_is_empty(self, mock_session):
        mock_session.return_value.post.return_value = _response({"me": None})
        assert validate_credentials("token") is False

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_invalid_on_graphql_errors(self, mock_session):
        mock_session.return_value.post.return_value = _response({}, errors=[{"message": "Not Authenticated"}])
        assert validate_credentials("token") is False

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_invalid_on_exception(self, mock_session):
        mock_session.return_value.post.side_effect = Exception("boom")
        assert validate_credentials("token") is False


class TestGetRowsPaged:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_boards_paginate_until_short_page(self, mock_session):
        full_page = [{"id": str(i)} for i in range(PAGE_SIZE)]
        mock_session.return_value.post.side_effect = [
            _response({"boards": full_page}),
            _response({"boards": [{"id": "last"}]}),
        ]

        batches = list(get_rows("token", "boards", mock.MagicMock()))

        assert len(batches) == 2
        first_vars = mock_session.return_value.post.call_args_list[0].kwargs["json"]["variables"]
        second_vars = mock_session.return_value.post.call_args_list[1].kwargs["json"]["variables"]
        assert first_vars == {"limit": PAGE_SIZE, "page": 1}
        assert second_vars == {"limit": PAGE_SIZE, "page": 2}

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_graphql_error_raises(self, mock_session):
        mock_session.return_value.post.return_value = _response({}, errors=[{"message": "Field not found"}])

        with pytest.raises(MondayGraphQLError):
            list(get_rows("token", "users", mock.MagicMock()))

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_requests_carry_token_and_api_version(self, mock_session):
        mock_session.return_value.post.return_value = _response({"users": []})

        list(get_rows("token", "users", mock.MagicMock()))

        headers = mock_session.call_args.kwargs["headers"]
        assert headers["Authorization"] == "token"
        assert headers["API-Version"]


class TestGetRowsItems:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_items_fan_out_over_boards_and_walk_cursors(self, mock_session):
        full_items = [{"id": str(i)} for i in range(ITEMS_PAGE_SIZE)]
        mock_session.return_value.post.side_effect = [
            _response({"boards": [{"id": "b1"}]}),  # board ids page
            _response({"boards": [{"items_page": {"cursor": "cur1", "items": full_items}}]}),
            _response({"next_items_page": {"cursor": None, "items": [{"id": "tail"}]}}),
        ]

        batches = list(get_rows("token", "items", mock.MagicMock()))

        flat = [item for batch in batches for item in batch]
        assert len(flat) == ITEMS_PAGE_SIZE + 1
        assert all(item["_board_id"] == "b1" for item in flat)
        next_vars = mock_session.return_value.post.call_args_list[2].kwargs["json"]["variables"]
        assert next_vars == {"cursor": "cur1", "limit": ITEMS_PAGE_SIZE}

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_items_stop_when_cursor_absent(self, mock_session):
        mock_session.return_value.post.side_effect = [
            _response({"boards": [{"id": "b1"}]}),
            _response({"boards": [{"items_page": {"cursor": None, "items": [{"id": "only"}]}}]}),
        ]

        batches = list(get_rows("token", "items", mock.MagicMock()))

        assert [item["id"] for batch in batches for item in batch] == ["only"]
        assert mock_session.return_value.post.call_count == 2

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_items_handle_board_without_items_page(self, mock_session):
        mock_session.return_value.post.side_effect = [
            _response({"boards": [{"id": "b1"}]}),
            _response({"boards": []}),
        ]

        assert list(get_rows("token", "items", mock.MagicMock())) == []


class TestMondaySourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = MONDAY_ENDPOINTS[endpoint]
        response = monday_source("token", endpoint, mock.MagicMock())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
        assert response.partition_mode is None
        assert response.partition_keys is None

    def test_items_have_composite_primary_key(self):
        response = monday_source("token", "items", mock.MagicMock())
        assert response.primary_keys == ["_board_id", "id"]
