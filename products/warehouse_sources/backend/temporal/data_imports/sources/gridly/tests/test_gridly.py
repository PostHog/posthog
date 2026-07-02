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


def _view_response(view: dict[str, Any]) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = view
    resp.status_code = 200
    resp.ok = True
    return resp


def _error_response(status_code: int) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.status_code = status_code
    resp.ok = False
    resp.text = "error"
    resp.raise_for_status.side_effect = requests.HTTPError(f"{status_code} Client Error", response=resp)
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
    def test_empty_page_yields_nothing(self, mock_session):
        mock_session.return_value.get.return_value = _records_response([], total=0)

        assert list(get_rows("key", "view", "records", mock.MagicMock(), _manager())) == []

    @mock.patch(f"{_MODULE}.PAGE_SIZE", 2)
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_saves_state_after_yield_and_not_on_terminal_page(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _records_response([{"id": "1"}, {"id": "2"}], total=3),
            _records_response([{"id": "3"}], total=3),
        ]
        manager = _manager()

        list(get_rows("key", "view", "records", mock.MagicMock(), manager))

        # State is saved once — after the first (full) page, pointing at the next offset — and never
        # after the terminal short page, so a crash re-fetches the last page rather than skipping it.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0].offset == 2

    @mock.patch(f"{_MODULE}.PAGE_SIZE", 2)
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_resumes_from_saved_offset(self, mock_session):
        mock_session.return_value.get.return_value = _records_response([], total=10)

        list(get_rows("key", "view", "records", mock.MagicMock(), _manager(GridlyResumeConfig(offset=4))))

        first_call = mock_session.return_value.get.call_args_list[0]
        assert json.loads(first_call.kwargs["params"]["page"])["offset"] == 4

    @mock.patch(f"{_MODULE}.PAGE_SIZE", 2)
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_sends_apikey_authorization_header(self, mock_session):
        mock_session.return_value.get.return_value = _records_response([], total=0)

        list(get_rows("mykey", "view", "records", mock.MagicMock(), _manager()))

        headers = mock_session.return_value.get.call_args.kwargs["headers"]
        assert headers["Authorization"] == "ApiKey mykey"


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

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_view_without_columns_yields_nothing(self, mock_session):
        mock_session.return_value.get.return_value = _view_response({"id": "view", "columns": []})

        assert list(get_rows("key", "view", "columns", mock.MagicMock(), _manager())) == []


class TestRetries:
    @mock.patch("time.sleep")
    @mock.patch(f"{_MODULE}.PAGE_SIZE", 2)
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_retries_retryable_status_then_succeeds(self, mock_session, _sleep):
        mock_session.return_value.get.side_effect = [
            _error_response(500),
            _error_response(429),
            _records_response([{"id": "1"}], total=1),
        ]

        batches = list(get_rows("key", "view", "records", mock.MagicMock(), _manager()))

        assert batches == [[{"id": "1"}]]
        assert mock_session.return_value.get.call_count == 3

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
    def test_probes_the_configured_view(self, mock_session):
        response = mock.MagicMock()
        response.status_code = 200
        mock_session.return_value.get.return_value = response

        validate_credentials("key", "myview")

        url = mock_session.return_value.get.call_args.args[0]
        assert urlparse(url).path == "/v1/views/myview"

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
