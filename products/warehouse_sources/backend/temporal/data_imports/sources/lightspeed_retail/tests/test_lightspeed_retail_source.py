import datetime

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
        "version, expected_sunset",
        [
            (LIGHTSPEED_RETAIL_API_VERSION_2_0, None),
            (LIGHTSPEED_RETAIL_API_VERSION_2026_01, datetime.date(2027, 1, 1)),
        ],
    )
    def test_deprecated_api_version_metadata(self, version, expected_sunset):
        # Drives the in-product warning and the source-level repin migration.
        deprecation = self.source.get_version_deprecation(version)
        assert deprecation is not None
        assert deprecation.sunset_at == expected_sunset
        assert self.source.get_version_deprecation(LIGHTSPEED_RETAIL_API_VERSION_2026_07) is None

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
