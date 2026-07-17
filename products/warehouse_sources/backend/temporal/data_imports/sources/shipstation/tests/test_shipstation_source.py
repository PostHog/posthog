import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ShipStationSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.shipstation.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shipstation.shipstation import (
    ShipStationResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shipstation.source import ShipStationSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestShipStationSource:
    def setup_method(self):
        self.source = ShipStationSource()
        self.team_id = 123
        self.config = ShipStationSourceConfig(api_key="api-key", api_secret="api-secret")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.SHIPSTATION

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "ShipStation"
        assert config.label == "ShipStation"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/shipstation.png"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_key", "api_secret"]

    @pytest.mark.parametrize("field_name", ["api_key", "api_secret"])
    def test_credential_field_is_secret_password(self, field_name):
        config = self.source.get_source_config
        secret_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == field_name)
        assert secret_field.type == SourceFieldInputConfigType.PASSWORD
        assert secret_field.secret is True
        assert secret_field.required is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://ssapi.shipstation.com/orders?pageSize=500",
            "403 Client Error: Forbidden for url: https://ssapi.shipstation.com/stores",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://ssapi.shipstation.com/orders",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        # Only the date-filterable list endpoints support incremental sync.
        assert incremental == {"orders", "shipments", "fulfillments"}

    def test_incremental_schemas_advertise_their_fields(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["orders"].incremental_fields == INCREMENTAL_FIELDS["orders"]
        assert {f["field"] for f in schemas["orders"].incremental_fields} == {"modifyDate", "createDate"}
        assert schemas["products"].incremental_fields == []
        assert schemas["products"].supports_append is False

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["orders"])
        assert len(schemas) == 1
        assert schemas[0].name == "orders"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid ShipStation API credentials"),
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
        # Validation probes the default version's host (new sources are created on v1).
        mock_validate.assert_called_once_with(self.config.api_key, self.config.api_secret, "v1")

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is ShipStationResumeConfig

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

    def test_advertises_v1_only_but_honors_explicit_v2_pin(self):
        # v1 is the only functional version today, so it is the only advertised/default
        # one. A v2 pin is still honored verbatim (opt-in escape hatch for the transport
        # groundwork) — the base class never silently remaps a stored pin.
        assert self.source.supported_versions == ("v1",)
        assert self.source.default_version == "v1"
        assert self.source.resolve_api_version(None) == "v1"
        assert self.source.resolve_api_version("v2") == "v2"

    @pytest.mark.parametrize("pin, expected", [(None, "v1"), ("v1", "v1"), ("v2", "v2")])
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.shipstation.source.shipstation_source"
    )
    def test_source_for_pipeline_resolves_api_version(self, mock_shipstation_source, pin, expected):
        inputs = mock.MagicMock()
        inputs.schema_name = "orders"
        inputs.should_use_incremental_field = False
        inputs.incremental_field = None
        inputs.api_version = pin

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_shipstation_source.call_args.kwargs["api_version"] == expected

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
