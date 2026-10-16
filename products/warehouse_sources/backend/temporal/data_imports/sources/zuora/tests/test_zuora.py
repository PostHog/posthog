from datetime import UTC, date, datetime
from typing import Any

import pytest

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.zuora import ZuoraSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.zuora.settings import ENDPOINTS, ZUORA_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.zuora.source import ZuoraSource
from products.warehouse_sources.backend.temporal.data_imports.sources.zuora.zuora import (
    ZuoraResumeConfig,
    _base_url,
    _format_timestamp,
    validate_credentials,
)


def _page(items: list[dict[str, Any]], next_page: str | None = None) -> ScriptedResponse:
    return ScriptedResponse(json={"data": items, "nextPage": next_page})


def _token_response(status_code: int = 200, expires_in: int = 3599) -> ScriptedResponse:
    if status_code < 300:
        return ScriptedResponse(
            status=status_code, json={"access_token": "tok-1", "token_type": "bearer", "expires_in": expires_in}
        )
    return ScriptedResponse(status=status_code, json={"error": "invalid_client"})


def _driver() -> SourceDriver:
    return SourceDriver(
        ZuoraSource(), ZuoraSourceConfig(environment="us_production", client_id="cid", client_secret="sec")
    )


def _data_requests(result: DriveResult) -> list[RecordedRequest]:
    return [request for request in result.requests if request.path.startswith("/object-query/")]


class TestBaseUrl:
    def test_invalid_environment_raises(self):
        with pytest.raises(ValueError):
            _base_url("nope")


class TestFormatTimestamp:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC), "2024-01-02T03:04:05Z"),
            (datetime(2024, 1, 2, 3, 4, 5), "2024-01-02T03:04:05Z"),
            (date(2024, 1, 2), "2024-01-02T00:00:00Z"),
            ("2024-01-02T03:04:05Z", "2024-01-02T03:04:05Z"),
        ],
    )
    def test_format_values(self, value, expected):
        assert _format_timestamp(value) == expected


class TestValidateCredentials:
    def test_invalid_credentials(self):
        with scripted_network(always(_token_response(status_code=401))):
            assert validate_credentials("us_production", "cid", "bad") is False

    def test_network_error_propagates(self):
        # A transient network failure must not be reported as invalid credentials.
        with scripted_network(always(ConnectionError("boom"))), pytest.raises(requests.ConnectionError):
            validate_credentials("us_production", "cid", "sec")

    def test_sandbox_environment_uses_sandbox_host(self):
        with scripted_network([_token_response()]) as network:
            validate_credentials("eu_sandbox", "cid", "sec")

        assert [request.url for request in network.requests_log] == ["https://rest.sandbox.eu.zuora.com/oauth/token"]


class TestGetRows:
    def test_incremental_passes_updateddate_gt_filter(self):
        result = _driver().run(
            "invoices",
            route({"/oauth/token": [_token_response()], "/object-query/invoices": [_page([])]}),
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC),
        )

        request = _data_requests(result)[0]
        assert request.param("filter[]") == "updateddate.GT:2024-01-02T03:04:05Z"
        assert "filter%5B%5D=updateddate.GT%3A2024-01-02T03%3A04%3A05Z" in request.url

    def test_resumes_from_saved_cursor(self):
        result = _driver().run(
            "accounts",
            route({"/oauth/token": [_token_response()], "/object-query/accounts": [_page([{"id": "a9"}])]}),
            resume_state=ZuoraResumeConfig(cursor="cur-9"),
        )

        # The resumed run targets the saved page with the cursor alone.
        request = _data_requests(result)[0]
        assert dict(request.query) == {"cursor": ("cur-9",)}
        assert "cursor=cur-9" in request.url
        assert "pageSize" not in request.url

    def test_mints_token_once_and_sends_bearer(self):
        result = _driver().run(
            "accounts",
            route(
                {
                    "/oauth/token": [_token_response()],
                    "/object-query/accounts": [_page([{"id": "a1"}], next_page="cur-1"), _page([{"id": "a2"}])],
                }
            ),
        )

        # One mint covers the whole run while the ~1h token is unexpired.
        assert result.paths.count("/oauth/token") == 1
        data_requests = _data_requests(result)
        assert len(data_requests) == 2
        assert all(request.headers["authorization"] == "Bearer tok-1" for request in data_requests)


class TestZuoraSourceResponse:
    def test_all_endpoints_have_paths(self):
        assert set(ENDPOINTS) == set(ZUORA_ENDPOINTS.keys())
