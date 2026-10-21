from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.active_campaign.active_campaign import (
    PAGE_SIZE,
    ActiveCampaignPaginator,
    ActiveCampaignResumeConfig,
    _normalize_base_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.active_campaign.settings import (
    ACTIVE_CAMPAIGN_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.active_campaign.source import ActiveCampaignSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.activecampaign import (
    ActiveCampaignSourceConfig,
)


def _full_page() -> list[dict[str, Any]]:
    return [{"id": str(i)} for i in range(PAGE_SIZE)]


def _meta_response(total: Any) -> MagicMock:
    response = MagicMock()
    response.json.return_value = {"meta": {"total": total}}
    return response


def _driver(api_url: str = "https://acme.api-us1.com") -> SourceDriver:
    return SourceDriver(ActiveCampaignSource(), ActiveCampaignSourceConfig(api_url=api_url, api_key="test-key"))


class TestNormalizeBaseUrl:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("https://acme.api-us1.com", "https://acme.api-us1.com"),
            ("https://acme.api-us1.com/", "https://acme.api-us1.com"),
            ("https://acme.api-us1.com/api/3", "https://acme.api-us1.com"),
            ("https://acme.api-us1.com/api/3/", "https://acme.api-us1.com"),
            ("  https://acme.api-us1.com  ", "https://acme.api-us1.com"),
            ("acme.api-us1.com", "https://acme.api-us1.com"),
            ("acme.api-us1.com/api/3/", "https://acme.api-us1.com"),
            ("http://acme.api-us1.com", "http://acme.api-us1.com"),
        ],
    )
    def test_normalize(self, raw: str, expected: str) -> None:
        assert _normalize_base_url(raw) == expected


class TestActiveCampaignPaginator:
    def test_get_resume_state_none_on_terminal_page(self) -> None:
        paginator = ActiveCampaignPaginator()
        paginator.update_state(_meta_response(1000), [])
        assert paginator.get_resume_state() is None


class TestActiveCampaignSourceResumeBehavior:
    """Tests how the source resumes through the pipeline."""

    def _page_body(self, endpoint: str, items: list[dict[str, Any]], total: Any) -> dict[str, Any]:
        selector = ACTIVE_CAMPAIGN_ENDPOINTS[endpoint].data_selector
        return {selector: items, "meta": {"total": total}}

    @pytest.mark.parametrize(
        "endpoint", ["contacts", "deals", "lists", "campaigns", "deal_activities", "contact_automations"]
    )
    def test_fresh_run_saves_offset_after_each_non_terminal_page(self, endpoint: str) -> None:
        result = _driver().run(
            endpoint,
            [
                ScriptedResponse(json=self._page_body(endpoint, _full_page(), 150)),
                ScriptedResponse(json=self._page_body(endpoint, [{"id": "x"}], 150)),
            ],
        )

        # First request starts at offset 0; the second carries the advanced offset.
        assert result.params("offset") == ["0", str(PAGE_SIZE)]
        assert result.saved_states == [ActiveCampaignResumeConfig(offset=PAGE_SIZE)]
        assert len(result.rows) == PAGE_SIZE + 1
        assert result.raised is None

    def test_resume_seeds_paginator_with_saved_offset(self) -> None:
        result = _driver().run(
            "contacts",
            [ScriptedResponse(json=self._page_body("contacts", [{"id": "resumed"}], 150))],
            resume_state=ActiveCampaignResumeConfig(offset=PAGE_SIZE),
        )

        assert result.params("offset") == [str(PAGE_SIZE)]
        assert result.rows == [{"id": "resumed"}]
        assert result.raised is None

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        result = _driver().run(
            "contacts",
            [ScriptedResponse(json=self._page_body("contacts", [{"id": "a"}], 1))],
        )

        assert result.params("offset") == ["0"]
        assert result.rows == [{"id": "a"}]
        assert result.raised is None


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected_valid"),
        [
            (200, True),
        ],
    )
    def test_status_code_mapping(self, status_code: int, expected_valid: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code, json={}))) as network:
            valid, error = validate_credentials("https://acme.api-us1.com", "test-key")

        assert valid is expected_valid
        assert (error is None) is expected_valid
        assert network.requests_log[0].path == "/api/3/contacts"
        assert network.requests_log[0].param("limit") == "1"

    def test_rejects_non_https_url(self) -> None:
        valid, error = validate_credentials("http://acme.api-us1.com", "test-key")
        assert valid is False
        assert error is not None and "https" in error

    def test_network_error_returns_message(self) -> None:
        with scripted_network([Exception("boom")]):
            valid, error = validate_credentials("https://acme.api-us1.com", "test-key")

        assert valid is False
        assert error == "boom"

    def test_does_not_follow_redirects(self) -> None:
        # Redirect-based SSRF guard: even a host that passes validation must not be
        # allowed to 3xx-redirect onto an internal host, so the request disables it.
        with scripted_network(
            [ScriptedResponse(status=302, headers={"Location": "https://169.254.169.254/metadata"})]
        ) as network:
            valid, error = validate_credentials("https://acme.api-us1.com", "test-key")

        assert valid is False
        assert error is not None
        assert len(network.requests_log) == 1

    def test_redirect_returns_actionable_account_name_message(self) -> None:
        # A redirect means the account name in the URL is likely wrong — surface that
        # instead of a bare status code.
        with scripted_network([ScriptedResponse(status=302, headers={"Location": "/login"})]):
            valid, error = validate_credentials("https://acme.api-us1.com", "test-key")

        assert valid is False
        assert error is not None and "account name" in error
        assert "status code" not in error


class TestSsrfProtection:
    """The user-supplied api_url must not be usable to reach internal/metadata hosts."""

    def test_validate_credentials_blocks_internal_host(self) -> None:
        with patch("posthog.security.url_validation.is_dev_mode", return_value=False):
            valid, error = validate_credentials("https://169.254.169.254", "test-key")
        assert valid is False
        assert error is not None and "not allowed" in error

    def test_source_for_pipeline_blocks_internal_host(self) -> None:
        with patch("posthog.security.url_validation.is_dev_mode", return_value=False):
            result = _driver("https://169.254.169.254").run("contacts", [])

        assert isinstance(result.raised, ValueError)
        assert "not allowed" in str(result.raised)
        assert result.requests == []

    def test_source_for_pipeline_disables_redirects(self) -> None:
        # The sync path hands RESTClient a session built with redirects off, so a
        # 3xx to an internal host can't be followed during a sync either.
        result = _driver().run("contacts", [ScriptedResponse(json={"contacts": [], "meta": {"total": 0}})])

        assert result.session_options[0]["allow_redirects"] is False
        assert result.raised is None
