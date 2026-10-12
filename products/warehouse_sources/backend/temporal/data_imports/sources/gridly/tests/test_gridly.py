import json
from typing import Any
from urllib.parse import urlparse

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.gridly.gridly import (
    MAX_RETRY_ATTEMPTS,
    GridlyResumeConfig,
    GridlyRetryableError,
    get_rows,
    gridly_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gridly.settings import ENDPOINTS

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.gridly.gridly"


def _records_response(records: list[dict[str, Any]], total: int | None) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = records
    resp.headers = {} if total is None else {"X-Total-Count": str(total)}
    resp.status_code = 200
    resp.ok = True
    return resp


def _view_response(data: dict[str, Any] | list[dict[str, Any]]) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = data
    resp.status_code = 200
    resp.ok = True
    return resp


def _error_response(status_code: int) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.status_code = status_code
    resp.ok = False
    resp.reason = "Unauthorized"
    resp.url = "https://api.gridly.com/v1/views/view/records?page=%7B%22offset%22%3A0%7D"
    # _fetch echoes a customer view's record content on error; assert it never reaches logs.
    resp.text = "secret customer record content"
    return resp


def _manager(resume: GridlyResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


class TestRecordsPagination:
    @mock.patch(f"{_MODULE}.PAGE_SIZE", 2)
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_paginates_by_offset_and_yields_raw_records(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _records_response([{"id": "1"}, {"id": "2"}], total=3),
            _records_response([{"id": "3"}], total=3),
        ]

        batches = list(get_rows("key", "view", "records", mock.MagicMock(), _manager()))

        # Rows are yielded one page (list) at a time in the shape the API returns them.
        assert batches == [[{"id": "1"}, {"id": "2"}], [{"id": "3"}]]

        calls = mock_session.return_value.get.call_args_list
        # The `page` param is a JSON blob with offset advancing by the page length.
        assert json.loads(calls[0].kwargs["params"]["page"]) == {"offset": 0, "limit": 2}
        assert json.loads(calls[1].kwargs["params"]["page"]) == {"offset": 2, "limit": 2}

    @mock.patch(f"{_MODULE}.PAGE_SIZE", 2)
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_stops_on_short_page_without_total(self, mock_session):
        # A short page (fewer than the page size) terminates even when X-Total-Count is absent.
        mock_session.return_value.get.return_value = _records_response([{"id": "1"}], total=None)

        batches = list(get_rows("key", "view", "records", mock.MagicMock(), _manager()))

        assert batches == [[{"id": "1"}]]
        assert mock_session.return_value.get.call_count == 1

    @mock.patch(f"{_MODULE}.PAGE_SIZE", 2)
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_resumes_from_saved_offset(self, mock_session):
        mock_session.return_value.get.return_value = _records_response([], total=10)

        list(get_rows("key", "view", "records", mock.MagicMock(), _manager(GridlyResumeConfig(offset=4))))

        first_call = mock_session.return_value.get.call_args_list[0]
        assert json.loads(first_call.kwargs["params"]["page"])["offset"] == 4


class TestColumns:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_reads_columns_from_view_object(self, mock_session):
        mock_session.return_value.get.return_value = _view_response(
            {"id": "view", "name": "Food", "columns": [{"id": "c1"}, {"id": "c2"}]}
        )

        batches = list(get_rows("key", "view", "columns", mock.MagicMock(), _manager()))

        assert batches == [[{"id": "c1"}, {"id": "c2"}]]
        url = mock_session.return_value.get.call_args.args[0]
        assert urlparse(url).path == "/v1/views/view"


_HIERARCHY_RESPONSES: dict[tuple[str, tuple[tuple[str, Any], ...]], list[dict[str, Any]]] = {
    ("/v1/projects", ()): [{"id": 1, "name": "P1"}, {"id": 2, "name": "P2"}],
    ("/v1/databases", (("projectId", 1),)): [{"id": "db1", "name": "D1"}],
    ("/v1/databases", (("projectId", 2),)): [],
    ("/v1/grids", (("dbId", "db1"),)): [{"id": "g1", "name": "G1"}, {"id": "g2", "name": "G2"}],
    ("/v1/views", (("gridId", "g1"),)): [{"id": "v1", "name": "Default view"}],
    ("/v1/views", (("gridId", "g2"),)): [{"id": "v2", "name": "Default view"}, {"id": "v3", "name": "Fr"}],
}


def _hierarchy_get(url: str, params: dict[str, Any], **_kwargs: Any) -> mock.MagicMock:
    return _view_response(_HIERARCHY_RESPONSES[(urlparse(url).path, tuple(sorted(params.items())))])


class TestHierarchy:
    @pytest.mark.parametrize(
        "endpoint, expected_batches",
        [
            ("projects", [[{"id": 1, "name": "P1"}, {"id": 2, "name": "P2"}]]),
            ("databases", [[{"id": "db1", "name": "D1", "projectId": 1}]]),
            (
                "grids",
                [[{"id": "g1", "name": "G1", "dbId": "db1"}, {"id": "g2", "name": "G2", "dbId": "db1"}]],
            ),
            (
                "views",
                [
                    [{"id": "v1", "name": "Default view", "gridId": "g1"}],
                    [{"id": "v2", "name": "Default view", "gridId": "g2"}, {"id": "v3", "name": "Fr", "gridId": "g2"}],
                ],
            ),
        ],
    )
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_walks_hierarchy_and_tags_rows_with_parent_id(self, mock_session, endpoint, expected_batches):
        mock_session.return_value.get.side_effect = _hierarchy_get

        batches = list(get_rows("key", "view", endpoint, mock.MagicMock(), _manager()))

        assert batches == expected_batches


class TestRetries:
    @mock.patch("time.sleep")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_retries_exhausted_raises(self, mock_session, _sleep):
        mock_session.return_value.get.return_value = _error_response(500)

        with pytest.raises(GridlyRetryableError):
            list(get_rows("key", "view", "records", mock.MagicMock(), _manager()))

        assert mock_session.return_value.get.call_count == MAX_RETRY_ATTEMPTS

    @mock.patch("time.sleep")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_client_error_is_not_retried(self, mock_session, _sleep):
        # A 401/403 can never be fixed by retrying, so it raises immediately (no retry loop).
        mock_session.return_value.get.return_value = _error_response(401)

        with pytest.raises(requests.HTTPError):
            list(get_rows("key", "view", "records", mock.MagicMock(), _manager()))

        assert mock_session.return_value.get.call_count == 1

    @mock.patch("time.sleep")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_client_error_does_not_leak_response_body_or_query_string(self, mock_session, _sleep):
        # The error body echoes customer record content and the URL carries the `page` blob; neither
        # may reach the raised error (surfaced as latest_error) or the logs.
        response = _error_response(401)
        mock_session.return_value.get.return_value = response
        logger = mock.MagicMock()

        with pytest.raises(requests.HTTPError) as exc_info:
            list(get_rows("key", "view", "records", logger, _manager()))

        raised = str(exc_info.value)
        assert response.text not in raised
        assert "page=" not in raised
        assert raised == "401 Client Error: Unauthorized for url: https://api.gridly.com/v1/views/view/records"

        logged = " ".join(str(call) for call in logger.error.call_args_list)
        assert response.text not in logged
        assert "page=" not in logged


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_valid",
        [
            (200, True),
            (401, False),
            (403, False),
            (404, False),
            (500, False),
        ],
    )
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_status_mapping(self, mock_session, status_code, expected_valid):
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        is_valid, message = validate_credentials("key", "view")

        assert is_valid is expected_valid
        assert (message is None) is expected_valid

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_swallows_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")

        is_valid, message = validate_credentials("key", "view")

        assert is_valid is False
        assert message == "boom"


class TestSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        response = gridly_source("key", "view", endpoint, mock.MagicMock(), mock.MagicMock())

        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"
        # No stable datetime on records → nothing to partition on.
        assert response.partition_keys is None
        assert response.partition_mode is None
