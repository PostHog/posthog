from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.deel.deel import (
    PAGE_SIZE,
    DeelResumeConfig,
    deel_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.deel.settings import DEEL_ENDPOINTS, ENDPOINTS


def _make_manager(resume_state: DeelResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(items: list[dict[str, Any]], cursor: str | None = None) -> mock.MagicMock:
    resp = mock.MagicMock()
    page: dict[str, Any] = {"total_rows": len(items)}
    if cursor is not None:
        page["cursor"] = cursor
    resp.json.return_value = {"data": items, "page": page}
    resp.status_code = 200
    resp.ok = True
    return resp


@pytest.fixture(autouse=True)
def _no_sleep():
    with mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.deel.deel.time.sleep"):
        yield


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, (True, None)),
            # A valid token without people:read still 403s; only 401 means the
            # token itself is bad.
            (403, (True, None)),
            (401, (False, "Invalid Deel API token")),
        ],
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.deel.deel.make_tracked_session")
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected):
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert validate_credentials("token") == expected

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.deel.deel.make_tracked_session")
    def test_validate_credentials_reports_network_error_distinctly(self, mock_session):
        # A transient network failure must not masquerade as a bad token.
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")
        valid, error = validate_credentials("token")
        assert valid is False
        assert error is not None and error.startswith("Could not reach Deel")


class TestGetRowsOffsetPagination:
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.deel.deel.make_tracked_session")
    def test_paginates_until_short_page(self, mock_session):
        full_page = [{"id": str(i)} for i in range(PAGE_SIZE)]
        mock_session.return_value.get.side_effect = [
            _response(full_page),
            _response([{"id": "last"}]),
        ]

        manager = _make_manager()
        batches = list(get_rows("token", "people", mock.MagicMock(), manager))

        assert len(batches) == 2
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0].offset == PAGE_SIZE
        second_url = mock_session.return_value.get.call_args_list[1].args[0]
        assert parse_qs(urlparse(second_url).query)["offset"] == [str(PAGE_SIZE)]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.deel.deel.make_tracked_session")
    def test_resumes_from_saved_offset(self, mock_session):
        mock_session.return_value.get.return_value = _response([])

        manager = _make_manager(DeelResumeConfig(offset=150))
        list(get_rows("token", "people", mock.MagicMock(), manager))

        url = mock_session.return_value.get.call_args.args[0]
        assert parse_qs(urlparse(url).query)["offset"] == ["150"]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.deel.deel.make_tracked_session")
    def test_empty_response_stops_without_saving_state(self, mock_session):
        mock_session.return_value.get.return_value = _response([])

        manager = _make_manager()
        batches = list(get_rows("token", "people", mock.MagicMock(), manager))

        assert batches == []
        manager.save_state.assert_not_called()


class TestGetRowsCursorPagination:
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.deel.deel.make_tracked_session")
    def test_paginates_via_after_cursor(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response([{"id": "1"}], cursor="cur_abc"),
            _response([{"id": "2"}]),
        ]

        manager = _make_manager()
        batches = list(get_rows("token", "contracts", mock.MagicMock(), manager))

        assert [item["id"] for batch in batches for item in batch] == ["1", "2"]
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0].cursor == "cur_abc"
        second_url = mock_session.return_value.get.call_args_list[1].args[0]
        assert parse_qs(urlparse(second_url).query)["after_cursor"] == ["cur_abc"]

    @pytest.mark.parametrize("num_pages", [2, 3])
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.deel.deel.make_tracked_session")
    def test_saves_state_after_each_non_terminal_page(self, mock_session, num_pages):
        # Pages 1..n-1 carry a cursor; the terminal page has none, so state is
        # saved exactly n - 1 times — once after every page that advances.
        responses = [_response([{"id": str(i)}], cursor=f"cur_{i}") for i in range(1, num_pages)]
        responses.append(_response([{"id": str(num_pages)}]))
        mock_session.return_value.get.side_effect = responses

        manager = _make_manager()
        list(get_rows("token", "contracts", mock.MagicMock(), manager))

        assert manager.save_state.call_count == num_pages - 1
        saved_cursors = [call.args[0].cursor for call in manager.save_state.call_args_list]
        assert saved_cursors == [f"cur_{i}" for i in range(1, num_pages)]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.deel.deel.make_tracked_session")
    def test_resumes_from_saved_cursor(self, mock_session):
        mock_session.return_value.get.return_value = _response([])

        manager = _make_manager(DeelResumeConfig(cursor="cur_resume"))
        list(get_rows("token", "contracts", mock.MagicMock(), manager))

        url = mock_session.return_value.get.call_args.args[0]
        assert parse_qs(urlparse(url).query)["after_cursor"] == ["cur_resume"]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.deel.deel.make_tracked_session")
    def test_empty_page_with_cursor_stops(self, mock_session):
        mock_session.return_value.get.return_value = _response([], cursor="cur_loop")

        manager = _make_manager()
        batches = list(get_rows("token", "contracts", mock.MagicMock(), manager))

        assert batches == []
        assert mock_session.return_value.get.call_count == 1
        manager.save_state.assert_not_called()


class TestDeelSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = DEEL_ENDPOINTS[endpoint]
        response = deel_source("token", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("config", list(DEEL_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config):
        if config.partition_key:
            assert config.partition_key == "created_at"
