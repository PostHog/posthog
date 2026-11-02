from datetime import UTC, date, datetime
from typing import Any

import pytest

from parameterized import parameterized
from requests.exceptions import ConnectionError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.invoiced import (
    InvoicedSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.invoiced.invoiced import (
    INVOICED_BASE_URL,
    PAGE_SIZE,
    InvoicedResumeConfig,
    InvoicedUntrustedURLError,
    _to_unix_timestamp,
    _validate_pagination_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.invoiced.source import InvoicedSource


class TestToUnixTimestamp:
    @parameterized.expand(
        [
            ("aware_datetime", datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC), 1704164645),
            ("naive_datetime_assumed_utc", datetime(2024, 1, 2, 3, 4, 5), 1704164645),
            ("date", date(2024, 1, 2), 1704153600),
            ("int", 1700000000, 1700000000),
            ("numeric_string", "1700000000", 1700000000),
        ]
    )
    def test_converts_to_epoch_seconds(self, _name: str, value: Any, expected: int) -> None:
        assert _to_unix_timestamp(value) == expected


class TestSourcePagination:
    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(InvoicedSource(), InvoicedSourceConfig(api_key="api-key"))

    def test_incremental_request_includes_updated_after_and_sort(self) -> None:
        result = self._driver().run(
            "invoices",
            [ScriptedResponse(json=[])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=1700000000,
        )

        assert result.raised is None
        assert result.requests[0].param("updated_after") == "1700000000"
        assert result.requests[0].param("sort") == "updated_at asc"
        assert result.requests[0].param("per_page") == str(PAGE_SIZE)

    @parameterized.expand(
        [
            ("tasks", "updated_at asc"),
            ("credit_balance_adjustments", None),
            ("events", None),
        ]
    )
    def test_endpoint_without_updated_after_ignores_cursor(self, endpoint: str, expected_sort: str | None) -> None:
        # These endpoints document no `updated_after` filter (and only some document `sort`), so a
        # stale cursor must not leak an undocumented param into the request.
        result = self._driver().run(
            endpoint,
            [ScriptedResponse(json=[])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=1700000000,
        )

        assert result.raised is None
        assert result.requests[0].param("updated_after") is None
        assert result.requests[0].param("sort") == expected_sort
        assert result.requests[0].param("per_page") == str(PAGE_SIZE)

    def test_non_list_body_fails_loud(self) -> None:
        result = self._driver().run("customers", [ScriptedResponse(json={"error": "boom"})])

        # List endpoints return a top-level array; a non-list body means the shape changed.
        assert isinstance(result.raised, ValueError)
        assert "list response body" in str(result.raised)

    def test_hostile_upstream_next_url_is_rejected(self) -> None:
        # An upstream Link header pointing at another host must abort before the API key is sent
        # there, and the poisoned URL must not be persisted as resume state.
        result = self._driver().run(
            "customers",
            [
                ScriptedResponse(
                    json=[{"id": 1}],
                    headers={"Link": '<https://evil.example.com/customers>; rel="next"'},
                )
            ],
        )

        assert isinstance(result.raised, InvoicedUntrustedURLError)
        assert result.paths == ["/customers"]
        assert result.saved_states == []

    def test_hostile_resumed_next_url_is_rejected(self) -> None:
        # A poisoned resume state from Redis must never be requested with the API key.
        result = self._driver().run(
            "customers",
            [],
            resume_state=InvoicedResumeConfig(next_url="https://evil.example.com/customers"),
        )

        assert isinstance(result.raised, InvoicedUntrustedURLError)
        assert result.requests == []


class TestValidatePaginationUrl:
    @parameterized.expand(
        [
            ("first_page", f"{INVOICED_BASE_URL}/customers?per_page=100"),
            ("next_page", f"{INVOICED_BASE_URL}/customers?per_page=100&page=2"),
            ("other_endpoint", f"{INVOICED_BASE_URL}/invoices?page=3"),
        ]
    )
    def test_trusted_urls_pass_through(self, _name: str, url: str) -> None:
        assert _validate_pagination_url(url) == url

    @parameterized.expand(
        [
            ("foreign_host", "https://evil.example.com/customers"),
            ("subdomain_lookalike", "https://api.invoiced.com.evil.example.com/customers"),
            ("http_scheme", "http://api.invoiced.com/customers"),
            ("metadata_endpoint", "http://169.254.169.254/latest/meta-data/"),
        ]
    )
    def test_untrusted_urls_raise(self, _name: str, url: str) -> None:
        with pytest.raises(InvoicedUntrustedURLError):
            _validate_pagination_url(url)


class TestValidateCredentials:
    @parameterized.expand([("unauthorized", 401)])
    def test_auth_failure_maps_to_invalid_key(self, _name: str, status_code: int) -> None:
        with scripted_network([ScriptedResponse(status=status_code)]) as network:
            assert validate_credentials("bad-key") == (False, "Invalid Invoiced API key")

        assert network.requests_log[0].path == "/customers"

    def test_unexpected_status_returns_message(self) -> None:
        with scripted_network(always(ScriptedResponse(status=500))) as network:
            ok, message = validate_credentials("key")

        assert ok is False
        assert message == "Invoiced returned HTTP 500"
        assert {request.path for request in network.requests_log} == {"/customers"}

    def test_connection_error_returns_message(self) -> None:
        with scripted_network(always(ConnectionError("boom"))) as network:
            ok, message = validate_credentials("key")

        assert ok is False
        assert message is not None and "Could not connect to Invoiced" in message
        assert {request.path for request in network.requests_log} == {"/customers"}

    def test_probe_disables_redirects_to_protect_api_key(self) -> None:
        # The Basic-auth API key rides on the probe; the session must be built with redirects pinned
        # off so a redirect can't replay it to the redirect target during validation.
        with scripted_network([ScriptedResponse(json=[])]) as network:
            assert validate_credentials("good-key") == (True, None)

        assert network.session_options[0]["allow_redirects"] is False
