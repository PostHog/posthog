import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.lightspeedretail import (
    LightspeedRetailSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lightspeed_retail.constants import (
    LIGHTSPEED_RETAIL_API_VERSION_2_0,
    LIGHTSPEED_RETAIL_API_VERSION_2026_01,
    LIGHTSPEED_RETAIL_API_VERSION_2026_07,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lightspeed_retail.source import (
    LightspeedRetailSource,
)


class TestLightspeedRetailSource:
    def setup_method(self):
        self.source = LightspeedRetailSource()
        self.team_id = 123
        self.config = LightspeedRetailSourceConfig(domain_prefix="mystore", api_token="api-token")

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
        # An unpinned source probes the default version.
        mock_validate.assert_called_once_with(
            self.config.domain_prefix, self.config.api_token, LIGHTSPEED_RETAIL_API_VERSION_2026_07
        )

    @pytest.mark.parametrize(
        "pinned, expected",
        [
            (None, LIGHTSPEED_RETAIL_API_VERSION_2026_07),
            (LIGHTSPEED_RETAIL_API_VERSION_2_0, LIGHTSPEED_RETAIL_API_VERSION_2_0),
            (LIGHTSPEED_RETAIL_API_VERSION_2026_01, LIGHTSPEED_RETAIL_API_VERSION_2026_01),
            (LIGHTSPEED_RETAIL_API_VERSION_2026_07, LIGHTSPEED_RETAIL_API_VERSION_2026_07),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.lightspeed_retail.source.validate_lightspeed_credentials"
    )
    def test_validate_credentials_probes_the_pinned_version(self, mock_validate, pinned, expected):
        mock_validate.return_value = True

        self.source.validate_credentials(self.config, self.team_id, api_version=pinned)

        assert mock_validate.call_args.args[2] == expected

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.lightspeed_retail.source.lightspeed_retail_source"
    )
    def test_source_for_pipeline_plumbs_arguments(self, mock_lightspeed_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "sales"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = 999
        inputs.api_version = LIGHTSPEED_RETAIL_API_VERSION_2026_01
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_lightspeed_source.assert_called_once()
        kwargs = mock_lightspeed_source.call_args.kwargs
        assert kwargs["domain_prefix"] == "mystore"
        assert kwargs["api_token"] == "api-token"
        assert kwargs["endpoint"] == "sales"
        assert kwargs["team_id"] is inputs.team_id
        assert kwargs["job_id"] is inputs.job_id
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == 999
        assert kwargs["api_version"] == LIGHTSPEED_RETAIL_API_VERSION_2026_01

    @pytest.mark.parametrize(
        "pinned, expected",
        [
            (None, LIGHTSPEED_RETAIL_API_VERSION_2026_07),
            (LIGHTSPEED_RETAIL_API_VERSION_2_0, LIGHTSPEED_RETAIL_API_VERSION_2_0),
            (LIGHTSPEED_RETAIL_API_VERSION_2026_01, LIGHTSPEED_RETAIL_API_VERSION_2026_01),
            (LIGHTSPEED_RETAIL_API_VERSION_2026_07, LIGHTSPEED_RETAIL_API_VERSION_2026_07),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.lightspeed_retail.source.lightspeed_retail_source"
    )
    def test_source_for_pipeline_syncs_on_the_pinned_version(self, mock_lightspeed_source, pinned, expected):
        inputs = mock.MagicMock()
        inputs.schema_name = "sales"
        inputs.should_use_incremental_field = False
        inputs.api_version = pinned

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_lightspeed_source.call_args.kwargs["api_version"] == expected

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
