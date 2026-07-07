import pytest
from unittest import mock

import structlog

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import IP2WhoisSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.ip2whois.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.ip2whois.source import IP2WhoisSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _make_inputs(schema_name: str = "whois") -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-id",
        source_id="source-id",
        team_id=123,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="job-id",
        logger=structlog.get_logger(),
        reset_pipeline=False,
    )


class TestIP2WhoisSource:
    def setup_method(self):
        self.source = IP2WhoisSource()
        self.team_id = 123
        self.config = IP2WhoisSourceConfig(api_key="test-key", domains="example.com")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.IP2WHOIS

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "IP2Whois"
        assert config.label == "IP2WHOIS"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is True
        assert config.iconPath == "/static/services/ip2whois.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/ip2whois"

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

    @pytest.mark.parametrize("status", ["401 Client Error", "403 Client Error"])
    def test_non_retryable_errors_cover_auth_and_host(self, status):
        errors = self.source.get_non_retryable_errors()

        assert any(status in key and "https://api.ip2whois.com" in key for key in errors)

    def test_non_retryable_errors_cover_account_level_api_error(self):
        # Account/quota errors are raised as "IP2WHOIS API error [...]" and must fail fast.
        assert any("IP2WHOIS API error" in key for key in self.source.get_non_retryable_errors())

    def test_documented_tables_render_without_credentials(self):
        tables = self.source.get_documented_tables()

        assert {table["name"] for table in tables} == set(ENDPOINTS)

    def test_canonical_descriptions_cover_every_endpoint(self):
        assert set(self.source.get_canonical_descriptions()) == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, None), True, None),
            ((False, "Invalid IP2WHOIS API key"), False, "Invalid IP2WHOIS API key"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.ip2whois.source.validate_ip2whois_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_key, self.config.domains)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.ip2whois.source.ip2whois_source")
    def test_source_for_pipeline_plumbs_args(self, mock_ip2whois_source):
        inputs = _make_inputs()

        self.source.source_for_pipeline(self.config, inputs)

        mock_ip2whois_source.assert_called_once_with(
            api_key="test-key",
            endpoint="whois",
            domains_raw="example.com",
            logger=inputs.logger,
        )
