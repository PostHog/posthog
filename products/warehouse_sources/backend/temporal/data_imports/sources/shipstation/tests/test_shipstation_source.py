import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import VersionDeprecation
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.shipstation import (
    ShipStationSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shipstation.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    SHIPSTATION_V1,
    SHIPSTATION_V2,
    V2_ENDPOINTS,
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

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://ssapi.shipstation.com/orders?pageSize=500",
            "403 Client Error: Forbidden for url: https://ssapi.shipstation.com/stores",
            "401 Client Error: Unauthorized for url: https://api.shipstation.com/v2/shipments?page_size=500",
            "403 Client Error: Forbidden for url: https://api.shipstation.com/v2/carriers",
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

    def test_declares_both_versions_defaulting_to_v2_with_v1_deprecated(self):
        # The core of this change: v2 is the newest supported version and default, v1 is
        # deprecated (no announced sunset date). A dropped deprecation or a held-back default
        # would silently keep new sources on the retired v1 API.
        assert self.source.supported_versions == (SHIPSTATION_V1, SHIPSTATION_V2)
        assert self.source.default_version == SHIPSTATION_V2
        assert self.source.deprecated_versions == (VersionDeprecation(version=SHIPSTATION_V1, sunset_at=None),)

    @pytest.mark.parametrize(
        "api_version, expected_names, expected_incremental",
        [
            (SHIPSTATION_V1, set(ENDPOINTS), {"orders", "shipments", "fulfillments"}),
            (SHIPSTATION_V2, set(V2_ENDPOINTS), {"shipments", "labels", "batches", "manifests", "pickups"}),
        ],
    )
    def test_get_schemas_returns_the_pinned_versions_catalog(self, api_version, expected_names, expected_incremental):
        # v1 and v2 expose different resource sets; discovery must follow the pin or a pinned
        # source's tables disappear/duplicate on reconciliation.
        schemas = self.source.get_schemas(self.config, self.team_id, api_version=api_version)

        assert {schema.name for schema in schemas} == expected_names
        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        assert incremental == expected_incremental

    def test_get_schemas_defaults_to_v2(self):
        # An unpinned discovery call resolves to the default version (v2).
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {schema.name for schema in schemas} == set(V2_ENDPOINTS)

    def test_incremental_schemas_advertise_their_fields(self):
        schemas = {
            schema.name: schema
            for schema in self.source.get_schemas(self.config, self.team_id, api_version=SHIPSTATION_V1)
        }

        assert schemas["orders"].incremental_fields == INCREMENTAL_FIELDS["orders"]
        assert {f["field"] for f in schemas["orders"].incremental_fields} == {"modifyDate", "createDate"}
        assert schemas["products"].incremental_fields == []
        assert schemas["products"].supports_append is False

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["orders"], api_version=SHIPSTATION_V1)
        assert len(schemas) == 1
        assert schemas[0].name == "orders"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

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

    @pytest.mark.parametrize("pin, expected", [(None, SHIPSTATION_V2), ("v1", "v1"), ("v2", "v2")])
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.shipstation.source.shipstation_source"
    )
    def test_source_for_pipeline_resolves_api_version(self, mock_shipstation_source, pin, expected):
        # The resolved pin must reach the transport, else a v2 source would sync against v1.
        inputs = mock.MagicMock()
        inputs.schema_name = "shipments"
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
