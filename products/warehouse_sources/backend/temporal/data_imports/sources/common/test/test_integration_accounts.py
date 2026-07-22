import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.integration_accounts import (
    IntegrationAccount,
    filter_integration_accounts,
)

_ACCOUNTS = [
    IntegrationAccount(value="PostHog/posthog", display_name="PostHog/posthog"),
    IntegrationAccount(value="PostHog/code", display_name="PostHog/code"),
    IntegrationAccount(value="123", display_name="Acme Ads", secondary_text="ACC-987"),
    IntegrationAccount(value="456", display_name="Client One", group="Umbrella Corp"),
]


class TestFilterIntegrationAccounts:
    @pytest.mark.parametrize("search", [None, "", "   "])
    def test_empty_search_returns_all(self, search):
        assert filter_integration_accounts(_ACCOUNTS, search) == _ACCOUNTS

    def test_matches_value_case_insensitively(self):
        result = filter_integration_accounts(_ACCOUNTS, "CODE")
        assert [a.value for a in result] == ["PostHog/code"]

    def test_matches_display_name(self):
        result = filter_integration_accounts(_ACCOUNTS, "acme")
        assert [a.value for a in result] == ["123"]

    def test_matches_secondary_text(self):
        result = filter_integration_accounts(_ACCOUNTS, "acc-987")
        assert [a.value for a in result] == ["123"]

    def test_matches_group(self):
        # The client folds `group` into its own search text, but it can only match rows the server
        # returned — so searching a manager's name has to survive this filter first.
        result = filter_integration_accounts(_ACCOUNTS, "umbrella")
        assert [a.value for a in result] == ["456"]

    def test_no_match_returns_empty(self):
        assert filter_integration_accounts(_ACCOUNTS, "nonexistent") == []

    def test_trims_whitespace(self):
        assert [a.value for a in filter_integration_accounts(_ACCOUNTS, "  code  ")] == ["PostHog/code"]
