import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.spacelift import (
    SpaceliftSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.spacelift.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.spacelift.source import SpaceliftSource

_SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.spacelift.source"


class TestSpaceliftSource:
    def setup_method(self):
        self.source = SpaceliftSource()
        self.team_id = 123
        self.config = SpaceliftSourceConfig(account_name="my-company", api_key_id="key-id", api_key_secret="key-secret")

    def test_account_name_is_a_connection_host_field(self):
        # Retargeting the account subdomain must force re-entering the API secret,
        # otherwise a PATCH could redirect the stored secret to an attacker's host.
        assert self.source.connection_host_fields == ["account_name"]

    @pytest.mark.parametrize(
        "observed_error",
        [
            "Invalid Spacelift API key: the API key ID or secret is incorrect",
            "Spacelift API returned unauthorized: the API key lacks access to this data (unauthorized)",
            "Invalid Spacelift account name: 'evil.com/x'",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "Spacelift: retryable HTTP error 503",
            "Spacelift GraphQL error: internal error",
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
        ],
    )
    def test_non_retryable_errors_does_not_match_transient_failures(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    def test_only_runs_supports_incremental(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["runs"].supports_incremental is True
        assert [f["field"] for f in schemas["runs"].incremental_fields] == ["createdAt"]
        assert schemas["runs"].incremental_fields == INCREMENTAL_FIELDS["runs"]
        for name, schema in schemas.items():
            # Incremental re-pulls a lookback window that only merge dedupes.
            assert schema.supports_append is False
            if name != "runs":
                assert schema.supports_incremental is False

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["runs", "stacks"])
        assert {schema.name for schema in schemas} == {"runs", "stacks"}

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_documented_tables_render_without_credentials(self):
        assert self.source.lists_tables_without_credentials is True
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
