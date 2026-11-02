import pytest
from unittest import mock

from products.warehouse_sources.backend.facade.source_config import SourceFieldInputConfig, SourceFieldInputConfigType
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

    @pytest.mark.parametrize(
        "field_name, required",
        [
            # api_key is needed by both versions; api_secret is v1-only, so optional at the form
            # level (v2 users have no secret) and enforced for v1 in validate_credentials.
            ("api_key", True),
            ("api_secret", False),
        ],
    )
    def test_credential_field_is_secret_password(self, field_name, required):
        config = self.source.get_source_config
        secret_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == field_name)
        assert secret_field.type == SourceFieldInputConfigType.PASSWORD
        assert secret_field.secret is True
        assert secret_field.required is required

    def test_declares_both_versions_defaulting_to_v2_with_v1_deprecated(self):
        # The core of this change: v2 is the newest supported version and default, v1 is
        # deprecated (no announced sunset date). A dropped deprecation or a held-back default
        # would silently keep new sources on the retired v1 API.
        assert self.source.supported_versions == (SHIPSTATION_V1, SHIPSTATION_V2)
        assert self.source.default_version == SHIPSTATION_V2
        assert self.source.deprecated_versions == (VersionDeprecation(version=SHIPSTATION_V1, sunset_at=None),)

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["orders"], api_version=SHIPSTATION_V1)
        assert len(schemas) == 1
        assert schemas[0].name == "orders"

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

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.shipstation.source.shipstation_source"
    )
    def test_source_for_pipeline_plumbs_arguments(self, mock_shipstation_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "orders"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-02T03:04:05.0000000"
        inputs.incremental_field = "modifyDate"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_shipstation_source.assert_called_once()
        kwargs = mock_shipstation_source.call_args.kwargs
        assert kwargs["api_key"] == "api-key"
        assert kwargs["api_secret"] == "api-secret"
        assert kwargs["endpoint"] == "orders"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-01-02T03:04:05.0000000"
        assert kwargs["incremental_field"] == "modifyDate"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.shipstation.source.shipstation_source"
    )
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_shipstation_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "stores"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-01-02"
        inputs.incremental_field = None

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_shipstation_source.call_args.kwargs["db_incremental_field_last_value"] is None
