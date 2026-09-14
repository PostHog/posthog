import pytest

from posthog.schema import SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ip2whois import (
    IP2WhoisSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ip2whois.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.ip2whois.source import IP2WhoisSource


class TestIP2WhoisSource:
    def setup_method(self):
        self.source = IP2WhoisSource()
        self.team_id = 123
        self.config = IP2WhoisSourceConfig(api_key="test-key", domains="example.com")

    def test_get_source_config_fields(self):
        fields = self.source.get_source_config.fields

        by_name = {field.name: field for field in fields if isinstance(field, SourceFieldInputConfig)}
        assert set(by_name) == {"api_key", "domains"}

        api_key_field = by_name["api_key"]
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.required is True
        assert api_key_field.secret is True

        domains_field = by_name["domains"]
        assert domains_field.type == SourceFieldInputConfigType.TEXTAREA
        assert domains_field.required is True
        # The domain list is not a secret — it must round-trip on edit rather than be masked.
        assert domains_field.secret is False

    def test_lists_tables_without_credentials(self):
        # Static endpoint catalog with no I/O — must opt in so public docs render the table list.
        assert self.source.lists_tables_without_credentials is True

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_get_schemas_is_full_refresh_only(self, endpoint):
        # IP2WHOIS has no server-side change cursor, so neither incremental nor append is offered.
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas[endpoint].supports_incremental is False
        assert schemas[endpoint].supports_append is False
        assert schemas[endpoint].incremental_fields == []

    def test_get_schemas_filtered_by_names(self):
        assert [s.name for s in self.source.get_schemas(self.config, self.team_id, names=["whois"])] == ["whois"]
        assert self.source.get_schemas(self.config, self.team_id, names=["nonexistent"]) == []

    def test_non_retryable_errors_cover_account_level_api_error(self):
        # Account/quota errors are raised as "IP2WHOIS API error [...]" and must fail fast.
        assert any("IP2WHOIS API error" in key for key in self.source.get_non_retryable_errors())

    def test_documented_tables_render_without_credentials(self):
        tables = self.source.get_documented_tables()

        assert {table["name"] for table in tables} == set(ENDPOINTS)
