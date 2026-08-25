import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.clerk.settings import CLERK_ENDPOINTS, ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.clerk.source import ClerkSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.clerk import ClerkSourceConfig


class TestClerkSource:
    def setup_method(self):
        self.source = ClerkSource()
        self.team_id = 123
        self.config = ClerkSourceConfig(secret_key="sk_live_test")

    @pytest.mark.parametrize(
        "expected_key",
        [
            "401 Client Error: Unauthorized for url: https://api.clerk.com",
            "403 Client Error: Forbidden for url: https://api.clerk.com",
            "422 Client Error: Unprocessable Entity for url: https://api.clerk.com/v1/saml_connections",
        ],
    )
    def test_non_retryable_errors_includes_clerk_key(self, expected_key):
        errors = self.source.get_non_retryable_errors()

        assert expected_key in errors

    @pytest.mark.parametrize(
        "observed_error",
        [
            # `users` endpoint, invalid/revoked secret key.
            "401 Client Error: Unauthorized for url: https://api.clerk.com/v1/users?limit=100",
            # `saml_connections` endpoint, SAML/Enterprise SSO not available on the account's plan.
            "422 Client Error: Unprocessable Entity for url: https://api.clerk.com/v1/saml_connections?limit=100",
            # `enterprise_connections` endpoint, Enterprise SSO not available on the account's instance.
            "422 Client Error: Unprocessable Entity for url: https://api.clerk.com/v1/enterprise_connections?limit=100 | api error: code=feature_requires_email_address_enabled",
            # `api_keys` endpoint, which Clerk rejects without a subject param on the list request.
            "400 Client Error: Bad Request for url: https://api.clerk.com/v1/api_keys?limit=100",
            # `redirect_urls` endpoint, not available on the account's Clerk plan or instance.
            "404 Client Error: Not Found for url: https://api.clerk.com/v1/redirect_urls?limit=100 | api error: code=resource_not_found",
        ],
    )
    def test_non_retryable_errors_matches_observed_error_message(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    def test_non_retryable_errors_does_not_match_400_on_other_clerk_endpoints(self):
        # A 400 from a different endpoint is a genuinely bad request worth investigating, not the
        # known api_keys limitation — the match must stay scoped to `api_keys`.
        other_endpoint_error = "400 Client Error: Bad Request for url: https://api.clerk.com/v1/users?limit=100"

        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_endpoint_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "401 Client Error: Unauthorized for url: https://api.attio.com/v2/objects/users",
        ],
    )
    def test_non_retryable_errors_does_not_match_other_vendors(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()

        assert not any(key in other_vendor_error for key in non_retryable_errors)

    def test_non_retryable_errors_does_not_match_404_on_other_clerk_endpoints(self):
        # A 404 from a different endpoint may be a genuinely missing record worth investigating, not
        # the redirect_urls account limitation — the match must stay scoped to `redirect_urls`.
        other_endpoint_error = "404 Client Error: Not Found for url: https://api.clerk.com/v1/users?limit=100"

        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_endpoint_error for key in non_retryable_errors)

    def test_non_retryable_errors_does_not_match_422_on_other_clerk_endpoints(self):
        # A 422 from a different endpoint is a genuinely bad request worth investigating, not an
        # account limitation — the match must stay scoped to `saml_connections`.
        other_endpoint_error = (
            "422 Client Error: Unprocessable Entity for url: https://api.clerk.com/v1/users?limit=100"
        )

        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_endpoint_error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        schema_names = {schema.name for schema in schemas}
        assert schema_names == set(ENDPOINTS)
        assert all(not schema.supports_incremental for schema in schemas)
        assert all(not schema.supports_append for schema in schemas)

    def test_get_schemas_filtered_by_names(self):
        first_endpoint = next(iter(ENDPOINTS))
        schemas = self.source.get_schemas(self.config, self.team_id, names=[first_endpoint])

        assert len(schemas) == 1
        assert schemas[0].name == first_endpoint

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["nonexistent"])

        assert schemas == []

    @pytest.mark.parametrize("endpoint", sorted(CLERK_ENDPOINTS))
    def test_every_endpoint_is_documented(self, endpoint):
        # `lists_tables_without_credentials` publishes this catalog to the public docs, so an
        # endpoint added without a canonical entry ships an undocumented table.
        entry = self.source.get_canonical_descriptions()[endpoint]

        assert entry["description"]
        assert entry["docs_url"].startswith("https://clerk.com/")
        assert entry["columns"]["id"]
