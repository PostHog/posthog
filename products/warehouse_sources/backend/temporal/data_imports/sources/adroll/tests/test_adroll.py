from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.adroll.adroll import (
    MAX_RETRY_ATTEMPTS,
    AdRollRetryableError,
    adroll_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.adroll.settings import ADROLL_ENDPOINTS, ENDPOINTS

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.adroll.adroll"


def _response(results: list[dict[str, Any]]) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = {"results": results}
    resp.status_code = 200
    resp.ok = True
    return resp


def _error_response(status_code: int) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.status_code = status_code
    resp.ok = False
    resp.text = "error"
    return resp


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
            (401, False),
            (403, False),
            (500, False),
        ],
    )
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected):
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert validate_credentials("cid", "pat") is expected

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_validate_includes_apikey_and_token_header(self, mock_session):
        response = mock.MagicMock()
        response.status_code = 200
        mock_session.return_value.get.return_value = response

        validate_credentials("cid", "pat")

        url = mock_session.return_value.get.call_args.args[0]
        assert parse_qs(urlparse(url).query)["apikey"] == ["cid"]
        headers = mock_session.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Token pat"

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_validate_credentials_swallows_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("cid", "pat") is False


class TestGetRows:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_advertisables_single_fetch(self, mock_session):
        mock_session.return_value.get.return_value = _response([{"eid": "ADV1"}])

        batches = list(get_rows("cid", "pat", "advertisables", mock.MagicMock()))

        assert batches == [[{"eid": "ADV1"}]]
        url = mock_session.return_value.get.call_args.args[0]
        assert urlparse(url).path == "/api/v1/organization/get_advertisables"
        assert parse_qs(urlparse(url).query)["apikey"] == ["cid"]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_campaigns_fan_out_over_advertisables(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response([{"eid": "ADV1"}, {"eid": "ADV2"}]),
            _response([{"eid": "C1"}]),
            _response([{"eid": "C2"}]),
        ]

        batches = list(get_rows("cid", "pat", "campaigns", mock.MagicMock()))

        flat = [item for batch in batches for item in batch]
        assert [(c["eid"], c["_advertisable_eid"]) for c in flat] == [("C1", "ADV1"), ("C2", "ADV2")]
        urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        assert parse_qs(urlparse(urls[1]).query)["advertisable"] == ["ADV1"]
        assert parse_qs(urlparse(urls[2]).query)["advertisable"] == ["ADV2"]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_advertisables_without_eid_are_skipped(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response([{"name": "broken"}]),
        ]

        assert list(get_rows("cid", "pat", "ads", mock.MagicMock())) == []
        assert mock_session.return_value.get.call_count == 1

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_empty_response_yields_nothing(self, mock_session):
        mock_session.return_value.get.return_value = _response([])

        assert list(get_rows("cid", "pat", "advertisables", mock.MagicMock())) == []

    @mock.patch("time.sleep")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_retries_retryable_status_then_succeeds(self, mock_session, _mock_sleep):
        mock_session.return_value.get.side_effect = [
            _error_response(500),
            _error_response(429),
            _response([{"eid": "ADV1"}]),
        ]

        batches = list(get_rows("cid", "pat", "advertisables", mock.MagicMock()))

        assert batches == [[{"eid": "ADV1"}]]
        assert mock_session.return_value.get.call_count == MAX_RETRY_ATTEMPTS

    @mock.patch("time.sleep")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_retries_exhausted_raises(self, mock_session, _mock_sleep):
        mock_session.return_value.get.return_value = _error_response(500)

        with pytest.raises(AdRollRetryableError):
            list(get_rows("cid", "pat", "advertisables", mock.MagicMock()))

        assert mock_session.return_value.get.call_count == MAX_RETRY_ATTEMPTS


class TestAdRollSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = ADROLL_ENDPOINTS[endpoint]
        response = adroll_source("cid", "pat", endpoint, mock.MagicMock())

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        assert response.sort_mode == "asc"
        assert response.partition_mode is None
        assert response.partition_keys is None
