import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    LightspeedRetailSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lightspeed_retail.lightspeed_retail import (
    LightspeedRetailResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lightspeed_retail.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lightspeed_retail.source import (
    LightspeedRetailSource,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestLightspeedRetailSource:
    def setup_method(self):
        self.source = LightspeedRetailSource()
        self.team_id = 123
        self.config = LightspeedRetailSourceConfig(domain_prefix="mystore", api_token="api-token")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.LIGHTSPEEDRETAIL

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "LightspeedRetail"
        assert config.label == "Lightspeed Retail"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/lightspeed_retail.png"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["domain_prefix", "api_token"]

    def test_api_token_field_is_secret_password(self):
        config = self.source.get_source_config
        token_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_token")
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.secret is True
        assert token_field.required is True

    def test_domain_prefix_is_a_connection_host_field(self):
        # The stored token is sent to the host derived from domain_prefix, so
        # retargeting it must force re-entry of the secret.
        assert self.source.connection_host_fields == ["domain_prefix"]

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://mystore.retail.lightspeed.app/api/2.0/sales",
            "403 Client Error: Forbidden for url: https://mystore.retail.lightspeed.app/api/2.0/customers",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    def test_non_retryable_errors_does_not_match_server_errors(self):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(
            key in "500 Server Error for url: https://mystore.retail.lightspeed.app/api/2.0/sales"
            for key in non_retryable_errors
        )

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        # Every v2.0 collection supports the version keyset cursor.
        assert all(schema.supports_incremental for schema in schemas)
        assert all(schema.supports_append for schema in schemas)

    def test_schemas_advertise_version_cursor(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["sales"].incremental_fields == INCREMENTAL_FIELDS["sales"]
        assert [f["field"] for f in schemas["sales"].incremental_fields] == ["version"]

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["sales"])
        assert len(schemas) == 1
        assert schemas[0].name == "sales"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Lightspeed Retail credentials"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.lightspeed_retail.source.validate_lightspeed_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.domain_prefix, self.config.api_token)

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is LightspeedRetailResumeConfig

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.lightspeed_retail.source.lightspeed_retail_source"
    )
    def test_source_for_pipeline_plumbs_arguments(self, mock_lightspeed_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "sales"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = 999
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_lightspeed_source.assert_called_once()
        kwargs = mock_lightspeed_source.call_args.kwargs
        assert kwargs["domain_prefix"] == "mystore"
        assert kwargs["api_token"] == "api-token"
        assert kwargs["endpoint"] == "sales"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == 999

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.lightspeed_retail.source.lightspeed_retail_source"
    )
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_lightspeed_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "outlets"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = 999

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_lightspeed_source.call_args.kwargs["db_incremental_field_last_value"] is None
