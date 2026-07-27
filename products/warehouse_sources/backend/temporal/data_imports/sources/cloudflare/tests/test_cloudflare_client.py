import json
from typing import Any

import pytest
from unittest import mock

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.cloudflare.cloudflare import (
    PAGE_SIZE,
    cloudflare_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cloudflare.settings import (
    CLOUDFLARE_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the cloudflare module.
CLOUDFLARE_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.cloudflare.cloudflare.make_tracked_session"
)


def _response(
    result: list[dict[str, Any]],
    total_pages: int | None = None,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
) -> Response:
    body: dict[str, Any] = {"success": True, "result": result}
    if total_pages is not None:
        body["result_info"] = {"total_pages": total_pages}
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    if headers:
        resp.headers.update(headers)
    return resp


def _error_response(status_code: int) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp.url = "https://api.cloudflare.com/client/v4/probe"
    resp._content = json.dumps({"success": False, "errors": [{"code": status_code}]}).encode()
    return resp


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and snapshot each request's url/params AT PREPARE TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the
    run shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {})})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestValidateCredentials:
    @mock.patch(CLOUDFLARE_SESSION_PATCH)
    def test_valid_on_verify_success(self, mock_session) -> None:
        mock_session.return_value.get.return_value = _response([], total_pages=1)
        assert validate_credentials("token") is True

    @mock.patch(CLOUDFLARE_SESSION_PATCH)
    def test_invalid_when_success_false(self, mock_session) -> None:
        resp = Response()
        resp.status_code = 200
        resp._content = json.dumps({"success": False, "result": None}).encode()
        mock_session.return_value.get.return_value = resp
        assert validate_credentials("token") is False

    @pytest.mark.parametrize("status_code", [401, 403, 500])
    @mock.patch(CLOUDFLARE_SESSION_PATCH)
    def test_invalid_on_error_status(self, mock_session, status_code) -> None:
        mock_session.return_value.get.return_value = _error_response(status_code)
        assert validate_credentials("token") is False

    @mock.patch(CLOUDFLARE_SESSION_PATCH)
    def test_invalid_on_exception(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("token") is False


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_zones_paginate_via_total_pages(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response([{"id": "z1"}], total_pages=2),
                _response([{"id": "z2"}], total_pages=2),
            ],
        )

        rows = _rows(cloudflare_source("token", "zones", team_id=1, job_id="j"))

        assert [r["id"] for r in rows] == ["z1", "z2"]
        assert snapshots[0]["params"]["page"] == 1
        assert snapshots[0]["params"]["per_page"] == PAGE_SIZE
        assert snapshots[1]["params"]["page"] == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_result_info_falls_back_to_short_page(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": "a1"}])])

        rows = _rows(cloudflare_source("token", "accounts", team_id=1, job_id="j"))

        assert [r["id"] for r in rows] == ["a1"]
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_page_without_result_info_continues(self, MockSession) -> None:
        session = MockSession.return_value
        full_page = [{"id": str(i)} for i in range(PAGE_SIZE)]
        _wire(session, [_response(full_page), _response([{"id": "tail"}])])

        rows = _rows(cloudflare_source("token", "accounts", team_id=1, job_id="j"))

        assert len(rows) == PAGE_SIZE + 1
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_response_yields_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], total_pages=0)])

        assert _rows(cloudflare_source("token", "zones", team_id=1, job_id="j")) == []
        assert session.send.call_count == 1


class TestZoneFanout:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_dns_records_fan_out_over_zones_and_inject_zone_id(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response([{"id": "z1"}, {"id": "z2"}], total_pages=1),
                _response([{"id": "r1"}], total_pages=1),
                _response([{"id": "r2"}], total_pages=1),
            ],
        )

        rows = _rows(cloudflare_source("token", "dns_records", team_id=1, job_id="j"))

        assert [(r["id"], r["_zone_id"]) for r in rows] == [("r1", "z1"), ("r2", "z2")]
        assert snapshots[0]["url"] == "https://api.cloudflare.com/client/v4/zones"
        assert snapshots[1]["url"] == "https://api.cloudflare.com/client/v4/zones/z1/dns_records"
        assert snapshots[2]["url"] == "https://api.cloudflare.com/client/v4/zones/z2/dns_records"

    @pytest.mark.parametrize("status_code", [403, 404])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_dns_records_skips_inaccessible_zone_and_continues(self, MockSession, status_code) -> None:
        # A token can list every zone but lack DNS access on a subset; one
        # forbidden zone must not abort the whole stream.
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([{"id": "z1"}, {"id": "z2"}], total_pages=1),
                _error_response(status_code),
                _response([{"id": "r2"}], total_pages=1),
            ],
        )

        rows = _rows(cloudflare_source("token", "dns_records", team_id=1, job_id="j"))

        assert [(r["id"], r["_zone_id"]) for r in rows] == [("r2", "z2")]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_dns_records_reraises_unexpected_zone_error(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([{"id": "z1"}], total_pages=1),
                _error_response(400),
            ],
        )

        with pytest.raises(requests.HTTPError):
            _rows(cloudflare_source("token", "dns_records", team_id=1, job_id="j"))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_forbidden_zone_listing_propagates(self, MockSession) -> None:
        # No zone access at all (the top-level listing) must still fail loudly
        # so the schema is flagged non-retryable rather than silently emptied.
        session = MockSession.return_value
        _wire(session, [_error_response(403)])

        with pytest.raises(requests.HTTPError):
            _rows(cloudflare_source("token", "dns_records", team_id=1, job_id="j"))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_zone_without_id_is_skipped(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([{"name": "no-id"}, {"id": "z1"}], total_pages=1),
                _response([{"id": "r1"}], total_pages=1),
            ],
        )

        rows = _rows(cloudflare_source("token", "dns_records", team_id=1, job_id="j"))

        assert [(r["id"], r["_zone_id"]) for r in rows] == [("r1", "z1")]
        assert session.send.call_count == 2


class TestRetry:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_429_honors_retry_after_and_exhausts_attempts(self, MockSession) -> None:
        # Retry-After of 0 keeps the test fast while still exercising the honored-wait path.
        session = MockSession.return_value
        responses = [_error_response(429) for _ in range(5)]
        for resp in responses:
            resp.headers["Retry-After"] = "0"
        _wire(session, responses)

        with pytest.raises(RESTClientRetryableError) as exc_info:
            _rows(cloudflare_source("token", "zones", team_id=1, job_id="j"))

        assert exc_info.value.retry_after == 0.0
        # Exhausts all attempts since every page stays rate-limited.
        assert session.send.call_count == 5


class TestCloudflareSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_response_metadata_per_endpoint(self, MockSession, endpoint) -> None:
        MockSession.return_value.headers = {}
        config = CLOUDFLARE_ENDPOINTS[endpoint]
        response = cloudflare_source("token", endpoint, team_id=1, job_id="j")

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        assert response.sort_mode == "asc"
        assert response.partition_mode is None
        assert response.partition_keys is None
