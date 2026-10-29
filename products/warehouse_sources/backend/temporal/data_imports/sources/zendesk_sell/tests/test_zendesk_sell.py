from typing import Any

import pytest

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.zendesksell import (
    ZendeskSellSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zendesk_sell.source import ZendeskSellSource
from products.warehouse_sources.backend.temporal.data_imports.sources.zendesk_sell.zendesk_sell import (
    PER_PAGE,
    ZendeskSellResumeConfig,
    ZendeskSellUntrustedURLError,
    _validate_pagination_url,
    validate_credentials,
)

FIRST_URL = "https://api.getbase.com/v2/contacts"
PAGE_2_URL = "https://api.getbase.com/v2/contacts?page=2&per_page=100"


def _envelope(records: list[dict[str, Any]], next_page: str | None) -> dict[str, Any]:
    """Build the Zendesk Sell collection envelope around a list of record dicts."""
    links: dict[str, Any] = {"self": "https://api.getbase.com/v2/contacts?page=1&per_page=100"}
    if next_page:
        links["next_page"] = next_page
    return {
        "items": [{"data": r, "meta": {"type": "contact"}} for r in records],
        "meta": {"type": "collection", "count": len(records), "links": links},
    }


def _response(body: dict[str, Any], status: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status, json=body)


def _run(script: Any, resume_state: ZendeskSellResumeConfig | None = None) -> DriveResult:
    driver = SourceDriver(ZendeskSellSource(), ZendeskSellSourceConfig(access_token="token"))
    return driver.run("contacts", script, resume_state=resume_state)


class TestPagination:
    def test_checkpoints_only_when_more_pages_remain(self) -> None:
        result = _run(
            [
                _response(_envelope([{"id": 1}], next_page=PAGE_2_URL)),
                _response(_envelope([{"id": 2}], next_page=None)),
            ]
        )

        # Exactly one checkpoint: after the first page (which had a next_page). The final page must not
        # persist state, so a completed sync leaves nothing to resume into.
        assert result.saved_states == [ZendeskSellResumeConfig(next_url=PAGE_2_URL)]

    def test_resumes_from_saved_next_url(self) -> None:
        result = _run(
            [_response(_envelope([{"id": 2}], next_page=None))],
            resume_state=ZendeskSellResumeConfig(next_url=PAGE_2_URL),
        )

        # The initial page is never requested — only the saved next_url is fetched.
        assert result.rows == [{"id": 2}]
        assert result.urls == [PAGE_2_URL]

    def test_item_without_data_fails_fast(self) -> None:
        # Every envelope item must carry `data`; a missing key is a malformed response and must raise
        # rather than silently drop the record.
        result = _run([_response({"items": [{"meta": {"type": "contact"}}], "meta": {"links": {}}})])

        assert isinstance(result.raised, KeyError)

    def test_hostile_upstream_next_page_is_rejected(self) -> None:
        result = _run([_response(_envelope([{"id": 1}], next_page="https://evil.example.com/v2/contacts"))])

        assert isinstance(result.raised, ZendeskSellUntrustedURLError)
        # The poisoned link must not be persisted as resume state.
        assert result.saved_states == []

    def test_hostile_resumed_next_url_is_rejected(self) -> None:
        result = _run([], resume_state=ZendeskSellResumeConfig(next_url="https://evil.example.com/v2/contacts"))

        assert isinstance(result.raised, ZendeskSellUntrustedURLError)
        # A poisoned resume state must never reach the network with the bearer token.
        assert result.requests == []

    def test_bearer_token_registered_for_redaction(self) -> None:
        result = _run([_response(_envelope([{"id": 1}], next_page=None))])

        # The token flows through framework auth, which registers it for value-based log/error redaction.
        assert result.session_options[0]["redact_values"] == ("token",)


class TestRetryClassification:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_retry_then_raise(self, _name: str, status: int) -> None:
        result = _run(always(_response({}, status=status)))

        assert isinstance(result.raised, RESTClientRetryableError)
        # Retried up to the client's attempt budget rather than failing on the first transient error.
        assert len(result.requests) > 1

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_http_error(self, _name: str, status: int) -> None:
        result = _run([_response({}, status=status)])

        assert isinstance(result.raised, requests.HTTPError)


class TestValidatePaginationUrl:
    @parameterized.expand(
        [
            ("first_page", f"https://api.getbase.com/v2/contacts?per_page={PER_PAGE}"),
            ("next_page", PAGE_2_URL),
            ("other_endpoint", "https://api.getbase.com/v2/deals?page=3"),
        ]
    )
    def test_trusted_urls_pass_through(self, _name: str, url: str) -> None:
        assert _validate_pagination_url(url) == url

    @parameterized.expand(
        [
            ("foreign_host", "https://evil.example.com/v2/contacts"),
            ("subdomain_lookalike", "https://api.getbase.com.evil.example.com/v2/contacts"),
            ("http_scheme", "http://api.getbase.com/v2/contacts"),
            ("wrong_path_prefix", "https://api.getbase.com/internal/contacts"),
            ("missing_path", "https://api.getbase.com"),
            ("metadata_endpoint", "http://169.254.169.254/latest/meta-data/"),
        ]
    )
    def test_untrusted_urls_raise(self, _name: str, url: str) -> None:
        with pytest.raises(ZendeskSellUntrustedURLError):
            _validate_pagination_url(url)


class TestValidateCredentials:
    def test_probe_session_redacts_token_and_disables_redirects(self) -> None:
        with scripted_network(always(_response({}))) as network:
            validate_credentials("secret-token")
        assert network.session_options[0]["redact_values"] == ("secret-token",)
        assert network.session_options[0]["allow_redirects"] is False
