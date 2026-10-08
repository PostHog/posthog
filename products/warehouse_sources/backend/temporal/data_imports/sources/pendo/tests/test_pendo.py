from typing import Any

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.pendo.pendo import (
    PendoResumeConfig,
    get_rows,
    pendo_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pendo.settings import ENDPOINTS, PENDO_ENDPOINTS

PENDO_PATH = "products.warehouse_sources.backend.temporal.data_imports.sources.pendo.pendo"


def _make_manager(resume_state: PendoResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _resp(json_data: Any, status: int = 200) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = json_data
    resp.status_code = status
    resp.ok = 200 <= status < 300
    return resp


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status, expected_valid, expected_substr",
        [
            (200, True, None),
            (401, False, "Invalid Pendo integration key"),
            (403, False, "Invalid Pendo integration key"),
            (500, False, "unexpected status code"),
        ],
    )
    @mock.patch(f"{PENDO_PATH}.make_tracked_session")
    def test_status_mapping(self, mock_session, status, expected_valid, expected_substr):
        mock_session.return_value.get.return_value = _resp({}, status)

        is_valid, message = validate_credentials("key", "us")

        assert is_valid is expected_valid
        if expected_substr is None:
            assert message is None
        else:
            assert message is not None
            assert expected_substr in message

    @mock.patch(f"{PENDO_PATH}.make_tracked_session")
    def test_swallows_network_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")

        is_valid, message = validate_credentials("key", "us")

        assert is_valid is False
        assert message is not None

    @mock.patch(f"{PENDO_PATH}.make_tracked_session")
    def test_redacts_the_integration_key(self, mock_session):
        mock_session.return_value.get.return_value = _resp({}, 200)

        validate_credentials("secret-key", "us")

        assert mock_session.call_args.kwargs["redact_values"] == ("secret-key",)


class TestGetRowsListEndpoint:
    @mock.patch(f"{PENDO_PATH}.LIST_CHUNK_SIZE", 2)
    @mock.patch(f"{PENDO_PATH}.make_tracked_session")
    def test_resumes_from_saved_offset(self, mock_session):
        items = [{"id": i} for i in range(5)]
        mock_session.return_value.request.return_value = _resp(items)
        manager = _make_manager(PendoResumeConfig(offset=4))

        batches = list(get_rows("key", "us", "pages", mock.MagicMock(), manager))

        assert [row["id"] for batch in batches for row in batch] == [4]


class TestGetRowsAggregation:
    @mock.patch(f"{PENDO_PATH}.AGGREGATION_PAGE_SIZE", 2)
    @mock.patch(f"{PENDO_PATH}.make_tracked_session")
    def test_paginates_via_filter_cursor_and_limit(self, mock_session):
        # Pendo's aggregation pipeline has no skip/offset stage (a "skip" step is rejected with
        # a 400 "unknown step type" error), so paging must use a `>` filter cursor on the sort field.
        page1 = {"results": [{"visitorId": "1"}, {"visitorId": "2"}]}
        page2 = {"results": [{"visitorId": "3"}]}
        mock_session.return_value.request.side_effect = [_resp(page1), _resp(page2)]
        manager = _make_manager()

        batches = list(get_rows("key", "us", "visitors", mock.MagicMock(), manager))

        assert [row["visitorId"] for batch in batches for row in batch] == ["1", "2", "3"]

        calls = mock_session.return_value.request.call_args_list
        method, url = calls[0].args[:2]
        assert method == "POST"
        assert url == "https://app.pendo.io/api/v1/aggregation"

        first_pipeline = calls[0].kwargs["json"]["request"]["pipeline"]
        assert {"source": {"visitors": None}} in first_pipeline
        assert {"sort": ["visitorId"]} in first_pipeline
        assert {"limit": 2} in first_pipeline
        assert not any("filter" in step for step in first_pipeline)

        second_pipeline = calls[1].kwargs["json"]["request"]["pipeline"]
        assert {"filter": 'visitorId>"2"'} in second_pipeline

        last_ids = [call.args[0].last_id for call in manager.save_state.call_args_list]
        assert last_ids == ["2", "3"]

    @mock.patch(f"{PENDO_PATH}.make_tracked_session")
    def test_escapes_quotes_in_the_filter_cursor(self, mock_session):
        # visitorId is set by the customer's own tracking code, so a value containing a `"`
        # must not be able to break out of the filter string literal and alter the expression.
        mock_session.return_value.request.return_value = _resp({"results": []})
        manager = _make_manager(PendoResumeConfig(last_id='ab"cd'))

        list(get_rows("key", "us", "visitors", mock.MagicMock(), manager))

        pipeline = mock_session.return_value.request.call_args.kwargs["json"]["request"]["pipeline"]
        assert {"filter": 'visitorId>"ab\\"cd"'} in pipeline


class TestPendoSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = PENDO_ENDPOINTS[endpoint]
        response = pendo_source("key", "us", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        # Pendo timestamps are epoch-ms, so we intentionally ship unpartitioned full-refresh tables.
        assert response.partition_mode is None
        assert response.partition_keys is None
