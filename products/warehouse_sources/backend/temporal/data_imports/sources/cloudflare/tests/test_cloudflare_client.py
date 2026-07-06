from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

import requests
from tenacity import Future, RetryCallState

from products.warehouse_sources.backend.temporal.data_imports.sources.cloudflare.cloudflare import (
    MAX_RETRY_AFTER_SECONDS,
    PAGE_SIZE,
    CloudflareRetryableError,
    _parse_retry_after,
    _wait_strategy,
    cloudflare_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cloudflare.settings import (
    CLOUDFLARE_ENDPOINTS,
    ENDPOINTS,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.cloudflare.cloudflare"


def _response(result: list[dict[str, Any]], total_pages: int | None = None, success: bool = True) -> mock.MagicMock:
    resp = mock.MagicMock()
    body: dict[str, Any] = {"success": success, "result": result}
    if total_pages is not None:
        body["result_info"] = {"total_pages": total_pages}
    resp.json.return_value = body
    resp.status_code = 200
    resp.ok = True
    return resp


def _rate_limited_response(headers: dict[str, str] | None = None) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.status_code = 429
    resp.ok = False
    resp.headers = headers or {}
    return resp


def _retry_state(exc: BaseException) -> RetryCallState:
    state = RetryCallState(retry_object=mock.MagicMock(), fn=None, args=(), kwargs={})
    state.outcome = Future.construct(1, exc, has_exception=True)
    return state


def _error_response(status_code: int) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.status_code = status_code
    resp.ok = False
    resp.raise_for_status.side_effect = requests.HTTPError(
        f"{status_code} Client Error for url: https://api.cloudflare.com", response=resp
    )
    return resp


class TestValidateCredentials:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_valid_on_verify_success(self, mock_session):
        mock_session.return_value.get.return_value = _response([], success=True)
        assert validate_credentials("token") is True

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_invalid_when_success_false(self, mock_session):
        mock_session.return_value.get.return_value = _response([], success=False)
        assert validate_credentials("token") is False

    @pytest.mark.parametrize("status_code", [401, 403, 500])
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_invalid_on_error_status(self, mock_session, status_code):
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response
        assert validate_credentials("token") is False

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_invalid_on_exception(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("token") is False


class TestGetRows:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_zones_paginate_via_total_pages(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response([{"id": "z1"}], total_pages=2),
            _response([{"id": "z2"}], total_pages=2),
        ]

        batches = list(get_rows("token", "zones", mock.MagicMock()))

        assert [item["id"] for batch in batches for item in batch] == ["z1", "z2"]
        urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        assert parse_qs(urlparse(urls[0]).query)["page"] == ["1"]
        assert parse_qs(urlparse(urls[1]).query)["page"] == ["2"]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_missing_result_info_falls_back_to_short_page(self, mock_session):
        mock_session.return_value.get.return_value = _response([{"id": "a1"}])

        batches = list(get_rows("token", "accounts", mock.MagicMock()))

        assert len(batches) == 1
        assert mock_session.return_value.get.call_count == 1

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_dns_records_fan_out_over_zones_and_inject_zone_id(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response([{"id": "z1"}, {"id": "z2"}], total_pages=1),
            _response([{"id": "r1"}], total_pages=1),
            _response([{"id": "r2"}], total_pages=1),
        ]

        batches = list(get_rows("token", "dns_records", mock.MagicMock()))

        flat = [item for batch in batches for item in batch]
        assert [(r["id"], r["_zone_id"]) for r in flat] == [("r1", "z1"), ("r2", "z2")]
        urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        assert urlparse(urls[1]).path == "/client/v4/zones/z1/dns_records"
        assert urlparse(urls[2]).path == "/client/v4/zones/z2/dns_records"

    @pytest.mark.parametrize("status_code", [403, 404])
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_dns_records_skips_inaccessible_zone_and_continues(self, mock_session, status_code):
        # A token can list every zone but lack DNS access on a subset; one
        # forbidden zone must not abort the whole stream.
        mock_session.return_value.get.side_effect = [
            _response([{"id": "z1"}, {"id": "z2"}], total_pages=1),
            _error_response(status_code),
            _response([{"id": "r2"}], total_pages=1),
        ]
        logger = mock.MagicMock()

        batches = list(get_rows("token", "dns_records", logger))

        flat = [item for batch in batches for item in batch]
        assert [(r["id"], r["_zone_id"]) for r in flat] == [("r2", "z2")]
        logger.warning.assert_called_once()

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_dns_records_reraises_unexpected_zone_error(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response([{"id": "z1"}], total_pages=1),
            _error_response(400),
        ]

        with pytest.raises(requests.HTTPError):
            list(get_rows("token", "dns_records", mock.MagicMock()))

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_forbidden_zone_listing_propagates(self, mock_session):
        # No zone access at all (the top-level listing) must still fail loudly
        # so the schema is flagged non-retryable rather than silently emptied.
        mock_session.return_value.get.side_effect = [_error_response(403)]

        with pytest.raises(requests.HTTPError):
            list(get_rows("token", "dns_records", mock.MagicMock()))

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_full_page_without_result_info_continues(self, mock_session):
        full_page = [{"id": str(i)} for i in range(PAGE_SIZE)]
        mock_session.return_value.get.side_effect = [
            _response(full_page),
            _response([{"id": "tail"}]),
        ]

        batches = list(get_rows("token", "accounts", mock.MagicMock()))

        assert len(batches) == 2

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_empty_response_yields_nothing(self, mock_session):
        mock_session.return_value.get.return_value = _response([], total_pages=0)

        assert list(get_rows("token", "zones", mock.MagicMock())) == []


class TestRetryAfterHandling:
    @pytest.mark.parametrize(
        "headers, expected",
        [
            ({"Retry-After": "30"}, 30.0),
            ({"Retry-After": "0"}, 0.0),
            ({"Retry-After": "12.5"}, 12.5),
            ({}, None),
            ({"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}, None),
            ({"Retry-After": "soon"}, None),
        ],
    )
    def test_parse_retry_after(self, headers, expected):
        assert _parse_retry_after(_rate_limited_response(headers)) == expected

    def test_wait_strategy_honors_retry_after(self):
        exc = CloudflareRetryableError("rate limited", retry_after=45.0)
        assert _wait_strategy(_retry_state(exc)) == 45.0

    def test_wait_strategy_caps_retry_after(self):
        exc = CloudflareRetryableError("rate limited", retry_after=10_000.0)
        assert _wait_strategy(_retry_state(exc)) == MAX_RETRY_AFTER_SECONDS

    def test_wait_strategy_falls_back_to_backoff_without_retry_after(self):
        exc = CloudflareRetryableError("server error", retry_after=None)
        # Jittered exponential backoff for the first attempt stays small and bounded.
        assert 0 < _wait_strategy(_retry_state(exc)) <= 60

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_429_carries_retry_after_into_exception(self, mock_session):
        # Retry-After of 0 keeps the test fast while still exercising the honored-wait path.
        mock_session.return_value.get.return_value = _rate_limited_response({"Retry-After": "0"})

        with pytest.raises(CloudflareRetryableError) as exc_info:
            list(get_rows("token", "zones", mock.MagicMock()))

        assert exc_info.value.retry_after == 0.0
        # Exhausts all attempts since every page stays rate-limited.
        assert mock_session.return_value.get.call_count == 5


class TestCloudflareSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = CLOUDFLARE_ENDPOINTS[endpoint]
        response = cloudflare_source("token", endpoint, mock.MagicMock())

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        assert response.sort_mode == "asc"
        assert response.partition_mode is None
        assert response.partition_keys is None
