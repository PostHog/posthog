from typing import Any
from urllib.parse import urlparse

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.amazon_ads.amazon_ads import (
    PAGE_SIZE,
    _base_url,
    amazon_ads_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.amazon_ads.settings import (
    AMAZON_ADS_ENDPOINTS,
    ENDPOINTS,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.amazon_ads.amazon_ads"


def _token_response() -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = {"access_token": "the-token", "expires_in": 3600}
    resp.status_code = 200
    resp.ok = True
    return resp


def _json_response(body: Any) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = body
    resp.status_code = 200
    resp.ok = True
    return resp


class TestBaseUrl:
    @pytest.mark.parametrize(
        "region, expected_host",
        [
            ("na", "https://advertising-api.amazon.com"),
            ("eu", "https://advertising-api-eu.amazon.com"),
            ("fe", "https://advertising-api-fe.amazon.com"),
        ],
    )
    def test_regional_hosts(self, region, expected_host):
        assert _base_url(region) == expected_host

    def test_invalid_region_raises(self):
        with pytest.raises(ValueError):
            _base_url("evil")


class TestValidateCredentials:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_valid_when_token_mints_and_profiles_list(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _json_response([{"profileId": 1}])

        assert validate_credentials("na", "cid", "sec", "rt") is True

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_invalid_when_token_mint_fails(self, mock_session):
        resp = mock.MagicMock()
        resp.raise_for_status.side_effect = requests.HTTPError("400 Client Error", response=mock.MagicMock())
        mock_session.return_value.post.return_value = resp

        assert validate_credentials("na", "cid", "sec", "rt") is False

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_invalid_when_profiles_forbidden(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()
        forbidden = mock.MagicMock()
        forbidden.status_code = 403
        mock_session.return_value.get.return_value = forbidden

        assert validate_credentials("na", "cid", "sec", "rt") is False

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_invalid_region_rejected_without_request(self, mock_session):
        assert validate_credentials("evil", "cid", "sec", "rt") is False
        mock_session.return_value.post.assert_not_called()


class TestGetRows:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_profiles_single_fetch(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _json_response([{"profileId": 1}, {"profileId": 2}])

        batches = list(get_rows("na", "cid", "sec", "rt", "profiles", mock.MagicMock()))

        assert batches == [[{"profileId": 1}, {"profileId": 2}]]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_sp_campaigns_fan_out_per_profile_with_scope_header(self, mock_session):
        mock_session.return_value.post.side_effect = [
            _token_response(),
            _json_response({"campaigns": [{"campaignId": 11}], "nextToken": "tok"}),
            _json_response({"campaigns": [{"campaignId": 12}]}),
        ]
        mock_session.return_value.get.return_value = _json_response([{"profileId": 1}])

        batches = list(get_rows("na", "cid", "sec", "rt", "sp_campaigns", mock.MagicMock()))

        flat = [item for batch in batches for item in batch]
        assert [(c["campaignId"], c["_profile_id"]) for c in flat] == [(11, "1"), (12, "1")]
        first_list_call = mock_session.return_value.post.call_args_list[1]
        assert urlparse(first_list_call.args[0]).path == "/sp/campaigns/list"
        assert first_list_call.kwargs["headers"]["Amazon-Advertising-API-Scope"] == "1"
        assert first_list_call.kwargs["headers"]["Content-Type"] == "application/vnd.spCampaign.v3+json"
        assert first_list_call.kwargs["json"] == {"maxResults": PAGE_SIZE}
        second_list_call = mock_session.return_value.post.call_args_list[2]
        assert second_list_call.kwargs["json"] == {"maxResults": PAGE_SIZE, "nextToken": "tok"}

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_remints_token_on_401(self, mock_session):
        expired = mock.MagicMock()
        expired.status_code = 401
        expired.ok = False
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.side_effect = [expired, _json_response([{"profileId": 1}])]

        batches = list(get_rows("na", "cid", "sec", "rt", "profiles", mock.MagicMock()))

        assert batches == [[{"profileId": 1}]]
        # One mint at start + one re-mint after the 401.
        assert mock_session.return_value.post.call_count == 2

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_no_profiles_yields_nothing(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _json_response([])

        assert list(get_rows("na", "cid", "sec", "rt", "sp_campaigns", mock.MagicMock())) == []


class TestAmazonAdsSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = AMAZON_ADS_ENDPOINTS[endpoint]
        response = amazon_ads_source("na", "cid", "sec", "rt", endpoint, mock.MagicMock())

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        assert response.sort_mode == "asc"
        assert response.partition_mode is None
        assert response.partition_keys is None
