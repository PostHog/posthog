from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.avalara.avalara import AvalaraResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.avalara.settings import (
    AVALARA_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.avalara.source import AvalaraSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.avalara import (
    AvalaraSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

_FANOUT_ENDPOINTS = {"Transactions", "Nexus", "Customers", "ExemptionCertificates"}


class TestAvalaraSource:
    def setup_method(self):
        self.source = AvalaraSource()
        self.team_id = 123
        self.config = AvalaraSourceConfig(account_id="12345", license_key="key", environment="production")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.AVALARA

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Avalara"
        assert config.label == "Avalara AvaTax"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/avalara.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/avalara"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["account_id", "license_key"]

    def test_license_key_field_is_secret_password(self):
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "license_key")
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_account_id_field_is_not_secret(self):
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "account_id")
        assert field.secret is False
        assert field.required is True

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://rest.avatax.com/api/v2/companies",),
            ("403 Client Error: Forbidden for url: https://rest.avatax.com/api/v2/companies/1/nexus",),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @parameterized.expand(
        [
            ("429 Client Error: Too Many Requests for url: https://rest.avatax.com/api/v2/companies",),
            ("500 Server Error: Internal Server Error for url: https://rest.avatax.com/api/v2/companies",),
            ("HTTPSConnectionPool(host='rest.avatax.com', port=443): Read timed out.",),
        ]
    )
    def test_non_retryable_errors_do_not_match_transient(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas_match_endpoints_with_correct_sync_modes(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        for name in ENDPOINTS:
            assert schemas[name].supports_incremental is True
            assert schemas[name].supports_append is True
            assert [f["field"] for f in schemas[name].incremental_fields] == ["modifiedDate"]

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["Companies"])
        assert len(schemas) == 1
        assert schemas[0].name == "Companies"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_lists_tables_without_credentials_publishes_catalog(self):
        # Static endpoint catalog (no I/O) — the public docs table list should render.
        assert self.source.lists_tables_without_credentials is True
        documented = self.source.get_documented_tables()
        assert {table["name"] for table in documented} == set(ENDPOINTS)

    def test_canonical_descriptions_cover_every_endpoint(self):
        canonical = self.source.get_canonical_descriptions()
        assert set(canonical) == set(AVALARA_ENDPOINTS)

    def test_fanout_endpoints_key_include_parent_identifier(self):
        # Fan-out children aggregate rows across every company, so their primary key must include
        # a company identifier unless the API documents a globally unique id (Transactions does).
        for name in _FANOUT_ENDPOINTS - {"Transactions"}:
            assert "companyId" in AVALARA_ENDPOINTS[name].primary_keys

    @parameterized.expand(
        [
            ((True, None), True, None),
            (
                (False, "Avalara authentication failed. Check your account ID and license key."),
                False,
                "Avalara authentication failed. Check your account ID and license key.",
            ),
        ]
    )
    def test_validate_credentials(self, mock_return, expected_valid, expected_message):
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.avalara.source.validate_avalara_credentials"
        ) as mock_validate:
            mock_validate.return_value = mock_return
            is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("12345", "key", "production")

    def test_get_resumable_source_manager_bound_to_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert manager._data_class is AvalaraResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.avalara.source.avalara_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_avalara_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "Transactions"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        inputs.incremental_field = "modifiedDate"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_avalara_source.assert_called_once()
        kwargs = mock_avalara_source.call_args.kwargs
        assert kwargs["account_id"] == "12345"
        assert kwargs["license_key"] == "key"
        assert kwargs["environment"] == "production"
        assert kwargs["endpoint"] == "Transactions"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["incremental_field"] == "modifiedDate"
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.avalara.source.avalara_source")
    def test_source_for_pipeline_omits_cursor_when_not_incremental(self, mock_avalara_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "Companies"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        inputs.incremental_field = "modifiedDate"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        kwargs = mock_avalara_source.call_args.kwargs
        assert kwargs["db_incremental_field_last_value"] is None
        assert kwargs["incremental_field"] is None
