import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.salesforce.source import SalesforceSource


class TestSalesforceSourceNonRetryableErrors:
    def setup_method(self):
        self.source = SalesforceSource()

    @pytest.mark.parametrize(
        "error_message",
        [
            "Integration not found: 157911",
            "ValueError: Integration not found: 42",
        ],
    )
    def test_deleted_integration_is_non_retryable(self, error_message):
        # OAuthMixin.get_oauth_integration raises "Integration not found: <id>" when the linked
        # Salesforce integration was deleted. The id is volatile, so we match the stable prefix.
        non_retryable_errors = self.source.get_non_retryable_errors()

        assert any(pattern in error_message for pattern in non_retryable_errors), (
            f"Expected '{error_message}' to match a non-retryable pattern"
        )

    def test_not_found_is_non_retryable_with_a_curated_message(self):
        # An org still on the previous Salesforce release answers 404 to every path of the pinned
        # version, so the raw error stores the instance url and the SOQL query verbatim.
        error_message = (
            "404 Client Error: Not Found for url: https://example.my.salesforce.com"
            "/services/data/v67.0/query?q=SELECT+FIELDS%28ALL%29+FROM+Contact"
        )
        non_retryable_errors = self.source.get_non_retryable_errors()

        matched = [pattern for pattern in non_retryable_errors if pattern in error_message]
        assert matched == ["404 Client Error: Not Found for url"]

        friendly = non_retryable_errors[matched[0]]
        assert friendly is not None
        assert "salesforce.com" not in friendly
        assert "404" not in friendly


class TestSalesforceSourceVersions:
    def setup_method(self):
        self.source = SalesforceSource()

    def test_new_sources_default_to_v67(self):
        assert self.source.default_version == "v67.0"
        assert self.source.resolve_api_version(None) == "v67.0"

    @pytest.mark.parametrize("version", ["v61.0", "v67.0"])
    def test_existing_pin_is_honored(self, version):
        # Pinned rows keep their version even after the default bump.
        assert version in self.source.supported_versions
        assert self.source.resolve_api_version(version) == version
