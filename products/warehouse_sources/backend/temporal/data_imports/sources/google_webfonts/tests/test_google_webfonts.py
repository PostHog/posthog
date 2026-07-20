from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.google_webfonts.google_webfonts import (
    MAX_RETRY_ATTEMPTS,
    GoogleWebfontsRetryableError,
    get_rows,
    google_webfonts_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_webfonts.settings import (
    ENDPOINTS,
    GOOGLE_WEBFONTS_ENDPOINTS,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.google_webfonts.google_webfonts"


def _response(items: list[dict[str, Any]]) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = {"kind": "webfonts#webfontList", "items": items}
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
            (400, False),  # invalid key
            (403, False),  # missing/unregistered key
            (500, False),
        ],
    )
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected):
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert validate_credentials("AIza-key") is expected

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_validate_sends_key_in_header_not_url(self, mock_session):
        response = mock.MagicMock()
        response.status_code = 200
        mock_session.return_value.get.return_value = response

        validate_credentials("AIza-secret")

        # Key must ride the X-goog-api-key header so it never lands in a logged request URL.
        headers = mock_session.call_args.kwargs["headers"]
        assert headers["X-goog-api-key"] == "AIza-secret"
        url = mock_session.return_value.get.call_args.args[0]
        assert "AIza-secret" not in url

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_validate_credentials_propagates_connection_errors(self, mock_session):
        # Connection-level failures must surface so the caller can distinguish "unreachable"
        # from "invalid key" rather than blaming the credential.
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")
        with pytest.raises(requests.ConnectionError):
            validate_credentials("AIza-key")


class TestGetRows:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_yields_items_array_and_requests_stable_sort(self, mock_session):
        mock_session.return_value.get.return_value = _response([{"family": "Roboto"}, {"family": "Lato"}])

        batches = list(get_rows("AIza-key", "webfonts", mock.MagicMock()))

        assert batches == [[{"family": "Roboto"}, {"family": "Lato"}]]
        url = mock_session.return_value.get.call_args.args[0]
        assert urlparse(url).path == "/webfonts/v1/webfonts"
        assert parse_qs(urlparse(url).query)["sort"] == ["alpha"]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_empty_catalog_yields_nothing(self, mock_session):
        mock_session.return_value.get.return_value = _response([])

        assert list(get_rows("AIza-key", "webfonts", mock.MagicMock())) == []

    @mock.patch("time.sleep")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_retries_retryable_status_then_succeeds(self, mock_session, _mock_sleep):
        mock_session.return_value.get.side_effect = [
            _error_response(500),
            _error_response(429),
            _response([{"family": "Roboto"}]),
        ]

        batches = list(get_rows("AIza-key", "webfonts", mock.MagicMock()))

        assert batches == [[{"family": "Roboto"}]]
        assert mock_session.return_value.get.call_count == 3

    @mock.patch("time.sleep")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_retries_exhausted_raises(self, mock_session, _mock_sleep):
        mock_session.return_value.get.return_value = _error_response(503)

        with pytest.raises(GoogleWebfontsRetryableError):
            list(get_rows("AIza-key", "webfonts", mock.MagicMock()))

        assert mock_session.return_value.get.call_count == MAX_RETRY_ATTEMPTS


class TestGoogleWebfontsSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = GOOGLE_WEBFONTS_ENDPOINTS[endpoint]
        response = google_webfonts_source("AIza-key", endpoint, mock.MagicMock())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
        assert response.partition_mode is None
        assert response.partition_keys is None
