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
