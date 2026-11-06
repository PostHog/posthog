import base64
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs

import pytest

from products.warehouse_sources.sources.ramp._config import RampSourceConfig
from products.warehouse_sources.sources.ramp.ramp import (
    RampResumeConfig,
    _base_url,
    _format_timestamp,
    check_endpoint_access,
    validate_credentials,
)
from products.warehouse_sources.sources.ramp.settings import PAGE_SIZE, TOKEN_SCOPES
from products.warehouse_sources.sources.ramp.source import RampSource
from products.warehouse_sources.sources.sdk.testing import (
    DriveResult,
    ScriptedResponse,
    SourceDriver,
    route,
    scripted_network,
)

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


def _source(endpoint: str, pages: list[ScriptedResponse], path: str | None = None, **inputs: Any) -> DriveResult:
    script = route({"/token": [_token()], f"/developer/v1/{path or endpoint}": pages})
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
    @pytest.mark.parametrize(
        "schema_name, expected_scope",
        [
            (None, TOKEN_SCOPES),
            ("bills", "bills:read"),
        ],
    )
    def test_mint_requests_documented_scopes(self, schema_name, expected_scope):
        with scripted_network([_token()]) as network:
            validate_credentials("production", "cid", "sec", schema_name)

        request = network.requests_log[0]
        # HTTP Basic client auth: credentials ride in the auth header, scopes in the form body.
        assert request.url == TOKEN_URL
        assert parse_qs((request.body or b"").decode()) == {
            "grant_type": ["client_credentials"],
            "scope": [expected_scope],
        }
        assert request.headers["authorization"] == "Basic " + base64.b64encode(b"cid:sec").decode()

    def test_invalid_when_token_mint_rejected(self):
        with scripted_network([_token(status_code=401)]):
            is_valid, message = validate_credentials("production", "cid", "sec")

        assert is_valid is False
        assert "credentials" in (message or "")


class TestCheckEndpointAccess:
    @pytest.mark.parametrize(
        "token_status, expected_denied",
        [(200, False), (400, True)],
    )
    def test_billing_statements_probe_their_own_scope(self, token_status, expected_denied):
        with scripted_network([_token(status_code=token_status)]) as network:
            reason = check_endpoint_access("production", "cid", "sec", "billing_statements")

        assert parse_qs((network.requests_log[0].body or b"").decode())["scope"] == ["billing_statements:read"]
        assert (reason is not None) == expected_denied
        if expected_denied:
            assert "billing_statements:read" in (reason or "")


class TestGetRows:
    @pytest.mark.parametrize(
        "endpoint, incremental, expected_from_date, expected_page_size, expected_sort_mode",
        [
            ("transactions", True, "2024-01-02T00:00:00Z", PAGE_SIZE, "desc"),
            ("transfers", True, "2024-01-02T00:00:00Z", PAGE_SIZE, None),
            ("statements", True, "2024-01-02T00:00:00Z", 10, None),
            ("transfers", False, None, PAGE_SIZE, None),
            ("statements", False, None, 10, None),
            ("locations", False, None, PAGE_SIZE, "asc"),
        ],
    )
    def test_request_shaping_and_sort_mode(
        self, endpoint, incremental, expected_from_date, expected_page_size, expected_sort_mode
    ):
        result = _source(
            endpoint,
            [_page([])],
            should_use_incremental_field=incremental,
            db_incremental_field_last_value=datetime(2024, 1, 2, tzinfo=UTC) if incremental else None,
        )

        assert result.raised is None
        data_requests = [request for request in result.requests if request.path.endswith(f"/{endpoint}")]
        assert data_requests[0].param("from_date") == expected_from_date
        assert data_requests[0].param("page_size") == str(expected_page_size)
        assert result.response is not None
        assert result.response.sort_mode == expected_sort_mode

    @pytest.mark.parametrize(
        "endpoint, path, scope",
        [
            ("billing_statements", "billing/statements", "billing_statements:read"),
            ("locations", "locations", "locations:read"),
            ("entities", "entities", "entities:read"),
            ("transfers", "transfers", "transfers:read"),
            ("statements", "statements", "statements:read"),
        ],
    )
    def test_endpoints_mint_only_their_own_scope_and_walk_pages(self, endpoint, path, scope):
        result = _source(
            endpoint,
            [
                _page([{"id": "r1"}], next_url=f"https://api.ramp.com/developer/v1/{path}?start=r1"),
                _page([{"id": "r2"}]),
            ],
            path=path,
        )

        assert result.raised is None
        token_request = next(request for request in result.requests if request.path.endswith("/token"))
        assert parse_qs((token_request.body or b"").decode())["scope"] == [scope]
        assert [row["id"] for row in result.rows] == ["r1", "r2"]
        assert result.urls[-1] == f"https://api.ramp.com/developer/v1/{path}?start=r1"

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

    def test_vendor_contacts_fan_out_over_vendors_with_a_vendor_scoped_token(self):
        script = route(
            {
                "/token": [_token()],
                "/developer/v1/vendors": [
                    _page([{"id": "v1"}], next_url="https://api.ramp.com/developer/v1/vendors?start=v1"),
                    _page([{"id": "v2"}]),
                ],
                "/vendors/v1/contacts": [_page([{"id": "c1"}])],
                "/vendors/v2/contacts": [
                    _page([{"id": "c2"}], next_url="https://api.ramp.com/developer/v1/vendors/v2/contacts?start=c2"),
                    _page([{"id": "c3"}]),
                ],
            }
        )
        config = RampSourceConfig(environment="production", client_id="cid", client_secret="sec")
        result = SourceDriver(RampSource(), config).run("vendor_contacts", script)

        assert result.raised is None
        assert [(row["vendor_id"], row["id"]) for row in result.rows] == [("v1", "c1"), ("v2", "c2"), ("v2", "c3")]
        token_request = next(request for request in result.requests if request.path.endswith("/token"))
        token_body = parse_qs((token_request.body or b"").decode())
        assert token_body["scope"] == ["vendors:read"]
