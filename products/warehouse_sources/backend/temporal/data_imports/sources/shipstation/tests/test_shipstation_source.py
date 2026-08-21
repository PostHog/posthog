import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import VersionDeprecation
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.shipstation import (
    ShipStationSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shipstation.settings import (
    SHIPSTATION_V1,
    SHIPSTATION_V2,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shipstation.source import ShipStationSource


class TestShipStationSource:
    def setup_method(self):
        self.source = ShipStationSource()
        self.team_id = 123
        self.config = ShipStationSourceConfig(api_key="api-key", api_secret="api-secret")

    def test_declares_both_versions_defaulting_to_v2_with_v1_deprecated(self):
        # The core of this change: v2 is the newest supported version and default, v1 is
        # deprecated (no announced sunset date). A dropped deprecation or a held-back default
        # would silently keep new sources on the retired v1 API.
        assert self.source.supported_versions == (SHIPSTATION_V1, SHIPSTATION_V2)
        assert self.source.default_version == SHIPSTATION_V2
        assert self.source.deprecated_versions == (VersionDeprecation(version=SHIPSTATION_V1, sunset_at=None),)

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, None), True, None),
            (
                (False, "ShipStation API v1 requires both an API key and an API secret."),
                False,
                "ShipStation API v1 requires both an API key and an API secret.",
            ),
            ((False, None), False, "Invalid ShipStation API credentials"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.shipstation.source.validate_shipstation_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        # Pre-creation validation probes the default version (new sources are stamped v2).
        mock_validate.assert_called_once_with(self.config.api_key, self.config.api_secret, SHIPSTATION_V2)
