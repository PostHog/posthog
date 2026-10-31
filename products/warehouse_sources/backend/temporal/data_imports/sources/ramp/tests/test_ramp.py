import base64
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    ScriptedResponse,
    SourceDriver,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ramp import RampSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.ramp.ramp import (
    PAGE_SIZE,
    RampResumeConfig,
    _base_url,
    _format_timestamp,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ramp.settings import TOKEN_SCOPES
from products.warehouse_sources.backend.temporal.data_imports.sources.ramp.source import RampSource

TOKEN_URL = "https://api.ramp.com/developer/v1/token"


def _page(items: list[dict[str, Any]], next_url: str | None = None) -> ScriptedResponse:
    return ScriptedResponse(json={"data": items, "page": {"next": next_url}})


def _token(status_code: int = 200, expires_in: int = 864000) -> ScriptedResponse:
    body: dict[str, Any] = (
        {"access_token": "the-token", "expires_in": expires_in, "token_type": "Bearer"}
        if status_code < 300
        else {"error": "invalid_client"}
    )
    return ScriptedResponse(status=status_code, json=body)


def _source(endpoint: str, pages: list[ScriptedResponse], **inputs: Any) -> DriveResult:
    script = route({"/token": [_token()], f"/developer/v1/{endpoint}": pages})
    config = RampSourceConfig(environment="production", client_id="cid", client_secret="sec")
    return SourceDriver(RampSource(), config).run(endpoint, script, **inputs)


class TestBaseUrl:
    def test_invalid_environment_raises(self):
        with pytest.raises(ValueError):
            _base_url("evil")


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
    def test_mint_requests_documented_scopes(self):
        with scripted_network([_token()]) as network:
            validate_credentials("production", "cid", "sec")

        request = network.requests_log[0]
        # HTTP Basic client auth: credentials ride in the auth header, scopes in the form body.
        assert request.url == TOKEN_URL
        assert parse_qs((request.body or b"").decode()) == {
            "grant_type": ["client_credentials"],
            "scope": [TOKEN_SCOPES],
        }
        assert request.headers["authorization"] == "Basic " + base64.b64encode(b"cid:sec").decode()

    def test_invalid_when_token_mint_rejected(self):
        with scripted_network([_token(status_code=401)]):
            is_valid, message = validate_credentials("production", "cid", "sec")

        assert is_valid is False
        assert "credentials" in (message or "")


class TestGetRows:
    def test_incremental_transactions_use_from_date(self):
        result = _source(
            "transactions",
            [_page([])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 2, tzinfo=UTC),
        )

        data_requests = [request for request in result.requests if request.path.endswith("/transactions")]
        assert data_requests[0].param("from_date") == "2024-01-02T00:00:00Z"
        assert data_requests[0].param("page_size") == str(PAGE_SIZE)

    def test_a_run_with_no_saved_state_starts_from_the_first_page(self):
        result = _source("transactions", [_page([{"id": "t1"}])])

        assert result.raised is None
        assert result.urls[-1].startswith("https://api.ramp.com/developer/v1/transactions?page_size=")

    def test_mints_token_once_and_sends_bearer(self):
        result = _source(
            "transactions",
            [
                _page([{"id": "t1"}], next_url="https://api.ramp.com/developer/v1/transactions?p=2"),
                _page([{"id": "t2"}]),
            ],
        )

        # One mint covers the whole run while the ~10-day token is unexpired.
        assert result.paths.count("/developer/v1/token") == 1
        data_requests = [request for request in result.requests if request.path.endswith("/transactions")]
        assert len(data_requests) == 2
        assert all(request.headers["authorization"] == "Bearer the-token" for request in data_requests)

    def test_rejects_off_host_next_url(self):
        # SSRF guard: a page.next pointing off the configured Ramp host is rejected before the
        # request (and its bearer token) leaves the process.
        result = _source(
            "transactions",
            [_page([{"id": "t1"}], next_url="https://evil.example.com/developer/v1/transactions")],
        )

        assert isinstance(result.raised, ValueError)
        assert not any("evil.example.com" in url for url in result.urls)

    def test_rejects_off_host_resume_url(self):
        result = _source(
            "transactions",
            [],
            resume_state=RampResumeConfig(next_url="https://evil.example.com/developer/v1/transactions"),
        )

        assert isinstance(result.raised, ValueError)
        assert not any("evil.example.com" in url for url in result.urls)
        assert result.saved_states == []
